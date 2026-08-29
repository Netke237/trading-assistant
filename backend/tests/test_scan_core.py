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

from app.schemas import ScanResult


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
