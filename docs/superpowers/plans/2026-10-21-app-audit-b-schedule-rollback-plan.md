# Implementation Plan: Atomic Schedule Store Rollback on Failed Save (#374)

**Target Issue:** #374 (`Failed schedule writes change API state while disk and scheduler retain old values`)  
**Phase ID:** `APP-AUDIT-B-SCHEDULE-ROLLBACK`  
**Parent Audit:** #350 (`APP-AUDIT-SETTINGS-PROFILES`, Item 5)  
**Branch:** `board/app-audit-b-schedule-rollback-7eefd461`  
**Date:** 2026-10-21  

---

## 1. Problem Statement & Audit Evidence

### Defect Mechanism
Under `backend/app/services/`:
- `ingestion_schedule_store.py` (`IngestionScheduleStore`)
- `edgar_schedule_store.py` (`EdgarScheduleStore`)
- `sp500_schedule_store.py` (`Sp500ScheduleStore`)
- `tuning_schedule_store.py` (`TuningScheduleStore`)

In each store, `set(...)` currently mutates `self._data` in-memory under lock **before** calling `_save()` outside the lock:
```python
def set(self, enabled: bool, time: str) -> None:
    with self._lock:
        self._data["enabled"] = bool(enabled)
        self._data["time"] = time
    self._save()

def _save(self) -> None:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    tmp = self._path.with_suffix(".yaml.tmp")
    with self._lock:
        data_copy = dict(self._data)
    tmp.write_text(yaml.dump(data_copy, default_flow_style=False))
    os.replace(tmp, self._path)
```

When `tmp.write_text` or `os.replace` fails (e.g., `OSError` injected during atomic file replacement, filesystem read-only, disk full, or serialization failure):
1. **API State Ahead of Disk:** In-memory `self._data` has already been updated to the uncommitted draft values (`enabled=False`, `time="22:59"`). A subsequent `get()` returns the failed values, while the disk still contains the prior committed configuration.
2. **Scheduler Divergence:** The router endpoints (`/api/data/{ingest,edgar,sp500}/schedule` and `/api/strategy-tuning/schedule`) call `store.set(...)` followed by `scheduler.configure(...)`. Because `store.set(...)` raises a 500 error, `scheduler.configure(...)` is never called. Thus, the scheduler continues running with the old configuration, while the store's in-memory `get()` claims the new configuration is active.
3. **Leaked Temporary Sidecars:** The temporary file `.yaml.tmp` is never cleaned up if `os.replace` fails, leaving orphaned temp files on disk.
4. **Race Conditions:** `_data` is mutated in `set()`, but the lock is released before `_save()` runs. Concurrent readers calling `get()` observe the uncommitted state before it has touched disk.

### The Gate
A finding blocks only if it can put a **WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA**.
Here: A failed save leaves in-memory store state corrupted with an uncommitted configuration that disagrees with disk and the active scheduler, misrepresenting automated ingestion and tuning schedules to the operator until backend process restart.

---

## 2. Proposed Architecture & Solution

### A. Atomic Candidate Write Under Lock (`_save_locked`)
For all four stores:
1. Hold `self._lock` across the entire candidate preparation, disk persistence, and in-memory update.
2. In `set(...)`:
   - Compute `candidate = dict(self._data)`
   - Mutate candidate fields:
     - `ingestion`, `edgar`, `sp500`: `candidate["enabled"] = bool(enabled)`, `candidate["time"] = time`
     - `tuning`: `candidate["enabled"] = bool(enabled)`, `candidate["time"] = time`, and `candidate["days_of_week"] = list(days_of_week)` if provided
   - Call `self._save_locked(candidate)`
   - Only upon successful return of `_save_locked`, commit `self._data = candidate`
3. In `_save_locked(self, candidate: dict) -> None`:
   - Ensure parent directory exists: `self._path.parent.mkdir(parents=True, exist_ok=True)`
   - Define temporary path: `tmp = self._path.with_suffix(".yaml.tmp")`
   - Use a `try...finally` block:
     ```python
     try:
         tmp.write_text(yaml.dump(candidate, default_flow_style=False), encoding="utf-8")
         os.replace(tmp, self._path)
     finally:
         if tmp.exists():
             try:
                 tmp.unlink()
             except OSError:
                 pass
     ```
   - If `os.replace(tmp, self._path)` succeeds, `tmp` has been atomically moved to `self._path`, so `tmp.exists()` is `False`, and `finally` is a no-op.
   - If `write_text` or `os.replace` raises any exception:
     - The `finally` block unlinks `tmp` if it still exists.
     - The exception bubbles up to `set()`.
     - In `set()`, `self._data = candidate` is never reached. `self._data` remains the previous committed dict.
     - The exception is re-raised to the router endpoint (FastAPI returns 500).

