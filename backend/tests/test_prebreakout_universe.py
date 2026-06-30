import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_prebreakout_accepts_universe_field():
    """universe field is accepted and passed to expand_universe."""
    with patch(
        "app.routers.stock_scan.expand_universe",
        return_value=["AAPL", "MSFT"],
    ) as mock_expand, patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "universe": ["DOW30"],
                "direction": "Bullish",
            })
        assert resp.status_code == 200
        mock_expand.assert_called_once_with(["DOW30"])


@pytest.mark.asyncio
async def test_prebreakout_empty_symbols_and_no_universe_returns_empty():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "symbols": [],
            "direction": "Bullish",
        })
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_prebreakout_unknown_preset_returns_400():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "universe": ["RUSSELL2000"],
            "direction": "Bullish",
        })
    assert resp.status_code == 400
