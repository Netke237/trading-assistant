# Adversarial Audit Report: APP-AUDIT-B-SCHEDULE-ROLLBACK Implementation Plan

**Target Document:** `docs/superpowers/plans/2026-10-21-app-audit-b-schedule-rollback-plan.md`  
**Phase ID:** `APP-AUDIT-B-SCHEDULE-ROLLBACK` (#374)  
**Parent Audit:** #350 (`APP-AUDIT-SETTINGS-PROFILES`, Item 5)  
**Auditor:** Independent Adversarial Reviewer (Subagent `7a41b7c1-9a80-46ed-8c5f-c5356bd470e8`)  
**Standard:** `bmad-review-adversarial-general` with strict gate floor:
> *A finding blocks only if it can put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED DATA. A comment counts only if a competent reader acting on it would write a wrong change (it misstates mechanism).*

---

## 1. Scope & Codebase Verification

The implementation plan was cross-checked line-by-line against the live codebase:
- `backend/app/services/ingestion_schedule_store.py`
- `backend/app/services/edgar_schedule_store.py`
- `backend/app/services/sp500_schedule_store.py`
- `backend/app/services/tuning_schedule_store.py`
- `backend/app/routers/ingestion.py`
- `backend/app/routers/strategy_tuning.py`
- `backend/app/main.py` (startup scheduler wiring)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/settings/families.py` (audit harness reproducing #5)
- `docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/settings/findings.md` (finding item 5)
- `docs/superpowers/PROJECT_STATE.json` (active phase configuration and verification probe)

---

## 2. Gate-Level Analysis & Checks

### Check 1: In-Memory State Rollback & Atomicity
- **Mechanism in Plan:** In `set(...)`, a draft dictionary `candidate = dict(self._data)` is assembled and passed to `self._save_locked(candidate)`. Only upon normal return (disk persistence succeeded via atomic file replacement) is `self._data = candidate` committed.
- **Failure Scenario Analysis:** If `tmp.write_text` fails (e.g. `ENOSPC`) or `os.replace` fails (e.g. `OSError`, permission denied, destination lock):
  - Execution jumps to `finally:` block.
  - The exception propagates out of `_save_locked` into `set()`.
  - `self._data = candidate` is never executed.
  - `self._data` remains the previous committed state.
  - Subsequent calls to `get()` return the committed state, preventing uncommitted draft values from appearing in the UI or API.

### Check 2: Lock Scope & Concurrency Safety
- **Mechanism in Plan:** `self._lock` is acquired before candidate preparation and held continuously through `_save_locked` and `self._data = candidate`.
- **Concurrency Analysis:**
  - Standard `threading.Lock()` is used.
  - In existing code, `set()` released `self._lock` before calling `_save()`, which allowed concurrent readers calling `get()` to observe uncommitted in-memory mutations, and allowed concurrent writers to race on the shared `.yaml.tmp` file.
  - In the proposed code, `self._lock` guards candidate creation, disk writing, and in-memory mutation as a single atomic critical section.
  - `_save_locked` does not attempt to re-acquire `self._lock`, avoiding re-entrancy deadlock.
  - `_save()` is preserved as a backwards-compatible wrapper that acquires `self._lock` and delegates to `_save_locked(self._data)`.

### Check 3: Sidecar `.yaml.tmp` Cleanup
- **Mechanism in Plan:**
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
- **Lifecycle Analysis:**
  - When `os.replace` succeeds, `tmp` is moved to `self._path`, so `tmp.exists()` evaluates to `False`; `finally` is a no-op.
  - When `write_text` or `os.replace` raises an exception, `tmp` remains on disk; `finally` detects `tmp.exists()` and unlinks `tmp`.
  - `except OSError: pass` ensures that if unlinking fails (e.g., file lock by antivirus scanner), the primary exception is preserved and re-raised to the router.
  - Verified against `families.py:140` (`not sidecar.exists()`).

### Check 4: `TuningScheduleStore` Collection Handling
- **Mechanism in Plan:**
  ```python
  candidate = dict(self._data)
  candidate["enabled"] = bool(enabled)
  candidate["time"] = time
  if days_of_week is not None:
      candidate["days_of_week"] = list(days_of_week)
  ```
- **Data Integrity Analysis:**
  - If `days_of_week is not None`: `list(days_of_week)` allocates a fresh list, avoiding shared in-place mutation of `self._data["days_of_week"]`.
  - If `days_of_week is None`: `candidate["days_of_week"]` retains the previous list reference, but is not mutated during the call.
  - If `_save_locked` raises, neither `self._data` nor its `days_of_week` list has been modified.

### Check 5: Router & Scheduler Isolation
- **Mechanism in Plan:** Exceptions from `store.set(...)` bubble directly to router endpoints (`/api/data/{ingest,edgar,sp500}/schedule` and `/api/strategy-tuning/schedule`).
- **Endpoint Analysis:**
  - The endpoints in `backend/app/routers/ingestion.py` and `backend/app/routers/strategy_tuning.py` do not trap general `OSError` exceptions.
  - Unhandled exceptions abort handler execution before reaching `scheduler.configure(...)`, returning HTTP 500.
  - The APScheduler job retains its existing schedule in memory and on disk.
  - This matches `families.py:140` (`configure_calls_after_failure == 0`).

### Check 6: `PROJECT_STATE.json` Alignment & Verify Probe
- Phase `APP-AUDIT-B-SCHEDULE-ROLLBACK` defines:
  ```json
  "verify": {
    "kind": "present",
    "path": "backend/app/services/ingestion_schedule_store.py",
    "pattern": "_save_locked"
  }
  ```
- File 1 in the plan explicitly implements `def _save_locked(self, candidate: dict) -> None:`, satisfying `scripts/state.py` verification.

### Check 7: Test Coverage Plan
- Section 4 defines `backend/tests/test_schedule_store_rollback.py` covering:
  - Normal persistence and readback across all 4 stores.
  - Failure injection via `os.replace` patch raising `OSError`.
  - Verification of unchanged in-memory state on failure.
  - Verification of unchanged on-disk YAML on failure.
  - Verification of temporary sidecar deletion.
  - Router endpoint status code 500 and mock scheduler call count verification.

---

## 3. Audit Conclusion

No mechanism, concurrency, type, or persistence defects were found that could put a wrong number in front of a user, send an incorrect broker order, or corrupt persisted data.

GATE FINDINGS: 0
