"""Tests for ScanScheduleStore corrupt file recovery and backup preservation (#401).

Guarantees:
1. Malformed syntax, non-dict root, non-int version, and non-list entries do NOT
   overwrite or corrupt the file on disk at load time.
2. The store records the load error via `store.load_error`.
3. Subsequent save (upsert or delete) creates an exact timestamped + UUID backup
   (`.bak.<stamp>-<uuid>.yaml`) preserving the original recovery bytes before
   overwriting the disk file with valid schema version 2 YAML.
4. Independent re-opening loads the new valid file cleanly without errors.
5. Missing files and valid files do not produce spurious backups.
"""
from __future__ import annotations

from pathlib import Path
import yaml
import pytest

from app.services.scan_schedule_store import ScanScheduleStore, _SCHEMA_VERSION


def _sample_entry(**overrides) -> dict:
    base = {
        "id": "e1",
        "label": "Sample Schedule",
        "mode": "options",
        "profile_id": "p1",
        "profile_name": "My Profile",
        "profile_synced_at": "2026-01-01T00:00:00Z",
        "resolved_request": {
            "universe": ["AAPL"],
            "direction": "Bullish",
            "horizon": "Swing",
            "overrides": {},
        },
        "pattern": "fixed_time",
        "enabled": True,
        "days_of_week": [0, 1, 2, 3, 4],
        "fire_time": "09:00",
    }
    base.update(overrides)
    return base


def _list_backups(dir_path: Path) -> list[Path]:
    return list(dir_path.glob("*.bak.*.yaml"))


def test_corrupt_yaml_syntax_preserved_on_load_and_backed_up_on_save(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    corrupt_content = "version: 2\nentries: [unterminated syntax"
    path.write_text(corrupt_content, encoding="utf-8")

    # 1. Load: disk file untouched, entries empty, load_error populated
    store = ScanScheduleStore(path=path)
    assert store.list() == []
    assert store.load_error is not None
    assert path.read_text(encoding="utf-8") == corrupt_content
    assert _list_backups(tmp_path) == []

    # 2. Subsequent write: backs up corrupt bytes, writes valid v2, clears load_error
    entry = _sample_entry()
    store.upsert(entry)

    backups = _list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_content
    assert store.load_error is None
    assert store.get("e1") == entry

    # 3. Verify newly written file is valid YAML version 2
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["version"] == _SCHEMA_VERSION
    assert len(raw["entries"]) == 1
    assert raw["entries"][0]["id"] == "e1"

    # 4. Re-open independently: clean load
    store2 = ScanScheduleStore(path=path)
    assert store2.load_error is None
    assert len(store2.list()) == 1
    assert store2.get("e1")["label"] == "Sample Schedule"

    # 5. Subsequent write does NOT create another backup
    store2.upsert(_sample_entry(id="e2", label="Second Entry"))
    assert len(_list_backups(tmp_path)) == 1


def test_non_dict_root_yaml_backed_up_on_save(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    raw_list_content = "- item1\n- item2\n- item3\n"
    path.write_text(raw_list_content, encoding="utf-8")

    store = ScanScheduleStore(path=path)
    assert store.list() == []
    assert store.load_error is not None
    assert "Root YAML must be a mapping" in store.load_error
    assert path.read_text(encoding="utf-8") == raw_list_content
    assert _list_backups(tmp_path) == []

    entry = _sample_entry()
    store.upsert(entry)

    backups = _list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == raw_list_content
    assert store.load_error is None

    store2 = ScanScheduleStore(path=path)
    assert store2.load_error is None
    assert store2.list() == [entry]


def test_invalid_version_yaml_backed_up_on_save(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    invalid_ver_content = "version: not-an-int\nentries: []\n"
    path.write_text(invalid_ver_content, encoding="utf-8")

    store = ScanScheduleStore(path=path)
    assert store.list() == []
    assert store.load_error is not None
    assert "Invalid schema version" in store.load_error
    assert path.read_text(encoding="utf-8") == invalid_ver_content

    entry = _sample_entry()
    store.upsert(entry)

    backups = _list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == invalid_ver_content
    assert store.load_error is None

    store2 = ScanScheduleStore(path=path)
    assert store2.load_error is None
    assert store2.list() == [entry]


def test_non_list_entries_yaml_backed_up_on_save(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    non_list_content = "version: 2\nentries: 'not-a-list'\n"
    path.write_text(non_list_content, encoding="utf-8")

    store = ScanScheduleStore(path=path)
    assert store.list() == []
    assert store.load_error is not None
    assert "'entries' must be a list" in store.load_error
    assert path.read_text(encoding="utf-8") == non_list_content

    entry = _sample_entry()
    store.upsert(entry)

    backups = _list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == non_list_content
    assert store.load_error is None

    store2 = ScanScheduleStore(path=path)
    assert store2.load_error is None
    assert store2.list() == [entry]


def test_missing_file_no_backup_created(tmp_path: Path):
    path = tmp_path / "does_not_exist.yaml"
    store = ScanScheduleStore(path=path)
    assert store.list() == []
    assert store.load_error is None

    entry = _sample_entry()
    store.upsert(entry)

    assert path.exists()
    assert _list_backups(tmp_path) == []
    assert store.list() == [entry]


def test_clean_v2_upsert_no_spurious_backup(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    entry1 = _sample_entry(id="e1", label="Entry 1")
    path.write_text(
        yaml.dump({"version": _SCHEMA_VERSION, "entries": [entry1]}),
        encoding="utf-8",
    )

    store = ScanScheduleStore(path=path)
    assert store.load_error is None
    assert store.list() == [entry1]

    entry2 = _sample_entry(id="e2", label="Entry 2")
    store.upsert(entry2)

    assert _list_backups(tmp_path) == []
    assert len(store.list()) == 2


def test_delete_backs_up_corrupt_file(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    corrupt_content = "version: 2\nentries: [malformed"
    path.write_text(corrupt_content, encoding="utf-8")

    store = ScanScheduleStore(path=path)
    assert store.load_error is not None

    store.delete("nonexistent_id")

    backups = _list_backups(tmp_path)
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == corrupt_content
    assert store.load_error is None
    assert store.list() == []

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["version"] == _SCHEMA_VERSION
    assert raw["entries"] == []


def test_reload_reflects_disk_state(tmp_path: Path):
    path = tmp_path / "scan_schedule.yaml"
    corrupt_content = "{corrupt: [syntax"
    path.write_text(corrupt_content, encoding="utf-8")

    store = ScanScheduleStore(path=path)
    assert store.load_error is not None

    # Fix file on disk externally
    entry = _sample_entry()
    path.write_text(
        yaml.dump({"version": _SCHEMA_VERSION, "entries": [entry]}),
        encoding="utf-8",
    )
    store.reload()
    assert store.load_error is None
    assert store.list() == [entry]

    # Re-corrupt file on disk externally
    path.write_text(corrupt_content, encoding="utf-8")
    store.reload()
    assert store.load_error is not None
    assert store.list() == []

    # Remove file on disk externally
    path.unlink()
    store.reload()
    assert store.load_error is None
    assert store.list() == []