### B. Backward Compatibility for `_save()`
If any test or internal caller invokes `self._save()`, preserve `_save(self) -> None` as a delegator to `_save_locked(self._data)` under lock:
```python
def _save(self) -> None:
    with self._lock:
        self._save_locked(self._data)
```
This ensures zero breakage of private interfaces.

---

## 3. Targeted Code Changes

### File 1: `backend/app/services/ingestion_schedule_store.py`
```python
    def set(self, enabled: bool, time: str) -> None:
        with self._lock:
            candidate = dict(self._data)
            candidate["enabled"] = bool(enabled)
            candidate["time"] = time
            self._save_locked(candidate)
            self._data = candidate

    def _save_locked(self, candidate: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        try:
            tmp.write_text(yaml.dump(candidate, default_flow_style=False), encoding="utf-8")
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _save(self) -> None:
        with self._lock:
            self._save_locked(self._data)
```

### File 2: `backend/app/services/edgar_schedule_store.py`
Identical atomic pattern to `ingestion_schedule_store.py`.

### File 3: `backend/app/services/sp500_schedule_store.py`
Identical atomic pattern to `ingestion_schedule_store.py`.

### File 4: `backend/app/services/tuning_schedule_store.py`
```python
    def set(self, enabled: bool, time: str, days_of_week: list[int] | None = None) -> None:
        with self._lock:
            candidate = dict(self._data)
            candidate["enabled"] = bool(enabled)
            candidate["time"] = time
            if days_of_week is not None:
                candidate["days_of_week"] = list(days_of_week)
            self._save_locked(candidate)
            self._data = candidate

    def _save_locked(self, candidate: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        try:
            tmp.write_text(yaml.dump(candidate, default_flow_style=False), encoding="utf-8")
            os.replace(tmp, self._path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    def _save(self) -> None:
        with self._lock:
            self._save_locked(self._data)
```

---

## 4. Test & Verification Plan

### Dedicated Unit & Integration Tests: `backend/tests/test_schedule_store_rollback.py`
Create a comprehensive test module parametrized over all 4 stores:
1. **Normal Persistence & Readback:**
   - Call `set(...)` with new values.
   - Assert in-memory `get()` returns the new values.
   - Assert on-disk YAML file matches new values.
   - Assert fresh store instance loaded from the file matches new values.
2. **Failure Injection & In-Memory Rollback:**
   - Establish initial committed state (e.g. `enabled=True, time="01:17"`).
   - Patch `os.replace` to raise `OSError("disk failure")`.
   - Call `set(enabled=False, time="22:59")`.
   - Assert `OSError` is raised.
   - Assert `store.get()` returns the original committed state (`enabled=True, time="01:17"`), NOT the failed draft.
   - Assert on-disk YAML file retains the original committed state.
   - Assert sidecar `.yaml.tmp` does NOT exist on disk (cleaned up by `finally`).
   - Instantiate a fresh store instance from disk and assert it returns the original committed state.
3. **Router-Level Rollback & Scheduler Isolation:**
   - Test router endpoints `/api/data/ingest/schedule`, `/api/data/edgar/schedule`, `/api/data/sp500/schedule`, and `/api/strategy-tuning/schedule` using `TestClient`.
   - Under patched `os.replace`, POST failing payload.
   - Assert response status is 500.
   - GET endpoint: assert returned schedule matches original committed state.
   - Assert mock scheduler `configure` method was NOT called after the failed write.

---

## 5. Non-Goals & Boundaries
- No changes to `scan_schedule_store.py` (already hardened with `_SCHEMA_VERSION = 3` and atomic rollback in PR #461 and PR #434).
- No changes to notification settings store (`atomic_yaml.py` already handles multi-writer settings.yaml).
- No changes to UI components or scheduler jobs.
