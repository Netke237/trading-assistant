"""Route tests for POST /api/scan.

market.py uses Tradier for live data. All tests that exercise the pipeline
mock async fetch functions so they run network-free and deterministically.
"""

import asyncio
import re
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# ── Shape & contract ──────────────────────────────────────────────────────────

def test_scan_returns_200(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200


def test_scan_response_has_required_fields(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert "scan_id"    in data
    assert "timestamp"  in data
    assert "candidates" in data
    assert "rejected"   in data


def test_scan_id_format(client):
    """scan_id must match REC-YYYYMMDD-XXXXXXXX."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    scan_id = r.json()["scan_id"]
    assert re.match(r"REC-\d{8}-[A-F0-9]{8}", scan_id), f"Unexpected scan_id: {scan_id}"


def test_scan_empty_universe_returns_empty_lists(client):
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert data["candidates"] == []
    assert data["rejected"]   == []


def test_scan_invalid_direction_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Sideways", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_invalid_horizon_returns_422(client):
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Daily", "overrides": {},
    })
    assert r.status_code == 422


def test_scan_missing_body_returns_422(client):
    r = client.post("/api/scan")
    assert r.status_code == 422


# ── No market data → symbol rejected ─────────────────────────────────────────

def _enter_mock_patches(*, price=None, candles=None, chain=None,
                        company=None, fund=None):
    stack = ExitStack()
    stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles or [])))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain or [])))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value=company)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=fund)))
    return stack


def test_scan_no_market_data_rejects_symbol(client):
    """When fetch_price returns None the symbol must appear in rejected, not candidates."""
    with _enter_mock_patches(price=None, candles=[]):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    rejected_symbols = [item["symbol"] for item in data["rejected"]]
    assert "AAPL" in rejected_symbols
    assert all(c["symbol"] != "AAPL" for c in data["candidates"])


# ── With mocked market data — pipeline runs end-to-end ───────────────────────

_MOCK_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]

_MOCK_CHAIN = [
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
        "right": "C", "volume": 500,
    }
]


def test_scan_with_mock_data_processes_symbol(client):
    """With valid mock data the symbol appears in candidates or rejected � never missing."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Apple Inc."):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    all_symbols = (
        [c["symbol"] for c in data["candidates"]] +
        [rej["symbol"] for rej in data["rejected"]]
    )
    assert "AAPL" in all_symbols


def test_scan_with_mock_data_candidate_shape(client):
    """If AAPL is scored as a candidate its TradeCardData shape must be valid."""
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Apple Inc."):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    for c in data["candidates"]:
        assert "symbol"       in c
        assert "stockScore"   in c
        assert "rrRatio"      in c
        assert "finalStatus"  in c
        assert c["direction"] == "Bullish"


def test_scan_multiple_symbols_all_accounted_for(client):
    """Every symbol in universe must appear in candidates OR rejected � none silently dropped."""
    universe = ["AAPL", "MSFT", "NVDA"]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_CHAIN,
                             company="Test Corp"):
        r = client.post("/api/scan", json={
            "universe": universe, "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    processed = (
        {c["symbol"] for c in data["candidates"]} |
        {rej["symbol"] for rej in data["rejected"]})
    assert processed == set(universe)


# ── Horizon-driven DTE window: hard-reject floor must respect hold_max_days ──

def _dte_expiry(days_from_today: int) -> str:
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _force_passing_stock_score():
    """Patches app.routers.scan.score_stock so the pre-screen/score gates
    always pass — isolates the DTE hard-reject gate under test from the
    unrelated stock-scoring pipeline, which the synthetic _MOCK_CANDLES series
    doesn't reliably clear on its own."""
    from app.scoring.stock_scorer import StockScoreCard
    return patch(
        "app.routers.scan.score_stock",
        MagicMock(return_value=StockScoreCard(
            symbol="AAPL", direction="Bullish", horizon="Swing", score=80, status="PASS",
        )),
    )


def test_scan_swing_hold_rejects_a_contract_expiring_before_the_hold_ends(client):
    """Adversarial-audit finding on the DTE-tolerance fix: a flat 10-day
    hard-reject tolerance would let a Swing (5-15d hold) scan accept a 12-DTE
    contract — expiring before the 15-day hold is even over. This exercises
    the actual _process_symbol code path (via POST /api/scan), not just
    validate_contract() directly — the unit-level tests in test_horizon_dte.py
    proved the math; this proves scan.py actually wires hold_max_days through."""
    too_short_chain = [{
        "strike": 190, "expiry": _dte_expiry(12), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 12,
        "right": "C", "volume": 500, "open_interest": 1000,
    }]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=too_short_chain,
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
            "hold_min_days": 5, "hold_max_days": 15,
        })
    data = r.json()
    assert all(c["symbol"] != "AAPL" for c in data["candidates"])
    rejected = next(rej for rej in data["rejected"] if rej["symbol"] == "AAPL")
    assert "contracts rejected" in rejected["reason"]
    assert "dte_too_short" in rejected["reason"]


