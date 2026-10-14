"""Tests for _compute_deltas and the _execute_scan_core / run_scan split
(Part 3, §3.5) — the regression tests for audit round 1's top finding: a
scheduled run must never mutate _last_request/_last_result/
_last_stock_request/_last_stock_result or invoke the auto-trader, and manual
run_scan()/run_stock_scan() behavior must be unchanged by the refactor.

_compute_deltas tests moved here from the now-deleted test_scan_scheduler.py
(which tested the retired ScanScheduler class).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas import ScanResult


@pytest.fixture(autouse=True)
def _quiet_stock_benchmark_for_state_tests(monkeypatch):
    # This module verifies globals, dispatch and persistence, with an empty
    # stock universe. It does not measure SPY data or benchmark arithmetic.
    from unittest.mock import AsyncMock
    import app.routers.stock_scan as stock
    monkeypatch.setattr(stock, "get_historical_bars", AsyncMock(return_value=[]))
    monkeypatch.setattr(stock, "fetch_quotes", lambda symbols: {})
    monkeypatch.setattr(stock, "_rs_benchmark_candles", AsyncMock(return_value=None))


@pytest.fixture
def stock_client():
    """Minimal TestClient wiring only the stock-scan router — mirrors the
    fixture in test_stock_scan_router.py (module-local there, not in
    conftest.py, so redefined here rather than imported across test files)."""
    from app.database import get_db
    from app.routers.stock_scan import router as stock_scan_router
    from tests.conftest import _override_get_db

    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


# ── Delta computation ────────────────────────────────────────────────────────

def test_compute_deltas_empty_previous():
    from app.routers.scan import _compute_deltas
    current = ScanResult(
        scan_id="REC-20260101-DDDDDDDD",
        timestamp="2026-01-01T00:00:00+00:00",
        candidates=[],
        rejected=[],
    )
    assert _compute_deltas(current, None) == []


def test_compute_deltas_rank_and_score():
    from app.routers.scan import _compute_deltas
    from app.schemas import TradeCardData, ScoreBreakdown, ContractScoreBreakdown, ContractDetails, TradeEntry, TradeExit

    def make_card(symbol: str, score: int) -> TradeCardData:
        return TradeCardData(
            symbol=symbol,
            company=symbol,
            price=100.0,
            direction="Bullish",
            status="PASS",
            stockScore=score,
            stockConfidence="PASS",
            stockBreakdown=ScoreBreakdown(trend=50, pullback=50, trigger=50, event=50, volatility=50),
            contract=f"{symbol}|100|2026-06-20|C",
            contractScore=50,
            contractConfidence="PASS",
            contractBreakdown=ContractScoreBreakdown(dteFit=50, delta=50, ivAttractiveness=50, liquidity=50, spread=50),
            contractDetails=ContractDetails(strike=100, expiry="2026-06-20", right="C", mid=1.0, delta=0.5, theta=-0.05, ivRank=50, dte=30),
            entry=TradeEntry(limit=1.0, maxFill=1.05, orderType="Limit"),
            exit=TradeExit(invalidation=95.0, premiumStop=0.6, timeStopDays=10, target=110.0),
            rrRatio=2.0,
            rrModel="BS repriced (IV-derived)",
            finalStatus="PASS",
        )

    prev = ScanResult(
        scan_id="PREV",
        timestamp="2026-01-01T00:00:00+00:00",
        candidates=[make_card("AAPL", 70), make_card("MSFT", 60)],
        rejected=[],
    )
    current = ScanResult(
        scan_id="CURR",
        timestamp="2026-01-01T01:00:00+00:00",
        candidates=[make_card("MSFT", 65), make_card("AAPL", 75)],
        rejected=[],
    )

    deltas = _compute_deltas(current, prev)
    by_symbol = {d.symbol: d for d in deltas}

    # AAPL moved from rank 0 -> 1, so rank_delta = 0 - 1 = -1
    assert by_symbol["AAPL"].rank_delta == -1
    assert by_symbol["AAPL"].score_delta == 5

    # MSFT moved from rank 1 -> 0, so rank_delta = 1 - 0 = +1
    assert by_symbol["MSFT"].rank_delta == 1
    assert by_symbol["MSFT"].score_delta == 5


# ── _execute_scan_core never touches manual-run globals ──────────────────────

@pytest.mark.asyncio
async def test_execute_scan_core_does_not_touch_manual_globals():
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession

    orig_request = scan_module._last_request
    orig_result = scan_module._last_result
    orig_status = scan_module._last_status

    scan_module._last_request = None
    scan_module._last_result = None
    scan_module._last_status = "idle"

    try:
        async with _TestSession() as db:
            req = scan_module.ScanRequest(universe=[], direction="Bullish", horizon="Swing", overrides={})
            result = await scan_module._execute_scan_core(req, db, previous_result=None)
        assert result.scan_id is not None
        # The core must not have touched any manual-run-slot global.
        assert scan_module._last_request is None
        assert scan_module._last_result is None
        assert scan_module._last_status == "idle"
    finally:
        scan_module._last_request = orig_request
        scan_module._last_result = orig_result
        scan_module._last_status = orig_status


@pytest.mark.asyncio
async def test_execute_scan_core_never_fires_auto_trader():
    """Even with the auto-trader armed, _execute_scan_core (the path Part 3's
    scheduled runner uses) must never call maybe_fire_on_scan — only
    run_scan() (manual) does, per the plan's explicit "no unattended trades
    from a scheduled run" decision."""
    import app.routers.scan as scan_module
    from unittest.mock import patch
    from tests.conftest import _TestSession

    with patch("app.services.auto_trader.auto_trader.maybe_fire_on_scan") as mock_fire:
        async with _TestSession() as db:
            req = scan_module.ScanRequest(universe=[], direction="Bullish", horizon="Swing", overrides={})
            await scan_module._execute_scan_core(req, db, previous_result=None)
        mock_fire.assert_not_called()


