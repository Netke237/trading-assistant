# backend/app/routers/chart_alerts.py
"""Chart alert CRUD endpoints — alert rules and history (Phase 4)."""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.market import completed_bars_for_interval
from app.services.market_session import completed_session_bars
from app.services.scheduling_tz import MARKET_TZ
from app.database import get_db, AsyncSessionLocal
from app.models.alert import AlertRuleModel, AlertHistoryModel
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, build_regime_snapshot,
    is_cooldown_passed, _STRUCTURE_LABELS,
)
from app.services.composite_trigger_evaluator import hmm_intraday_interval_error
from app.services.historical_store import get_bars
from app.services.indicator_compute import compute_indicators_for_conditions
from app.services.market_structure import compute_structure
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
    # ge=1 + the model_validator below only gate the two mutation endpoints
    # (POST /rules, PUT /rules/{id}) that construct a ConditionGroupIn from a
    # request body. _deserialize_rule() reads n_of_m_threshold back out of
    # already-stored rule_json with a plain dict .get() (no Pydantic model in
    # that path), and alert_evaluator.py's `or 1` / chartAlertEngine.ts's `?? 1`
    # fallbacks still read that raw value -- so a legacy or corrupted row that
    # already has a 0 or out-of-range threshold persisted is NOT retroactively
    # fixed by this; it only stops new bad values from being written going forward.
    n_of_m_threshold: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode='after')
    def validate_threshold_within_condition_count(self) -> 'ConditionGroupIn':
        """Reject an n_of_m_threshold that exceeds the number of conditions --
        e.g. threshold=50 with 2 conditions doesn't crash anything, but makes
        the rule's sum(evaluations) >= threshold permanently False (silently
        un-fireable; see alert_evaluator.py's N_OF_M branch). Only checked when
        conditions is non-empty -- there's nothing meaningful to validate the
        upper bound against otherwise, and an empty-conditions group is a
        separate, pre-existing concern this fix doesn't address. Also only
        checked when logic == 'N_OF_M' -- the field is meaningless for AND/OR
        logic, so a stale/irrelevant n_of_m_threshold left over from switching
        a rule's logic away from N_OF_M must not block an otherwise-valid
        AND/OR rule.
        """
        if (
            self.logic == 'N_OF_M'
            and self.n_of_m_threshold is not None
            and self.conditions
            and self.n_of_m_threshold > len(self.conditions)
        ):
            raise ValueError(
                f'n_of_m_threshold ({self.n_of_m_threshold}) cannot exceed the number '
                f'of conditions ({len(self.conditions)})'
            )
        return self

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

class ChecklistItemIn(BaseModel):
    label: str
    met: bool

class AlertHistoryCreate(BaseModel):
    rule_id: str
    symbol: str
    interval: str
    triggered_at: str
    candle: dict
    trigger_values: dict = Field(default_factory=dict)
    reason: str
    # Validated as a real sub-model (not list[dict]) so a malformed item (e.g.
    # missing 'met') is rejected with a 422 here, before create_history_entry()
    # ever reaches db.commit() -- _build_notification_text() does unguarded
    # c['met']/c['label'] subscript access on each item, which would otherwise
    # raise a KeyError *after* the history row was already persisted, leaving
    # a row in the DB with no notification ever built or sent.
    checklist: Optional[list[ChecklistItemIn]] = None

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


def _composite_primary_model(composite: object) -> object:
    primary = composite.get('primary') if isinstance(composite, dict) else None
    return primary.get('model') if isinstance(primary, dict) else None


_NOT_COMPOSITE = object()


def _stored_pair(row: AlertRuleModel) -> tuple:
    """(interval, primary model) of a stored COMPOSITE rule; a sentinel model for
    anything else (unparseable, non-dict, standard) so it never equals a new pair."""
    try:
        parsed = json.loads(row.rule_json)
    except (TypeError, ValueError):
        return (row.interval, _NOT_COMPOSITE)
    if not isinstance(parsed, dict) or parsed.get('__type') != 'composite':
        return (row.interval, _NOT_COMPOSITE)
    return (row.interval, _composite_primary_model(parsed))


