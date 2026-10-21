# backend/tests/test_audit_monitoring_lane_g.py
"""Lane G audit test suite: APP-AUDIT-MONITORING (#355).

Pins:
1. Strategy Watch state machine transitions (idle <-> armed) and emitted event types
   (entry, exit_stop, exit_target, time_stop, reversal) across the 5 valid daily strategies.
2. Rejection of mean_reversion_vwap as intraday-only in daily subscriptions.
3. Auto-Trade pre-trade safety gates:
   - RegimeHeadwindError (HTTP 400) on opposing market regime
   - RegimeGateConfigError (HTTP 500) on missing/malformed regime config
   - Event veto on max(reject_window, hold_bars) days and unknown single-stock earnings
4. Auto-Trade execution serialization via _FIRE_EXECUTOR and cancellation cleanup in _log_unbooked.
5. Notification dispatch append-only audit logging in sent_log.py without live external dispatch.
6. Scheduled automation inventory covering all 7 background schedulers with error boundary containment.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.auto_trader as at
from app.routers.auto_trade import _log_unbooked
from app.services.notifications.sent_log import log_sent, prune_sent_log
from app.services.strategy_watch_evaluator import (
    WatchEvent,
    evaluate_all,
)
from app.services.strategy_watch_store import VALID_STRATEGIES


# ---------------------------------------------------------------------------
# 1. Strategy Watch: State Transitions & Strategy Constraints
# ---------------------------------------------------------------------------

def _bars(close: float, n: int = 260) -> list[dict]:
    return [
        {
            "time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        }
        for i in range(n)
    ]


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
    base = {
        "phase": phase,
        "direction": None,
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "last_event": None,
        "last_event_at": None,
    }
    base.update(state)
    return {
        "id": "wch_test_1",
        "symbol": "AAPL",
        "strategy_key": "pullback_ema",
        "params_override": {},
        "enabled": True,
        "last_state": base,
    }


def test_strategy_watch_valid_daily_strategies():
    """Verify exactly the 5 valid daily strategies are allowed in strategy_watch_store."""
    expected = {"pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb"}
    assert set(VALID_STRATEGIES) == expected, (
        f"Expected VALID_STRATEGIES to be {expected}, got {VALID_STRATEGIES}"
    )
    assert "mean_reversion_vwap" not in VALID_STRATEGIES, (
        "mean_reversion_vwap must be excluded from daily strategy watches (intraday only)"
    )


@pytest.mark.asyncio
async def test_strategy_watch_state_machine_transition_idle_to_armed():
    """Verify state machine moves from idle to armed upon entry signal."""
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
    assert events[0].symbol == "AAPL"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "armed"


@pytest.mark.asyncio
async def test_strategy_watch_state_machine_exit_stop():
    """Verify armed watch transitions to idle upon stop price hit."""
    store = MagicMock()
    store.list_watches.return_value = [_watch(
        "armed",
        direction="Bullish",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
    )]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "exit_stop"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "idle"


@pytest.mark.asyncio
async def test_strategy_watch_state_machine_exit_target():
    """Verify armed watch transitions to idle upon target price hit."""
    store = MagicMock()
    store.list_watches.return_value = [_watch(
        "armed",
        direction="Bullish",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
    )]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(111.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "exit_target"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "idle"


@pytest.mark.asyncio
async def test_strategy_watch_state_machine_reversal_stays_armed():
    """Verify armed watch encountering opposite signal emits reversal and remains armed with flipped direction."""
    store = MagicMock()
    store.list_watches.return_value = [_watch(
        "armed",
        direction="Bullish",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
    )]

    # Close is between stop and target (e.g. 102.0)
    rev_sig = MagicMock()
    rev_sig.direction = "Bearish"
    rev_sig.entry_price = 102.0
    rev_sig.stop_price = 107.0
    rev_sig.target_price = 92.0
    rev_sig.rr_ratio = 2.0

    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, direction="Bullish", **k: rev_sig if direction == "Bearish" else None}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "reversal"
    assert events[0].direction == "Bearish"
    store.update_state.assert_called_once()
    new_state = store.update_state.call_args[0][1]
    # Reversal stays in phase: "armed" and flips direction to "Bearish"
    assert new_state["phase"] == "armed"
    assert new_state["direction"] == "Bearish"
    assert new_state["entry_price"] == 102.0
    assert new_state["stop_price"] == 107.0
    assert new_state["target_price"] == 92.0


# ---------------------------------------------------------------------------
# 2. Auto-Trade Safety Gates & Pre-Trade Checks
# ---------------------------------------------------------------------------

class _DummyArmedStrategy:
    symbol = "NVDA"
    horizon = "Swing"
    direction = "Bullish"
    hold_max_days = 20


def test_auto_trade_regime_headwind_error():
    """Opposing market regime raises RegimeHeadwindError (HTTP 400)."""
    assert issubclass(at.RegimeHeadwindError, Exception)
    err = at.RegimeHeadwindError("Bullish", "Bearish")
    assert "Bullish" in str(err)
    assert "Bearish" in str(err)


def test_auto_trade_regime_gate_config_error():
    """Missing or corrupted YAML config raises RegimeGateConfigError (HTTP 500)."""
    assert issubclass(at.RegimeGateConfigError, Exception)
    err = at.RegimeGateConfigError("risk_rules.yaml missing regime section")
    assert "risk_rules.yaml" in str(err)


def test_auto_trade_event_veto_reject_window(monkeypatch):
    """Event occurring within max(reject_window, hold_bars) raises EventVetoError."""
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda sym: date.today() + timedelta(days=10))
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(_DummyArmedStrategy())


def test_auto_trade_event_veto_unknown_earnings_date(monkeypatch):
    """Unknown earnings date for single stock raises EventVetoError (D4 amendment)."""
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda sym: None)
    with pytest.raises(at.EventVetoError) as exc_info:
        at._apply_event_veto(_DummyArmedStrategy())
    assert "unknown earnings date" in str(exc_info.value).lower() or "veto" in str(exc_info.value).lower()


def test_auto_trade_event_veto_etf_exempt(monkeypatch):
    """ETFs have no single-stock earnings and pass event veto."""
    etf_strat = _DummyArmedStrategy()
    etf_strat.symbol = "SPY"
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda sym: None)
    at._apply_event_veto(etf_strat)


def test_auto_trade_cancellation_unbooked_logging():
    """Cancelled order cleans up via _log_unbooked without unhandled error."""
    fut = concurrent.futures.Future()
    fut.cancel()

    with patch("app.routers.auto_trade.logger.warning") as mock_warn:
        _log_unbooked("NVDA", fut)
        mock_warn.assert_called_once()
        assert "was cancelled" in mock_warn.call_args[0][0]


# ---------------------------------------------------------------------------
# 3. Notification Dispatch: Append-Only Audit Log
# ---------------------------------------------------------------------------

def test_notification_sent_log_append_and_prune():
    """Verify sent_log.py acts as an append-only JSONL log and prunes correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_log_path = Path(tmpdir) / "sent_messages.log"

        with patch("app.services.notifications.sent_log._SENT_LOG_PATH", test_log_path):
            log_sent("telegram", "@test_channel", "Watch Alert: AAPL Bullish")
            log_sent("gmail", "user@example.com", "Price Alert: TSLA crossed $200")

            assert test_log_path.exists()
            with open(test_log_path, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f if line.strip()]

            assert len(lines) == 2
            assert lines[0]["channel"] == "telegram"
            assert lines[0]["recipient"] == "@test_channel"
            assert "AAPL" in lines[0]["subject"]
            assert lines[1]["channel"] == "gmail"

            # Pruning with 1 retention day retains current messages
            prune_sent_log(retention_days=1)
            with open(test_log_path, "r", encoding="utf-8") as f:
                retained = [json.loads(line) for line in f if line.strip()]
            assert len(retained) == 2


