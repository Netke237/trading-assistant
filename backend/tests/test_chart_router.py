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
    mock_get.assert_called_once_with("AAPL", "15min", None)


@pytest.mark.asyncio
async def test_history_rejects_non_positive_days():
    """`days` is honored as an explicit override (not floored) since the
    days-as-a-limit fix, so a non-positive value is no longer implicitly
    corrected by the old `max(days, cap)` widening — it must be rejected
    at the query-param boundary instead of flowing a negative/zero window
    into the data layer."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp_zero = await client.get("/chart/history", params={"symbol": "AAPL", "interval": "daily", "days": 0})
        resp_negative = await client.get("/chart/history", params={"symbol": "AAPL", "interval": "daily", "days": -5})
    assert resp_zero.status_code == 422
    assert resp_negative.status_code == 422


# NOTE: the WebSocket tests below use the *synchronous* Starlette TestClient and
# must NOT be `async`/`@pytest.mark.asyncio`. Running a sync TestClient inside an
# already-running event loop deadlocks. They also intentionally do NOT use
# `with TestClient(app)` (which would run the app lifespan): the endpoint is fully
# mocked here, and triggering lifespan starts the module-level notification queue
# worker, whose import-time asyncio.Queue binds to the first test's event loop and
# then raises "bound to a different event loop" on the next test. Skipping lifespan
# keeps these tests isolated.


def test_ws_sends_history_on_connect():
    """WebSocket sends history message immediately after connect."""
    import asyncio
    with patch("app.routers.chart.get_intraday", return_value=MOCK_CANDLES):
        with patch("app.routers.chart.get_stream_client") as mock_sc:
            q: asyncio.Queue = asyncio.Queue()
            mock_sc.return_value.subscribe = AsyncMock(return_value=q)
            mock_sc.return_value.unsubscribe = lambda *a: None

            from starlette.testclient import TestClient
            client = TestClient(app)
            with client.websocket_connect("/chart/stream/AAPL?interval=15min") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "history"
                assert len(msg["candles"]) == 2


def test_stream_empty_candles_sends_error():
    """WebSocket sends error message when get_intraday returns empty list."""
    with patch("app.routers.chart.get_intraday", return_value=[]):
        with patch("app.routers.chart.get_stream_client") as mock_sc:
            mock_sc.return_value.subscribe = AsyncMock(return_value=None)
            mock_sc.return_value.unsubscribe = lambda *a: None

            from starlette.testclient import TestClient
            client = TestClient(app)
            with client.websocket_connect("/chart/stream/CLX?interval=4h") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "No chart data" in msg["message"]


def test_stream_exception_sends_friendly_error():
    """WebSocket sends friendly error message without exposing raw exception text."""
    with patch("app.routers.chart.get_intraday", side_effect=Exception("internal boom")):
        with patch("app.routers.chart.get_stream_client") as mock_sc:
            mock_sc.return_value.subscribe = AsyncMock(return_value=None)
            mock_sc.return_value.unsubscribe = lambda *a: None

            from starlette.testclient import TestClient
            client = TestClient(app)
            with client.websocket_connect("/chart/stream/AAPL?interval=15min") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "boom" not in msg["message"]
