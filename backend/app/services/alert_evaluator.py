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
class ConditionGroup:
    logic: Literal['AND', 'OR']
    conditions: list = field(default_factory=list)


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


def _evaluate_condition(condition, closed_candle: dict, indicators: dict,
                        signals: list[dict], candle_time: str) -> tuple[bool, dict]:
    trigger_values: dict = {}

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
    return f' {rule.group.logic} '.join(p for p in parts if p)


def evaluate_rules(rules: list[AlertRuleInput], closed_candle: dict,
                   all_candles: list[dict], indicators: dict, signals: list[dict],
                   now: datetime) -> list[dict]:
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
            met, tv = _evaluate_condition(c, closed_candle, indicators, signals, closed_candle['time'])
            accumulated_trigger_values.update(tv)
            evaluations.append(met)

        triggered = all(evaluations) if rule.group.logic == 'AND' else any(evaluations)

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
