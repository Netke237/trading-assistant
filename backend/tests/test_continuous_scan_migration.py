"""Tests for the Part 3, §3.9 one-shot startup migration: an old
continuous-scan session left status=='running' must be migrated into one
`pattern='loop'` ScanScheduleEntry, not silently dropped."""
from __future__ import annotations

import pytest
import yaml

from app.schemas import ScanRequest, ScanResult


def test_settings_yaml_path_resolves_to_the_real_config_file():
    """Direct check on app.main._SETTINGS_YAML_PATH's real, UNMOCKED value —
    added after a live audit-verification exercise found a gap: the other
    tests in this file all monkeypatch this constant to a tmp_path fixture,
    so none of them actually exercise whether the constant itself is
    computed correctly. Reintroducing the exact bug this file's other tests
    were written to catch (backend/app/main.py's _SETTINGS_YAML_PATH using
    `.parent` instead of `.parent.parent`, resolving to the nonexistent
    backend/app/config/settings.yaml instead of the real backend/config/
    settings.yaml) and rerunning the suite did NOT fail any existing test —
    proof this check was missing, not just belt-and-suspenders."""
    from app.main import _SETTINGS_YAML_PATH
    assert _SETTINGS_YAML_PATH.name == "settings.yaml"
    assert _SETTINGS_YAML_PATH.parent.name == "config"
    assert _SETTINGS_YAML_PATH.parent.parent.name == "backend"
    assert _SETTINGS_YAML_PATH.exists(), (
        f"{_SETTINGS_YAML_PATH} does not exist — if this ever legitimately "
        "changes (e.g. settings.yaml is removed from the repo), that's a "
        "reason to update this test, not to weaken it silently."
    )


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
async def test_migration_reads_real_settings_yaml_not_class_defaults(monkeypatch, tmp_path):
    """Regression test for a bug caught by adversarial review: the migration's
    settings.yaml path resolution once had one `.parent` too few, pointing at
    a nonexistent file — the surrounding try/except silently swallowed the
    resulting FileNotFoundError and fell back to ScheduleConfig()'s class
    defaults. The original version of this test didn't catch it because the
    real repo's settings.yaml happened to coincide with the class defaults
    on every field it asserted on. This test writes a fixture with values
    that deliberately differ from every one of ScheduleConfig's defaults, so
    a silent fallback is observably distinguishable from a real read.

    Uses a tmp_path fixture, monkeypatching app.main._SETTINGS_YAML_PATH,
    rather than touching the real backend/config/settings.yaml — a prior
    version of this test wrote directly to that real, gitignored file and
    left it permanently corrupted with fixture garbage on any host where it
    didn't already exist before the test ran (a fresh clone or CI box —
    exactly where this regression test would most need to catch the bug it
    exists for), caught by post-implementation adversarial review."""
    import app.main as main_module
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

    fixture_path = tmp_path / "settings.yaml"
    fixture_path.write_text(yaml.dump({"scan": {"schedule": fixture_schedule}}))
    monkeypatch.setattr(main_module, "_SETTINGS_YAML_PATH", fixture_path)

    orig_request, orig_result = scan_module._last_request, scan_module._last_result
    scan_module._last_request = req
    scan_module._last_result = result
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    before_ids = {e["id"] for e in scan_schedule_store.list()}
    try:
        await _migrate_continuous_scan_session_if_running("running")
        new_entries = [e for e in scan_schedule_store.list() if e["id"] not in before_ids]
        assert len(new_entries) == 1
        migrated = new_entries[0]
        assert migrated["cadence_minutes"] == fixture_schedule["cadence_minutes"]
        assert migrated["window_start_hour"] == fixture_schedule["window_start_hour"]
        assert migrated["window_end_hour"] == fixture_schedule["window_end_hour"]
        assert migrated["days_of_week"] == fixture_schedule["days_of_week"]
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
