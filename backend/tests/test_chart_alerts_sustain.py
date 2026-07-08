# backend/tests/test_chart_alerts_sustain.py
"""Integration test: sustain_minutes survives a round trip through
_deserialize_rule -> evaluate_rules -> persisted condition_state."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from app.routers.chart_alerts import _deserialize_rule
from app.services.alert_evaluator import evaluate_rules


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _rule_row(condition_state='{}'):
    rule_json = json.dumps({
        'logic': 'AND',
        'conditions': [{'kind': 'price', 'operator': '>', 'value': 100, 'sustain_minutes': 5}],
    })
    return AlertRuleModel(
        id='rule-1', user_id='default', name='Sustain rule', symbol='AAPL', interval='15min',
        enabled=True, rule_json=rule_json, cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
        condition_state=condition_state,
    )


@pytest.mark.asyncio
async def test_deserialized_rule_carries_sustain_minutes_and_condition_state():
    row = _rule_row(condition_state=json.dumps({'0': '2024-01-02T09:30:00'}))
    rule_input = _deserialize_rule(row.rule_json, row)
    assert rule_input.group.conditions[0].sustain_minutes == 5
    assert rule_input.condition_state == {'0': '2024-01-02T09:30:00'}


@pytest.mark.asyncio
async def test_sustain_state_round_trips_through_evaluate_rules():
    row = _rule_row(condition_state=json.dumps({'0': '2024-01-02T09:30:00'}))
    rule_input = _deserialize_rule(row.rule_json, row)
    candle = {'time': '2024-01-02T09:45', 'open': 100, 'high': 106, 'low': 99, 'close': 103, 'volume': 1000}
    now = datetime(2024, 1, 2, 9, 36)  # 6 minutes after the recorded pending_since
    results = evaluate_rules([rule_input], candle, [candle], {}, [], now)
    assert len(results) == 1
    # Persisting back to the row (as evaluate_and_notify_for_symbol does) must
    # reflect the mutated state.
    row.condition_state = json.dumps(rule_input.condition_state)
    assert json.loads(row.condition_state) == {'0': '2024-01-02T09:30:00'}


def test_parse_candle_time_handles_z_suffix_and_epoch_and_garbage():
    from app.routers.chart_alerts import _parse_candle_time
    from datetime import datetime
    # Always naive (tzinfo stripped), regardless of whether the input carried an
    # offset -- evaluate_rules' now - pending_since subtraction requires every
    # `now` value across a dry-run candle list to be consistently naive or it
    # raises TypeError on offset-naive vs offset-aware subtraction.
    z_result = _parse_candle_time('2024-01-02T09:30:00Z')
    assert z_result == datetime.fromisoformat('2024-01-02T09:30:00')
    assert z_result.tzinfo is None
    assert _parse_candle_time(1704186600) == datetime.fromtimestamp(1704186600)
    # Garbage input must not raise — falls back to "now" (just check it returns a datetime).
    result = _parse_candle_time('not-a-time')
    assert isinstance(result, datetime)


def test_parse_candle_time_naive_and_aware_inputs_are_mutually_subtractable():
    """Regression test: a dry-run candle list that mixes 'Z'-suffixed and bare
    ISO timestamps must not raise TypeError when evaluate_rules subtracts
    consecutive `now` values (via the sustain-minutes pending_since check)."""
    from app.routers.chart_alerts import _parse_candle_time
    aware_input = _parse_candle_time('2024-01-02T09:30:00Z')
    naive_input = _parse_candle_time('2024-01-02T09:40:00')
    # Must not raise TypeError: can't subtract offset-naive and offset-aware datetimes
    delta = (naive_input - aware_input).total_seconds()
    assert delta == 600.0
