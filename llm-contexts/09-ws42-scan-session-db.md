---
workstream: WS-42
branch: feat/ws-42-scan-session-db
phase: 4 (post-merge remediation)
depends_on: all phases merged to main (a8c3fb7)
conflict_class: Low — modifies scan.py, main.py, scan_session.py, migrations/env.py;
               adds one Alembic revision and one test file. No schema field renames.
---

# WS-42: ScanSession DB Persistence

## Mission

Wire the already-committed `ScanSession` SQLAlchemy model into `scan.py` and `main.py`
so that scan results and continuous-scan state survive server restarts.

Current state (what was deferred):
- `backend/app/models/scan_session.py` — model exists, uses `ScanSessionBase`
  (intentional — `Base` auto-injects a PostgreSQL UUID PK which conflicts with the
  string PK we manage ourselves)
- `backend/tests/conftest.py` — already imports `ScanSessionBase` and creates its
  table in the in-memory SQLite test DB. Do NOT touch conftest.py.
- `backend/app/routers/scan.py` — still has `_last_request` and `_last_result` as
  pure module-level globals with no DB persistence
- `backend/migrations/env.py` — does NOT include `ScanSessionBase.metadata` in
  `target_metadata`; so autogenerate ignores the table entirely

Design: **hybrid cache + DB.** Keep `_scheduler`, `_last_request`, `_last_result`
as in-memory module-level variables (fast access, scheduler must be in-process).
After every completed scan, upsert a single `ScanSession` row (fixed `id="current"`)
that mirrors those values as JSON. On app startup, read that row back and restore
the globals — then auto-resume the scheduler if status was `"running"`.

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/models/scan_session.py` | Modify | Add `last_request_json TEXT` column |
| `backend/migrations/env.py` | Modify | Add `ScanSessionBase.metadata` to `target_metadata` |
| `backend/migrations/versions/<new>.py` | Create | Alembic revision: create scan_sessions table + add last_request_json |
| `backend/app/routers/scan.py` | Modify | Add `get_db` dep to 3 endpoints; add `_upsert_session()` helper; expose `restore_from_db()` |
| `backend/app/main.py` | Modify | Add FastAPI `lifespan` context manager that restores state on startup |
| `backend/tests/test_scan_session.py` | Create | 3 tests covering persist, restore, auto-resume |

**Do NOT touch any other file.**

---

## Read-Only References

Read these files in full before writing a single line:

- `backend/app/models/scan_session.py` — current model (ScanSessionBase, existing columns)
- `backend/app/models/base.py` — why ScanSessionBase cannot inherit from Base
- `backend/app/database.py` — `AsyncSessionLocal` (use this directly in lifespan),
  `get_db` (use as Depends in endpoints)
- `backend/app/routers/scan.py` — full file; understand `_scheduler`, `_last_request`,
  `_last_result`, `_scheduled_scan()`, `run_scan()`, `start_continuous_scan()`,
  `stop_continuous_scan()`, `continuous_scan_status()`
- `backend/app/services/scan_scheduler.py` — ScanScheduler interface: `bind()`,
  `start()`, `stop()`, `set_cadence()`, `get_status()`
- `backend/app/schemas/__init__.py` — `ScanResult`, `ScanRequest`, `ContinuousScanConfig`
- `backend/app/main.py` — current `create_app()` structure (no lifespan yet)
- `backend/migrations/env.py` — current `target_metadata` list
- `backend/tests/conftest.py` — READ ONLY; understand what it already does for
  ScanSessionBase tables and the get_db override; do not modify it

---

## Task 1: Model — add last_request_json column

In `backend/app/models/scan_session.py`:

Add one column alongside the existing columns:
```
last_request_json   TEXT, nullable=True
```

Keep `ScanSessionBase` exactly as-is. Do not change any other column. Do not import
or reference `Base` from `base.py`.

---

## Task 2: Alembic migration

**Step A — wire ScanSessionBase into env.py**

In `backend/migrations/env.py`:
- Import `ScanSessionBase` from `app.models.scan_session`
- Add `ScanSessionBase.metadata` to the `target_metadata` list (currently
  `[Base.metadata, DatabaseBase.metadata]` → becomes a list of three)

**Step B — generate the revision**

From the `backend/` directory:
```
alembic revision --autogenerate -m "add scan_sessions table"
```

Verify the generated file:
- Creates `scan_sessions` table with all columns: `id`, `status`,
  `last_result_json`, `last_request_json`, `created_at`, `updated_at`
- If the table already exists in the target DB (dev.db), autogenerate may emit
  only an `add_column` for `last_request_json` — that is correct behaviour

Commit the migration file.

---

## Task 3: scan.py — DB wiring

### 3a. Imports to add at the top of scan.py (after existing imports)

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession
import json as _json
```

### 3b. Private helper: _upsert_session()

Add this function near the top of scan.py (below the existing helpers,
before the route handlers). It upserts a single row with `id="current"`:

- Accepts: `db: AsyncSession`, `req: ScanRequest | None`, `result: ScanResult | None`,
  `status: str`
