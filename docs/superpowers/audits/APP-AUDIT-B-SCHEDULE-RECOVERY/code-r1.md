# Adversarial Code Audit (Round 1): APP-AUDIT-B-SCHEDULE-RECOVERY (#401)

**Reviewer**: Independent Adversarial Auditor (`7ca49754-0750-42ae-bc8e-f714a4488ca5`)
**Target Diff**: `6dd96dc67fd54b3d6099ff496551267345c2ff97..d450af10`
**Reviewed Files**:
- `backend/app/services/scan_schedule_store.py`
- `backend/tests/test_scan_schedule_recovery.py`
- `docs/superpowers/plans/2026-10-20-app-audit-b-schedule-recovery-plan.md`
- `docs/superpowers/PROJECT_STATE.json`

---

## Audit Verification & Scrutiny

### 1. Load-Time Non-Destructive Behavior
- **Mechanism verified**: `ScanScheduleStore._load()` reads disk content using explicit `encoding="utf-8"` and validates:
  1. `isinstance(raw, dict)`
  2. `int(raw.get("version", 1) or 1)` with `(ValueError, TypeError)` handling
  3. `isinstance(raw_entries, list)`
- On any exception (`yaml.YAMLError`, `ValueError`, `UnicodeDecodeError`, `OSError`), execution immediately branches to `except Exception as exc:`. Under `self._lock`, `self._entries` is set to `{}` and `self._load_error` records `str(exc)`.
- Crucially, `_load()` executes zero write calls on disk during failure. The original unparseable or corrupt source bytes remain completely unmodified on disk.

### 2. Overwrite Protection & Backup Creation
- **Mechanism verified**: When an update occurs (`upsert` or `delete`), `_save_locked()` checks:
  ```python
  if self._load_error and self._path.exists():
      self._backup_corrupt()
      self._load_error = None
  ```
- `_backup_corrupt()` copies the source file via `shutil.copy` to `self._path.with_suffix(".bak.<timestamp>-<uuid>.yaml")`.
- If `_backup_corrupt()` fails (e.g. OS permissions), the exception is raised before `os.replace`, rolling back in-memory state in `upsert`/`delete` and preventing any file truncation or overwrite.
- The new valid payload is written to a temporary file (`.yaml.tmp`) and atomically moved to `self._path` via `os.replace`.
- Subsequent writes do not create duplicate `.bak` files because `self._load_error` is set to `None`.

### 3. Schema Migration & Backup Interaction
- **Mechanism verified**: In `_load()`, when schema migration is necessary (`version_int < _SCHEMA_VERSION`):
  1. Entries are transformed via `self._migrate_entry(e)` to set `params_horizon` and strip frozen strategy fields.
  2. Under lock, `self._load_error = None`.
  3. `self._backup()` delegates to `self._backup_corrupt()`, creating the migration backup.
  4. `self._save_locked()` is called. Because `self._load_error` was already cleared to `None`, `_save_locked()` does NOT generate a duplicate backup.
- This ensures clean separation between corruption backup and schema migration backup without duplicate files.

### 4. Encoding, Clean Reloads, and Concurrency
- Both `read_text` and `write_text` explicitly enforce `encoding="utf-8"`, eliminating OS-default (e.g. Windows CP1252) encoding mismatches.
- `reload()` re-reads disk state under lock, correctly populating `_load_error` if disk contents are externally corrupted, and clearing `_load_error` when valid YAML is present.
- Lock acquisition across `list()`, `get()`, `upsert()`, `delete()`, and `load_error` property prevents lost-update races.

### 5. Regression & Test Suite Verification
- All 8 new test cases in `backend/tests/test_scan_schedule_recovery.py` pass:
  - Corrupt YAML syntax preservation on load & backup on save
  - Non-dict root YAML backup on save
  - Invalid version YAML backup on save
  - Non-list entries YAML backup on save
  - Missing file produces no spurious backup
  - Clean v2 updates produce no spurious backup
  - Deletion backs up corrupt file before empty v2 write
  - `reload()` correctly tracks external disk modifications
- Full schedule test suite passed without regression: 50/50 tests passed (`test_scan_schedule.py`, `test_scan_schedule_entry.py`, `test_scan_schedule_recovery.py`).
- `python scripts/state.py` verified with 0 drift.

---

GATE FINDINGS: 0
