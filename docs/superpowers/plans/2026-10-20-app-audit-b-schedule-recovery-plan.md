# Plan: APP-AUDIT-B-SCHEDULE-RECOVERY (#401)

## Target & Problem Statement
- **Issue**: #401 (`Saving after invalid scan schedule YAML overwrites the only recovery bytes`)
- **Phase ID**: `APP-AUDIT-B-SCHEDULE-RECOVERY`
- **Location**: `backend/app/services/scan_schedule_store.py`
- **Root Cause**:
  `ScanScheduleStore._load()` previously swallowed all load failures (`except Exception: pass`), leaving `self._entries = {}` without recording that a load failure occurred. When a subsequent write (`upsert` or `delete`) is executed, `_save_locked()` blindly wrote out a new YAML file, replacing the corrupt/unparseable file on disk without creating a backup. The only original recovery bytes were permanently destroyed.
- **Expected Behavior**:
  1. An unresolved load failure (malformed syntax, non-dict root, unparseable version string, non-list entries) must NOT overwrite the file on disk at load time (preserves bytes on load).
  2. The store must record the load failure and expose it (`load_error` property).
  3. When an ordinary write (`upsert` or `delete`) occurs while an unresolved load failure is active and the file exists on disk, the store must preserve the exact corrupt source bytes by creating a timestamped and UUID-tagged backup (`.bak.<timestamp>-<uuid>.yaml`) before overwriting with the new valid YAML payload.
  4. Subsequent reads and independent process reopening on the newly written file must reload cleanly without error.

---

## Detailed Mechanism & Implementation Plan

### 1. `ScanScheduleStore` State Tracking in `backend/app/services/scan_schedule_store.py`
Add `self._load_error: str | None = None` to `__init__`.
Expose `load_error` as a thread-safe property:
```python
@property
def load_error(self) -> str | None:
    with self._lock:
        return self._load_error
```

### 2. Robust Parse & Error Catching in `_load(self)`
In `_load(self)`:
- Read file content.
- Parse with `yaml.safe_load(content) or {}`.
- Validate root object is a dictionary (`isinstance(raw, dict)`). If not, raise `ValueError(f"Root YAML must be a mapping, got {type(raw).__name__}")`.
- Validate version value can be converted to int (`int(raw.get("version", 1) or 1)`). If `(ValueError, TypeError)` raised, raise `ValueError(f"Invalid schema version: {raw.get('version')}")`.
- Validate `entries` is a list (`isinstance(raw.get("entries", []), list)`). If not, raise `ValueError(f"'entries' must be a list, got {type(entries).__name__}")`.
- On success:
  - Check schema migration: `migrate = version_int < _SCHEMA_VERSION`.
  - If `migrate`: transform entries via `entries = [self._migrate_entry(e) for e in entries]` to strip frozen strategy fields and set `params_horizon`.
  - Populate `loaded: dict[str, dict]` from the (migrated) `entries` list (dropping malformed individual rows that lack `id`, matching existing contract).
  - Under lock: update `self._entries = loaded`, set `self._load_error = None`.
  - If `migrate`: call `self._backup()` and `self._save_locked()`.
- On exception (`except Exception as exc`):
  - Under lock: set `self._entries = {}`, `self._load_error = str(exc)`.
  - Log warning: `logger.warning("scan_schedule: failed to load %s: %s", self._path, exc)`.
  - Crucially: do NOT modify `self._path` on disk during `_load()`.

### 3. Preserving Corrupt Source Bytes via `_backup_corrupt(self)`
Define:
```python
def _backup_corrupt(self) -> Path | None:
    """Preserve unparseable or corrupt source YAML before overwriting it."""
    if not self._path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = self._path.with_suffix(f".bak.{stamp}-{uuid.uuid4().hex[:8]}.yaml")
    shutil.copy(self._path, backup_path)
    return backup_path
```

In `_save_locked(self)`:
```python
def _save_locked(self) -> None:
    """Must be called with self._lock already held."""
    self._path.parent.mkdir(parents=True, exist_ok=True)
    if self._load_error and self._path.exists():
        self._backup_corrupt()
        self._load_error = None
    tmp = self._path.with_suffix(".yaml.tmp")
    data = {"version": _SCHEMA_VERSION, "entries": list(self._entries.values())}
    tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    os.replace(tmp, self._path)
```
When `_save_locked()` is called while `self._load_error` is set:
1. `_backup_corrupt()` makes an exact byte-for-byte copy of `self._path` to `self._path.with_suffix(f".bak.{stamp}-{uuid}.yaml")`.
2. `self._load_error` is cleared.
3. The new valid YAML is written via atomic temp file replace.
4. If subsequent saves happen, no extra backup is generated because `self._load_error` is now `None`.

### 4. Provide `reload(self)`
```python
def reload(self) -> None:
    """Reload canonical state from disk under lock."""
    if self._path.exists():
        self._load()
    else:
        with self._lock:
            self._entries = {}
            self._load_error = None
```

---

## The Gate & Risk Analysis
- **Wrong Numbers**: None. Scan schedule entries define job intervals, mode, and target profile. No pricing or score calculation arithmetic is modified.
- **Corrupt Persisted Data**: This fix directly PREVENTS corrupt persisted data loss by preserving unparseable source files in `.bak.<stamp>-<uuid>.yaml` before any overwrite, and ensuring the new file is valid schema version 2 YAML.
- **Concurrency**: `_save_locked` and `_backup_corrupt` execute while `self._lock` is held. Atomic file replacement via `os.replace` is preserved.

---

## Verification & Test Plan
1. **Unit tests in `backend/tests/test_scan_schedule_recovery.py`**:
   - `test_corrupt_yaml_syntax_preserved_on_load_and_backed_up_on_save`:
     - Write malformed YAML (`version: 2\nentries: [unterminated`).
     - Load store: assert `store.list() == []`, `store.load_error is not None`, file content on disk unchanged.
     - Call `store.upsert(entry)`: assert write succeeds, original file backed up with exact match in `.bak.*.yaml`, new file has valid version 2 and entry.
     - Open new `ScanScheduleStore(path)`: assert `store.list() == [entry]`, `store.load_error is None`.
   - `test_non_dict_root_yaml_backed_up_on_save`:
     - Write root list (`- a\n- b\n`).
     - Test load preservation, error reporting, backup creation on upsert, clean reopening.
   - `test_invalid_version_yaml_backed_up_on_save`:
     - Write `version: not-an-int\nentries: []`.
     - Test load preservation, error reporting, backup creation on upsert, clean reopening.
   - `test_missing_file_no_backup_created`:
     - Non-existent path: assert `load_error is None`, `upsert` writes file without creating spurious backup.
   - `test_clean_v2_upsert_no_spurious_backup`:
     - Valid v2 file: assert normal upsert updates file without creating `.bak.*.yaml`.
2. **Run existing test suites**:
   - `backend/.venv/Scripts/pytest backend/tests/test_scan_schedule*.py`
   - All backend regression tests.
3. **Verify state**:
   - `python scripts/state.py` reports clean (0 drift).
