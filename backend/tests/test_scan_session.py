"""Tests for ScanSession DB persistence (manual-run slot only).

The old continuous-scan mechanism this file used to also cover
(`_scheduler`, POST/DELETE /api/scan/continuous) was retired in Part 3 of
the scheduler-timezone-awareness plan — see test_scan_schedule.py for its
replacement, and test_scan_core.py for the _compute_deltas /
_execute_scan_core regression tests that moved out of test_scan_scheduler.py
(deleted).
"""

from __future__ import annotations

import json
import pytest

from app.models.scan_session import ScanSession
from app.schemas import ScanRequest, ScanResult, SCAN_RESULT_SCHEMA_VERSION

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


# ── Test 2: restore_from_db restores globals ─────────────────────────────────

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
                    # Stamped, because the only sanctioned writer stamps: _persist
                    # sets schema_version on every result it saves, so a row this
                    # code wrote is never unmarked. Hand-building the row here
                    # bypassed that and produced a blob restore_from_db correctly
                    # refuses as pre-IV-basis-split (PHASE-A-NULL-IVRANK-2026-09-06).
                    # The refusal itself is pinned in test_scan_result_vintage.py;
                    # what THIS test is about is the happy path.
                    last_result_json=ScanResult(
                        scan_id="REC-20260101-TESTTEST",
                        timestamp="2026-01-01T00:00:00+00:00",
                        candidates=[],
                        rejected=[],
                    ).model_copy(
                        update={"schema_version": SCAN_RESULT_SCHEMA_VERSION}
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


# ── Test 3: /scan/last-run ────────────────────────────────────────────────────

def test_last_run_idle_when_no_scan_yet(client, monkeypatch):
    import app.routers.scan as scan_module
    monkeypatch.setattr(scan_module, "_last_request", None)
    monkeypatch.setattr(scan_module, "_last_status", "idle")
    monkeypatch.setattr(scan_module, "_last_updated_at", None)
    r = client.get("/api/scan/last-run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "idle"
    assert body["updated_at"] is None
    assert body["universe"] is None
    assert body["strategy"] is None


def test_last_run_reflects_last_completed_scan(client):
    r = client.post("/api/scan", json={
        "universe": [],
        "direction": "Bullish",
        "horizon": "Swing",
        "overrides": {},
    })
    assert r.status_code == 200

    r = client.get("/api/scan/last-run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "complete"
    assert body["updated_at"] is not None
    assert body["direction"] == "Bullish"
    assert body["horizon"] == "Swing"


def test_last_run_exposes_the_iv_thresholds_the_scan_applied(client):
    """The spread line and the percentile line reach /scan/last-run, paired to
    the result by scan_id — this is the whole point of the three fields:
    iv_basis_analysis.py collecting over HTTP must measure section 4 against
    the number the run used, not the schema default."""
    r = client.post("/api/scan", json={
        "universe": [],
        "direction": "Bearish",
        "horizon": "Swing",
        "overrides": {},
        "iv_abs_threshold": 62.5,
        "iv_rank_threshold": 44.0,
    })
    assert r.status_code == 200
    scan_id = r.json()["scan_id"]

    body = client.get("/api/scan/last-run").json()
    assert body["iv_abs_threshold"] == 62.5
    assert body["iv_rank_threshold"] == 44.0
    # Pairing: the id names the result /scan/last serves right now, so a
    # collector can tell these thresholds describe THAT scan's rows.
    assert body["scan_id"] == scan_id
    assert client.get("/api/scan/last").json()["scan_id"] == scan_id


def test_last_run_reports_the_seeded_abs_threshold_not_the_default(client):
    """A PRE-SPLIT body names only iv_rank_threshold, and ScanRequest seeds the
    absolute knob from it. The endpoint must report what was APPLIED (30.0),
    because reporting the class default of 50 would put a threshold the scan
    never used into the measurement store — the exact false measurement the
    field exists to prevent."""
    r = client.post("/api/scan", json={
        "universe": [],
        "direction": "Bearish",
        "horizon": "Swing",
        "overrides": {},
        "iv_rank_threshold": 30.0,
    })
    assert r.status_code == 200

    body = client.get("/api/scan/last-run").json()
    assert body["iv_abs_threshold"] == 30.0
    assert body["iv_rank_threshold"] == 30.0


def test_last_run_thresholds_are_none_before_any_scan(client, monkeypatch):
    """No request means UNKNOWN, not 50. observations() records None as "not
    recoverable" and the report says so out loud; a 50 here would be indistin-
    guishable from a scan that really ran at 50."""
    import app.routers.scan as scan_module
    monkeypatch.setattr(scan_module, "_last_request", None)
    monkeypatch.setattr(scan_module, "_last_result", None)
    monkeypatch.setattr(scan_module, "_last_status", "idle")
    monkeypatch.setattr(scan_module, "_last_updated_at", None)
    body = client.get("/api/scan/last-run").json()
    assert body["scan_id"] is None
    assert body["iv_abs_threshold"] is None
    assert body["iv_rank_threshold"] is None


def test_last_run_scan_id_is_none_when_the_result_was_refused(client, monkeypatch):
    """restore_from_db drops a pre-split result but keeps its request. The
    params are then real and there is nothing to pair them with, so scan_id
    must be None — otherwise a collector would stamp thresholds onto rows this
    backend cannot even serve."""
    import app.routers.scan as scan_module
    from app.schemas import ScanRequest
    monkeypatch.setattr(scan_module, "_last_request", ScanRequest(
        universe=["AAPL"], direction="Bearish", horizon="Swing",
        iv_abs_threshold=62.5,
    ))
    monkeypatch.setattr(scan_module, "_last_result", None)
    monkeypatch.setattr(scan_module, "_last_status", "idle")
    body = client.get("/api/scan/last-run").json()
    assert body["iv_abs_threshold"] == 62.5
    assert body["scan_id"] is None


def test_continuous_scan_endpoints_are_gone(client):
    """Part 3, §3.9: the retired single-slot continuous-scan endpoints must
    not exist any more — a schedule with zero entries now means "nothing
    scheduled," not "silently replay whatever was last clicked."."""
    assert client.post("/api/scan/continuous", json={"enabled": True, "cadence_minutes": 30}).status_code == 404
    assert client.delete("/api/scan/continuous").status_code == 404
    assert client.get("/api/scan/continuous/status").status_code == 404