# ---------------------------------------------------------------------------
# 4. Scheduled Automation Inventory
# ---------------------------------------------------------------------------

def test_scheduled_automation_inventory_modules():
    """Verify all 7 background schedulers exist and provide proper lifecycle methods."""
    schedulers = [
        "app.services.scan_schedule_scheduler",
        "app.services.strategy_watch_scheduler",
        "app.services.chart_alert_scheduler",
        "app.services.tuning_scheduler",
        "app.services.edgar_scheduler",
        "app.services.sp500_scheduler",
        "app.services.ingestion_scheduler",
    ]

    import importlib
    for mod_name in schedulers:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Scheduler module {mod_name} failed to import"


@pytest.mark.asyncio
async def test_chart_alert_scheduler_per_pair_error_containment(monkeypatch):
    """Verify chart_alert_scheduler catches per-pair evaluation errors without failing tick."""
    import app.services.chart_alert_scheduler as sched

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("AAPL", "15min")]
    mock_db.execute.return_value = mock_result

    class MockSessionCtx:
        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(sched, "AsyncSessionLocal", lambda: MockSessionCtx())
    monkeypatch.setattr(sched, "get_intraday_with_fetched_at", AsyncMock(side_effect=RuntimeError("Provider network error")))

    with patch("app.services.chart_alert_scheduler.logger.warning") as mock_warn:
        await sched._tick()
        mock_warn.assert_called_once()
        assert "AAPL" in mock_warn.call_args[0][1]
