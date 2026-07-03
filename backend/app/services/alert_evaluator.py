# backend/app/services/alert_evaluator.py
"""Python mirror of frontend/lib/chartAlertEngine.ts — server-side alert rule evaluation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal


@dataclass
class PriceCondition:
    kind: Literal['price']
    operator: str
    value: float


@dataclass
class IndicatorCondition:
    kind: Literal['indicator']
    indicator: str
    operator: str
    value: float


@dataclass
class StructureCondition:
    kind: Literal['structure']
    signal_kind: str
    direction: Optional[str] = None
    min_confidence: Optional[int] = None


@dataclass
class RegimeCondition:
    kind: Literal['regime']
    model: str = 'OMM'        # 'OMM' | 'HMM' | 'any'
    state: str = 'Bull'       # 'Bull' | 'Bear' | 'Choppy' | 'any'
    min_conviction: Optional[float] = None


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


def make_history_id() -> str:
    return uuid.uuid4().hex[:10]


def _is_cooldown_passed(rule: AlertRuleInput, now: datetime) -> bool:
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


def _evaluate_regime_condition(condition, regime_by_model: Optional[dict]) -> tuple[bool, dict]:
    if not regime_by_model:
        return False, {}
    if condition.model == 'any':
        # Check every available model's snapshot, not just whichever happens to be
        # present first — a rule with model='any' means "match if either model
        # reports this state," not "match against OMM if OMM data exists, HMM only
        # as an afterthought."
        candidates = [r for r in (regime_by_model.get('OMM'), regime_by_model.get('HMM')) if r]
    else:
        regime = regime_by_model.get(condition.model)
        candidates = [regime] if regime else []
    if not candidates:
        return False, {}
    for regime in candidates:
        state_match = condition.state == 'any' or regime.get('state') == condition.state
        conviction = regime.get('conviction')
        # build_regime_snapshot() computes OMM conviction with a fixed Bullish framing
        # (positive = model favors Bull persisting). For a condition targeting the Bear
        # state, flip the sign so min_conviction consistently means "how strongly does
        # the regime favor the selected state" — otherwise a strongly-Bear regime shows
        # up as strongly-negative conviction and can never clear a positive min_conviction
        # threshold. Other states (Choppy/any/HMM's Trending/Mean-reverting/...) have no
        # natural Bull/Bear opposite, so their conviction is left as computed.
        if conviction is not None and condition.state == 'Bear':
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
        if not _is_cooldown_passed(rule, now):
            continue

        accumulated_trigger_values: dict = {}
        evaluations = []
        for c in rule.group.conditions:
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'], regime_by_model)
            accumulated_trigger_values.update(tv)
            evaluations.append(met)

        if rule.group.logic == 'AND':
            triggered = all(evaluations)
        elif rule.group.logic == 'OR':
            triggered = any(evaluations)
        else:  # N_OF_M
            threshold = rule.group.n_of_m_threshold or 1
            triggered = sum(evaluations) >= threshold

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
            })
    return results
