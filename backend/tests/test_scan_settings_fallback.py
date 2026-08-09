"""Regression coverage for scan.py's settings.yaml fallback (fixed 2026-08).

Before this fix, app.routers.scan read config/settings.yaml unguarded at
module import time. settings.yaml is gitignored (local override only), so any
fresh checkout with no local file crashed on import, breaking collection of
every test that transitively imports the scan router."""
from pathlib import Path

import yaml

from app.routers import scan


def test_load_settings_uses_local_file_when_present(tmp_path, monkeypatch):
    local = tmp_path / "settings.yaml"
    local.write_text(yaml.safe_dump({"scan": {"cadence_minutes": 42}}))
    example = tmp_path / "settings.example.yaml"
    example.write_text(yaml.safe_dump({"scan": {"cadence_minutes": 99}}))

    monkeypatch.setattr(scan, "_SETTINGS_PATH", local)
    monkeypatch.setattr(scan, "_SETTINGS_EXAMPLE_PATH", example)

    assert scan._load_settings() == {"scan": {"cadence_minutes": 42}}


def test_load_settings_falls_back_to_example_when_local_missing(tmp_path, monkeypatch):
    local = tmp_path / "settings.yaml"  # never created — simulates a fresh checkout
    example = tmp_path / "settings.example.yaml"
    example.write_text(yaml.safe_dump({"scan": {"cadence_minutes": 99}}))

    monkeypatch.setattr(scan, "_SETTINGS_PATH", local)
    monkeypatch.setattr(scan, "_SETTINGS_EXAMPLE_PATH", example)

    assert not local.exists()
    assert scan._load_settings() == {"scan": {"cadence_minutes": 99}}


def test_load_settings_never_crashes_module_import():
    """The real, non-monkeypatched module-level _settings must exist and be a
    dict regardless of whether backend/config/settings.yaml happens to be
    present in this environment right now."""
    assert isinstance(scan._settings, dict)


def test_settings_example_yaml_is_committed_and_parses():
    """Guards the fallback path itself: settings.example.yaml must actually
    be a real, committed, parseable file — the fallback is worthless if this
    ever goes missing or gitignored."""
    example_path = Path(scan.__file__).parent.parent.parent / "config" / "settings.example.yaml"
    assert example_path.exists(), "settings.example.yaml must be committed for the fallback to work"
    parsed = yaml.safe_load(example_path.read_text())
    assert isinstance(parsed, dict) and parsed
