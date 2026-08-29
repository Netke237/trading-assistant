"""Tests for the Part 3, §3.9 one-shot startup migration: an old
continuous-scan session left status=='running' must be migrated into one
`pattern='loop'` ScanScheduleEntry, not silently dropped."""
from __future__ import annotations

import pytest

from app.schemas import ScanRequest, ScanResult


@pytest.mark.asyncio
async def test_migration_noop_when_not_running():
    from app.main import _migrate_continuous_scan_session_if_running
    from app.services.scan_schedule_store import scan_schedule_store

    before = len(scan_schedule_store.list())
    await _migrate_continuous_scan_session_if_running("stopped")
    await _migrate_continuous_scan_session_if_running(None)
    assert len(scan_schedule_store.list()) == before


@pytest.mark.asyncio
async def test_migration_creates_loop_entry_when_running_with_request(monkeypatch):
    from app.main import _migrate_continuous_scan_session_if_running
    from app.services.scan_schedule_store import scan_schedule_store
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession
    import app.database as dbmod

    req = ScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing", overrides={})
    result = ScanResult(scan_id="REC-MIG-1", timestamp="2026-01-01T00:00:00+00:00", candidates=[], rejected=[])

    orig_request, orig_result = scan_module._last_request, scan_module._last_result
    scan_module._last_request = req
    scan_module._last_result = result
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    try:
        before_ids = {e["id"] for e in scan_schedule_store.list()}
        await _migrate_continuous_scan_session_if_running("running")
        after = scan_schedule_store.list()
        new_entries = [e for e in after if e["id"] not in before_ids]
        assert len(new_entries) == 1
        migrated = new_entries[0]
        assert migrated["pattern"] == "loop"
        assert migrated["mode"] == "options"
        assert migrated["resolved_request"]["universe"] == ["AAPL"]
        assert migrated["label"] == "Migrated from continuous scan"

        # Running it again (simulating a second boot) must not duplicate —
        # the session is now marked "stopped" by the migration itself, so a
        # second call with the real (now "stopped") status is a no-op.
        await _migrate_continuous_scan_session_if_running("stopped")
        assert len(scan_schedule_store.list()) == len(after)
    finally:
        for e in scan_schedule_store.list():
            if e["id"] not in before_ids:
                scan_schedule_store.delete(e["id"])
        scan_module._last_request = orig_request
        scan_module._last_result = orig_result


@pytest.mark.asyncio
async def test_migration_skips_entry_creation_when_no_last_request(monkeypatch):
    """last_request_json null/unparseable (restore_from_db() only populates
    _last_request when that column is truthy) — skip migration, just mark
    the session stopped, per the plan's explicit corrected guidance."""
    from app.main import _migrate_continuous_scan_session_if_running
    from app.services.scan_schedule_store import scan_schedule_store
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession
    import app.database as dbmod

    orig_request, orig_result = scan_module._last_request, scan_module._last_result
    scan_module._last_request = None
    scan_module._last_result = None
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    try:
        before = len(scan_schedule_store.list())
        await _migrate_continuous_scan_session_if_running("running")
        assert len(scan_schedule_store.list()) == before
    finally:
        scan_module._last_request = orig_request
        scan_module._last_result = orig_result
