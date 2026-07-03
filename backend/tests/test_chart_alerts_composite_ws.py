"""Tests for the WebSocket composite-rule path in chart_alerts.evaluate_and_notify_for_symbol.

Closes the parity gap between the WS path (evaluate_from_context) and the scheduled
watch path (evaluate_scheduled): a composite rule with strategy_confirmations must
behave the same regardless of which path evaluates it.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401


async def _make_session_factory():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return Session


def _make_composite_rule_row(rule_id: str, symbol: str, interval: str, trigger_def: dict) -> AlertRuleModel:
    return AlertRuleModel(
        id=rule_id, user_id='default', name='Composite Rule', symbol=symbol, interval=interval,
        enabled=True, rule_json=json.dumps({**trigger_def, '__type': 'composite'}),
        cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
    )


_TRIGGER_DEF = {
    "primary": {"model": "any"},
    "confirmations": [],
    "min_confirmations": 0,
    "strategy_confirmations": ["mean_reversion_rsi"],
    "min_strategy_confirmations": 1,
    "direction": "Bullish",
}

_FLAT_BARS = [
    {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for _ in range(120)
]

_FLAT_CANDLES = [
    {"time": f"t{i}", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
    for i in range(120)
]


@pytest.mark.asyncio
async def test_ws_composite_path_gates_on_strategy_confirmations(monkeypatch):
    """A composite rule with strategy_confirmations must not fire over WS unless the
    mean-reversion strategy actually fired. Explicitly monkeypatches the signal fn to
    return None (rather than relying on insufficient bars to fail closed) so this test
    actually distinguishes "strategy did not confirm" from "not enough data to tell" —
    mirroring Task 1's test_evaluate_from_context_strategy_confirmations_not_met_with_bars."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))
    monkeypatch.setattr(
        strategy_engine, 'mean_reversion_rsi_signal',
        lambda bars, direction='Bullish': None,
    )

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-1', 'AAPL', '15min', _TRIGGER_DEF))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []


@pytest.mark.asyncio
async def test_ws_composite_path_fires_when_strategy_confirms(monkeypatch):
    """Same rule, but the mean-reversion strategy is mocked to confirm — should fire,
    and the reason text should name the matched strategy (proving describe_match
    also received bars)."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))
    monkeypatch.setattr(
        strategy_engine, 'mean_reversion_rsi_signal',
        lambda bars, direction='Bullish': MagicMock(),
    )

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-2', 'AAPL', '15min', _TRIGGER_DEF))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    assert 'mean_reversion_rsi' in triggered[0]['reason']


@pytest.mark.asyncio
async def test_ws_composite_path_skips_bars_fetch_when_not_needed(monkeypatch):
    """A composite rule with no strategy_confirmations must not trigger a bars fetch at all."""
    from app.routers import chart_alerts

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    trigger_def = {"primary": {"model": "any"}, "confirmations": [], "min_confirmations": 0}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-3', 'AAPL', '15min', trigger_def))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_not_called()


@pytest.mark.asyncio
async def test_ws_composite_path_passes_rule_direction_to_describe_match(monkeypatch):
    """A Bearish composite rule's reason text must reflect strategy matches computed
    with direction='Bearish', not silently fall back to describe_match's Bullish
    default — this is what keeps the WS path's reason text consistent with the
    scheduled path's (which already passes direction=wdir)."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))

    seen_directions = []

    def _fake_signal(bars, direction='Bullish'):
        seen_directions.append(direction)
        return MagicMock()

    monkeypatch.setattr(strategy_engine, 'mean_reversion_rsi_signal', _fake_signal)

    bearish_trigger_def = {**_TRIGGER_DEF, "direction": "Bearish"}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-4', 'AAPL', '15min', bearish_trigger_def))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    # describe_match() re-runs the strategy scan to build the reason text — assert
    # every call it made to the signal fn used 'Bearish', never the 'Bullish' default.
    assert seen_directions and all(d == 'Bearish' for d in seen_directions)
