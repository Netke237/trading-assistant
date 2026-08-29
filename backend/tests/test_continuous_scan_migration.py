"""Tests for the Part 3, §3.9 one-shot startup migration: an old
continuous-scan session left status=='running' must be migrated into one
`pattern='loop'` ScanScheduleEntry, not silently dropped."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.schemas import ScanRequest, ScanResult

_REAL_SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"


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
async def test_migration_reads_real_settings_yaml_not_class_defaults(monkeypatch):
    """Regression test for a bug caught by adversarial review: the migration's
    settings.yaml path resolution (`_Path(__file__).parent...` inside
    app/main.py) once had one `.parent` too few, pointing at a nonexistent
    file — the surrounding try/except silently swallowed the resulting
    FileNotFoundError and fell back to ScheduleConfig()'s class defaults.
    The original version of this test file didn't catch it because the real
    repo's settings.yaml happened to coincide with the class defaults on
    every field it asserted on (cadence_minutes/window_start_hour/
    window_end_hour/days_of_week). This test writes a fixture with values
    that deliberately differ from every one of ScheduleConfig's defaults, so
    a silent fallback is observably distinguishable from a real read."""
    from app.main import _migrate_continuous_scan_session_if_running
    from app.services.scan_schedule_store import scan_schedule_store
    from app.schemas.schedule import ScheduleConfig
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession
    import app.database as dbmod

    defaults = ScheduleConfig().model_dump()
    fixture_schedule = {
        "enabled_options": True,
        "enabled_stocks": False,
        "cadence_minutes": defaults["cadence_minutes"] + 15,
        "days_of_week": [5, 6],  # deliberately not the [0..4] default
        "window_start_hour": (defaults["window_start_hour"] + 1) % 24,
        "window_end_hour": min(defaults["window_end_hour"] + 1, 24),
        "timezone_name": defaults["timezone_name"],
    }
    assert fixture_schedule["cadence_minutes"] != defaults["cadence_minutes"]
    assert fixture_schedule["window_start_hour"] != defaults["window_start_hour"]
    assert fixture_schedule["window_end_hour"] != defaults["window_end_hour"]
    assert fixture_schedule["days_of_week"] != defaults["days_of_week"]

    req = ScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing", overrides={})
    result = ScanResult(scan_id="REC-MIG-2", timestamp="2026-01-01T00:00:00+00:00", candidates=[], rejected=[])

    orig_request, orig_result = scan_module._last_request, scan_module._last_result
    scan_module._last_request = req
    scan_module._last_result = result
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    original_settings_text = _REAL_SETTINGS_PATH.read_text() if _REAL_SETTINGS_PATH.exists() else None
    original_raw = yaml.safe_load(original_settings_text) if original_settings_text else {}
    try:
        patched_raw = dict(original_raw)
        patched_raw["scan"] = {**patched_raw.get("scan", {}), "schedule": fixture_schedule}
        _REAL_SETTINGS_PATH.write_text(yaml.dump(patched_raw))

        before_ids = {e["id"] for e in scan_schedule_store.list()}
        await _migrate_continuous_scan_session_if_running("running")
        new_entries = [e for e in scan_schedule_store.list() if e["id"] not in before_ids]
        assert len(new_entries) == 1
        migrated = new_entries[0]
        assert migrated["cadence_minutes"] == fixture_schedule["cadence_minutes"]
        assert migrated["window_start_hour"] == fixture_schedule["window_start_hour"]
        assert migrated["window_end_hour"] == fixture_schedule["window_end_hour"]
        assert migrated["days_of_week"] == fixture_schedule["days_of_week"]
    finally:
        if original_settings_text is not None:
            _REAL_SETTINGS_PATH.write_text(original_settings_text)
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
