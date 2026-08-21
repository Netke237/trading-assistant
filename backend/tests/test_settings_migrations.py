"""One-time settings.yaml migrations must actually run once -- never re-fire
on a later process start and silently undo a user's explicit config change
(the exact bug class round 3 of the 2026-08-21 structural-stop audit found on
the frontend equivalent, ALERT_STORE_VERSION in lib/alertStore.ts)."""
from __future__ import annotations

import yaml

from app.services.settings_migrations import (
    STRUCTURAL_STOP_BREACHED_MIGRATION_ID,
    migrate_structural_stop_breached_enabled_types,
)


def _write(path, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def _read(path) -> dict:
    return yaml.safe_load(path.read_text())


def test_backfills_missing_type_and_marks_migration_done(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    _write(settings_path, {"alert_delivery": {"enabledTypes": ["TP_HIT", "STOP_REACHED"]}})

    migrate_structural_stop_breached_enabled_types(settings_path)

    cfg = _read(settings_path)
    assert "STRUCTURAL_STOP_BREACHED" in cfg["alert_delivery"]["enabledTypes"]
    assert STRUCTURAL_STOP_BREACHED_MIGRATION_ID in cfg["_settingsMigrations"]


def test_does_not_re_add_type_after_user_explicitly_removed_it(tmp_path):
    """Simulates: migration ran once (marker set), user later unchecked the
    type and saved -> a second 'startup' (e.g. uvicorn --reload, a crash, a
    deploy) must NOT silently re-add it."""
    settings_path = tmp_path / "settings.yaml"
    _write(settings_path, {
        "alert_delivery": {"enabledTypes": ["TP_HIT", "STOP_REACHED"]},  # user removed it
        "_settingsMigrations": [STRUCTURAL_STOP_BREACHED_MIGRATION_ID],
    })

    migrate_structural_stop_breached_enabled_types(settings_path)

    cfg = _read(settings_path)
    assert "STRUCTURAL_STOP_BREACHED" not in cfg["alert_delivery"]["enabledTypes"]


def test_is_idempotent_across_repeated_startups(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    _write(settings_path, {"alert_delivery": {"enabledTypes": ["TP_HIT", "STOP_REACHED"]}})

    migrate_structural_stop_breached_enabled_types(settings_path)
    migrate_structural_stop_breached_enabled_types(settings_path)
    migrate_structural_stop_breached_enabled_types(settings_path)

    cfg = _read(settings_path)
    assert cfg["alert_delivery"]["enabledTypes"].count("STRUCTURAL_STOP_BREACHED") == 1
    assert cfg["_settingsMigrations"].count(STRUCTURAL_STOP_BREACHED_MIGRATION_ID) == 1


def test_noop_when_settings_file_does_not_exist(tmp_path):
    settings_path = tmp_path / "settings.yaml"  # never created
    migrate_structural_stop_breached_enabled_types(settings_path)
    assert not settings_path.exists()


def test_noop_when_enabled_types_already_missing_or_not_a_list(tmp_path):
    """No alert_delivery block at all -- nothing to backfill, but the
    migration still must not raise, and marks itself done so it doesn't keep
    re-checking on every future startup."""
    settings_path = tmp_path / "settings.yaml"
    _write(settings_path, {"scan": {"universe": "SP500"}})

    migrate_structural_stop_breached_enabled_types(settings_path)

    cfg = _read(settings_path)
    assert STRUCTURAL_STOP_BREACHED_MIGRATION_ID in cfg["_settingsMigrations"]
