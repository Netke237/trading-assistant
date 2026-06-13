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