- Serialises `req` and `result` to JSON strings (use `.model_dump_json()`)
- Merges into the `ScanSession` table using `await db.merge(ScanSession(id="current", ...))`
- Commits with `await db.commit()`

### 3c. Exposed function: restore_from_db()

Add a module-level async function `restore_from_db()` that:
1. Opens its own `AsyncSessionLocal()` session (cannot use Depends here)
2. Queries `SELECT * FROM scan_sessions WHERE id = 'current'`
3. If a row is found:
   - Deserialises `last_result_json` → `ScanResult` → writes to `_last_result` global
   - Deserialises `last_request_json` → `ScanRequest` → writes to `_last_request` global
   - Returns the row's `status` string (caller uses this for scheduler auto-resume)
4. If no row: returns `None`

This function is called from `main.py` lifespan, not from any HTTP handler.

### 3d. Endpoint: run_scan()

Add `db: AsyncSession = Depends(get_db)` as a parameter (after `req: ScanRequest`).

At the end of the function, immediately before `return result`, call:
```python
await _upsert_session(db, req=_last_request, result=result, status="complete")
```

`_last_result = result` stays in place (keep the in-memory global too).

### 3e. Endpoint: start_continuous_scan()

Add `db: AsyncSession = Depends(get_db)`.

After `await _scheduler.start()`, call:
```python
await _upsert_session(db, req=_last_request, result=_last_result, status="running")
```

### 3f. Endpoint: stop_continuous_scan()

Add `db: AsyncSession = Depends(get_db)`.

After `await _scheduler.stop()`, call:
```python
await _upsert_session(db, req=_last_request, result=_last_result, status="stopped")
```

### 3g. CRITICAL: _scheduled_scan() — direct call, not HTTP

`_scheduled_scan()` calls `run_scan(_last_request)` directly (bypassing FastAPI routing),
so `Depends(get_db)` does NOT resolve automatically. Fix it to create its own session:

```python
async def _scheduled_scan() -> ScanResult:
    if _last_request is None:
        raise RuntimeError("No previous scan request to repeat")
    async with AsyncSessionLocal() as db:
        return await run_scan(_last_request, db)
```

`run_scan()` accepts `db` as a positional argument after `req` — this works because
FastAPI only calls `Depends` when routing through HTTP; direct calls pass args normally.

---

## Task 4: main.py — lifespan startup hook

Convert `create_app()` to use a FastAPI `lifespan` context manager.

Pattern:
```python
from contextlib import asynccontextmanager
from app.routers.scan import (
    restore_from_db, _scheduler, _load_default_cadence,
    _scheduled_scan,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    status = await restore_from_db()   # restores _last_request, _last_result
    if status == "running":
        _scheduler.bind(_scheduled_scan)
        await _scheduler.start()
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    if _scheduler._running:
        await _scheduler.stop()
```

Pass `lifespan=lifespan` to the `FastAPI(...)` constructor. No other changes to
`create_app()`.

---

## Task 5: test_scan_session.py

Write `backend/tests/test_scan_session.py` with these 3 tests using the existing
`client` fixture from conftest (which already overrides get_db with in-memory SQLite):

**test_scan_result_persisted_to_db** — call `POST /api/scan` with a minimal payload
(mock Tradier calls as needed), then query `ScanSession` table directly via the
test engine; assert a row with `id="current"` exists and `last_result_json` is
non-null and parses as a valid JSON object with a `scan_id` key.

**test_continuous_scan_status_persisted** — call `POST /api/scan/continuous` with
a cadence, then `GET /api/scan/continuous/status`; assert `running: true`; then
`DELETE /api/scan/continuous`; assert the DB row has `status="stopped"`.

**test_restore_from_db_restores_globals** — patch `_last_result` and `_last_request`
to `None`, insert a synthetic `ScanSession` row into the test DB directly, then
call `await restore_from_db()`, then assert that the module-level globals are
no longer `None`.

Adapt mock targets to what conftest already patches. If Tradier mocks are needed
for `POST /api/scan`, follow the existing pattern in `test_routes.py` or
`test_shortlist.py`.

---

## Acceptance Criteria

- [ ] `scan_sessions` table exists in the DB with columns: `id`, `status`,
  `last_result_json`, `last_request_json`, `created_at`, `updated_at`
- [ ] `POST /api/scan` with any valid payload → `scan_sessions` table has a row
  with `id="current"`, `status="complete"`, non-null `last_result_json`
- [ ] Server restart → `restore_from_db()` populates `_last_result` and
  `_last_request` from DB; `_compute_deltas()` works correctly on the next scan
- [ ] `POST /api/scan/continuous` → DB row has `status="running"`;
  `DELETE /api/scan/continuous` → `status="stopped"`
- [ ] If DB row has `status="running"` at startup, scheduler auto-resumes
  (verified by checking `GET /api/scan/continuous/status` after server restart)
- [ ] `pytest tests/test_scan_session.py -v` — 3 tests pass
- [ ] `pytest --tb=short -q` — full suite still 132+ passed, 0 failed
- [ ] PR submitted targeting `main`; diff includes only files in Owned Files table
