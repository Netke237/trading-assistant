"""Tests for POST /api/scan/fib-pullback endpoint."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app

BARS_50 = [
    {"open": 100.0 + i * 0.1, "high": 101.0 + i * 0.1,
     "low": 99.0 + i * 0.1, "close": 100.5 + i * 0.1, "volume": 1_000_000}
    for i in range(120)
]


@pytest.mark.asyncio
async def test_fib_pullback_returns_list():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        row = data[0]
        assert "symbol" in row
        assert "fib_level_hit" in row
        assert "fib_dist_pct" in row
        assert "at_level" in row
        assert "confidence" in row


@pytest.mark.asyncio
async def test_fib_pullback_accepts_params_override():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["MSFT"],
                "direction": "Bullish",
                "params_override": {
                    "fib_swing_lookback": 80,
                    "fib_levels": [38.2, 61.8],
                    "fib_tolerance_pct": 0.02,
                },
            })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_fib_pullback_rejects_unknown_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"bad_key": 99},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_empty_bars_skipped():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_fib_pullback_universe_expansion():
    with patch("app.routers.stock_scan.expand_universe") as mock_expand, \
         patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_expand.return_value = ["AAPL", "MSFT"]
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": [],
                "direction": "Bullish",
                "universe": ["SP500"],
            })
    assert resp.status_code == 200
    assert len(resp.json()) == 2
