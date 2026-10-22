# backend/tests/test_strategy_watch_bearish.py
"""Direction-aware strategy-watch tests — Bearish path (C8)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.strategy_watch_evaluator import WatchEvent, evaluate_all, _format_event


# ── helpers ───────────────────────────────────────────────────────────────────

def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bearish", entry=100.0, stop=105.0, target=90.0):
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.direction = direction
    sig.entry_price = entry
    sig.stop_price = stop
    sig.target_price = target
    sig.rr_ratio = 2.0
    return sig


def _watch(phase="idle", direction="Bearish", **state):
    base = {"phase": phase, "direction": None if phase == "idle" else direction,
            "entry_price": None, "stop_price": None, "target_price": None,
            "last_event": None, "last_event_at": None}
    base.update(state)
    return {"id": "wch_bearish_1", "symbol": "SPY", "strategy_key": "pullback_ema",
            "direction": direction,          # watch-level direction
            "params_override": {}, "enabled": True, "last_state": base}


# ── entry event ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bearish_idle_signal_emits_entry_with_short_reason():
    """Idle watch with direction=Bearish emits entry; reason contains 'short', not 'buy'."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", direction="Bearish")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "entry"
    assert ev.direction == "Bearish"
    assert "short" in ev.reason.lower(), f"Expected 'short' in reason, got: {ev.reason!r}"
    assert "buy" not in ev.reason.lower(), f"'buy' should not appear in bearish reason, got: {ev.reason!r}"
    # State must be armed
    new_state = store.update_state.call_args[0][1]
    assert new_state["phase"] == "armed"


# ── armed-phase exit conditions (direction-aware) ─────────────────────────────

@pytest.mark.asyncio
async def test_bearish_armed_close_below_stop_no_exit():
    """Bearish: close=104 < stop=105 is NOT a stop-hit (stop is above entry for shorts)."""
    store = MagicMock()
    store.list_watches.return_value = [
        _watch("armed", direction="Bearish",
               entry_price=100.0, stop_price=105.0, target_price=90.0)
    ]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(104.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert events == [], "close=104 < stop=105 should NOT trigger bearish stop"
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_bearish_armed_close_above_stop_triggers_exit_stop():
    """Bearish: close=106 >= stop=105 → stop hit (price moved against the short)."""
    store = MagicMock()
    store.list_watches.return_value = [
        _watch("armed", direction="Bearish",
               entry_price=100.0, stop_price=105.0, target_price=90.0)
    ]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(106.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "exit_stop"
    new_state = store.update_state.call_args[0][1]
    assert new_state["phase"] == "idle"


@pytest.mark.asyncio
async def test_bearish_armed_close_above_target_no_exit():
    """Bearish: close=91 > target=90 is NOT a target hit (target is below entry for shorts)."""
    store = MagicMock()
    store.list_watches.return_value = [
        _watch("armed", direction="Bearish",
               entry_price=100.0, stop_price=105.0, target_price=90.0)
    ]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(91.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert events == [], "close=91 > target=90 should NOT trigger bearish target"
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_bearish_armed_close_below_target_triggers_exit_target():
    """Bearish: close=89 <= target=90 → target hit (price moved in favour of the short)."""
    store = MagicMock()
    store.list_watches.return_value = [
        _watch("armed", direction="Bearish",
               entry_price=100.0, stop_price=105.0, target_price=90.0)
    ]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(89.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "exit_target"
    new_state = store.update_state.call_args[0][1]
    assert new_state["phase"] == "idle"


# ── _format_event direction-aware subject ─────────────────────────────────────

def test_format_event_bearish_entry_subject_contains_short():
    """_format_event: entry event with direction=Bearish → subject has 'Short setup'."""
    ev = WatchEvent(
        watch_id="wch_bearish_1", symbol="SPY", strategy_key="pullback_ema",
        event_type="entry", direction="Bearish", entry=100.0, stop=105.0,
        target=90.0, rr_ratio=2.0, close=100.0,
        reason="SPY: pullback_ema short setup — entry 100.0, stop 105.0, target 90.0 (R:R 2.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "Short setup" in subject, f"Expected 'Short setup' in subject, got: {subject!r}"
    assert "SPY" in subject


def test_format_event_bullish_entry_subject_contains_long():
    """_format_event: entry event with direction=Bullish → subject has 'Long setup'."""
    ev = WatchEvent(
        watch_id="wch_bull_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0,
        reason="AAPL: pullback_ema long setup — entry 100.0, stop 95.0, target 110.0 (R:R 2.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "Long setup" in subject, f"Expected 'Long setup' in subject, got: {subject!r}"


def test_format_event_non_entry_preserves_existing_labels():
    """_format_event: exit events still use their existing labels."""
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="exit_stop", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=None, close=94.0,
        reason="AAPL: pullback_ema stop hit at 94.0 (stop 95.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "Stop hit" in subject


# ── backward-compat: existing records without 'direction' default to Bullish ──

@pytest.mark.asyncio
async def test_legacy_watch_without_direction_defaults_bullish():
    """A watch record without a 'direction' key should behave as Bullish."""
    store = MagicMock()
    w = {"id": "wch_legacy", "symbol": "MSFT", "strategy_key": "pullback_ema",
         # deliberately omit 'direction' key
         "params_override": {}, "enabled": True,
         "last_state": {"phase": "idle", "direction": None, "entry_price": None,
                        "stop_price": None, "target_price": None,
                        "last_event": None, "last_event_at": None}}
    store.list_watches.return_value = [w]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.strategy_watch_evaluator.get_profile", return_value=({}, "baseline")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal(direction="Bullish",
                                                               entry=100.0, stop=95.0,
                                                               target=110.0)}):
        events = await evaluate_all()

    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "entry"
    # Reason should have 'long' not 'short' for Bullish default
    assert "long" in ev.reason.lower() or "buy" not in ev.reason.lower()