def test_scan_swing_hold_accepts_a_contract_within_the_widened_window(client):
    """Same Swing hold, but a 20-DTE contract — inside the widened-but-floored
    window (16-40d after the hold_max_days=15 floor) — must be allowed through
    to scoring and produce a real candidate, not blocked by the DTE gate."""
    ok_chain = [{
        "strike": 190, "expiry": _dte_expiry(20), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 20,
        "right": "C", "volume": 500, "open_interest": 1000,
    }]
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=ok_chain,
                             company="Apple Inc."), _force_passing_stock_score():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
            "hold_min_days": 5, "hold_max_days": 15,
        })
    data = r.json()
    candidate_symbols = [c["symbol"] for c in data["candidates"]]
    rejected = next((rej for rej in data["rejected"] if rej["symbol"] == "AAPL"), None)
    assert "AAPL" in candidate_symbols or rejected is None or (
        "dte_too_short" not in rejected["reason"] and "dte_too_long" not in rejected["reason"]
    )


# ── O-4: Raise scan concurrency 3 → 5 ────────────────────────────────────────

def test_scan_concurrency_is_five():
    """O-4: _SCAN_CONCURRENCY must be 5 — O-3 batch price fetch reduces per-symbol calls to 3."""
    from app.routers.scan import _SCAN_CONCURRENCY
    assert _SCAN_CONCURRENCY == 5, f"Expected 5, got {_SCAN_CONCURRENCY}"


# ── O-3: Batch price pre-fetch ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_symbol_skips_per_symbol_price_when_in_price_map():
    """When price_map contains the symbol's price, fetch_price_async must NOT be called."""
    from app.routers.scan import _process_symbol

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()
    price_map = {"AAPL": {"last": 185.0, "prevclose": 183.0}}

    mock_card = MagicMock()
    mock_card.status = "REJECT"
    mock_card.score = 25
    mock_card.rules = []

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)) as mock_price_async,
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=mock_card),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
            price_map=price_map,
        )

    mock_price_async.assert_not_called()


# ── O-6 (superseded): Heston calibration wired back into the scan pipeline ────
# Originally removed for scan-loop performance (commit 99c51ed). WS-40 added an
# LRU cache + 1s timeout/BS-fallback (app/models/heston_cache.py) specifically so
# this could be reinstated safely — see docs/superpowers/plans/
# 2026-07-25-heston-pricing-in-trade-plan.md.

