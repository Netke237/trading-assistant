"""Tests for ScanScheduler and continuous scan endpoints."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.schemas import ScanResult, ScanDelta, ContinuousScanConfig
from app.services.scan_scheduler import ScanScheduler


# ── ScanScheduler unit tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduler_start_stop():
    scheduler = ScanScheduler(cadence_minutes=5)
    calls = []

    async def dummy_scan() -> ScanResult:
        calls.append(1)
        return ScanResult(
            scan_id="REC-20260101-AAAAAAAA",
            timestamp=datetime.now(timezone.utc).isoformat(),
            candidates=[],
            rejected=[],
        )

    scheduler.bind(dummy_scan)
    await scheduler.start()
    assert scheduler.get_status()["running"] is True

    await scheduler.stop()
    assert scheduler.get_status()["running"] is False


@pytest.mark.asyncio
async def test_scheduler_runs_scan_once_per_loop():
    scheduler = ScanScheduler(cadence_minutes=60)
    calls = []

    async def dummy_scan() -> ScanResult:
        calls.append(1)
        return ScanResult(
            scan_id="REC-20260101-AAAAAAAA",
            timestamp=datetime.now(timezone.utc).isoformat(),
            candidates=[],
            rejected=[],
        )

    scheduler.bind(dummy_scan)
    await scheduler.start()
    # Give the loop a moment to execute one iteration
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert len(calls) >= 1


@pytest.mark.asyncio
async def test_scheduler_status_fields():
    scheduler = ScanScheduler(cadence_minutes=30)

    async def dummy_scan() -> ScanResult:
        return ScanResult(
            scan_id="REC-20260101-BBBBBBBB",
            timestamp=datetime.now(timezone.utc).isoformat(),
            candidates=[],
            rejected=[],
        )

    scheduler.bind(dummy_scan)
    await scheduler.start()
    await asyncio.sleep(0.05)
    status = scheduler.get_status()
    await scheduler.stop()

    assert "running" in status
    assert "last_run_at" in status
    assert "next_run_at" in status
    assert status["cadence_minutes"] == 30


@pytest.mark.asyncio
async def test_scheduler_last_result():
    scheduler = ScanScheduler(cadence_minutes=60)

    async def dummy_scan() -> ScanResult:
        return ScanResult(
            scan_id="REC-20260101-CCCCCCCC",
            timestamp=datetime.now(timezone.utc).isoformat(),
            candidates=[],
            rejected=[],
        )

    scheduler.bind(dummy_scan)
    await scheduler.start()
    await asyncio.sleep(0.05)
    await scheduler.stop()

    last = scheduler.get_last_result()
    assert last is not None
    assert last.scan_id == "REC-20260101-CCCCCCCC"


@pytest.mark.asyncio
async def test_scheduler_set_cadence_clamps():
    scheduler = ScanScheduler(cadence_minutes=60)
    scheduler.set_cadence(3)
    assert scheduler.cadence == 5
    scheduler.set_cadence(2000)
    assert scheduler.cadence == 1440
    scheduler.set_cadence(45)
    assert scheduler.cadence == 45


@pytest.mark.asyncio
async def test_scheduler_no_bind_raises():
    scheduler = ScanScheduler(cadence_minutes=5)
    with pytest.raises(RuntimeError, match="no scan function bound"):
        await scheduler._loop()


# ── Delta computation tests ──────────────────────────────────────────────────

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


# ── Route tests ──────────────────────────────────────────────────────────────

def test_continuous_start_validates_shape(client):
    from unittest.mock import AsyncMock, MagicMock
    import app.routers.scan as scan_module

    mock_scheduler = MagicMock()
    mock_scheduler.start = AsyncMock()
    original = scan_module._scheduler
    scan_module._scheduler = mock_scheduler
    try:
        r = client.post("/api/scan/continuous", json={"enabled": True, "cadence_minutes": 30})
        assert r.status_code == 200
        data = r.json()
        assert data["enabled"] is True
        assert data["cadence_minutes"] == 30
    finally:
        scan_module._scheduler = original


def test_continuous_invalid_cadence_low(client):
    r = client.post("/api/scan/continuous", json={"enabled": True, "cadence_minutes": 3})
    # Pydantic validation should reject < 5
    assert r.status_code == 422


def test_continuous_invalid_cadence_high(client):
    r = client.post("/api/scan/continuous", json={"enabled": True, "cadence_minutes": 2000})
    assert r.status_code == 422


def test_continuous_status_endpoint_shape(client):
    import app.routers.scan as scan_module
    r = client.get("/api/scan/continuous/status")
    assert r.status_code == 200
    status = r.json()
    assert "running" in status
    assert "last_run_at" in status
    assert "next_run_at" in status
    assert "cadence_minutes" in status


def test_continuous_stop_endpoint_shape(client):
    from unittest.mock import AsyncMock, MagicMock
    import app.routers.scan as scan_module

    mock_scheduler = MagicMock()
    mock_scheduler.stop = AsyncMock()
    original = scan_module._scheduler
    scan_module._scheduler = mock_scheduler
    try:
        r = client.delete("/api/scan/continuous")
        assert r.status_code == 200
        assert r.json()["status"] == "stopped"
    finally:
        scan_module._scheduler = original