async def migrate_hmm_intraday_rule_intervals(session_factory=None) -> list[dict]:
    """A4f-rules (decision A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25): a composite
    HMM_intraday rule stored on '1D'/'1W' never fires -- evaluate_and_notify_for_symbol
    hands the HMM no intraday bars on those intervals. Move each to '5m' (what the
    dialog displayed), mark its name "(interval was 1D)", reset its sustain clock and
    log the list. Every such row (disabled ones and any user_id included); only
    '1D'/'1W', the two spellings that path treats as daily/weekly. Idempotent: a
    migrated row is '5m'. run_chart_alert_scheduler calls it at the top of each loop
    iteration until one call succeeds -- normally once, before the first tick; after
    a failure (e.g. the DB not up yet) ticks run, on unmigrated rules that cannot
    fire anyway, until a retry succeeds. A row that raises unexpectedly is logged
    and skipped, so it cannot block the others or make every retry fail."""
    factory = session_factory or AsyncSessionLocal
    migrated: list[dict] = []
    async with factory() as db:
        result = await db.execute(
            select(AlertRuleModel).where(AlertRuleModel.interval.in_(('1D', '1W')))
        )
        for row in result.scalars().all():
            try:
                parsed = json.loads(row.rule_json)
            except Exception:
                logger.debug('A4f rule migration: skipping %s, rule_json does not parse', row.id)
                continue
            try:
                if not isinstance(parsed, dict) or parsed.get('__type') != 'composite':
                    continue
                if _composite_primary_model(parsed) != 'HMM_intraday':
                    continue
                old = row.interval
                note = f' (interval was {old})'
                new_name = (row.name or '')[:200 - len(note)] + note
            except Exception:
                logger.warning('A4f rule migration: skipping %s, unexpected row shape', row.id, exc_info=True)
                continue
            row.interval = '5m'
            row.name = new_name
            row.condition_state = '{}'
            migrated.append({'id': row.id, 'symbol': row.symbol, 'name': row.name, 'from': old})
        if migrated:
            await db.commit()
    if migrated:
        listing = ', '.join(f"{m['id']} {m['symbol']} {m['from']!r}" for m in migrated)
        logger.warning(
            "A4f: migrated %d HMM_intraday composite rule(s) from a daily/weekly interval "
            "to '5m' (on that interval they could not fire): [%s]", len(migrated), listing,
        )
    return migrated

def _history_to_dict(row: AlertHistoryModel) -> dict:
    return {
        'id': row.id, 'rule_id': row.rule_id, 'symbol': row.symbol, 'interval': row.interval,
        'triggered_at': row.triggered_at, 'candle': json.loads(row.candle_json),
        'trigger_values': json.loads(row.trigger_values), 'reason': row.reason,
    }

def _parse_candle_time(raw: object) -> datetime:
    """Parse a candle's time field for use as evaluate_rules' `now` in the manual
    dry-run endpoint. Accepts ISO strings (with or without a trailing 'Z') or
    epoch-seconds numbers; falls back to wall-clock time on anything else so a
    malformed pasted candle doesn't hard-crash the request.

    Always returns a naive datetime (tzinfo stripped from any offset-aware
    parse) -- evaluate_rules' cooldown/sustain math does now - pending_since,
    and pending_since is always the naive isoformat() of a previous call's
    return value. A dry-run candle list that mixes 'Z'-suffixed and bare ISO
    timestamps would otherwise alternate between aware and naive `now` values
    across the loop, raising TypeError on the subtraction and permanently
    resetting the sustain clock every tick instead of ever letting it elapse.
    """
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw)
        if isinstance(raw, str):
            parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
    except (ValueError, TypeError, OSError):
        pass
    logger.warning('test_rule: could not parse candle time %r, using current time', raw)
    return datetime.now()

_INTERVAL_LABELS = {
    '1D': 'Daily chart', '1W': 'Weekly chart',
    '1min': '1-minute chart', '5min': '5-minute chart', '15min': '15-minute chart',
    '1h': 'Hourly chart', '4h': '4-hour chart',
}


def _interval_label(interval: str) -> str:
    return _INTERVAL_LABELS.get(interval, f'{interval} chart')