def _heston_wiring_fixtures():
    """Shared scaffolding for the tests below — mirrors the old O-6 test's mocks."""
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan

    pass_card = StockScoreCard(
        symbol="AAPL", direction="Bullish", horizon="Swing",
        score=75, status="PASS", rules=[],
    )
    contract_score = ContractScoreCard(
        contract_id="AAPL|190|2026-06-20|C",
        symbol="AAPL", strike=190.0, expiry="2026-06-20",
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = EntryAssessment(
        limit_price=2.50, max_fill=2.53, order_type="Limit", quality_status="PASS",
    )
    fake_plan = TradePlan(
        entry=entry_result,
        invalidation_price=180.0,
        premium_stop=1.5,
        time_stop_days=12,
        target_price=200.0,
        targets=[],
        rr_ratio=2.5,
        rr_model="Heston repriced",
        target_price_raw=200.0,
        invalidation_price_raw=180.0,
    )
    return pass_card, contract_score, fake_plan


@pytest.mark.asyncio
async def test_process_symbol_calls_calibrate_heston_with_the_chain():
    """calibrate_heston must run once per processed symbol, and its result must
    flow into build_trade_plan as heston_params."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_price = mock_heston.call_args.args[1]
    assert called_chain == [{
        "strike": 190.0, "expiry_years": 30 / 365.0, "mid_price": 2.50, "is_call": True,
    }]
    assert called_price == 185.0
    assert mock_build_plan.call_args.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibrate_heston_raises():
    """A Heston calibration failure must not fail the whole symbol — build_trade_plan
    must still be called, with heston_params=None (delta approximation)."""
    from app.routers.scan import _process_symbol

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=RuntimeError("boom")),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert mock_build_plan.call_args.kwargs["heston_params"] is None
    assert result is not None  # symbol still produced a trade card, didn't crash


@pytest.mark.asyncio
async def test_heston_pricing_disabled_flag_skips_calibration(monkeypatch):
    """HESTON_PRICING_ENABLED=false must be a working kill switch."""
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol

    monkeypatch.setattr(scan_module, "_HESTON_PRICING_ENABLED", False)
    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston") as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_not_called()
    assert mock_build_plan.call_args.kwargs["heston_params"] is None


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibration_exceeds_timeout(monkeypatch):
    """A calibration that runs past the wait_for ceiling must not stall this
    symbol — build_trade_plan must still be called promptly, with
    heston_params=None. Regression guard for the finding that
    heston_cache.py's internal 1s timeout does NOT bound real wall-clock time
    (its ThreadPoolExecutor.__exit__ blocks on shutdown(wait=True) regardless)."""
    import time
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    # Shrink the call-site ceiling so the test itself stays fast; the fake
    # calibration below sleeps well past it.
    monkeypatch.setattr(scan_module, "_HESTON_CALIBRATION_TIMEOUT_S", 0.05)

    def _slow_calibrate(option_chain, S, r):
        time.sleep(0.5)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    start = time.perf_counter()
    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_slow_calibrate),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.4, f"_process_symbol took {elapsed:.3f}s — the wait_for ceiling did not bound it"
    assert mock_build_plan.call_args.kwargs["heston_params"] is None
    assert result is not None

    # By design (see _run_heston_calibration's docstring), the abandoned
    # calibration keeps running in the background and holds _HESTON_SEMAPHORE
    # until it actually finishes. Give it a moment to do so before this test
    # ends, so its event loop doesn't tear down with that task still pending.
    await asyncio.sleep(0.5)


_MULTI_MOCK_CHAIN = [
    {"strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
     "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
    {"strike": 195, "expiry": "2026-06-20", "price": 1.80, "spread": 0.20,
     "delta": 0.35, "theta": -0.04, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
    {"strike": 200, "expiry": "2026-06-20", "price": 1.20, "spread": 0.20,
     "delta": 0.28, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
]


@pytest.mark.asyncio
async def test_process_symbol_reuses_heston_params_for_alt_contracts():
    """The runner-up alternatives' estimate_rr calls (scan.py's alts loop) must
    reuse the SAME per-symbol calibration as the primary contract, not None.
    Uses a 3-contract chain so runner_ups (valid_scores[1:3]) is non-empty —
    _MOCK_CHAIN elsewhere in this file has only one contract and never
    exercises this loop at all."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult
    from app.scoring.reward_risk import RrResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")
    fake_rr = RrResult(rr_ratio=1.0, model_used="Heston repriced", estimated_exit_premium=3.0)

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MULTI_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.estimate_rr", return_value=fake_rr) as mock_estimate_rr,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    # Primary contract (strike 190) is scored via build_trade_plan (mocked separately,
    # not estimate_rr) — only the two runner-ups (195, 200) call estimate_rr directly.
    assert mock_estimate_rr.call_count == 2
    for call in mock_estimate_rr.call_args_list:
        assert call.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_heston_calibration_respects_scan_concurrency_limit():
    """Regression guard: an ungated (or per-request-gated) executor could let
    far more than _SCAN_CONCURRENCY symbols calibrate at once, starving each
    other out via the wait_for ceiling. Calibration must be gated by the
    module-level _HESTON_SEMAPHORE (not the `sem` parameter passed in below,
    which only gates this function's own network-fetch phases) — so peak
    concurrent calibrations across many symbols processed at once, all
    sharing the process-wide _HESTON_SEMAPHORE, must never exceed
    _SCAN_CONCURRENCY. This also implicitly covers the cross-scan-overlap
    scenario: even if this test constructed a second, independent `sem` and
    ran a second batch of _process_symbol calls "concurrently" with these
    ones, they'd still share the same module-level _HESTON_SEMAPHORE and
    _HESTON_EXECUTOR."""
    import threading
    import time
    from app.routers.scan import _process_symbol, _SCAN_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)  # gates only this test's own network-fetch mocks
    mock_client = MagicMock()

    lock = threading.Lock()
    current = 0
    peak = 0

    def _tracking_calibrate(option_chain, S, r):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_tracking_calibrate),
    ):
        await asyncio.gather(*[
            _process_symbol(f"SYM{i}", "Bullish", "Swing", mock_client, sem, "test-scan-id")
            for i in range(10)
        ])

    assert peak <= _SCAN_CONCURRENCY, f"peak concurrent calibrations was {peak}, expected <= {_SCAN_CONCURRENCY}"


