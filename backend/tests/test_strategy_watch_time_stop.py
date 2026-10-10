# backend/tests/test_strategy_watch_time_stop.py
"""STOCKS-HORIZON-T1 H7: a strategy watch carries a params horizon and its hold;
an armed watch held hold_max_days (UTC calendar days since the entry/reversal)
emits `time_stop` and returns to idle, before stop/target are checked."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.services.strategy_watch_evaluator import (
    WatchEvent, _format_event, evaluate_all, evaluate_and_notify,
)
from app.services.strategy_watch_store import StrategyWatchStore
from tests.watch_notify_helpers import configured_channels_no_real_sends, per_channel  # noqa: F401

_EV = "app.services.strategy_watch_evaluator"


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _armed(last_event_at: str, hold: int | None, last_event: str = "entry",
           params_horizon: str | None = "Swing") -> dict:
    w = {"id": "wch_1", "symbol": "AAPL", "strategy_key": "pullback_ema",
         "direction": "Bullish", "params_override": {}, "enabled": True,
         "last_state": {"phase": "armed", "direction": "Bullish", "entry_price": 100.0,
                        "stop_price": 95.0, "target_price": 110.0,
                        "last_event": last_event, "last_event_at": last_event_at}}
    if hold is not None or params_horizon is not None:
        w["params_horizon"] = params_horizon
        w["hold_max_days"] = hold
    return w


async def _run(watch: dict, now: datetime, close: float = 100.0):
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch(f"{_EV}.strategy_watch_store", store), \
         patch(f"{_EV}.get_bars", new_callable=AsyncMock, return_value=_bars(close)), \
         patch(f"{_EV}._utcnow", return_value=now), \
         patch.dict(f"{_EV}._SIGNAL_FNS", {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    return events, store


# ── evaluator ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_armed_15_days_hold_15_emits_time_stop_and_goes_idle():
    events, store = await _run(_armed("2026-01-01T15:00:00+00:00", 15),
                               datetime(2026, 1, 16, 15, 0, tzinfo=timezone.utc))
    assert [e.event_type for e in events] == ["time_stop"]
    ev = events[0]
    assert ev.reason == "AAPL: Pullback EMA time stop — held 15d (hold 15d)"
    assert ev.direction == "Bullish" and ev.rr_ratio is None and ev.close == 100.0
    new_state = store.update_state.call_args[0][1]
    assert new_state["phase"] == "idle" and new_state["last_event"] == "time_stop"


@pytest.mark.asyncio
async def test_armed_14_days_hold_15_emits_nothing():
    events, store = await _run(_armed("2026-01-01T15:00:00+00:00", 15),
                               datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc))
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_after_a_reversal_the_hold_counts_from_the_reversal():
    events, _ = await _run(_armed("2026-01-01T15:00:00+00:00", 15, last_event="reversal"),
                           datetime(2026, 1, 16, 15, 0, tzinfo=timezone.utc))
    assert [e.event_type for e in events] == ["time_stop"]


@pytest.mark.asyncio
async def test_watch_without_a_horizon_never_time_stops():
    for w in (_armed("2025-01-01T15:00:00+00:00", None, params_horizon=None),  # legacy: absent
              {**_armed("2025-01-01T15:00:00+00:00", 15), "params_horizon": None,
               "hold_max_days": None}):
        events, _ = await _run(w, datetime(2026, 1, 16, 15, 0, tzinfo=timezone.utc))
        assert events == []


@pytest.mark.asyncio
async def test_time_stop_is_checked_before_stop_and_target():
    # Close 94 is below the stop; the hold is reached too -> time_stop wins.
    events, _ = await _run(_armed("2026-01-01T15:00:00+00:00", 15),
                           datetime(2026, 1, 16, 15, 0, tzinfo=timezone.utc), close=94.0)
    assert [e.event_type for e in events] == ["time_stop"]


@pytest.mark.asyncio
async def test_utc_boundary_counts_utc_calendar_dates():
    # Entry at 23:30 UTC on Jan 1. At 00:30 UTC on Jan 16 only 14d 1h have
    # elapsed, but the UTC calendar dates are 15 apart -> time_stop. (In US
    # Eastern the two instants are Jan 1 18:30 and Jan 15 19:30: 14 dates, so a
    # local-date rule or an elapsed-time rule would not fire here.)
    w = _armed("2026-01-01T23:30:00+00:00", 15)
    events, _ = await _run(w, datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc))
    assert [e.event_type for e in events] == ["time_stop"]
    events, _ = await _run(w, datetime(2026, 1, 15, 23, 59, tzinfo=timezone.utc))
    assert events == []


# ── formatting and dispatch ──────────────────────────────────────────────────

def test_format_time_stop_like_exit_stop():
    ev = WatchEvent(watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
                    event_type="time_stop", direction="Bullish", entry=100.0, stop=95.0,
                    target=110.0, rr_ratio=None, close=101.0,
                    reason="AAPL: Pullback EMA time stop — held 15d (hold 15d)")
    subject, plain, html = _format_event(ev)
    assert subject == "Time stop: AAPL — Pullback EMA"
    assert "time stop — held 15d (hold 15d)" in plain and "Time stop" in html
    assert "time_stop" not in subject


@pytest.mark.asyncio
async def test_time_stop_dispatches_and_commits_like_exit_stop():
    store = MagicMock()
    store.list_watches.return_value = [_armed("2026-01-01T15:00:00+00:00", 15)]
    notify = AsyncMock(return_value=True)
    with patch(f"{_EV}.strategy_watch_store", store), \
         patch(f"{_EV}.get_bars", new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch(f"{_EV}._utcnow", return_value=datetime(2026, 1, 16, 15, 0, tzinfo=timezone.utc)), \
         patch.dict(f"{_EV}._SIGNAL_FNS", {"pullback_ema": lambda bars, **k: None}), \
         patch(f"{_EV}.read_notification_config", return_value=({"gmail": {"enabled": True}}, True)), \
         patch(f"{_EV}.notify_channels", per_channel(notify)):
        events = await evaluate_and_notify()
    assert [e.event_type for e in events] == ["time_stop"]
    notify.assert_called_once()
    assert notify.await_args[0][0] == "Time stop: AAPL — Pullback EMA"
    assert store.update_state.call_args[0][1]["phase"] == "idle"


# ── store ─────────────────────────────────────────────────────────────────────

def test_store_add_watch_records_horizon_and_hold(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    e = store.add_watch("AAPL", "pullback_ema", params_horizon="Quarterly")
    assert e["params_horizon"] == "Quarterly" and e["hold_max_days"] == 60
    plain = store.add_watch("MSFT", "pullback_ema")
    assert plain["params_horizon"] is None and plain["hold_max_days"] is None
    reloaded = StrategyWatchStore(path=tmp_path / "w.yaml")
    by_sym = {w["symbol"]: w for w in reloaded.list_watches()}
    assert by_sym["AAPL"]["hold_max_days"] == 60


def test_store_bulk_add_records_horizon_and_hold(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    added = store.add_watches_bulk(["AAPL", "MSFT"], "breakout_base", params_horizon="Annual")
    assert [(w["params_horizon"], w["hold_max_days"]) for w in added] == [("Annual", 200)] * 2


def test_store_load_leaves_legacy_watches_without_a_horizon(tmp_path):
    # A watch saved before H7 has no params_horizon/hold_max_days; absent reads
    # as None (no time stop); test_watch_without_a_horizon_never_time_stops
    # covers the evaluation.
    path = tmp_path / "w.yaml"
    path.write_text(
        "watches:\n- id: wch_old\n  symbol: AAPL\n  strategy_key: pullback_ema\n"
        "  params_override: {}\n  enabled: true\n")
    w = StrategyWatchStore(path=path).list_watches()[0]
    assert w.get("params_horizon") is None and w.get("hold_max_days") is None


# ── router ────────────────────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(tmp_path / "w.yaml"))
    import importlib
    import app.services.strategy_watch_store as sws
    importlib.reload(sws)
    import app.routers.strategy_watch as r
    importlib.reload(r)
    from app.main import create_app
    return create_app()


@pytest.mark.asyncio
async def test_router_add_and_bulk_accept_params_horizon(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        one = await ac.post("/api/strategy-watch/", json={
            "symbol": "AAPL", "strategy_key": "pullback_ema", "params_horizon": "Position"})
        assert one.status_code == 201
        assert one.json()["params_horizon"] == "Position" and one.json()["hold_max_days"] == 45
        bulk = await ac.post("/api/strategy-watch/bulk", json={
            "symbols": ["MSFT"], "strategy_key": "pullback_ema", "params_horizon": "SemiAnnual"})
        assert bulk.status_code == 201
        assert bulk.json()["watches"][0]["hold_max_days"] == 105
        none = await ac.post("/api/strategy-watch/", json={"symbol": "GOOG", "strategy_key": "pullback_ema"})
        assert none.json()["params_horizon"] is None and none.json()["hold_max_days"] is None
        bad = await ac.post("/api/strategy-watch/", json={
            "symbol": "NVDA", "strategy_key": "pullback_ema", "params_horizon": "Intraday"})
        assert bad.status_code == 422