def _composite_checklist(td: dict, detail: dict) -> list[dict]:
    """Best-effort per-condition checklist for composite (Markov + N-of-M) rules,
    mirroring the standard-rule checklist so composite alerts get the same
    plain-language notification treatment instead of being stuck on the old
    format. The primary Markov gate is always shown as met (evaluate_scheduled
    already required it to pass before any confirmation is checked).

    Matching a confirmation against describe_match()'s matched-name lists can't
    tell apart two confirmations of the SAME signal_kind with different
    directions -- describe_match() only returns which kind names matched, not
    which directional variant. The shipping AlertRuleBuilder/CompositeAlertDialog
    UI can't currently create that configuration (one direction per rule, unique
    signal_kind checkboxes), but POST /rules accepts composite_def directly with
    no such validation, so it's reachable. Rather than silently mislabel both
    rows as met, flag same-kind rows with a caveat so the ambiguity is visible
    instead of hidden -- exactly the kind of thing this whole feature exists to
    surface, not bury.
    """
    primary = td.get('primary', {}) or {}
    to_state = primary.get('to_state')
    primary_label = f"Trend regime: {'any state' if not to_state or to_state == 'any' else to_state}"
    if primary.get('model') not in (None, 'OMM', 'any'):
        primary_label += f" ({primary['model']} model)"
    rows = [{'label': primary_label, 'met': True}]

    structure_matched = detail.get('structure_matched', [])
    confirmations = td.get('confirmations', [])
    # Group by signal_kind -> set of distinct directions configured for it, not
    # just a raw count -- two confirmations of the same kind AND same direction
    # are redundant, not ambiguous (describe_match() can't misattribute a match
    # between them since there's nothing to distinguish). The caveat below only
    # makes sense when a kind has genuinely different directional variants.
    kind_directions: dict[str, set] = {}
    for c in confirmations:
        k = c.get('signal_kind', '')
        kind_directions.setdefault(k, set()).add(c.get('direction'))
    for c in confirmations:
        kind = c.get('signal_kind', '')
        base = _STRUCTURE_LABELS.get(kind, kind)
        direction = c.get('direction')
        suffix = f'{kind}, {direction}' if direction else kind
        label = f'{base} ({suffix})'
        if direction and len(kind_directions.get(kind, set())) > 1:
            label += ' [same-signal match, direction not confirmed]'
        rows.append({'label': label, 'met': kind in structure_matched})

    strategy_matched = detail.get('strategy_matched', [])
    for key in td.get('strategy_confirmations', []):
        rows.append({'label': f'Strategy: {key}', 'met': key in strategy_matched})

    return rows


def _composite_need_suffix(td: dict) -> str:
    """Accurate "(only needs...)" suffix for a composite rule, for use as
    _build_notification_text's need_suffix_override. Composite rules gate on
    TWO independent thresholds (min_confirmations for structure signals,
    min_strategy_confirmations for strategy signals) rather than the single
    N_OF_M/OR/AND model standard rules use, so this can't reuse that generic
    derivation -- without this, the composite call site left need_suffix
    permanently blank, hiding a genuine "only 1 of 3 was ever required" gap
    that standard N_OF_M rules do surface.
    """
    parts = []
    conf_total = len(td.get('confirmations', []))
    if conf_total:
        min_conf = td.get('min_confirmations', 1)
        if min_conf < conf_total:
            parts.append(f'only needs {min_conf} of {conf_total} structure signals')
    strat_total = len(td.get('strategy_confirmations', []))
    if strat_total:
        min_strat = td.get('min_strategy_confirmations', 1)
        if min_strat < strat_total:
            parts.append(f'only needs {min_strat} of {strat_total} strategy signals')
    return f" ({'; '.join(parts)})" if parts else ''


