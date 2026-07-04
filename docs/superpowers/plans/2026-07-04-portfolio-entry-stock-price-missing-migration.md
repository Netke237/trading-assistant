# Portfolio `entry_stock_price` Missing Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing Alembic migration for `portfolio_positions.entry_stock_price` so `GET /api/portfolio` stops returning HTTP 500, and add a narrow router guard as defense against a *future* missing-column drift.

**Architecture:** The `PortfolioPositionModel` declares `entry_stock_price` but no migration ever adds it, so every database at the current Alembic head lacks the column and the unguarded `select` in `get_portfolio` raises a DB error → 500. Fix = one new, reversible Alembic migration chained onto the current head, applied to whichever database(s) are in use, plus a small belt-and-suspenders exception guard in the router.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic; databases: SQLite (`backend/dev.db`) for host runs and PostgreSQL (`ritter-postgres` Docker container, `bamendjou` DB) for docker-compose runs.

---

## Verified ground truth (2026-07-04)

- **The model declares the column, no migration adds it.** `backend/app/models/portfolio.py:23` → `entry_stock_price = Column(Float, nullable=True)`. `grep -rln entry_stock_price backend/migrations/` → **no match**.
- **Both databases are at the same Alembic head and both lack the column.** `alembic heads` → single head `c8e2b47f9a13`. Confirmed live: SQLite `dev.db` and Postgres `bamendjou` are *both* at `c8e2b47f9a13`, and neither `portfolio_positions` table has `entry_stock_price`.
- **The failing endpoint.** `backend/app/routers/portfolio.py:52` `get_portfolio` does an unguarded `select(PortfolioPositionModel)`; against a table missing the column this raises — SQLite: `sqlalchemy.exc.OperationalError` ("no such column"); Postgres/asyncpg: `sqlalchemy.exc.ProgrammingError` (`UndefinedColumnError`). Either way → HTTP 500.
- **Alembic URL source.** `backend/migrations/env.py:36` sets `sqlalchemy.url` from `settings.DATABASE_URL`, and `settings` (`app/config.py`) loads `env_file=".env"` **relative to the process working directory**. So `alembic`/the app use **SQLite** when cwd is `backend/` (host / `start-backend.bat`) and **Postgres** when `DATABASE_URL` resolves to the postgres URL (docker-compose / root `.env`). The migration below is DB-agnostic and must be applied against **each** database that is actually used.

### Explicitly OUT of scope
- The previously-investigated **"stuck Loading…" symptom** is NOT addressed here. It was reproduced only under a non-standard host+SQLite launch, is not experienced in the normal environment, and has no confirmed application-code root cause. No `ensure_columns`/`create_all` reconciliation, no frontend `loading.tsx`/fetch-timeout changes — those were based on a wrong premise (the app **does** use Alembic under `backend/migrations/`, and `create_all()` is never called at startup) and are dropped.
- The Postgres-only extra column `portfolio_positions.updated_at` (present in Postgres, absent from the model and from SQLite) is a harmless pre-existing inconsistency — extra DB columns do not break ORM `select`s. Left untouched.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/migrations/versions/<generated>_add_entry_stock_price_to_portfolio_positions.py` | Create (via `alembic revision`) | Adds/drops the `entry_stock_price` column |
| `backend/app/routers/portfolio.py` | Modify | `get_portfolio` degrades to `[]` on a missing-column DB error (future-drift guard) |
| `backend/tests/test_portfolio_missing_column_guard.py` | Create | Test that a drifted table yields 200 `[]`, not 500 |

---

## Task 1: Author the migration

**Files:** Create a new migration under `backend/migrations/versions/` via Alembic (do NOT hand-write the revision id / down_revision — let Alembic chain it onto the current head).

- [ ] **Step 1: Confirm the current single head**

Run: `cd backend && venv/Scripts/python.exe -m alembic -c migrations/alembic.ini heads`
Expected: exactly `c8e2b47f9a13 (head)` (one line). If more than one head appears, STOP — a branch merge is needed first, which is out of scope for this plan.

- [ ] **Step 2: Generate the migration skeleton**

Run: `cd backend && venv/Scripts/python.exe -m alembic -c migrations/alembic.ini revision -m "add entry_stock_price to portfolio_positions"`
This creates `backend/migrations/versions/<hash>_add_entry_stock_price_to_portfolio_positions.py` with `down_revision = 'c8e2b47f9a13'` already filled in. Note the generated filename.

> Note: this uses `revision` (empty skeleton), NOT `--autogenerate`. Autogenerate would compare the *entire* model set against the DB and could sweep in the unrelated `updated_at` drift or other noise; we want a single, surgical column add.

- [ ] **Step 3: Fill in `upgrade`/`downgrade`**

Edit the generated file so its body reads (matching the existing style of `c8e2b47f9a13`'s file, plain `sa.Float()` to mirror `Column(Float)` in the model):

```python
from alembic import op
import sqlalchemy as sa

