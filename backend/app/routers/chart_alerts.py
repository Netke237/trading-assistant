# backend/app/routers/chart_alerts.py
"""Chart alert CRUD endpoints — alert rules and history (Phase 4)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.alert import AlertRuleModel, AlertHistoryModel
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    ConditionGroup, evaluate_rules,
)
from app.services.indicator_compute import compute_indicators_for_conditions
from app.services.notifications.dispatch import dispatch as _dispatch, load_notification_config as _load_notification_config
from app.services.notifications.alert_notifier import _format_dt

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/alerts', tags=['chart-alerts'])


# ── Pydantic request/response models ─────────────────────────────────────────

class PriceConditionIn(BaseModel):
    kind: str = 'price'
    operator: str
    value: float

class IndicatorConditionIn(BaseModel):
    kind: str = 'indicator'
    indicator: str
    operator: str
    value: float

class StructureConditionIn(BaseModel):
    kind: str = 'structure'
    signal_kind: str
    direction: Optional[str] = None
    min_confidence: Optional[int] = None

class ConditionGroupIn(BaseModel):
    logic: str = 'AND'
    conditions: list = Field(default_factory=list)

class AlertRuleCreate(BaseModel):
    id: Optional[str] = None
    name: str
    symbol: str
    interval: str
    enabled: bool = True
    group: ConditionGroupIn
    cooldown_minutes: int = 60
    expiry_date: Optional[str] = None

class AlertRulePatch(BaseModel):
    enabled: Optional[bool] = None
    last_triggered_at: Optional[str] = None

class AlertHistoryCreate(BaseModel):
    rule_id: str
    symbol: str
    interval: str
    triggered_at: str
    candle: dict
    trigger_values: dict = Field(default_factory=dict)
    reason: str

class AlertTestRequest(BaseModel):
    candles: list[dict]
    indicators: dict = Field(default_factory=dict)
    signals: list[dict] = Field(default_factory=list)

class NotificationTestRequest(BaseModel):
    channel: str
    to: Optional[str] = None
    subject: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rule_to_dict(row: AlertRuleModel) -> dict:
    return {
        'id': row.id, 'name': row.name, 'symbol': row.symbol, 'interval': row.interval,
        'enabled': row.enabled, 'group': json.loads(row.rule_json),
        'cooldown_minutes': row.cooldown_minutes, 'expiry_date': row.expiry_date,
        'created_at': row.created_at, 'last_triggered_at': row.last_triggered_at,
    }

def _history_to_dict(row: AlertHistoryModel) -> dict:
    return {
        'id': row.id, 'rule_id': row.rule_id, 'symbol': row.symbol, 'interval': row.interval,
        'triggered_at': row.triggered_at, 'candle': json.loads(row.candle_json),
        'trigger_values': json.loads(row.trigger_values), 'reason': row.reason,
    }

def _build_notification_text(entry: dict, rule_name: str | None = None) -> tuple[str, str, str]:
    """Returns (subject, plain_body, html_body).

    ``rule_name`` is the human-readable name of the alert rule; it falls back to
    the rule id when the name is unavailable. The trigger time is rendered as a
    local Date/Time (no microseconds) to match the portfolio alert format.
    """
    sym = entry.get('symbol', '?')
    ival = entry.get('interval', '?')
    reason = entry.get('reason', '')
    triggered_at = entry.get('triggered_at', '')
    tv = entry.get('trigger_values', {})
    rule_id = entry.get('rule_id', '')

    date_str, time_str = _format_dt(triggered_at)
    rule_label = rule_name or rule_id or '(unnamed rule)'

    subject = f'Bamendjou Alert - {rule_label} - {sym} [{ival}]'

    values_lines = []
    for k, v in tv.items():
        if isinstance(v, float):
            values_lines.append(f'{k}={v:.2f}')
        else:
            values_lines.append(f'{k}={v}')
    values_str = '  '.join(values_lines)

    plain = (f'Symbol:    {sym}\nInterval:  {ival}\n'
             f'Date:      {date_str}\nTime:      {time_str}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')

    html = (f'<b>Bamendjou Alert</b> - {sym} [{ival}]\n\n'
            f'<b>Trigger:</b> {reason}\n<b>Date:</b> {date_str}\n<b>Time:</b> {time_str}\n'
            f'<b>Values:</b> {values_str}\n<b>Rule:</b> {rule_label}\n')

    return subject, plain, html

def _deserialize_rule(rule_json_str: str, row: AlertRuleModel) -> AlertRuleInput:
    group_data = json.loads(rule_json_str)
    conditions = []
    for c in group_data.get('conditions', []):
        kind = c.get('kind', '')
        if kind == 'price':
            conditions.append(PriceCondition(kind='price', operator=c['operator'], value=c['value']))
        elif kind == 'indicator':
            conditions.append(IndicatorCondition(kind='indicator', indicator=c['indicator'], operator=c['operator'], value=c['value']))
        elif kind == 'structure':
            conditions.append(StructureCondition(kind='structure', signal_kind=c['signal_kind'], direction=c.get('direction'), min_confidence=c.get('min_confidence')))
    return AlertRuleInput(
        id=row.id, name=row.name, symbol=row.symbol, interval=row.interval,
        enabled=bool(row.enabled),
        group=ConditionGroup(logic=group_data.get('logic', 'AND'), conditions=conditions),
        cooldown_minutes=row.cooldown_minutes, expiry_date=row.expiry_date,
        created_at=row.created_at, last_triggered_at=row.last_triggered_at,
    )


# ── Alert Rules CRUD ─────────────────────────────────────────────────────────

@router.post('/rules', status_code=status.HTTP_201_CREATED)
async def create_rule(body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    rule_id = body.id or uuid.uuid4().hex
    if body.id:
        existing = await db.get(AlertRuleModel, rule_id)
        if existing:
            raise HTTPException(status_code=409, detail='Rule with this id already exists')
    now = datetime.now().isoformat()

    rule = AlertRuleModel(
        id=rule_id, user_id='default', name=body.name, symbol=body.symbol.upper(),
        interval=body.interval, enabled=body.enabled,
        rule_json=json.dumps(body.group.model_dump()),
        cooldown_minutes=body.cooldown_minutes, expiry_date=body.expiry_date,
        created_at=now, last_triggered_at=None,
    )
    db.add(rule)
    await db.commit()
    return _rule_to_dict(rule)


@router.get('/rules')
async def list_rules(symbol: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(AlertRuleModel).where(AlertRuleModel.user_id == 'default')
    if symbol:
        q = q.where(AlertRuleModel.symbol == symbol.upper())
    result = await db.execute(q.order_by(AlertRuleModel.created_at.desc()))
    return [_rule_to_dict(r) for r in result.scalars().all()]


@router.get('/rules/{rule_id}')
async def get_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    return _rule_to_dict(row)


@router.put('/rules/{rule_id}')
async def replace_rule(rule_id: str, body: AlertRuleCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    row.name = body.name
    row.symbol = body.symbol.upper()
    row.interval = body.interval
    row.enabled = body.enabled
    row.rule_json = json.dumps(body.group.model_dump())
    row.cooldown_minutes = body.cooldown_minutes
    row.expiry_date = body.expiry_date
    await db.commit()
    return _rule_to_dict(row)


@router.patch('/rules/{rule_id}')
async def patch_rule(rule_id: str, body: AlertRulePatch, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.last_triggered_at is not None:
        row.last_triggered_at = body.last_triggered_at
    await db.commit()
    return _rule_to_dict(row)


@router.delete('/rules/{rule_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    # Explicitly delete history for SQLite compatibility (FK CASCADE not always enforced)
    await db.execute(delete(AlertHistoryModel).where(AlertHistoryModel.rule_id == rule_id))
    await db.delete(row)
    await db.commit()


# ── Alert History ────────────────────────────────────────────────────────────

@router.post('/history', status_code=status.HTTP_201_CREATED)
async def create_history_entry(body: AlertHistoryCreate, db: AsyncSession = Depends(get_db)):
    entry = AlertHistoryModel(
        id=uuid.uuid4().hex, rule_id=body.rule_id, symbol=body.symbol,
        interval=body.interval, triggered_at=body.triggered_at,
        candle_json=json.dumps(body.candle),
        trigger_values=json.dumps(body.trigger_values), reason=body.reason,
    )
    db.add(entry)
    await db.commit()

    entry_dict = _history_to_dict(entry)
    rule_row = (await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == body.rule_id)
    )).scalar_one_or_none()
    rule_name = rule_row.name if rule_row else None
    subject, plain_body, html_body = _build_notification_text(entry_dict, rule_name)
    _notif_cfg = _load_notification_config()
    _gmail = _notif_cfg.get('gmail', {})
    _tg    = _notif_cfg.get('telegram', {})
    if _gmail.get('enabled'):
        logger.info('Dispatching alert email for %s [%s]', entry_dict.get('symbol'), entry_dict.get('interval'))
        _dispatch('gmail',
            to=_gmail.get('to', ''), subject=subject, body=plain_body,
            smtp_user=_gmail.get('smtp_user', ''), smtp_password=_gmail.get('smtp_password', ''),
        )
    if _tg.get('enabled'):
        logger.info('Dispatching alert Telegram for %s [%s]', entry_dict.get('symbol'), entry_dict.get('interval'))
        _dispatch('telegram',
            bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=html_body,
        )

    return entry_dict


@router.get('/history')
async def list_history(
    symbol: Optional[str] = None,
    interval: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(AlertHistoryModel)
    if symbol:
        q = q.where(AlertHistoryModel.symbol == symbol.upper())
    if interval:
        q = q.where(AlertHistoryModel.interval == interval)
    result = await db.execute(q.order_by(AlertHistoryModel.triggered_at.desc()).limit(limit))
    return [_history_to_dict(r) for r in result.scalars().all()]


@router.delete('/history/{history_id}', status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_history(history_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AlertHistoryModel).where(AlertHistoryModel.id == history_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='History entry not found')
    await db.delete(row)
    await db.commit()


@router.delete('/history', status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_history(db: AsyncSession = Depends(get_db)):
    await db.execute(delete(AlertHistoryModel))
    await db.commit()


# ── Test / Dry-run ───────────────────────────────────────────────────────────

@router.post('/rules/{rule_id}/test')
async def test_rule(rule_id: str, body: AlertTestRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    rule_input = _deserialize_rule(row.rule_json, row)
    matches = []
    for i in range(len(body.candles)):
        candle = body.candles[i]
        results = evaluate_rules([rule_input], candle, body.candles[:i + 1], body.indicators, body.signals, datetime.now())
        matches.extend(results)
    return {'matches': matches}


# ── Notification test ────────────────────────────────────────────────────────

@router.post('/notifications/test')
async def test_notification(body: NotificationTestRequest):
    if body.channel == 'gmail':
        from app.services.notifications.gmail import send_gmail as _send_gmail
        to = body.to or os.getenv('BAMENDJOU_GMAIL_RECIPIENT', os.getenv('BAMENDJOU_GMAIL_USER', ''))
        await _send_gmail(
            to=to,
            subject=body.subject or 'Bamendjou - Test Notification',
            body='This is a test notification from Bamendjou.',
            smtp_user=body.smtp_user or os.getenv('BAMENDJOU_GMAIL_USER', ''),
            smtp_password=body.smtp_password or os.getenv('BAMENDJOU_GMAIL_PASSWORD', ''),
        )
        return {'status': 'sent', 'channel': 'gmail'}
    elif body.channel == 'telegram':
        from app.services.notifications.telegram import send_telegram as _send_tg
        await _send_tg(
            text='<b>Bamendjou</b> - Test notification from your trading assistant.',
            bot_token=body.bot_token or os.getenv('BAMENDJOU_TELEGRAM_BOT_TOKEN', ''),
            chat_id=body.chat_id or os.getenv('BAMENDJOU_TELEGRAM_CHAT_ID', ''),
        )
        return {'status': 'sent', 'channel': 'telegram'}
    raise HTTPException(status_code=400, detail=f'Unknown channel: {body.channel}')


# ── WS helper (called from chart.py on candle-close) ─────────────────────────

async def evaluate_and_notify_for_symbol(
    symbol: str, interval: str, closed_candle: dict,
    all_candles: list[dict], signals: list[dict],
) -> list[dict]:
    """Load enabled rules, evaluate, persist history, enqueue notifications."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AlertRuleModel).where(
            AlertRuleModel.symbol == symbol.upper(),
            AlertRuleModel.interval == interval,
            AlertRuleModel.enabled == True,
            AlertRuleModel.user_id == 'default',
        ))
        rows = result.scalars().all()
        if not rows:
            return []

        rule_inputs = [_deserialize_rule(row.rule_json, row) for row in rows]

        # Compute indicators referenced by rule conditions
        all_conditions = []
        for ri in rule_inputs:
            all_conditions.extend(ri.group.conditions)
        indicators = compute_indicators_for_conditions(all_candles, all_conditions)

        triggered = evaluate_rules(rule_inputs, closed_candle, all_candles, indicators, signals, datetime.now())

        for entry in triggered:
            history = AlertHistoryModel(
                id=entry['id'], rule_id=entry['rule_id'], symbol=entry['symbol'],
                interval=entry['interval'], triggered_at=entry['triggered_at'],
                candle_json=json.dumps(entry['candle']),
                trigger_values=json.dumps(entry['trigger_values']),
                reason=entry['reason'],
            )
            db.add(history)

            rule_row = (await db.execute(
                select(AlertRuleModel).where(AlertRuleModel.id == entry['rule_id'])
            )).scalar_one_or_none()
            rule_name = rule_row.name if rule_row else None
            if rule_row:
                rule_row.last_triggered_at = entry['triggered_at']

            subject, plain_body, html_body = _build_notification_text(entry, rule_name)

            _notif_cfg = _load_notification_config()
            _gmail  = _notif_cfg.get('gmail', {})
            _tg     = _notif_cfg.get('telegram', {})

            if _gmail.get('enabled'):
                logger.info('Dispatching WS alert email for %s [%s]', entry['symbol'], entry['interval'])
                _dispatch('gmail',
                    to=_gmail.get('to', ''), subject=subject, body=plain_body,
                    smtp_user=_gmail.get('smtp_user', ''), smtp_password=_gmail.get('smtp_password', ''),
                )
            if _tg.get('enabled'):
                logger.info('Dispatching WS alert Telegram for %s [%s]', entry['symbol'], entry['interval'])
                _dispatch('telegram',
                    bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=html_body,
                )

        await db.commit()
    return triggered
