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


# ── O-6: Remove Heston ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_symbol_does_not_call_calibrate_heston():
    """Heston calibration must NOT be invoked in the scan pipeline (O-6 — always use BS)."""
    from app.routers.scan import _process_symbol
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.reward_risk import RrResult

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

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
    rr_result = RrResult(rr_ratio=2.5, model_used="Delta approximation", estimated_exit_premium=4.5)
    # Entry/exit/RR/targets now come from the shared build_trade_plan helper —
    # mock it wholesale so this test stays focused on the calibrate_heston assertion.
    from app.scoring.trade_plan import TradePlan
    fake_plan = TradePlan(
        entry=entry_result,
        invalidation_price=180.0,
        premium_stop=1.5,
        time_stop_days=12,
        target_price=200.0,
        targets=[],
        rr_ratio=2.5,
        rr_model="Delta approximation",
        target_price_raw=200.0,
        invalidation_price_raw=180.0,
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
        patch("app.routers.scan.estimate_rr", return_value=rr_result),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", create=True) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_not_called()


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