# revision identifiers are already filled in by `alembic revision`:
#   revision = '<generated hash>'
#   down_revision = 'c8e2b47f9a13'
#   branch_labels = None
#   depends_on = None


def upgrade() -> None:
    op.add_column('portfolio_positions', sa.Column('entry_stock_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('portfolio_positions', 'entry_stock_price')
```

Leave the auto-generated `revision`/`down_revision`/`branch_labels`/`depends_on` lines exactly as Alembic wrote them.

- [ ] **Step 4: Commit the migration (before applying, so it is captured even if a later step needs iteration)**

```bash
git add backend/migrations/versions/*add_entry_stock_price_to_portfolio_positions.py
git commit -m "feat(db): migration adding portfolio_positions.entry_stock_price"
```

---

## Task 2: Apply the migration to each database in use

The user runs **both** host (SQLite) and docker-compose (Postgres). Apply to both. `alembic` targets whatever `DATABASE_URL` resolves to (`env.py` reads `settings.DATABASE_URL`), so control the target by controlling `DATABASE_URL`.

- [ ] **Step 1: Apply to SQLite (`dev.db`)**

From `backend/` (cwd makes `.env` → the SQLite URL):
Run: `cd backend && venv/Scripts/python.exe -m alembic -c migrations/alembic.ini upgrade head`
Expected: Alembic logs `Running upgrade c8e2b47f9a13 -> <new hash>, add entry_stock_price to portfolio_positions`.

- [ ] **Step 2: Verify SQLite has the column**

Run:
```bash
cd backend && venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('dev.db'); print('entry_stock_price' in [r[1] for r in c.execute('PRAGMA table_info(portfolio_positions)')])"
```
Expected: `True`.

- [ ] **Step 3: Apply to Postgres (`bamendjou`)**

Ensure the `ritter-postgres` container is running (`docker ps | grep ritter-postgres`). Point `DATABASE_URL` at Postgres for this one command (Git Bash syntax):
Run:
```bash
cd backend && DATABASE_URL='postgresql+asyncpg://bamendjou:devpassword@localhost:5432/bamendjou' venv/Scripts/python.exe -m alembic -c migrations/alembic.ini upgrade head
```
Expected: same `Running upgrade c8e2b47f9a13 -> <new hash>` line. (If Alembic prints **no** `Running upgrade` line — i.e. a silent no-op — the migration was already applied to this database; that is fine, not an error.)

> Process note: `get_settings()` is `@lru_cache`d, so `DATABASE_URL` is read once per process. Each `alembic`/`curl` invocation above is a fresh process, so the inline env var takes effect — but do not expect to flip databases within a single long-running Python process.

- [ ] **Step 4: Verify Postgres has the column**

Run:
```bash
cd backend && venv/Scripts/python.exe -c "import asyncio,asyncpg
async def m():
    c=await asyncpg.connect('postgresql://bamendjou:devpassword@localhost:5432/bamendjou')
    cols=[r['column_name'] for r in await c.fetch(\"SELECT column_name FROM information_schema.columns WHERE table_name='portfolio_positions'\")]
    print('entry_stock_price' in cols); await c.close()
asyncio.run(m())"
```
Expected: `True`.

- [ ] **Step 5: Verify the endpoint returns 200 on the live backend (both DB modes if practical)**

Start the backend (host launch → SQLite) and hit the endpoint:
Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/portfolio`
Expected: **200** (was 500). If a Postgres-backed run is convenient (docker-compose), repeat and expect 200 there too.

---

## Task 3: Router guard against future missing-column drift (belt-and-suspenders)

The migration is the real fix; this guard ensures a *future* un-migrated column addition degrades to an empty list instead of a hard 500. It must catch both DB dialects' missing-column errors.

**Files:** Modify `backend/app/routers/portfolio.py` (`get_portfolio`, ~line 52); Create `backend/tests/test_portfolio_missing_column_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_portfolio_missing_column_guard.py
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client_drifted():
    # portfolio_positions table intentionally MISSING entry_stock_price (pre-migration shape).
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE portfolio_positions ("
            "id TEXT PRIMARY KEY, rec_id TEXT, symbol TEXT, contract TEXT, "
            "direction TEXT, entry_price FLOAT, qty INTEGER, entry_date TEXT, "
            "stop FLOAT, targets JSON, dte_total INTEGER, created_at TIMESTAMP)"
        ))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with Session() as s:
            yield s

    app = FastAPI()
    app.include_router(portfolio_router)  # prefix '/api'
    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def test_get_portfolio_degrades_to_empty_on_missing_column(client_drifted):
    resp = await client_drifted.get("/api/portfolio")
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_portfolio_missing_column_guard.py -v`
Expected: FAIL — `get_portfolio` currently raises (500), not 200/`[]`. (The test harness mirrors the proven pattern in `tests/test_chart_alerts_composite_create.py`: `@pytest_asyncio.fixture` + in-memory engine + `dependency_overrides[get_db]` + `ASGITransport`; `pytest.ini` has `asyncio_mode = auto`.)

- [ ] **Step 3: Add the guard**

In `backend/app/routers/portfolio.py`, add imports near the top:
```python
import logging
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)
```

Wrap only the `select` execution in `get_portfolio` (keep the existing rows→schema mapping below it unchanged):
```python
@router.get('/portfolio', response_model=list[PortfolioPositionSchema])
async def get_portfolio(db: AsyncSession = Depends(get_db)) -> list[PortfolioPositionSchema]:
    try:
        result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    except (OperationalError, ProgrammingError) as exc:
        # Belt-and-suspenders: if the table is schema-drifted (a model column with no
        # migration), degrade to empty instead of a hard 500. SQLite raises
        # OperationalError ("no such column"); asyncpg/Postgres raises ProgrammingError
        # (UndefinedColumnError). The real fix is the migration in Task 1; this stops a
        # FUTURE drift from taking the endpoint (and the portfolio rail) down.
        logger.error("get_portfolio schema error, returning empty: %s", exc)
        return []
    # ... existing rows→schema mapping unchanged ...
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_portfolio_missing_column_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/portfolio.py backend/tests/test_portfolio_missing_column_guard.py
git commit -m "fix(portfolio): degrade GET /api/portfolio to empty on missing-column drift"
```

---

## Task 4: Regression + reversibility check

- [ ] **Step 1: Full backend suite**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q`
Expected: previous pass count + 1 new test, 0 failed.

- [ ] **Step 2: Verify the migration is reversible (against SQLite dev.db)**

Run:
```bash
cd backend && venv/Scripts/python.exe -m alembic -c migrations/alembic.ini downgrade -1 && \
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('dev.db'); print('after downgrade, has col:', 'entry_stock_price' in [r[1] for r in c.execute('PRAGMA table_info(portfolio_positions)')])" && \
venv/Scripts/python.exe -m alembic -c migrations/alembic.ini upgrade head
```
Expected: `after downgrade, has col: False`, then the upgrade re-adds it (final state: column present, head = new revision). This proves both `upgrade` and `downgrade` work before the change is relied on.

- [ ] **Step 3: (If Postgres is the primary environment) repeat the reversibility check against Postgres**

Same as Step 2 but prefix each `alembic` command with `DATABASE_URL='postgresql+asyncpg://bamendjou:devpassword@localhost:5432/bamendjou'` and verify via the asyncpg snippet from Task 2 Step 4. Optional if Postgres isn't currently the active DB.

---

## Self-review checklist (done during writing)

- **Correct mechanism.** Uses Alembic (the app's actual migration system under `backend/migrations/`), not the earlier mistaken `create_all`/`ensure_columns` approach. `create_all()` is confirmed never called at startup, so nothing in this plan depends on it.
- **DB-agnostic.** The migration (`op.add_column`) applies to both SQLite and Postgres; the router guard catches both `OperationalError` (SQLite) and `ProgrammingError` (Postgres). Task 2 applies to both databases explicitly since the user uses both.
- **Surgical.** `alembic revision` (not `--autogenerate`) so only `entry_stock_price` is touched — the unrelated Postgres-only `updated_at` drift is not swept in.
- **Reversible + tested.** Task 4 verifies upgrade↔downgrade round-trips; Task 3 adds a real failing→passing test for the guard using the codebase's proven async test harness.
- **No data loss.** `op.add_column` with `nullable=True` adds an empty column; `downgrade` drops only that column. No table recreate.
- **Scope honesty.** The stall work is explicitly dropped with the reason recorded; only the confirmed, reproduced-on-both-DBs `entry_stock_price` 500 is fixed.
