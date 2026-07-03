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

_HMM_TRIGGER_DAILY = {
    "primary": {"model": "HMM_daily", "to_state": "Trending", "p_stay_min": 0.5, "p_transition_min": 0.0},
    "confirmations": [],
    "min_confirmations": 0,
}

_HMM_TRIGGER_INTRADAY = {
    "primary": {"model": "HMM_intraday", "to_state": "Trending", "p_stay_min": 0.5, "p_transition_min": 0.0},
    "confirmations": [],
    "min_confirmations": 0,
}


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


@pytest.mark.asyncio
async def test_ws_composite_path_does_not_treat_daily_interval_candles_as_intraday(monkeypatch):
    """A composite rule saved with interval='1D' and strategy_confirmations containing
    'mean_reversion_vwap' must NOT have its (daily) all_candles passed as bars_intraday
    into the VWAP mean-reversion check — that's genuinely daily data, not intraday.
    The mocked mean_reversion_vwap_signal records the bars it receives; because the
    rule's interval is daily, bars_intraday should be [] and _matched_strategy_signals'
    own len(bars) < 60 guard should skip calling the signal fn entirely."""
    from app.routers import chart_alerts
    import app.services.strategy_engine as strategy_engine

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))

    seen_bars_lengths = []

    def _fake_vwap_signal(bars, direction='Bullish'):
        seen_bars_lengths.append(len(bars))
        return None

    monkeypatch.setattr(strategy_engine, 'mean_reversion_vwap_signal', _fake_vwap_signal)

    daily_trigger_def = {**_TRIGGER_DEF, "strategy_confirmations": ["mean_reversion_vwap"]}
    async with Session() as db:
        db.add(_make_composite_rule_row('rule-5', 'AAPL', '1D', daily_trigger_def))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '1D', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert triggered == []
    # The VWAP signal fn must never have been called — proving bars_intraday was []
    # (not the mislabeled daily all_candles) for a '1D' rule.
    assert seen_bars_lengths == []


@pytest.mark.asyncio
async def test_ws_composite_path_evaluates_hmm_daily_using_all_candles_when_interval_is_daily(monkeypatch):
    """A composite rule with primary.model='HMM_daily' saved on a '1D' rule must be
    evaluated over WS using all_candles directly as bars_daily (no extra get_bars()
    fetch needed, since all_candles already IS daily data for a '1D' rule) — instead
    of always failing closed as it did before this fix."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-6', 'AAPL', '1D', _HMM_TRIGGER_DAILY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '1D', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_not_called()


@pytest.mark.asyncio
async def test_ws_composite_path_evaluates_hmm_intraday_primary_condition(monkeypatch):
    """A composite rule with primary.model='HMM_intraday' on an intraday rule must
    actually be evaluated over WS using all_candles as bars_intraday."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-7', 'AAPL', '15min', _HMM_TRIGGER_INTRADAY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_ws_composite_path_hmm_daily_fetches_bars_when_rule_interval_is_intraday(monkeypatch):
    """When the rule's own interval is intraday but primary.model='HMM_daily', the WS
    path must fetch real daily bars via get_bars() (all_candles is intraday data and
    would be the wrong series to fit a daily HMM on) rather than failing closed."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-8', 'AAPL', '15min', _HMM_TRIGGER_DAILY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_called_once()
