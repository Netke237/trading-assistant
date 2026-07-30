# backend/app/services/alert_evaluator.py
"""Python mirror of frontend/lib/chartAlertEngine.ts — server-side alert rule evaluation."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

logger = logging.getLogger(__name__)


@dataclass
class PriceCondition:
    kind: Literal['price']
    operator: str
    value: float
    sustain_minutes: Optional[int] = None


@dataclass
class IndicatorCondition:
    kind: Literal['indicator']
    indicator: str
    operator: str
    value: float
    sustain_minutes: Optional[int] = None


@dataclass
class StructureCondition:
    kind: Literal['structure']
    signal_kind: str
    direction: Optional[str] = None
    min_confidence: Optional[int] = None
    sustain_minutes: Optional[int] = None


@dataclass
class RegimeCondition:
    kind: Literal['regime']
    model: str = 'OMM'        # 'OMM' | 'HMM' | 'HMM_directional' | 'any'
    state: str = 'Bull'       # 'Bull' | 'Bear' | 'Choppy' | 'any'
    min_conviction: Optional[float] = None
    sustain_minutes: Optional[int] = None


@dataclass
class ConditionGroup:
    logic: Literal['AND', 'OR', 'N_OF_M']
    conditions: list = field(default_factory=list)
    n_of_m_threshold: Optional[int] = None


@dataclass
class AlertRuleInput:
    id: str
    name: str
    symbol: str
    interval: str
    enabled: bool
    group: ConditionGroup
    cooldown_minutes: int
    expiry_date: Optional[str]
    created_at: str
    last_triggered_at: Optional[str]
    condition_state: dict = field(default_factory=dict)


def make_history_id() -> str:
    return uuid.uuid4().hex[:10]


def is_cooldown_passed(rule: AlertRuleInput, now: datetime) -> bool:
    # Only reads .last_triggered_at and .cooldown_minutes — kept intentionally
    # duck-typed so chart_alerts.py's composite-rule path can call this with a
    # raw AlertRuleModel ORM row (which exposes the same two attribute names)
    # instead of constructing an AlertRuleInput. If either attribute is ever
    # renamed on ONE of these two types without the other, this silently
    # breaks with no type-checker warning — keep the names in sync.
    if not rule.last_triggered_at:
        return True
    try:
        last_ms = datetime.fromisoformat(rule.last_triggered_at.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return True
    return (now - last_ms).total_seconds() >= rule.cooldown_minutes * 60


def _is_expired(rule: AlertRuleInput, now: datetime) -> bool:
    if not rule.expiry_date:
        return False
    try:
        expiry = datetime.fromisoformat(rule.expiry_date)
        return now > expiry
    except (ValueError, AttributeError):
        return False


def _compare(op: str, a: float, b: float) -> bool:
    ops = {
        '>': lambda x, y: x > y,
        '<': lambda x, y: x < y,
        '>=': lambda x, y: x >= y,
        '<=': lambda x, y: x <= y,
    }
    return ops.get(op, lambda x, y: False)(a, b)


_REGIME_MODEL_NAMES = ('OMM', 'HMM', 'HMM_directional')


def _evaluate_regime_condition(condition, regime_by_model: Optional[dict]) -> tuple[bool, dict]:
    if not regime_by_model:
        return False, {}
    if condition.model == 'any':
        # Check every available model's snapshot, not just whichever happens to be
        # present first — a rule with model='any' means "match if either model
        # reports this state," not "match against OMM if OMM data exists, HMM only
        # as an afterthought." Model name travels with each candidate so the
        # sign-flip below can stay scoped to OMM specifically.
        candidates = [
            (name, regime_by_model.get(name)) for name in _REGIME_MODEL_NAMES if regime_by_model.get(name)
        ]
    else:
        regime = regime_by_model.get(condition.model)
        candidates = [(condition.model, regime)] if regime else []
    if not candidates:
        return False, {}
    for model_name, regime in candidates:
        state_match = condition.state == 'any' or regime.get('state') == condition.state
        conviction = regime.get('conviction')
        # OMM conviction is computed with a fixed Bullish framing (positive = model
        # favors Bull persisting). For a condition targeting the Bear state, flip the
        # sign so min_conviction consistently means "how strongly does the regime
        # favor the selected state" — otherwise a strongly-Bear regime shows up as
        # strongly-negative conviction and can never clear a positive min_conviction
        # threshold. This is scoped to OMM specifically: 'HMM' and 'HMM_directional'
        # report an unsigned p_stay-based conviction with no Bull/Bear framing to
        # flip — flipping it there would turn a legitimately high value negative and
        # make it fail min_conviction for no reason.
        if conviction is not None and model_name == 'OMM' and condition.state == 'Bear':
            conviction = -conviction
        conviction_match = (
            condition.min_conviction is None
            or (conviction is not None and conviction >= condition.min_conviction)
        )
        if state_match and conviction_match:
            return True, {'regime_state': 1}
    return False, {}


def build_regime_snapshot(candles: list[dict]) -> dict:
    """Compute {'OMM': {...}, 'HMM': {...}, 'HMM_directional': {...}} regime data for
    regime-kind alert conditions.

    A missing key means that model's regime could not be computed (insufficient
    bars, or hmmlearn unavailable) — matching conditions for that model fail closed
    rather than raising.

    OMM conviction is always computed with a fixed Bullish framing (RegimeCondition
    has no direction field to pick a framing from); _evaluate_regime_condition()
    only flips the sign for OMM Bear-state conditions, since OMM is the only model
    here whose conviction is Bullish-framed — 'HMM' and 'HMM_directional' report an
    unsigned p_stay-based conviction with no directional axis to flip.
    """
    closes = [c["close"] for c in candles] if candles else []
    snapshot: dict = {}

    if len(closes) >= 100:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes)
        if omm is not None:
            snapshot['OMM'] = {'state': omm.state, 'conviction': omm.conviction_pct}

    if len(candles) >= 200:
        from app.services.regime_hmm import compute_intraday_hmm
        hmm = compute_intraday_hmm(candles)
        if hmm is not None:
            # HmmResult has no conviction score; p_stay (probability of remaining
            # in the detected state) is the closest available confidence metric —
            # the regime-snapshot endpoint already surfaces P(stay) for HMM users.
            snapshot['HMM'] = {'state': hmm.state, 'conviction': round(hmm.p_stay * 100, 1)}

    if len(candles) >= 200:
        from app.services.regime_hmm_daily import compute_directional_hmm
        dhmm = compute_directional_hmm(candles)
        if dhmm is not None:
            # Same p_stay-as-conviction proxy as 'HMM' above — DirectionalHmmResult
            # has no separate conviction score either.
            snapshot['HMM_directional'] = {'state': dhmm.state, 'conviction': round(dhmm.p_stay * 100, 1)}

    return snapshot


def _evaluate_condition(condition, closed_candle: dict, indicators: dict,
                        signals: list[dict], candle_time: str,
                        regime_by_model: Optional[dict] = None) -> tuple[bool, dict]:
    trigger_values: dict = {}

    if condition.kind == 'regime':
        return _evaluate_regime_condition(condition, regime_by_model)

    if condition.kind == 'price':
        trigger_values['close'] = closed_candle['close']
        return _compare(condition.operator, closed_candle['close'], condition.value), trigger_values

    if condition.kind == 'indicator':
        series = indicators.get(condition.indicator)
        if not series:
            return False, trigger_values
        idx = next((i for i, p in enumerate(series) if p['time'] == candle_time), -1)
        if idx == -1:
            return False, trigger_values
        current_value = series[idx]['value']
        # Indicator series returns None for warm-up candles (before EMA/RSI
        # period is satisfied). Comparing None with a float raises TypeError —
        # treat as condition not met rather than crashing the evaluator.
        if current_value is None:
            return False, trigger_values
        trigger_values[condition.indicator] = current_value

        if condition.operator == 'crosses_above':
            if idx <= 0:
                return False, trigger_values
            prev_value = series[idx - 1]['value']
            return current_value > condition.value and prev_value <= condition.value, trigger_values
        if condition.operator == 'crosses_below':
            if idx <= 0:
                return False, trigger_values
            prev_value = series[idx - 1]['value']
            return current_value < condition.value and prev_value >= condition.value, trigger_values
        return _compare(condition.operator, current_value, condition.value), trigger_values

    if condition.kind == 'structure':
        for s in signals:
            if s.get('kind') != condition.signal_kind:
                continue
            if condition.direction and s.get('direction') != condition.direction:
                continue
            if condition.min_confidence is not None:
                conf = s.get('confidence', 0) or 0
                if conf < condition.min_confidence:
                    continue
            signal_time = s.get('time') or s.get('time_start', '')
            if signal_time >= candle_time:
                trigger_values[condition.signal_kind] = 1
                return True, trigger_values
        return False, trigger_values

    return False, trigger_values


_OPERATOR_PHRASES = {
    '>': 'above', '<': 'below', '>=': 'at or above', '<=': 'at or below',
    'crosses_above': 'crosses above', 'crosses_below': 'crosses below',
}

_STRUCTURE_LABELS = {
    'BOS': 'Breakout structure',
    'CHoCH': 'Reversal structure',
    'FVG': 'Price gap',
    'OrderBlock': 'Order block',
    'Divergence': 'Divergence',
}


def _condition_label(condition, trigger_values: dict | None = None) -> str:
    """Plain-English label for a single condition, used to build the per-condition
    checklist shown in redesigned notification text (see chart_alerts.py's
    _build_notification_text). Kept separate from _build_reason below, which
    stays untouched for backward compatibility with existing callers/tests.

    Includes disambiguating detail (direction, regime model, min conviction,
    live indicator/price reading) so two conditions that differ only in one of
    these fields don't render as identical checklist lines -- that would just
    reintroduce the "which one actually fired" ambiguity this checklist exists
    to eliminate.
    """
    tv = trigger_values or {}
    if condition.kind == 'price':
        # Same reachability as the regime/structure null guards above:
        # ConditionGroupIn.conditions is an untyped list with no per-item
        # schema, so a raw POST /rules call can send an explicit null for
        # operator/value and it reaches here as None rather than a dataclass
        # default (there is no default for these two fields).
        if condition.operator is None or condition.value is None:
            return 'Price condition'
        phrase = _OPERATOR_PHRASES.get(condition.operator, condition.operator)
        label = f'Price {phrase} {condition.value}'
        close = tv.get('close')
        if isinstance(close, (int, float)):
            label += f' (was {close:.2f})'
        return label
    if condition.kind == 'indicator':
        if not condition.indicator or condition.operator is None or condition.value is None:
            return 'Indicator condition'
        phrase = _OPERATOR_PHRASES.get(condition.operator, condition.operator)
        label = f'{condition.indicator} {phrase} {condition.value}'
        val = tv.get(condition.indicator)
        if isinstance(val, (int, float)):
            label += f' (was {val:.2f})'
        return label
    if condition.kind == 'regime':
        # `model`/`state` default to 'OMM'/'Bull' only when the JSON key is
        # ABSENT (see _deserialize_rule's c.get('model', 'OMM')) -- a raw API
        # call can send an explicit null for either, which reaches here as
        # None, not the dataclass default. Treat both null and 'any' as "any
        # state"/no model qualifier rather than rendering the literal word
        # "None", which would silently reintroduce the exact "which one fired"
        # ambiguity this checklist exists to eliminate.
        state = condition.state
        state_label = 'any state' if not state or state == 'any' else state
        label = f'Trend regime: {state_label}'
        if condition.model and condition.model not in ('OMM', 'any'):
            label += f' ({condition.model} model)'
        if condition.min_conviction is not None:
            label += f', conviction ≥{condition.min_conviction}%'
        return label
    if condition.kind == 'structure':
        if not condition.signal_kind:
            return 'Structure signal'
        base = _STRUCTURE_LABELS.get(condition.signal_kind, condition.signal_kind)
        suffix = f'{condition.signal_kind}, {condition.direction}' if condition.direction else condition.signal_kind
        return f'{base} ({suffix})'
    return 'Condition'


def _build_reason(rule: AlertRuleInput, trigger_values: dict) -> str:
    if not rule.group.conditions:
        return ''
    parts = []
    for c in rule.group.conditions:
        if c.kind == 'price':
            parts.append(f'Price {c.operator} {c.value}')
        elif c.kind == 'indicator':
            val = trigger_values.get(c.indicator)
            val_str = f' (was {val:.2f})' if val is not None else ' (was N/A)'
            parts.append(f'{c.indicator} {c.operator} {c.value}{val_str}')
        elif c.kind == 'structure':
            parts.append(f'{c.signal_kind} {c.direction or ""} detected'.strip())
        elif c.kind == 'regime':
            conv_str = f' (conv≥{c.min_conviction}%)' if c.min_conviction is not None else ''
            model_str = f'{c.model} ' if c.model != 'any' else ''
            parts.append(f'Regime {model_str}state = {c.state}{conv_str}')
    sep = (f' ({rule.group.n_of_m_threshold or 1}-of-{len(rule.group.conditions)}) '
           if rule.group.logic == 'N_OF_M' else f' {rule.group.logic} ')
    return sep.join(p for p in parts if p)


def evaluate_rules(rules: list[AlertRuleInput], closed_candle: dict,
                   all_candles: list[dict], indicators: dict, signals: list[dict],
                   now: datetime, regime_by_model: Optional[dict] = None) -> list[dict]:
    results = []
    for rule in rules:
        if not rule.enabled:
            continue
        if not rule.group.conditions:
            continue
        if _is_expired(rule, now):
            continue
        # NOTE: cooldown is intentionally checked AFTER sustain-clock bookkeeping
        # below (not here) -- if it gated the whole rule this early, a condition
        # that flips false-then-true-again WHILE the rule is in cooldown would
        # never get its sustain clock cleared/restarted (the per-condition loop
        # would simply never run), so the stale pending-since timestamp survives
        # the cooldown window and lets the condition fire instantly once
        # cooldown ends, instead of respecting a fresh sustain window.

        accumulated_trigger_values: dict = {}
        evaluations = []
        for cond_index, c in enumerate(rule.group.conditions):
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'], regime_by_model)
            accumulated_trigger_values.update(tv)

            # Defensive floor: negative sustain_minutes (e.g. from a raw API call
            # that bypasses the frontend's own clamp) would otherwise make a
            # condition satisfy the elapsed-time check on the very next tick
            # after first becoming true instead of behaving as "instant" (0).
            sustain_min = getattr(c, 'sustain_minutes', None)
            if sustain_min is not None and sustain_min < 0:
                sustain_min = 0
            if sustain_min:
                key = str(cond_index)
                if met:
                    pending_since_str = rule.condition_state.get(key)
                    if pending_since_str is None:
                        # First tick this condition is true — start the clock,
                        # but it hasn't been sustained for sustain_min yet.
                        rule.condition_state[key] = now.isoformat()
                        met = False
                    else:
                        try:
                            pending_since = datetime.fromisoformat(pending_since_str)
                            elapsed_min = (now - pending_since).total_seconds() / 60.0
                            met = elapsed_min >= sustain_min
                        except (ValueError, TypeError):
                            # Corrupted condition_state -- treat as not-yet-sustained
                            # rather than raising (which would abort evaluation for
                            # every rule in this batch) or firing immediately.
                            logger.warning(
                                'sustain-state parse failed for rule %s condition %s, '
                                'treating as not-sustained', rule.id, key,
                            )
                            rule.condition_state[key] = now.isoformat()
                            met = False
                else:
                    rule.condition_state.pop(key, None)

            evaluations.append(met)

        if rule.group.logic == 'AND':
            triggered = all(evaluations)
        elif rule.group.logic == 'OR':
            triggered = any(evaluations)
        else:  # N_OF_M
            threshold = rule.group.n_of_m_threshold or 1
            triggered = sum(evaluations) >= threshold

        # Cooldown suppresses firing, but must not skip the sustain-clock
        # bookkeeping above -- see the NOTE at the top of this loop.
        if triggered and not is_cooldown_passed(rule, now):
            triggered = False

        if triggered:
            entry_id = make_history_id()
            results.append({
                'id': entry_id,
                'rule_id': rule.id,
                'symbol': rule.symbol,
                'interval': rule.interval,
                'triggered_at': now.isoformat(),
                'candle': dict(closed_candle),
                'trigger_values': accumulated_trigger_values,
                'reason': _build_reason(rule, accumulated_trigger_values),
                'checklist': [
                    {'label': _condition_label(c, accumulated_trigger_values), 'met': m}
                    for c, m in zip(rule.group.conditions, evaluations)
                ],
            })
    return results
