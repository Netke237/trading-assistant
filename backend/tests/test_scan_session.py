"""Tests for WS-42 ScanSession DB persistence."""

from __future__ import annotations

import json
import pytest

from app.models.scan_session import ScanSession
from app.schemas import ScanRequest, ScanResult

# Re-use the test engine / session factory from conftest so we can query
# the same in-memory SQLite DB that the client fixture writes to.
from tests.conftest import _TestSession, _test_engine


# ── Test 1: Scan result persisted to DB ──────────────────────────────────────

def test_scan_result_persisted_to_db(client):
    """POST /api/scan with empty universe still writes a scan_sessions row."""
    r = client.post("/api/scan", json={
        "universe": [],
        "direction": "Bullish",
        "horizon": "Swing",
        "overrides": {},
    })
    assert r.status_code == 200

    # Query the DB directly
    import asyncio

    async def _check():
        async with _TestSession() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScanSession).where(ScanSession.id == "current")
            )
            return result.scalar_one_or_none()

    row = asyncio.run(_check())
    assert row is not None
    assert row.status == "complete"
    assert row.last_result_json is not None
    parsed = json.loads(row.last_result_json)
    assert "scan_id" in parsed


# ── Test 2: Continuous scan status persisted ─────────────────────────────────

def test_continuous_scan_status_persisted(client):
    """Start then stop continuous scan → DB row reflects running then stopped."""
    from unittest.mock import AsyncMock, MagicMock
    import app.routers.scan as scan_module

    mock_scheduler = MagicMock()
    mock_scheduler.start = AsyncMock()
    mock_scheduler.stop = AsyncMock()
    original = scan_module._scheduler
    scan_module._scheduler = mock_scheduler
    try:
        # Start
        r = client.post("/api/scan/continuous", json={
            "enabled": True, "cadence_minutes": 30,
        })
        assert r.status_code == 200
        status = r.json()
        assert status["enabled"] is True

        # Check DB
        import asyncio
        from sqlalchemy import select

        async def _check():
            async with _TestSession() as session:
                result = await session.execute(
                    select(ScanSession).where(ScanSession.id == "current")
                )
                return result.scalar_one_or_none()

        row = asyncio.run(_check())
        assert row is not None
        assert row.status == "running"

        # Stop
        r = client.delete("/api/scan/continuous")
        assert r.status_code == 200
        assert r.json()["status"] == "stopped"

        row = asyncio.run(_check())
        assert row is not None
        assert row.status == "stopped"
    finally:
        scan_module._scheduler = original


# ── Test 3: restore_from_db restores globals ─────────────────────────────────

@pytest.mark.asyncio
async def test_restore_from_db_restores_globals():
    """Insert a synthetic row → restore_from_db() repopulates module globals."""
    import app.routers.scan as scan_module

    # Save originals
    orig_request = scan_module._last_request
    orig_result = scan_module._last_result
    orig_async_session_local = scan_module.AsyncSessionLocal

    # Reset globals
    scan_module._last_request = None
    scan_module._last_result = None

    # Patch AsyncSessionLocal to use the test DB session maker
    scan_module.AsyncSessionLocal = _TestSession

    try:
        # Insert synthetic row (replace any existing)
        from sqlalchemy import delete
        async with _TestSession() as session:
            await session.execute(delete(ScanSession).where(ScanSession.id == "current"))
            await session.commit()

        async with _TestSession() as session:
            session.add(
                ScanSession(
                    id="current",
                    status="complete",
                    last_request_json=ScanRequest(
                        universe=["AAPL"], direction="Bullish", horizon="Swing"
                    ).model_dump_json(),
                    last_result_json=ScanResult(
                        scan_id="REC-20260101-TESTTEST",
                        timestamp="2026-01-01T00:00:00+00:00",
                        candidates=[],
                        rejected=[],
                    ).model_dump_json(),
                )
            )
            await session.commit()

        # Call restore
        status = await scan_module.restore_from_db()
        assert status == "complete"
        assert scan_module._last_request is not None
        assert scan_module._last_result is not None
        assert scan_module._last_result.scan_id == "REC-20260101-TESTTEST"
        assert scan_module._last_request.universe == ["AAPL"]
    finally:
        scan_module._last_request = orig_request
        scan_module._last_result = orig_result
        scan_module.AsyncSessionLocal = orig_async_session_local
