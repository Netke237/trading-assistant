---
workstream: WS-41
branch: feat/ws-41-hardening
phase: 3
depends_on: WS-33, WS-35, WS-37 (all merged to main — scan.py changes safe to base on current main)
conflict_class: Medium — touches scan.py (shared router) and settingsStore.ts. Must not change ScanRequest/ScanResponse field names or remove alertDeduplicationHours.
---

# WS-41: Infrastructure Hardening + test_routes.py Fix

## Mission

Four tasks bundled into one workstream:

1. **Multi-worker fix**: Replace 3 module-level globals in `scan.py` (`_scheduler`, `_last_request`, `_last_result`) with a `ScanSession` DB table so scan state is consistent across multiple Uvicorn workers.
2. **Shortlist cap**: Enforce `shortlist_max_candidates: 10` in `settings.yaml` — slice candidates before contract evaluation and signal truncation in the response.
3. **IV threshold wiring**: Move hardcoded `60` and `35` from `step-5-vol-events/page.tsx` into `settingsStore` so Settings → Alerts controls them.
4. **test_routes.py fix**: Update `conftest.py` to create all DB tables (WS-34's portfolio/watchlist/audit_event + this workstream's scan_session) so the 11 pre-existing `sqlalchemy.exc.OperationalError` failures resolve.

**PRD coverage:** G5, G7, R4, FR-13, FR-23, FR-45

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/models/scan_session.py` | Create | SQLAlchemy `ScanSession` ORM model |
| `backend/migrations/` | Modify | Alembic migration for scan_sessions table |
| `backend/app/routers/scan.py` | Modify | Replace 3 module-level globals with ScanSession DB reads/writes; add shortlist cap |
| `backend/app/schemas/__init__.py` | Modify | Add `shortlist_truncated: bool` and `original_count: int` to `ScanResponse` |
| `backend/config/settings.yaml` | Modify | Add `shortlist_max_candidates: 10` |
| `backend/tests/test_shortlist.py` | Create | Tests for shortlist cap enforcement |
| `backend/tests/conftest.py` | Modify | Create all DB tables in test DB; fix 11 pre-existing test_routes.py failures |
| `frontend/lib/settingsStore.ts` | Modify | Add `ivPassThreshold: 60` and `ivCautionThreshold: 35` (version 3→4) |
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | Modify | Read IV thresholds from settingsStore instead of hardcoded values |
| `frontend/app/(frame)/settings/page.tsx` | Modify | Add IV threshold inputs to Alerts sub-nav tab |

**Do NOT touch any other files.**

---

## Read-Only References

- `backend/app/models/base.py` — SQLAlchemy declarative base pattern to follow
- `backend/app/database.py` — async session factory, `get_db` dependency pattern
- `backend/app/routers/scan.py` — current module-level globals and shortlist logic (read whole file)
- `backend/app/schemas/__init__.py` — current `ScanResponse` fields (add only, never rename)
- `backend/config/settings.yaml` — existing YAML structure to extend
- `backend/tests/conftest.py` — current test fixture setup to extend
- `backend/tests/test_routes.py` — the 11 failing tests (understand what each route needs)
- `frontend/lib/settingsStore.ts` — current state: version=3, fields: `customW`, `customParams`, `broker`, `alertDeduplicationHours` — **DO NOT REMOVE ANY**
- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` — hardcoded `60` and `35` in `ivStatus()` function
- `frontend/app/(frame)/settings/page.tsx` — Alerts sub-nav tab to extend with new inputs

---

## CRITICAL WARNINGS

```
settingsStore.ts is currently at version=3 with fields:
  customW, customParams, broker, alertDeduplicationHours
WS-41 adds: ivPassThreshold (60), ivCautionThreshold (35)
NEVER remove or rename any existing field.
Bump version 3 → 4. Add migrate case for version < 4.
```

```
scan.py: WS-35 (universe expansion) and WS-37 (multi-target) are already
merged to main. Branch from current main — no rebase needed.
NEVER rename existing ScanRequest or ScanResponse fields.
ONLY ADD shortlist_truncated and original_count to ScanResponse.
```

---

## Task 1: ScanSession Model