# The human-readable interval-label fix below shipped as d7237dc. An earlier
# attempt (6fb722b) was added then reverted (bab1d21) on the now-deleted
# wip/audited-fixes branch -- that history is a dead end, not a sign this
# fix is missing or was undone.
def _build_notification_text(
    entry: dict, rule_name: str | None = None,
    rule_logic: str | None = None, rule_threshold: int | None = None,
    need_suffix_override: str | None = None,
) -> tuple[str, str, str]:
    """Returns (subject, plain_body, html_body).

    ``rule_name`` is the human-readable name of the alert rule; it falls back to
    the rule id when the name is unavailable. The trigger time is rendered as a
    local Date/Time (no microseconds) to match the portfolio alert format.

    When ``entry`` carries a 'checklist' (populated by evaluate_rules() for
    standard rules, _composite_checklist() for composite rules, or -- via
    POST /alerts/history's optional checklist field -- chartAlertEngine.ts's
    own conditionLabel()-based checklist for alerts fired locally from an open
    chart tab), the plain-language layout is used: rule name first, chart
    timeframe instead of raw interval code, and a per-condition ✓/✗ checklist
    instead of the flat "(N-of-M)"-joined condition text. Entries without a
    checklist fall back to the original technical Symbol/Interval/Trigger/
    Values layout -- this only happens today for a raw POST /alerts/history
    call that omits the optional field.

    ``need_suffix_override``, when not None, is used verbatim as the
    "Conditions met: X of Y{suffix}" suffix instead of deriving it from
    rule_logic/rule_threshold. Composite rules have two independent thresholds
    (min_confirmations for structure signals, min_strategy_confirmations for
    strategy signals) that don't fit the single N_OF_M/OR/AND model standard
    rules use, so the composite call site computes its own accurate suffix
    (or an empty string when nothing's worth noting) and passes it here rather
    than being silently dropped to a blank suffix.
    """
    sym = entry.get('symbol', '?')
    ival = entry.get('interval', '?')
    reason = entry.get('reason', '')
    triggered_at = entry.get('triggered_at', '')
    tv = entry.get('trigger_values', {})
    rule_id = entry.get('rule_id', '')
    checklist = entry.get('checklist')

    date_str, time_str = _format_dt(triggered_at)
    rule_label = rule_name or rule_id or '(unnamed rule)'

    subject = f'Bamendjou Chart Alert - {rule_label} - {sym} [{_interval_label(ival)}]'

    if checklist:
        close = (entry.get('candle') or {}).get('close')
        price_line = f'Price at trigger: ${close:.2f}\n' if isinstance(close, (int, float)) else ''

        matched = sum(1 for c in checklist if c['met'])
        total = len(checklist)
        if need_suffix_override is not None:
            need_suffix = need_suffix_override
        elif rule_logic == 'N_OF_M':
            # `rule_threshold` is the rule's configured n_of_m_threshold, or None
            # for rules saved before that field existed (see
            # test_legacy_rule_without_stored_threshold_still_defaults_to_none in
            # test_n_of_m_threshold_persistence.py) -- `or 1` mirrors
            # evaluate_rules()'s own fallback so this text always matches real
            # runtime behavior for both old and new rules.
            _threshold = rule_threshold or 1
            need_suffix = '' if _threshold >= total else f' (only needs {_threshold} to fire)'
        elif rule_logic == 'OR':
            need_suffix = ' (only needs 1 to fire)'
        elif rule_logic == 'AND':
            need_suffix = ' (all required)'
        else:
            need_suffix = ''

        # Telegram's HTML parse_mode only recognizes a small tag allowlist
        # (b/i/u/s/a/code/pre/blockquote) -- NOT <br> or any block tag. An
        # unsupported tag makes the Bot API reject the whole message with a
        # 400, which dispatch.py's error handling swallows into a log line with
        # no user-visible signal, so this is easy to ship broken and never
        # notice. Line breaks must be plain '\n' in both bodies -- Telegram
        # renders literal newlines as line breaks natively in HTML mode, same
        # as the plain-text email body.
        check_lines = '\n'.join(
            f"{'✓' if c['met'] else '✗'} {c['label']}" for c in checklist
        )

        plain = (
            f'{rule_label}\n'
            f'{sym} · {_interval_label(ival)} · {date_str}, {time_str} {_TZ_LABEL}\n'
            f'{price_line}'
            f'\nConditions met: {matched} of {total}{need_suffix}\n\n'
            f'  {check_lines.replace(chr(10), chr(10) + "  ")}\n'
        )
        # Rule names are free text (AlertRuleCreate.name has no format
        # constraint) and condition-group JSON is stored/read back without
        # schema validation on string fields (indicator name, signal_kind,
        # direction, state), so a rule built via a raw API call rather than the
        # UI could smuggle a literal '<' or '&' into any of these. Escaping
        # before interpolating into the HTML body prevents that from being
        # parsed as (invalid) markup -- the exact same silent-Telegram-failure
        # mode the <br> bug caused, just via user-controlled text instead of a
        # hardcoded tag.
        check_lines_html = '\n'.join(
            f"{'✓' if c['met'] else '✗'} {html_lib.escape(c['label'])}" for c in checklist
        )
        html = (
            f'<b>{html_lib.escape(rule_label)}</b>\n'
            f'{html_lib.escape(sym)} · {html_lib.escape(_interval_label(ival))} · {date_str}, {time_str} {_TZ_LABEL}\n'
            f'{price_line}'
            f'\n<b>Conditions met: {matched} of {total}{need_suffix}</b>\n\n'
            f'{check_lines_html}\n'
        )
        return subject, plain, html

    values_lines = []
    for k, v in tv.items():
        if isinstance(v, float):
            values_lines.append(f'{k}={v:.2f}')
        else:
            values_lines.append(f'{k}={v}')
    values_str = '  '.join(values_lines)

    plain = (f'Symbol:    {sym}\nInterval:  {_interval_label(ival)}\n'
             f'Date:      {date_str}\nTime:      {time_str} {_TZ_LABEL}\n'
             f'Trigger:   {reason}\nValues:    {values_str}\nRule:      {rule_label}\n')

    # Telegram mirrors the email body exactly (same fields, same order), with a
    # bold first line equal to the email subject (which carries the rule name).
    # Escaped for the same reason as the checklist branch above: rule name and
    # reason text are free-form and could otherwise be parsed as invalid HTML.
    html = (f'<b>{html_lib.escape(subject)}</b>\n\n'
            f'<b>Symbol:</b>    {html_lib.escape(sym)}\n<b>Interval:</b>  {html_lib.escape(_interval_label(ival))}\n'
            f'<b>Date:</b>      {date_str}\n<b>Time:</b>      {time_str} {_TZ_LABEL}\n'
            f'<b>Trigger:</b>   {html_lib.escape(reason)}\n<b>Values:</b>    {html_lib.escape(values_str)}\n'
            f'<b>Rule:</b>      {html_lib.escape(rule_label)}\n')

    return subject, plain, html