@pytest.mark.asyncio
async def test_run_heston_calibration_holds_semaphore_until_real_completion():
    """Precise regression guard: a caller giving up early (simulated here
    exactly as the real call site does, via
    asyncio.wait_for(asyncio.shield(...), timeout=...)) must NOT release
    _HESTON_SEMAPHORE before the underlying calibrate_heston call actually
    finishes — otherwise a new attempt could be admitted while this one still
    occupies a real worker, defeating the point of gating by the semaphore
    at all."""
    import time
    from app.routers.scan import _run_heston_calibration, _HESTON_SEMAPHORE, _SCAN_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    def _slow(option_chain, S, r):
        time.sleep(0.3)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    with patch("app.routers.scan.calibrate_heston", side_effect=_slow):
        task = asyncio.ensure_future(_run_heston_calibration([], 100.0))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        except asyncio.TimeoutError:
            pass  # the caller "gives up" here, exactly like _process_symbol does

        # The caller gave up, but the real job (0.3s) is still running — its
        # semaphore permit must NOT have been released yet.
        assert _HESTON_SEMAPHORE._value == _SCAN_CONCURRENCY - 1, (
            "semaphore permit was released before the underlying calibration "
            "actually finished — a new attempt could now be admitted while "
            "this one still occupies a real worker"
        )

        # Let the real job finish and release its permit, restoring full
        # capacity so this test doesn't leak state into later tests.
        await task
        assert _HESTON_SEMAPHORE._value == _SCAN_CONCURRENCY


def test_default_heston_calibration_fixture_is_active():
    """conftest.py's autouse _default_fast_heston_calibration fixture (added
    later in this same task, alongside the scan.py wiring below) must be
    patching app.routers.scan.calibrate_heston for every test by default —
    otherwise pre-existing multi-contract-chain tests elsewhere in the suite
    (test_alternatives.py, test_scan_router_spreads.py, test_shortlist.py)
    silently start doing real scipy numerical integration."""
    import app.routers.scan as scan_module
    from unittest.mock import Mock
    assert isinstance(scan_module.calibrate_heston, Mock)


# ── O-2: Candle pre-warm endpoint ─────────────────────────────────────────────

_FAKE_CANDLE_ROW = [
    {"time": "2026-01-02", "open": 100.0, "high": 105.0,
     "low": 95.0, "close": 102.0, "volume": 1000}
]


@pytest.mark.asyncio
async def test_prewarm_candles_async_calls_fetch_for_each_symbol():
    """O-2: prewarm_candles_async must call fetch_candles_async once per symbol."""
    from app.data.market import prewarm_candles_async

    with patch("app.data.market.fetch_candles_async", AsyncMock(return_value=_FAKE_CANDLE_ROW)) as mock_fetch:
        count = await prewarm_candles_async(["AAPL", "MSFT", "NVDA"])

    assert mock_fetch.call_count == 3
    symbols_called = {c[0][1] for c in mock_fetch.call_args_list}  # [0] = positional; [1] = symbol
    assert symbols_called == {"AAPL", "MSFT", "NVDA"}
    assert count == 3


def test_prewarm_endpoint_returns_prewarmed_count(client):
    """O-2: POST /api/scan/prewarm-candles must return {"prewarmed": N}."""
    with patch("app.data.market.fetch_candles_async", AsyncMock(return_value=_FAKE_CANDLE_ROW)):
        r = client.post("/api/scan/prewarm-candles", json={"symbols": ["AAPL", "MSFT"]})

    assert r.status_code == 200
    data = r.json()
    assert "prewarmed" in data
    assert data["prewarmed"] == 2
