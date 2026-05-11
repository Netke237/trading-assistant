"""Route tests for POST /api/scan.

market.py uses async Tradier calls. All tests that exercise the pipeline
mock fetch_batch_quotes, fetch_batch_candles, fetch_option_chain, fetch_events,
and fetch_company_name so they run network-free and deterministically.
"""

import re
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

def test_scan_no_market_data_rejects_symbol(client):
    """When candles are empty the symbol appears in rejected (pre-filter passes via quote, fails on blank candles)."""
    mock_quotes = {"AAPL": {"last": 185.0, "prevclose": 184.0, "average_volume": 5_000_000,
                              "week_52_high": 200.0, "week_52_low": 150.0}}
    with patch("app.routers.scan.fetch_batch_quotes",   return_value=mock_quotes), \
         patch("app.routers.scan.fetch_batch_candles",  return_value={"AAPL": []}), \
         patch("app.routers.scan.fetch_option_chain",  return_value=[]):
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

_MOCK_QUOTE = {
    "last": 185.0,
    "average_volume": 5_000_000,
    "week_52_high": 200.0,
    "week_52_low": 150.0,
}

_MOCK_EVENTS = {"earnings_date": None, "dividend_date": None}


def test_scan_with_mock_data_processes_symbol(client):
    """With valid mock data the symbol appears in candidates or rejected — never missing."""
    mock_quotes = {
        "AAPL": {"last": 185.0, "prevclose": 184.0, "average_volume": 60_000_000,
                  "week_52_high": 200.0, "week_52_low": 150.0},
    }
    with patch("app.routers.scan.fetch_batch_quotes",   return_value=mock_quotes), \
         patch("app.routers.scan.fetch_batch_candles",  return_value={"AAPL": _MOCK_CANDLES}), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_CHAIN), \
         patch("app.routers.scan.fetch_events",         return_value={"earnings_date": None, "dividend_date": None}), \
         patch("app.routers.scan.fetch_company_name",  return_value="Apple Inc."):
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
    mock_quotes = {
        "AAPL": {"last": 185.0, "prevclose": 184.0, "average_volume": 60_000_000,
                  "week_52_high": 200.0, "week_52_low": 150.0},
    }
    with patch("app.routers.scan.fetch_batch_quotes",   return_value=mock_quotes), \
         patch("app.routers.scan.fetch_batch_candles",  return_value={"AAPL": _MOCK_CANDLES}), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_CHAIN), \
         patch("app.routers.scan.fetch_events",         return_value={"earnings_date": None, "dividend_date": None}), \
         patch("app.routers.scan.fetch_company_name",  return_value="Apple Inc."):
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
    """Every symbol in universe must appear in candidates OR rejected — none silently dropped."""
    universe = ["AAPL", "MSFT", "NVDA"]
    quotes = {s: _MOCK_QUOTE for s in universe}
    candles = {s: _MOCK_CANDLES for s in universe}
    with patch("app.routers.scan.fetch_batch_quotes",   new_callable=AsyncMock, return_value=quotes), \
         patch("app.routers.scan.fetch_batch_candles",  new_callable=AsyncMock, return_value=candles), \
         patch("app.routers.scan.fetch_option_chain",   new_callable=AsyncMock, return_value=_MOCK_CHAIN), \
         patch("app.routers.scan.fetch_events",         new_callable=AsyncMock, return_value=_MOCK_EVENTS), \
         patch("app.routers.scan.fetch_company_name",   new_callable=AsyncMock, return_value="Corp"):
        r = client.post("/api/scan", json={
            "universe": universe, "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    data = r.json()
    processed = (
        {c["symbol"] for c in data["candidates"]} |
        {rej["symbol"] for rej in data["rejected"]})
    assert processed == set(universe)