def _deserialize_rule(rule_json_str: str, row: AlertRuleModel) -> AlertRuleInput:
    group_data = json.loads(rule_json_str)
    conditions = []
    for c in group_data.get('conditions', []):
        kind = c.get('kind', '')
        if kind == 'price':
            conditions.append(PriceCondition(
                kind='price', operator=c['operator'], value=c['value'],
                sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'indicator':
            conditions.append(IndicatorCondition(
                kind='indicator', indicator=c['indicator'], operator=c['operator'], value=c['value'],
                sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'structure':
            conditions.append(StructureCondition(
                kind='structure', signal_kind=c['signal_kind'], direction=c.get('direction'),
                min_confidence=c.get('min_confidence'), sustain_minutes=c.get('sustain_minutes'),
            ))
        elif kind == 'regime':
            conditions.append(RegimeCondition(
                kind='regime', model=c.get('model', 'OMM'), state=c.get('state', 'Bull'),
                min_conviction=c.get('min_conviction'), sustain_minutes=c.get('sustain_minutes'),
            ))
    return AlertRuleInput(
        id=row.id, name=row.name, symbol=row.symbol, interval=row.interval,
        enabled=bool(row.enabled),
        group=ConditionGroup(
            logic=group_data.get('logic', 'AND'),
            conditions=conditions,
            n_of_m_threshold=group_data.get('n_of_m_threshold'),
        ),
        cooldown_minutes=row.cooldown_minutes, expiry_date=row.expiry_date,
        created_at=row.created_at, last_triggered_at=row.last_triggered_at,
        condition_state=json.loads(row.condition_state or '{}'),
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
        _err = hmm_intraday_interval_error(body.composite_def, body.interval)
        if _err:
            raise HTTPException(status_code=422, detail=_err)
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
    # A4f-rules: refuse an HMM_intraday composite on a non-intraday interval --
    # unless this PUT leaves the stored (interval, primary model) pair as it is, so a
    # legacy rule the startup migration could not move stays toggleable/renameable.
    # A stale '1D' sent back onto a migrated '5m' rule changes the pair: refused.
    if body.rule_type == 'composite' and body.composite_def:
        _err = hmm_intraday_interval_error(body.composite_def, body.interval)
        if _err and _stored_pair(row) != (body.interval, _composite_primary_model(body.composite_def)):
            raise HTTPException(status_code=422, detail=_err)
    row.name = body.name
    row.symbol = body.symbol.upper()
    row.interval = body.interval
    row.enabled = body.enabled
    _old_rule_json = row.rule_json
    if body.rule_type == 'composite':
        if not body.composite_def:
            raise HTTPException(status_code=422, detail='composite_def is required when rule_type is "composite"')
        row.rule_json = json.dumps({"__type": "composite", **body.composite_def})
    else:
        row.rule_json = json.dumps(body.group.model_dump())
    row.cooldown_minutes = body.cooldown_minutes
    row.expiry_date = body.expiry_date
    # condition_state is keyed by each standard condition's positional index (or
    # the literal "composite" key) into the condition list. If the conditions
    # actually changed shape, any existing sustain-clock entries are meaningless
    # -- worse, misleading: a stale pending-since timestamp for what used to be
    # condition 0 would get inherited by whatever condition is at index 0 now,
    # letting it fire instantly instead of respecting its own sustain window.
    # But the frontend also calls this same PUT endpoint for patches that don't
    # touch conditions at all (e.g. toggling `enabled` re-sends the full rule
    # via updateRule -> putRuleToAPI) -- comparing old vs new rule_json first
    # means a same-conditions PUT doesn't needlessly wipe in-progress sustain
    # state that had nothing to do with the actual edit.
    if row.rule_json != _old_rule_json:
        row.condition_state = '{}'
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
    if body.checklist:
        entry_dict['checklist'] = [item.model_dump() for item in body.checklist]
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
        await _dispatch('gmail',
            to=_gmail.get('to', ''), subject=subject, body=plain_body,
            smtp_user=_gmail.get('smtp_user', ''), smtp_password=_gmail.get('smtp_password', ''),
        )
    if _tg.get('enabled'):
        logger.info('Dispatching alert Telegram for %s [%s]', entry_dict.get('symbol'), entry_dict.get('interval'))
        await _dispatch('telegram',
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
        # Use the candle's own timestamp as "now" (not wall-clock time) so
        # cooldown and sustain_minutes are evaluated against simulated time —
        # replaying history in real time would make sustain windows never elapse.
        candle_time = _parse_candle_time(candle.get('time'))
        results = evaluate_rules([rule_input], candle, window, body.indicators, body.signals, candle_time, regime_by_model)
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

def closed_candle_structure(candles: list[dict], closed_candle: dict, interval: str, symbol: str,
                            ht_candles: list[dict] | None = None) -> list[dict]:
    """A4e: structure signals for ALERT evaluation, computed on `candles` up to and
    including `closed_candle` -- never on the bars after it (the forming candle).

    A structure condition is met by a signal timed at or after the closed candle,
    and a composite confirmation by any signal in the list, so signals computed on
    the forming bar fired the closed candle's rule on a break that had not closed,
    or on a swing only the forming bar confirmed (find_swings looks right). Filtering
    full-list signals by time cannot undo the latter, hence the recompute.

    The closed candle is matched by time, searched from the end. If it is not in
    `candles`, returns []: fail closed rather than fall back to the forming bar.
    Both callers take closed_candle from `candles` itself, so that is unreachable.
    The display `structure` message (chart.py) stays on the full list.
    """
    closed_time = closed_candle.get('time')
    for i in range(len(candles) - 1, -1, -1):
        if candles[i].get('time') == closed_time:
            return compute_structure(candles[:i + 1], interval, symbol, ht_candles)
    return []


async def evaluate_and_notify_for_symbol(
    symbol: str, interval: str, closed_candle: dict,
    all_candles: list[dict], signals: list[dict],
    as_of: float | None = None,
) -> list[dict]:
    """Load enabled rules, evaluate, persist history, enqueue notifications.

    A4c: every REGIME model here (standard rules' regime conditions, composite
    rules' OMM and HMM_intraday primaries) fits on the COMPLETED candles of an
    intraday `interval` -- completeness judged at `as_of`, the wall-clock time
    `all_candles` was fetched (chart_cache.get_intraday_with_fetched_at), since
    a cached candle that was forming then stays partial. None = time.time().

    A4g: on 1D/1W the same readers -- plus the composite `bars_daily` (HMM_daily
    and the strategy confirmations) -- drop the forming daily/weekly bar
    (market_session.completed_session_bars, judged at `as_of`).

    A4e: `signals` must come from closed_candle_structure (both callers do), i.e.
    structure computed on the candles up to `closed_candle`, not the forming bar.
    Indicators still read `all_candles`: every indicator is causal and a condition
    reads the point at closed_candle['time'], so the forming bar cannot move it
    (pinned by tests/test_a4e_closed_candle_alignment.py). The VWAP confirmation
    reads completed bars too (VWAP-CONFIRMATION-LIKE-REGIME-MODELS, 2026-09-25).
    """
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

        # A4g: on 1D/1W drop the forming daily/weekly bar, judged at the FETCH time
        # (`as_of`) like A4c -- a cached snapshot taken mid-session stays partial.
        # Each helper is a no-op on the other's intervals, so intraday is unchanged.
        _as_of_dt = datetime.fromtimestamp(as_of, MARKET_TZ) if as_of is not None else datetime.now(MARKET_TZ)
        _regime_candles = completed_session_bars(
            completed_bars_for_interval(all_candles or [], interval, now=as_of), interval, now=_as_of_dt,
        )[-MAX_LIVE_MODEL_CANDLES:]

        needs_regime = any(c.kind == 'regime' for ri in rule_inputs for c in ri.group.conditions)
        regime_by_model = build_regime_snapshot(_regime_candles) if needs_regime else None

        # Compute indicators referenced by rule conditions
        all_conditions = []
        for ri in rule_inputs:
            all_conditions.extend(ri.group.conditions)
        indicators = compute_indicators_for_conditions(all_candles, all_conditions)

        triggered = evaluate_rules(rule_inputs, closed_candle, all_candles, indicators, signals, datetime.now(), regime_by_model)

        for _ri, _row in zip(rule_inputs, rows):
            _row.condition_state = json.dumps(_ri.condition_state)
        _rule_input_by_id = {_ri.id: _ri for _ri in rule_inputs}
        _rule_row_by_id = {_row.id: _row for _row in rows}

        for entry in triggered:
            history = AlertHistoryModel(
                id=entry['id'], rule_id=entry['rule_id'], symbol=entry['symbol'],
                interval=entry['interval'], triggered_at=entry['triggered_at'],
                candle_json=json.dumps(entry['candle']),
                trigger_values=json.dumps(entry['trigger_values']),
                reason=entry['reason'],
            )
            db.add(history)

            rule_row = _rule_row_by_id.get(entry['rule_id'])
            rule_name = rule_row.name if rule_row else None
            if rule_row:
                rule_row.last_triggered_at = entry['triggered_at']

            _entry_ri = _rule_input_by_id.get(entry['rule_id'])
            subject, plain_body, html_body = _build_notification_text(
                entry, rule_name,
                rule_logic=_entry_ri.group.logic if _entry_ri else None,
                rule_threshold=_entry_ri.group.n_of_m_threshold if _entry_ri else None,
            )

            _notif_cfg = _load_notification_config()
            _gmail  = _notif_cfg.get('gmail', {})
            _tg     = _notif_cfg.get('telegram', {})

            if _gmail.get('enabled'):
                logger.info('Dispatching WS alert email for %s [%s]', entry['symbol'], entry['interval'])
                await _dispatch('gmail',
                    to=_gmail.get('to', ''), subject=subject, body=plain_body,
                    smtp_user=_gmail.get('smtp_user', ''), smtp_password=_gmail.get('smtp_password', ''),
                )
            if _tg.get('enabled'):
                logger.info('Dispatching WS alert Telegram for %s [%s]', entry['symbol'], entry['interval'])
                await _dispatch('telegram',
                    bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=html_body,
                )

        # ── Composite rule evaluation ─────────────────────────────────────────
        if composite_rows:
            from app.services.composite_trigger_evaluator import (
                completed_daily_rows, evaluate_from_context_detailed, format_composite_reason,
            )
            from app.services.regime_omm import compute_omm
            _closes = [c["close"] for c in _regime_candles]
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
                    # round-trip. A4g: its COMPLETED bars (`_regime_candles`), so
                    # HMM_daily and the rsi/bb confirmations (require_choppy_regime
                    # included) read what a composite watch on get_bars reads.
                    _bars_daily = _regime_candles
                else:
                    try:
                        _end = date.today()
                        _start = _end - timedelta(days=730)
                        # P4b: completed sessions only, as a composite watch reads.
                        _bars_daily = completed_daily_rows(await get_bars(symbol, _start, _end), _as_of_dt)
                    except Exception as _exc:
                        logger.warning("composite rule strategy-confirmation bars fetch failed for %s: %s", symbol, _exc)
                        _bars_daily = []

            # all_candles are only genuinely intraday when the rule's own interval is
            # intraday — chart.py's get_intraday(symbol, interval) returns daily candles
            # for '1D'/'1W' rules, so passing them as bars_intraday would mislabel daily
            # data as intraday to the VWAP mean-reversion check.
            # VWAP-CONFIRMATION-LIKE-REGIME-MODELS: the VWAP confirmation reads the
            # COMPLETED bars of the rule's interval (_regime_candles), like the HMM.
            _bars_intraday = _regime_candles if interval not in ("1D", "1W") else []

            # D7 (Kenneth, 2026-09-26): on 1D/1W the VWAP daily variant reads the
            # completed get_bars rows a 1D/1W composite watch reads -- never the
            # chart's daily candles or weekly bars. Fetched once per tick, and only
            # when some composite rule lists VWAP; a failed fetch fails closed ([]).
            _bars_vwap_daily: list[dict] | None = None
            if interval in ("1D", "1W") and any(
                "mean_reversion_vwap" in (_rj.get("strategy_confirmations") or [])
                for _, _rj in composite_rows
            ):
                try:
                    _end = date.today()
                    _start = _end - timedelta(days=730)
                    _bars_vwap_daily = completed_daily_rows(await get_bars(symbol, _start, _end), _as_of_dt)
                except Exception as _exc:
                    logger.warning("composite rule VWAP daily bars fetch failed for %s: %s", symbol, _exc)
                    _bars_vwap_daily = []

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
                        regime_bars_intraday=_regime_candles if interval not in ("1D", "1W") else None,
                        interval=interval, bars_vwap_daily=_bars_vwap_daily,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue

                _sustain_min = _td.get("sustain_minutes")
                if isinstance(_sustain_min, (int, float)) and _sustain_min < 0:
                    _sustain_min = 0
                try:
                    _composite_state = json.loads(_row.condition_state or '{}')
                    if _sustain_min:
                        if _fired:
                            _pending_since_str = _composite_state.get("composite")
                            if _pending_since_str is None:
                                _composite_state["composite"] = datetime.now().isoformat()
                                _row.condition_state = json.dumps(_composite_state)
                                continue
                            _pending_since = datetime.fromisoformat(_pending_since_str)
                            _elapsed_min = (datetime.now() - _pending_since).total_seconds() / 60.0
                            if _elapsed_min < _sustain_min:
                                continue
                        elif "composite" in _composite_state:
                            _composite_state.pop("composite", None)
                            _row.condition_state = json.dumps(_composite_state)
                except (ValueError, TypeError) as _exc:
                    logger.warning("composite sustain-state parse failed for %s, treating as not-sustained: %s", symbol, _exc)
                    _fired = False

                if not _fired:
                    continue

                # Composite rules had NO cooldown gate at all — unlike standard
                # rules (evaluate_rules() -> is_cooldown_passed internally), which
                # meant a composite rule ALWAYS fired and emailed TWICE whenever the
                # live WS path (an open chart tab) and the background scheduler
                # (chart_alert_scheduler.py) both evaluated the same closed candle.
                # This narrows that to the same residual race standard rules already
                # accept (chart_alert_scheduler.py:78-81's documented "known
                # limitation"): `_row.last_triggered_at` is read once at the top of
                # this function and only written back at the final db.commit(), so
                # two calls that are ALREADY in flight concurrently at the moment
                # this check runs can still both pass it — this does not add locking,
                # it only removes the "every double-evaluation duplicates" guarantee.
                # Reuses the exact function the standard-rule path already relies on
                # — AlertRuleModel exposes the same cooldown_minutes/last_triggered_at
                # attributes is_cooldown_passed expects, so _row can be passed directly.
                if not is_cooldown_passed(_row, datetime.now()):
                    # Log at debug level: without this, a cooldown-suppressed fire
                    # is indistinguishable in the logs from "the rule never fired,"
                    # which would make "why didn't I get an email" undiagnosable.
                    logger.debug(
                        'composite rule %s (%s [%s]) suppressed by cooldown_minutes=%s',
                        _row.id, symbol, interval, _row.cooldown_minutes,
                    )
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
                    "checklist": _composite_checklist(_td, _detail),
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
                _subj, _plain, _html = _build_notification_text(
                    _entry, _rname, need_suffix_override=_composite_need_suffix(_td),
                )
                _ncfg = _load_notification_config()
                _gm = _ncfg.get('gmail', {})
                _tg = _ncfg.get('telegram', {})
                if _gm.get('enabled'):
                    await _dispatch('gmail', to=_gm.get('to', ''), subject=_subj, body=_plain,
                              smtp_user=_gm.get('smtp_user', ''), smtp_password=_gm.get('smtp_password', ''))
                if _tg.get('enabled'):
                    await _dispatch('telegram', bot_token=_tg.get('bot_token', ''), chat_id=_tg.get('chat_id', ''), text=_html)
                triggered.append(_entry)

        await db.commit()
    return triggered
