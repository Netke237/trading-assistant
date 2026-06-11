"""Tests for the ingestion router."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_ingest_post_triggers_job(app):
    with patch("app.routers.ingestion.start_ingestion_task") as mock_start:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/data/ingest", json={"symbols": ["AAPL", "MSFT"], "years": 1})
    assert resp.status_code == 202
    mock_start.assert_called_once()
    body = resp.json()
    assert body["status"] == "started"
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_ingest_status_returns_state(app):
    with patch("app.routers.ingestion.get_ingestion_state") as mock_state:
        mock_state.return_value = {
            "status": "completed", "total": 5, "done": 5, "failed": 0,
            "alpaca_count": 4, "gapfill_count": 1, "pruned_rows": 12,
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["alpaca_count"] == 4
