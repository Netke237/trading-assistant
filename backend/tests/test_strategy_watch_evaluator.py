# backend/tests/test_strategy_watch_evaluator.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.strategy_watch_evaluator import WatchEvent, evaluate_all


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bullish", entry=100.0, stop=95.0, target=110.0):
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.direction = direction
    sig.entry_price = entry
    sig.stop_price = stop
    sig.target_price = target
    sig.rr_ratio = 2.0
    return sig


def _watch(phase="idle", **state):
    base = {"phase": phase, "direction": None, "entry_price": None,
            "stop_price": None, "target_price": None, "last_event": None,
            "last_event_at": None}
    base.update(state)
    return {"id": "wch_1", "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": True, "last_state": base}


@pytest.mark.asyncio
async def test_idle_with_signal_emits_entry_and_arms():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert len(events) == 1
    assert events[0].event_type == "entry"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "armed"


@pytest.mark.asyncio
async def test_armed_below_stop_emits_exit_stop_and_resets():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_stop"
    assert store.update_state.call_args[0][1]["phase"] == "idle"


@pytest.mark.asyncio
async def test_armed_above_target_emits_exit_target():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(111.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_target"


@pytest.mark.asyncio
async def test_armed_holding_emits_nothing():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_get_bars_failure_skips_symbol():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, side_effect=RuntimeError("db down")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_watch_skipped():
    store = MagicMock()
    w = _watch("idle")
    w["enabled"] = False
    store.list_watches.return_value = [w]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)) as gb, \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    gb.assert_not_called()


from unittest.mock import patch as _patch

from app.services.strategy_watch_evaluator import evaluate_and_notify, _format_event


def test_format_event_builds_subject_and_bodies():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0,
        reason="AAPL: pullback_ema buy setup — entry 100.0, stop 95.0, target 110.0 (R:R 2.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "AAPL" in subject and "Long setup" in subject
    assert "100.0" in plain
    assert "<" in html  # html body has markup


def _composite_watch(**overrides):
    base = {"id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
            "strategy_key": "composite", "direction": "Bullish", "enabled": True,
            "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}}}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_composite_watch_describe_match_failure_still_fires_with_fallback_reason():
    """describe_match/format_composite_reason failing must not suppress an
    already-confirmed composite alert — it should fall back to a generic
    reason string and still append the WatchEvent."""
    store = MagicMock()
    store.list_watches.return_value = [_composite_watch()]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
               return_value=True), \
         patch("app.services.composite_trigger_evaluator.describe_match",
               side_effect=RuntimeError("boom")):
        events = await evaluate_all()
    assert len(events) == 1
    assert events[0].watch_id == "wch_comp_1"
    assert events[0].strategy_key == "composite"
    assert events[0].reason  # some reason string, not empty
    assert "AAPL" in events[0].reason


@pytest.mark.asyncio
async def test_evaluate_and_notify_dispatches_per_event():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0, reason="x",
    )
    with _patch("app.services.strategy_watch_evaluator.evaluate_all",
                new_callable=AsyncMock, return_value=[ev]), \
         _patch("app.services.strategy_watch_evaluator.notify_enabled_channels") as notify:
        result = await evaluate_and_notify()
    assert result == [ev]
    notify.assert_called_once()