def test_run_scan_manual_behavior_unchanged(client):
    """Manual run_scan() (via the HTTP endpoint) must still update the
    UI-facing globals exactly as before the refactor."""
    import app.routers.scan as scan_module
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200
    assert scan_module._last_request is not None
    assert scan_module._last_result is not None
    assert scan_module._last_result.scan_id == r.json()["scan_id"]


# ── _execute_stock_scan_core never touches manual-run globals ────────────────
# Stocks-mode counterpart to the options-mode tests above — flagged as a real
# coverage gap by post-implementation adversarial review: the plan's
# single most-scrutinized requirement (a scheduled run must never mutate
# _last_stock_request/_last_stock_result/_last_stock_status) had no direct
# test for stocks mode, only for options mode.

def _minimal_stock_request():
    import app.routers.stock_scan as stock_module
    return stock_module.StockScanRequest(
        universe=[], symbols=[], direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )


@pytest.mark.asyncio
async def test_execute_stock_scan_core_does_not_touch_manual_globals():
    import app.routers.stock_scan as stock_module
    from tests.conftest import _TestSession

    orig_request = stock_module._last_stock_request
    orig_result = stock_module._last_stock_result
    orig_status = stock_module._last_stock_status

    stock_module._last_stock_request = None
    stock_module._last_stock_result = None
    stock_module._last_stock_status = "idle"

    try:
        async with _TestSession() as db:
            req = _minimal_stock_request()
            result = await stock_module._execute_stock_scan_core(req, db, previous_result=None)
        assert result.scan_id is not None
        # The core must not have touched any manual-run-slot global.
        assert stock_module._last_stock_request is None
        assert stock_module._last_stock_result is None
        assert stock_module._last_stock_status == "idle"
    finally:
        stock_module._last_stock_request = orig_request
        stock_module._last_stock_result = orig_result
        stock_module._last_stock_status = orig_status


@pytest.mark.asyncio
async def test_execute_stock_scan_core_never_fires_auto_trader():
    """Same guarantee as the options-mode core: Part 3's scheduled runner
    must never place an unattended trade, for either mode."""
    import app.routers.stock_scan as stock_module
    from unittest.mock import patch
    from tests.conftest import _TestSession

    with patch("app.services.auto_trader.auto_trader.maybe_fire_on_scan") as mock_fire:
        async with _TestSession() as db:
            req = _minimal_stock_request()
            await stock_module._execute_stock_scan_core(req, db, previous_result=None)
        mock_fire.assert_not_called()


def test_run_stock_scan_manual_behavior_unchanged(stock_client):
    """Manual run_stock_scan() (via the HTTP endpoint) must still update the
    UI-facing globals exactly as before the refactor."""
    import app.routers.stock_scan as stock_module
    r = stock_client.post("/api/stock-scan", json={
        "universe": [], "symbols": [], "direction": "Bullish", "horizon": "Swing",
        "strategy": "pullback_ema",
    })
    assert r.status_code == 200
    assert stock_module._last_stock_request is not None
    assert stock_module._last_stock_result is not None
    assert stock_module._last_stock_result.scan_id == r.json()["scan_id"]


@pytest.mark.asyncio
async def test_run_scheduled_entry_stocks_dispatches_to_core_without_touching_globals(monkeypatch):
    """End-to-end: a valid stocks-mode ScanScheduleEntry fired through
    _run_scheduled_entry must dispatch to _execute_stock_scan_core and leave
    _last_stock_request/_last_stock_result/_last_stock_status untouched —
    the property the plan's audit called out as the most safety-critical
    one, now actually exercised through the real dispatch path rather than
    asserted by reading the code."""
    import uuid
    import app.routers.stock_scan as stock_module
    from app.services.scan_schedule_scheduler import _run_scheduled_entry
    from app.services.scan_schedule_store import scan_schedule_store
    from tests.conftest import _TestSession
    import app.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    orig_request = stock_module._last_stock_request
    orig_result = stock_module._last_stock_result
    orig_status = stock_module._last_stock_status
    stock_module._last_stock_request = None
    stock_module._last_stock_result = None
    stock_module._last_stock_status = "idle"

    entry_id = str(uuid.uuid4())
    entry = {
        "id": entry_id,
        "label": "test stocks entry",
        "mode": "stocks",
        "profile_id": "test-profile",
        "profile_name": "Test profile",
        "profile_synced_at": "2026-01-01T00:00:00+00:00",
        "resolved_request": {
            "universe": [], "symbols": [], "direction": "Bullish", "horizon": "Swing",
            "strategy": "pullback_ema",
        },
        "pattern": "fixed_time",
        "enabled": True,
        "days_of_week": [0, 1, 2, 3, 4],
        "fire_time": "02:00",
    }
    scan_schedule_store.upsert(entry)
    try:
        await _run_scheduled_entry(entry_id)
        assert stock_module._last_stock_request is None
        assert stock_module._last_stock_result is None
        assert stock_module._last_stock_status == "idle"

        from app.models.scheduled_scan_run import ScheduledScanRunModel
        from sqlalchemy import select
        async with _TestSession() as db:
            rows = (await db.execute(
                select(ScheduledScanRunModel).where(ScheduledScanRunModel.schedule_entry_id == entry_id)
            )).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert rows[0].mode == "stocks"
    finally:
        scan_schedule_store.delete(entry_id)
        stock_module._last_stock_request = orig_request
        stock_module._last_stock_result = orig_result
        stock_module._last_stock_status = orig_status
