"""Tests for the per-symbol regime snapshot endpoint used by the regime-alert dialog."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_regime_snapshot_omm_returns_state_and_conviction():
    """Mock compute_omm directly so the response shape is pinned down deterministically —
    do not rely on a synthetic bar series happening to classify a particular way."""
    fake_result = MagicMock()
    fake_result.state = "Bull"
    fake_result.p_stay = 0.7123
    fake_result.conviction_pct = 42
    fake_result.conviction_label = "Strong conviction"
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)), \
         patch("app.services.regime_omm.compute_omm", return_value=fake_result):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM", "direction": "Bullish"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "model": "OMM",
        "state": "Bull",
        "p_stay": 0.7123,
        "conviction_pct": 42,
        "conviction_label": "Strong conviction",
    }


@pytest.mark.asyncio
async def test_regime_snapshot_omm_insufficient_history_returns_422():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)), \
         patch("app.services.regime_omm.compute_omm", return_value=None):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM"},
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_regime_snapshot_unknown_model_rejected():
    """model is validated before get_bars is ever called — assert the I/O is skipped
    entirely rather than relying on the local DB happening to have AAPL history."""
    with patch("app.services.historical_store.get_bars", new=AsyncMock()) as mock_get_bars:
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "GARBAGE"},
            )
    assert resp.status_code == 400
    mock_get_bars.assert_not_called()


@pytest.mark.asyncio
async def test_regime_snapshot_invalid_direction_returns_400():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM", "direction": "Sideways"},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_regime_snapshot_no_bars_returns_404():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[])):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "NOSUCHSYM", "model": "OMM"},
            )
    assert resp.status_code == 404
