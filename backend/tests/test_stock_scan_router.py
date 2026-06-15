"""Unit tests for /api/stock-scan endpoint — schema and routing logic only (no live API calls)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.stock_scan import StockScanRequest
from app.routers.stock_scan import router as stock_scan_router


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_stock_scan_request_accepts_symbols():
    req = StockScanRequest(
        universe=["SP500"],
        symbols=["AAPL", "MSFT"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols == ["AAPL", "MSFT"]


def test_stock_scan_request_symbols_defaults_none():
    req = StockScanRequest(
        universe=["SP500"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols is None


# ── Endpoint fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def stock_client():
    """Minimal TestClient wiring only the stock-scan router."""
    app = FastAPI()
    app.include_router(stock_scan_router)
    return TestClient(app)


_BARS = [
    {"time": f"2024-01-{d:02d}", "open": 150.0, "high": 155.0,
     "low": 148.0, "close": 152.0, "volume": 1_000_000}
    for d in range(1, 62)   # 61 bars — enough for scoring but below signal threshold
]


def _reject_card():
    card = MagicMock()
    card.status = "REJECT"
    card.score = 20
    card.rules = []
    return card


# ── Regression: stock scan uses universe, not options candidates ───────────────

def test_stock_scan_expands_universe_when_no_symbols_given(stock_client):
    """Without symbols the router must call expand_universe and use its result."""
    # expand_universe is a lazy import inside run_stock_scan — patch the source module
    with (
        patch("app.data.universe_presets.expand_universe", return_value=["AAPL", "MSFT"]) as mock_expand,
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
        patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=_BARS)),
        patch("app.routers.stock_scan.score_stock", return_value=_reject_card()),
        patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Test")),
        patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=152.0)),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    mock_expand.assert_called_once_with(["SP500"])
    data = r.json()
    # Both symbols go through the pipeline (end up in rejected due to score, not silently dropped)
    all_symbols = {c["symbol"] for c in data["candidates"]} | {r["symbol"] for r in data["rejected"]}
    assert all_symbols == {"AAPL", "MSFT"}


def test_stock_scan_uses_symbols_directly_when_provided(stock_client):
    """When symbols is given the router must skip expand_universe entirely."""
    with (
        patch("app.data.universe_presets.expand_universe") as mock_expand,
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
        patch("app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=_BARS)),
        patch("app.routers.stock_scan.score_stock", return_value=_reject_card()),
        patch("app.routers.stock_scan.fetch_company_name_async", AsyncMock(return_value="Test")),
        patch("app.routers.stock_scan.fetch_price_async", AsyncMock(return_value=152.0)),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "symbols": ["NVDA"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    mock_expand.assert_not_called()
    data = r.json()
    all_symbols = {c["symbol"] for c in data["candidates"]} | {r["symbol"] for r in data["rejected"]}
    assert all_symbols == {"NVDA"}


def test_stock_scan_response_shape(stock_client):
    """Response must always contain scan_id, timestamp, candidates, rejected, pipeline."""
    with (
        patch("app.data.universe_presets.expand_universe", return_value=[]),
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })

    assert r.status_code == 200
    data = r.json()
    for field in ("scan_id", "timestamp", "candidates", "rejected", "pipeline"):
        assert field in data, f"Missing field: {field}"


# ── Regression: options scan pipeline is unaffected ───────────────────────────

def test_options_scan_returns_200(client):
    """POST /api/scan must still return 200 after the stock-scan decoupling."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 200


def test_options_scan_response_has_required_fields(client):
    """Options scan response shape must be unaffected by stock-scan changes."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    for field in ("scan_id", "timestamp", "candidates", "rejected"):
        assert field in data, f"Missing field: {field}"


def test_options_scan_empty_universe(client):
    """Options scan with empty universe must return empty candidates and rejected."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    })
    data = r.json()
    assert data["candidates"] == []
    assert data["rejected"] == []


def test_options_scan_invalid_direction_422(client):
    """Options scan must still reject invalid direction with 422."""
    r = client.post("/api/scan", json={
        "universe": ["AAPL"], "direction": "Sideways", "horizon": "Swing", "overrides": {},
    })
    assert r.status_code == 422