Create `backend/app/models/scan_session.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from app.models.base import Base


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id               = Column(String, primary_key=True)   # UUID string
    status           = Column(String, nullable=False, default="idle")
    # "idle" | "running" | "complete"
    last_result_json = Column(Text, nullable=True)        # JSON-serialized ScanResponse
    created_at       = Column(DateTime(timezone=True),
                              default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime(timezone=True),
                              default=lambda: datetime.now(timezone.utc),
                              onupdate=lambda: datetime.now(timezone.utc))
```

---

## Task 2: Alembic Migration

From the `backend/` directory run:

```bash
alembic revision --autogenerate -m "add scan_sessions table"
```

Verify the generated file creates the `scan_sessions` table with all five columns. Commit the migration file.

---

## Task 3: scan.py — Replace Module-Level Globals

Read `scan.py` in full before writing. The exact global names may differ — find the 3 module-level variables used to store scheduler state, the last scan request, and the last scan result.

**Pattern to apply:**

Where code writes `_last_result = result`:
```python
# Instead: upsert a ScanSession row
import uuid, json
from sqlalchemy import select
from app.models.scan_session import ScanSession

async with db_session() as db:
    row = ScanSession(
        id=str(uuid.uuid4()),
        status="complete",
        last_result_json=result.model_dump_json(),
    )
    await db.merge(row)   # or use upsert pattern matching your base
    await db.commit()
```

Where code reads `_last_result`:
```python
async with db_session() as db:
    q = select(ScanSession).order_by(ScanSession.updated_at.desc()).limit(1)
    row = (await db.execute(q)).scalars().first()
    if row and row.last_result_json:
        result = ScanResponse.model_validate_json(row.last_result_json)
```

Where code sets scheduler status to running:
```python
# Upsert a ScanSession row with status="running"
```

`GET /api/scan/status` endpoint must query `ScanSession` table rather than reading a module global.

Use the `get_db` dependency from `database.py` for all DB access — do not create a raw engine.

---

## Task 4: Shortlist Cap

### settings.yaml — add one line

```yaml
shortlist_max_candidates: 10
```

### ScanResponse — add two fields

In `backend/app/schemas/__init__.py`, extend `ScanResponse` (keep all existing fields):

```python
class ScanResponse(BaseModel):
    # ... existing fields unchanged ...
    shortlist_truncated: bool = False
    original_count: int = 0
```

### scan.py — enforce cap before contract evaluation

After candidates are scored and sorted, before the contract evaluation loop:

```python
# Read from settings
import yaml, pathlib
_settings = yaml.safe_load((pathlib.Path(__file__).parent.parent.parent / "config" / "settings.yaml").read_text())
max_candidates = _settings.get("shortlist_max_candidates", 10)

original_count = len(sorted_candidates)
shortlist_truncated = original_count > max_candidates
sorted_candidates = sorted_candidates[:max_candidates]
```

Pass `shortlist_truncated=shortlist_truncated, original_count=original_count` into the `ScanResponse(...)` constructor call.

---

## Task 5: IV Threshold Wiring (Frontend)

### settingsStore.ts — add two fields

Current version is `3`. Add alongside **all existing fields**:

```typescript
interface SettingsState {
  // existing — DO NOT TOUCH: customW, customParams, broker, alertDeduplicationHours
  ivPassThreshold:    number;
  ivCautionThreshold: number;
  setIvPassThreshold:    (n: number) => void;
  setIvCautionThreshold: (n: number) => void;
}
```

Initial values: `ivPassThreshold: 60`, `ivCautionThreshold: 35`.

Update `persist` config:
- Bump `version` from `3` to `4`
- Add migration case for `version < 4`:
  ```typescript
  if (version < 4) {
    return {
      ...prev,
      ivPassThreshold:    60,
      ivCautionThreshold: 35,
    } as SettingsState;
  }
  ```
- Add `ivPassThreshold` and `ivCautionThreshold` to `partialize`
- Add both to `resetToDefaults` (reset to `60` and `35`)

### step-5-vol-events/page.tsx — read from store

The file currently has at the top:

```typescript
function ivStatus(rank: number): Status {
  if (rank >= 60) return 'PASS';
  if (rank >= 35) return 'CAUTION';
  return 'REJECT';
}
```

Replace with store-driven thresholds. Move `ivStatus` inside the component or make it accept threshold params:

```typescript
import { useSettingsStore } from '@/lib/settingsStore';

export default function Step5Page() {
  const ivPassThreshold    = useSettingsStore((s) => s.ivPassThreshold);
  const ivCautionThreshold = useSettingsStore((s) => s.ivCautionThreshold);

  // ...existing code...

  function ivStatus(rank: number): Status {
    if (rank >= ivPassThreshold)    return 'PASS';
    if (rank >= ivCautionThreshold) return 'CAUTION';
    return 'REJECT';
  }

  // rest of component unchanged
}
```

### settings/page.tsx — Alerts tab

In the Alerts sub-nav tab, add two number inputs following the existing input pattern in that tab:

- **IV Pass Threshold** — label: "IV Pass Threshold", initial value from `settingsStore.ivPassThreshold`, calls `setIvPassThreshold` on change
- **IV Caution Threshold** — label: "IV Caution Threshold", initial value from `settingsStore.ivCautionThreshold`, calls `setIvCautionThreshold` on change

Match the existing form row style — no new CSS needed.

---

## Task 6: conftest.py Fix (11 test_routes.py failures)

### Current failures

**DB-related (sqlalchemy.exc.OperationalError — tables don't exist in test DB):**
- `test_watchlist_length_and_shape`
- `test_portfolio_length`
- `test_alerts_length`

**Data-return failures (route returns 0 items instead of expected fixture count):**
- `test_regime_shape`, `test_sectors_length`, `test_contracts_length_and_id`
- `test_events_length`, `test_tradecards_length`
- `test_candles_aapl`, `test_candles_unknown_symbol`

### Fix strategy

**Step 1 — read conftest.py and test_routes.py first.** Understand the current client fixture, what DB engine it uses, and what each failing route calls.

**For DB-related failures**, add a session-scoped autouse fixture that creates all tables:

```python
# conftest.py — add this fixture
import pytest
from app.models.base import Base
# Force all models to register with Base.metadata before create_all:
import app.models.portfolio    # noqa: F401
import app.models.watchlist    # noqa: F401
import app.models.audit_event  # noqa: F401
import app.models.scan_session  # noqa: F401  (created by this workstream)

@pytest.fixture(scope="session", autouse=True)
async def create_test_tables(engine):  # adapt param name to match existing engine fixture
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
```

If the existing conftest uses a sync engine or a different fixture name, adapt accordingly.

**For data-return failures**, read the implementation of each failing route to see what data source it calls (Tradier client, DB query, mock file, etc.). Add monkeypatches or pytest fixtures in conftest.py that return the expected fixture data. The specific mock targets depend on how those routes are currently implemented — read the routes before writing mocks.

After your fix, `pytest tests/test_routes.py` must go from 11 failures to 0.

---

## Task 7: test_shortlist.py

```python
# backend/tests/test_shortlist.py
from unittest.mock import patch


def test_shortlist_cap_enforced(client):
    """20 candidate symbols, cap=5 → response has ≤ 5 candidates, truncated=True."""
    symbols = [f"SYM{i:02d}" for i in range(20)]

    # Patch the settings loader to return cap=5 for this test
    with patch("app.routers.scan._settings", {"shortlist_max_candidates": 5}):
        r = client.post("/api/scan", json={
            "universe": symbols,
            "direction": "Bullish",
            "horizon": "Swing",
        })

    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is True
    assert body["original_count"] == 20
    assert len(body["candidates"]) <= 5


def test_shortlist_not_truncated_when_below_cap(client):
    with patch("app.routers.scan._settings", {"shortlist_max_candidates": 10}):
        r = client.post("/api/scan", json={
            "universe": ["AAPL", "MSFT"],
            "direction": "Bullish",
            "horizon": "Swing",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is False
```

Adapt the `patch` target to match the actual variable name in `scan.py` where settings are loaded.

---

## Tasks (in order)

- [ ] 1. Read `backend/app/routers/scan.py`, `backend/app/schemas/__init__.py`, `backend/config/settings.yaml`, `backend/app/models/base.py`, `backend/tests/conftest.py`, `backend/tests/test_routes.py`, `frontend/lib/settingsStore.ts`, `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`, `frontend/app/(frame)/settings/page.tsx`
- [ ] 2. Create `backend/app/models/scan_session.py`
- [ ] 3. Run `alembic revision --autogenerate -m "add scan_sessions table"` — verify migration
- [ ] 4. Replace scan.py module-level globals with ScanSession DB reads/writes
- [ ] 5. Add `shortlist_max_candidates: 10` to `settings.yaml`; enforce cap in scan.py before contract eval; add `shortlist_truncated` + `original_count` to `ScanResponse`
- [ ] 6. Add `ivPassThreshold: 60` and `ivCautionThreshold: 35` to `settingsStore.ts` (version 3→4, migrate, partialize, resetToDefaults, setters)
- [ ] 7. Replace hardcoded `60`/`35` in `step-5-vol-events/page.tsx` with settingsStore values
- [ ] 8. Add IV threshold inputs to Settings page Alerts tab
- [ ] 9. Fix `conftest.py`: create all DB tables + add mocks for data-returning routes; run `pytest tests/test_routes.py` → 0 failures
- [ ] 10. Write `backend/tests/test_shortlist.py` (2 test cases)
- [ ] 11. Run `pytest tests/test_shortlist.py -v` — pass
- [ ] 12. Run `cd frontend && npm run typecheck` — clean
- [ ] 13. Run `cd backend && pytest --tb=short -q` — full suite, no regressions

---

## Acceptance Criteria

- [ ] `GET /api/scan/status` reads from `ScanSession` table — consistent across multiple workers
- [ ] `POST /api/scan` with large universe caps at `shortlist_max_candidates`; response has `shortlist_truncated: true` and correct `original_count`
- [ ] IV thresholds in Step 5 UI reflect values set in Settings → Alerts
- [ ] `pytest tests/test_routes.py` — 0 failures (was 11)
- [ ] `pytest tests/test_shortlist.py` — pass
- [ ] `npm run typecheck` — clean
- [ ] Full `pytest` suite — no regressions

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-41 (Infrastructure Hardening) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-41-hardening (create from current main)
Phase: 3
Depends: WS-33, WS-35, WS-37 — all merged to main. Branch from current main, no rebase needed.

Read the full context doc before writing any code:
  F:\Git\GitHub\Trading assistant\llm-contexts\08-ws41-hardening.md

Key files to read BEFORE writing anything:
- backend/app/routers/scan.py — module-level globals + shortlist logic (read whole file)
- backend/app/schemas/__init__.py — ScanResponse (only ADD fields, never rename existing)
- backend/config/settings.yaml — YAML structure to extend
- backend/app/models/base.py — SQLAlchemy base class pattern
- backend/tests/conftest.py — current fixture setup
- backend/tests/test_routes.py — 11 failing tests (understand what each route needs)
- frontend/lib/settingsStore.ts — version=3, fields: customW, customParams, broker, alertDeduplicationHours — DO NOT REMOVE ANY
- frontend/app/(frame)/screener/step-5-vol-events/page.tsx — hardcoded 60 and 35 in ivStatus()
- frontend/app/(frame)/settings/page.tsx — Alerts tab to extend

CRITICAL: settingsStore.ts version is 3. Add ivPassThreshold (60) + ivCautionThreshold (35)
alongside all existing fields. Bump version to 4. Never remove customW, customParams,
broker, or alertDeduplicationHours.

CRITICAL: scan.py — never rename existing ScanRequest/ScanResponse fields. Only ADD
shortlist_truncated (bool) and original_count (int) to ScanResponse.

Tasks in order (see context doc for full implementation details):
1. Read all key files above
2. Create backend/app/models/scan_session.py
3. alembic revision --autogenerate -m "add scan_sessions table"
4. Replace scan.py globals with ScanSession DB reads/writes
5. Add shortlist cap (settings.yaml + scan.py + ScanResponse schema)
6. Add ivPassThreshold/ivCautionThreshold to settingsStore (version 4, migrate, partialize)
7. Wire step-5-vol-events/page.tsx to use store values
8. Add IV inputs to Settings Alerts tab
9. Fix conftest.py: create all DB tables + mock data → pytest tests/test_routes.py = 0 failures
10. Write test_shortlist.py (2 test cases)
11. cd backend && pytest tests/test_shortlist.py -v  (pass)
12. cd frontend && npm run typecheck  (clean)
13. cd backend && pytest --tb=short -q  (no regressions)

Return: pytest output (test_shortlist.py + full suite) and typecheck output.
```
