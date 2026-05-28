# backend/tests/test_chart_router.py
from __future__ import annotations
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport
from app.main import app


MOCK_CANDLES = [
    {"time": "2024-01-02 09:30", "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000},
    {"time": "2024-01-02 09:45", "open": 103.0, "high": 106.0, "low": 102.0, "close": 105.0, "volume": 1200},
]


@pytest.mark.asyncio
async def test_history_returns_candles():
    """GET /chart/history returns OHLCV list."""
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/chart/history", params={"symbol": "AAPL", "interval": "15min", "days": 55})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["close"] == 103.0


@pytest.mark.asyncio
async def test_history_uppercases_symbol():
    """Symbol is uppercased regardless of input."""
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES) as mock_get:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/chart/history", params={"symbol": "aapl", "interval": "15min"})
    mock_get.assert_called_once_with("AAPL", "15min", 55)


@pytest.mark.asyncio
async def test_ws_sends_history_on_connect():
    """WebSocket sends history message immediately after connect."""
    import asyncio
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES):
        with patch("app.routers.chart.get_stream_client") as mock_sc:
            q: asyncio.Queue = asyncio.Queue()
            mock_sc.return_value.subscribe = AsyncMock(return_value=q)
            mock_sc.return_value.unsubscribe = lambda *a: None

            from starlette.testclient import TestClient
            with TestClient(app) as client:
                with client.websocket_connect("/chart/stream/AAPL?interval=15min") as ws:
                    msg = ws.receive_json()
                    assert msg["type"] == "history"
                    assert len(msg["candles"]) == 2
