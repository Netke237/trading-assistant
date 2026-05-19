"""Route tests for POST /api/scan.

market.py uses Tradier for live data. All tests that exercise the pipeline
mock async fetch functions so they run network-free and deterministically.
"""

import re
from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

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
