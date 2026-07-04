# backend/app/routers/chart_alerts.py
"""Chart alert CRUD endpoints — alert rules and history (Phase 4)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.alert import AlertRuleModel, AlertHistoryModel
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
)
from app.services.historical_store import get_bars
from app.services.indicator_compute import compute_indicators_for_conditions
from app.services.notifications.dispatch import dispatch as _dispatch, load_notification_config as _load_notification_config
from app.services.notifications.alert_notifier import _format_dt, _TZ_LABEL

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/alerts', tags=['chart-alerts'])

# test_rule() re-fits a 3-state GaussianHMM from scratch on every candle once the
# causal window passes 200 bars (build_regime_snapshot() is called once per
# iteration) — an unbounded candle list makes this endpoint pathologically slow.
# 1500 comfortably covers a full intraday session's worth of 1-minute bars plus
# headroom, while still bounding worst-case per-request HMM refit count.
# Benchmarked 2026-07-04: 1500 candles ~= 1.0s full worst-case recompute (see
# scripts/bench_test_rule_candles.py), well within budget for a manual dry-run endpoint.
MAX_TEST_RULE_CANDLES = 1500

# The live WS path re-fits regime/HMM/OMM models on every candle close. Fitting over
# unbounded history makes each tick's cost grow with the symbol's stored history.
# Cap the model-fit window to a bounded recent slice; 1500 bars covers a full intraday
# session plus the models' 200-bar minimums with wide margin. Mirrors MAX_TEST_RULE_CANDLES.
MAX_LIVE_MODEL_CANDLES = 1500


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
    group: ConditionGroupIn = Field(default_factory=ConditionGroupIn)
    rule_type: str = 'standard'
    composite_def: Optional[dict] = None
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
    parsed = json.loads(row.rule_json)
    base = {
        'id': row.id, 'name': row.name, 'symbol': row.symbol, 'interval': row.interval,
        'enabled': row.enabled,
        'cooldown_minutes': row.cooldown_minutes, 'expiry_date': row.expiry_date,
        'created_at': row.created_at, 'last_triggered_at': row.last_triggered_at,
    }
    if isinstance(parsed, dict) and parsed.get('__type') == 'composite':
        composite_def = {k: v for k, v in parsed.items() if k != '__type'}
        base['rule_type'] = 'composite'
        base['composite_def'] = composite_def
        base['group'] = {'logic': 'AND', 'conditions': []}
    else:
        base['rule_type'] = 'standard'
        base['group'] = parsed
    return base

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

    subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{ival}]'

    values_lines = []
    for k, v in tv.items():
        if isinstance(v, float):
            values_lines.append(f'{k}={v:.2f}')
        else:
            values_lines.append(f'{k}={v}')
    values_str = '  '.join(values_lines)

    plain = (f'Symbol:    {sym}\nInterval:  {ival}\n'
             f'Date:      {date_str}\nTime:      {time_str} {_TZ_LABEL}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')

    # Telegram mirrors the email body exactly (same fields, same order), with a
    # bold first line equal to the email subject (which carries the rule name).
    html = (f'<b>{subject}</b>\n\n'
            f'<b>Symbol:</b>    {sym}\n<b>Interval:</b>  {ival}\n'
            f'<b>Date:</b>      {date_str}\n<b>Time:</b>      {time_str} {_TZ_LABEL}\n'
            f'<b>Trigger:</b>   {reason}\n<b>Values:</b>    {values_str}\n'
            f'<b>Rule:</b>      {rule_label}\n')

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
        elif kind == 'regime':
            conditions.append(RegimeCondition(kind='regime', model=c.get('model', 'OMM'), state=c.get('state', 'Bull'), min_conviction=c.get('min_conviction')))
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

    if body.rule_type == 'composite':
        if not body.composite_def:
            raise HTTPException(status_code=422, detail='composite_def is required when rule_type is "composite"')
        rule_json = json.dumps({"__type": "composite", **body.composite_def})
    else:
        rule_json = json.dumps(body.group.model_dump())

    rule = AlertRuleModel(
        id=rule_id, user_id='default', name=body.name, symbol=body.symbol.upper(),
        interval=body.interval, enabled=body.enabled,
        rule_json=rule_json,
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
    if len(body.candles) > MAX_TEST_RULE_CANDLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f'Too many candles for a dry-run test ({len(body.candles)} > {MAX_TEST_RULE_CANDLES}). '
                'Trim the candle list — each candle re-fits regime models when the rule has a regime condition.'
            ),
        )
    result = await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == rule_id, AlertRuleModel.user_id == 'default')
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Rule not found')
    rule_input = _deserialize_rule(row.rule_json, row)
    needs_regime = any(c.kind == 'regime' for c in rule_input.group.conditions)
    matches = []
    for i in range(len(body.candles)):
        candle = body.candles[i]
        window = body.candles[:i + 1]
        # Rebuilt every iteration (not once) so each candle's regime condition is
        # evaluated causally, matching only data available up to that point — but
        # this means compute_intraday_hmm's iterative HMM fit re-runs once per
        # candle once the window passes its 200-bar minimum. Acceptable for this
        # manual dry-run endpoint's typical candle-list sizes; a very large paste
        # would make this proportionally slower.
        regime_by_model = build_regime_snapshot(window) if needs_regime else None
        results = evaluate_rules([rule_input], candle, window, body.indicators, body.signals, datetime.now(), regime_by_model)
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

        # Separate composite rules from standard rules
        standard_rows = []
        composite_rows = []
        for _row in rows:
            _rj = json.loads(_row.rule_json)
            if _rj.get("__type") == "composite":
                composite_rows.append((_row, _rj))
            else:
                standard_rows.append(_row)
        rows = standard_rows  # existing path only processes standard rules

        rule_inputs = [_deserialize_rule(row.rule_json, row) for row in rows]

        needs_regime = any(c.kind == 'regime' for ri in rule_inputs for c in ri.group.conditions)
        regime_by_model = build_regime_snapshot(all_candles[-MAX_LIVE_MODEL_CANDLES:]) if needs_regime else None

        # Compute indicators referenced by rule conditions
        all_conditions = []
        for ri in rule_inputs:
            all_conditions.extend(ri.group.conditions)
        indicators = compute_indicators_for_conditions(all_candles, all_conditions)

        triggered = evaluate_rules(rule_inputs, closed_candle, all_candles, indicators, signals, datetime.now(), regime_by_model)

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

        # ── Composite rule evaluation ─────────────────────────────────────────
        if composite_rows:
            from app.services.composite_trigger_evaluator import evaluate_from_context_detailed, format_composite_reason
            from app.services.regime_omm import compute_omm
            _model_candles = all_candles[-MAX_LIVE_MODEL_CANDLES:] if all_candles else []
            _closes = [c["close"] for c in _model_candles]
            _omm = compute_omm(_closes) if len(_closes) >= 100 else None

            # Only fetch daily bars if some composite rule actually needs them — either
            # for strategy_confirmations, or because a rule's primary condition targets
            # the HMM_daily model (which requires daily bars to fit against).
            _needs_daily_bars = any(
                _rj.get("strategy_confirmations") or _rj.get("primary", {}).get("model") == "HMM_daily"
                for _, _rj in composite_rows
            )
            _bars_daily: list[dict] = []
            if _needs_daily_bars:
                if interval in ("1D", "1W"):
                    # all_candles is already daily/weekly data for this rule's own
                    # interval — reuse it instead of paying for an extra get_bars()
                    # round-trip.
                    _bars_daily = _model_candles
                else:
                    try:
                        _end = date.today()
                        _start = _end - timedelta(days=730)
                        _bars_daily = await get_bars(symbol, _start, _end)
                    except Exception as _exc:
                        logger.warning("composite rule strategy-confirmation bars fetch failed for %s: %s", symbol, _exc)
                        _bars_daily = []

            # all_candles are only genuinely intraday when the rule's own interval is
            # intraday — chart.py's get_intraday(symbol, interval) returns daily candles
            # for '1D'/'1W' rules, so passing them as bars_intraday would mislabel daily
            # data as intraday to the VWAP mean-reversion check.
            _bars_intraday = _model_candles if interval not in ("1D", "1W") else []

            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                _direction = _td.get("direction") or "Bullish"
                _rule_needs_daily = bool(_rj.get("strategy_confirmations")) or _rj.get("primary", {}).get("model") == "HMM_daily"
                _rule_daily = _bars_daily if _rule_needs_daily else []
                try:
                    _fired, _detail = evaluate_from_context_detailed(
                        _td, _omm, signals, indicators,
                        bars_daily=_rule_daily, bars_intraday=_bars_intraday,
                        direction=_direction, symbol=symbol,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue
                if not _fired:
                    continue
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
                _now = datetime.now().isoformat()
                _entry = {
                    "id": uuid.uuid4().hex,
                    "rule_id": _row.id,
                    "symbol": symbol,
                    "interval": interval,
                    "triggered_at": _now,
                    "candle": closed_candle,
                    "trigger_values": {
                        "composite": True,
                        "omm_state": _omm.state if _omm else None,
                        "structure_matched": _detail["structure_matched"],
                        "strategy_matched": _detail["strategy_matched"],
                    },
                    "reason": _reason,
                }
                _hist = AlertHistoryModel(
                    id=_entry["id"], rule_id=_entry["rule_id"], symbol=_entry["symbol"],
                    interval=_entry["interval"], triggered_at=_entry["triggered_at"],
                    candle_json=json.dumps(_entry["candle"]),
                    trigger_values=json.dumps(_entry["trigger_values"]),
                    reason=_entry["reason"],
                )
                db.add(_hist)
                if _row.last_triggered_at is not None or True:  # always update
                    _row.last_triggered_at = _now
                _rn = (await db.execute(select(AlertRuleModel).where(AlertRuleModel.id == _row.id))).scalar_one_or_none()
                _rname = _rn.name if _rn else None
                _subj, _plain, _html = _build_notification_text(_entry, _rname)
                _ncfg = _load_notification_config()
                _gm = _ncfg.get('gmail', {})
                _tg = _ncfg.get('telegram', {})
                if _gm.get('enabled'):
                    _dispatch('gmail', to=_gm.get('to', ''), subject=_subj, body=_plain,
                              smtp_user=_gm.get('smtp_user', ''), smtp_password=_gm.get('smtp_password', ''))
                if _tg.get('enabled'):
                    _dispatch('telegram', bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=_html)
                triggered.append(_entry)

        await db.commit()
    return triggered
