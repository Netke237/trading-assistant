"""Tests for the ingestion router."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.data.tiingo_budget import TiingoBudgetConfigError
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


# ── HISTORY-INCREMENTAL-NIGHTLY A2 (#478): tiingo_usage never breaks the status ──

@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    RuntimeError("db down"),
    TiingoBudgetConfigError("data_providers.tiingo.requests_per_hour is missing"),
])
async def test_ingest_status_survives_tiingo_usage_error(app, error, caplog):
    with patch("app.routers.ingestion.get_ingestion_state", return_value={"status": "idle"}), \
         patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})), \
         patch("app.data.tiingo_budget.usage_summary", AsyncMock(side_effect=error)):
        with caplog.at_level("WARNING", logger="app.routers.ingestion"):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert body["tiingo_usage"] is None
    assert str(error) in body["tiingo_usage_error"]
    assert any("tiingo usage unavailable" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_ingest_status_passes_tiingo_usage_through(app):
    usage = {"requests_per_hour": {"used": 1, "limit": 50, "nightly_stop_at": 50,
                                   "window": "rolling 1 h"}}
    with patch("app.routers.ingestion.get_ingestion_state", return_value={"status": "idle"}), \
         patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})), \
         patch("app.data.tiingo_budget.usage_summary", AsyncMock(return_value=usage)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    assert resp.json()["tiingo_usage"] == usage
    assert resp.json()["tiingo_usage_error"] is None


# ── HISTORY-INCREMENTAL-NIGHTLY B3 (#497): the per-run counters ──────────────

RUN_COUNTERS = ("suffix_only", "adjustment_changed", "prefix_refetched", "prefix_rescaled",
                "prefix_confirmed", "confirm_retry", "lag_window_full", "single_provider_recent",
                "single_provider_skipped_current", "revalidated", "revalidation_skipped_budget",
                "tiingo_requests", "tiingo_bytes")


@pytest.mark.asyncio
async def test_ingest_status_shows_the_run_counters(app):
    counters = {key: i + 1 for i, key in enumerate(RUN_COUNTERS)}
    with patch("app.routers.ingestion.get_ingestion_state",
               return_value={"status": "completed", **counters}), \
         patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})), \
         patch("app.data.tiingo_budget.usage_summary", AsyncMock(return_value={})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert {key: body[key] for key in RUN_COUNTERS} == counters
    assert body["tiingo_usage"] == {}


@pytest.mark.asyncio
async def test_ingest_status_answers_before_the_first_run_without_counters(app):
    with patch("app.routers.ingestion.get_ingestion_state", return_value={"status": "idle"}), \
         patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})), \
         patch("app.data.tiingo_budget.usage_summary", AsyncMock(return_value={})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "idle"
    assert not set(RUN_COUNTERS) & set(body)      # no run yet in this process: no counters


@pytest.mark.asyncio
async def test_ingest_status_shows_the_real_job_state_counters(app, monkeypatch):
    from app.services import ingestion_job
    assert ingestion_job.RUN_COUNTERS == RUN_COUNTERS
    monkeypatch.setattr(ingestion_job, "_state", {**ingestion_job._state,
                                                  **dict.fromkeys(RUN_COUNTERS, 0),
                                                  "suffix_only": 7, "tiingo_requests": None})
    with patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value={})),          patch("app.data.tiingo_budget.usage_summary", AsyncMock(return_value={})):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["suffix_only"] == 7 and body["tiingo_requests"] is None
    assert all(key in body for key in RUN_COUNTERS)
