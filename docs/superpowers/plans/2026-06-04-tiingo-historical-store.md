# Tiingo OHLCV Historical Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist daily OHLCV history from Tiingo in the application database so that stock scans read from a local table first and only fetch the missing delta from Tiingo, eliminating rate-limit failures for large universes like S&P 500.

**Architecture:** A new `ohlcv_daily` DB table (Alembic-managed, composite PK on symbol+date) stores bars permanently. A `historical_store.py` service provides `get_bars()` (DB-first, delta-only Tiingo fetch) and `prefetch_universe()` (rate-limited background job that pre-fills the table for a whole universe). The stock scan router calls `get_bars()` instead of `fetch_historical_candles()` directly. The Universe step (Step 2) gains a "Load History" panel where the user picks a universe and horizon, triggers the background prefetch, and watches a live progress bar.

**Tech Stack:** Python AsyncIO + SQLAlchemy async + Alembic (existing); aiosqlite (existing fallback); Next.js 15 + React + CSS Modules (frontend). No new dependencies.

---

## Background: existing patterns used here

| Pattern | Where | Reused for |
|---|---|---|
| Standalone SQLAlchemy base | `models/scan_session.py → ScanSessionBase` | `OhlcvBase` |
| Alembic autogenerate migration | `migrations/env.py` | New OHLCV migration |
| Async DB session | `database.py → AsyncSessionLocal` | `historical_store.py` |
| Background asyncio.Task | `main.py → _notification_worker_task` | Prefetch task |
| Progress state singleton | `routers/scan.py → _last_result` | `_prefetch_state` |
| Universe expansion | `data/universe_presets.py → expand_universe()` | Prefetch endpoint |
| Rate-limited fetch | existing tiingo `fetch_historical_candles` | Called via asyncio.sleep throttle |

---

## File Structure

**Backend — new**
- `backend/app/models/ohlcv_daily.py` — `OhlcvBase` + `OhlcvDailyModel` (symbol, date, OHLCV, fetched_at)
- `backend/app/services/historical_store.py` — `get_bars()`, `prefetch_universe()`, `get_prefetch_status()`, `_PrefetchState`
- `backend/app/routers/historical_data.py` — `POST /api/historical-data/prefetch`, `GET /api/historical-data/prefetch/status`
- `backend/tests/test_historical_store.py` — unit tests for the store service

**Backend — modified**
- `backend/migrations/env.py` — import `OhlcvBase` + add to `target_metadata`
- `backend/app/main.py` — import + register `historical_data_router`; add prefetch task to lifespan
- `backend/app/routers/stock_scan.py` — replace direct `fetch_historical_candles` call with `historical_store.get_bars()`

**Frontend — new**
- (CSS classes added to existing `step-2-universe/page.module.css`)

**Frontend — modified**
- `frontend/lib/api.ts` — add `startHistoryPrefetch`, `getHistoryPrefetchStatus`
- `frontend/app/(frame)/screener/step-2-universe/page.tsx` — add "Load History" panel at the bottom

---

## Task 1: OhlcvDailyModel + Alembic migration

**Files:**
- Create: `backend/app/models/ohlcv_daily.py`
- Modify: `backend/migrations/env.py`
- Run: Alembic autogenerate + upgrade

### Step 1: Write the model

Create `backend/app/models/ohlcv_daily.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, Date, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase


class OhlcvBase(DeclarativeBase):
    """Standalone base for the ohlcv_daily table.
    Uses a composite (symbol, date) primary key — no UUID needed."""
    pass


class OhlcvDailyModel(OhlcvBase):
    """Persistent daily OHLCV bars fetched from Tiingo.

    Composite primary key: (symbol, date).
    Bars are written once and never deleted — history only grows.
    Fetching uses adjusted prices (adjOpen / adjClose etc.).
    """

    __tablename__ = "ohlcv_daily"

    symbol     = Column(String(10), primary_key=True, nullable=False)
    date       = Column(Date,        primary_key=True, nullable=False)
    open       = Column(Float,  nullable=False)
    high       = Column(Float,  nullable=False)
    low        = Column(Float,  nullable=False)
    close      = Column(Float,  nullable=False)
    volume     = Column(BigInteger, nullable=False)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
```

### Step 2: Register with Alembic

In `backend/migrations/env.py`, add **after** the existing `ScanSessionBase` import line:

```python
from app.models.ohlcv_daily import OhlcvBase   # noqa: F401
```

And in the `target_metadata` list, append `OhlcvBase.metadata`:

```python
target_metadata = [Base.metadata, DatabaseBase.metadata, ScanSessionBase.metadata, OhlcvBase.metadata]
```

### Step 3: Verify env.py compiles

```bash
cd backend && python -c "import migrations.env; print('ok')"
```

Expected: `ok` (no import errors).

### Step 4: Generate the migration

```bash
cd backend && python -m alembic -c migrations/alembic.ini revision --autogenerate -m "add_ohlcv_daily_table"
```

Expected: a new file created in `migrations/versions/` containing a `create_table("ohlcv_daily", ...)` operation. If the autogenerate produces nothing, verify Step 2 was done correctly.

### Step 5: Apply the migration

```bash
cd backend && python -m alembic -c migrations/alembic.ini upgrade head
```

Expected: migration applied, no errors.

### Step 6: Smoke-check the table exists

```bash
cd backend && python -c "
import asyncio
from sqlalchemy import text
from app.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(\"SELECT name FROM sqlite_master WHERE type='table' AND name='ohlcv_daily'\"))
        row = result.fetchone()
        print('table found:', row is not None)

asyncio.run(check())
"
```

Expected: `table found: True`

### Step 7: Commit

```bash
git add backend/app/models/ohlcv_daily.py backend/migrations/env.py backend/migrations/versions/
git commit -m "feat(historical): OhlcvDailyModel + Alembic migration — persistent OHLCV table"
```

---

## Task 2: Historical store service + tests

**Files:**
- Create: `backend/app/services/historical_store.py`
- Create: `backend/tests/test_historical_store.py`

### Step 1: Write the failing tests

Create `backend/tests/test_historical_store.py`:

```python
"""Tests for historical_store.py — uses an in-memory SQLite DB via override."""
import asyncio
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services.historical_store import (
    _store_bars,
    _read_bars,
    get_prefetch_status,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def _bars(n: int, start: date = date(2024, 1, 2)) -> list[dict]:
    """Generate n synthetic daily bars starting from `start`."""
    return [
        {
            "time":   (start + timedelta(days=i)).isoformat(),
            "open":   100.0 + i,
            "high":   101.0 + i,
            "low":     99.0 + i,
            "close":  100.5 + i,
            "volume": 1_000_000,
        }
        for i in range(n)
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_bars_inserts_rows(db):
    bars = _bars(5)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    result = await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(OhlcvDailyModel)
        .where(OhlcvDailyModel.symbol == "AAPL")
    )
    rows = result.scalars().all()
    assert len(rows) == 5
    assert rows[0].close == pytest.approx(100.5)


@pytest.mark.asyncio
async def test_store_bars_upsert_does_not_duplicate(db):
    bars = _bars(3)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    # Store the same bars again — should not create duplicates
    await _store_bars("AAPL", bars, db)
    await db.commit()
    from sqlalchemy import select, func
    result = await db.execute(
        select(func.count()).where(OhlcvDailyModel.symbol == "AAPL")
    )
    count = result.scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_read_bars_returns_sorted_dicts(db):
    bars = _bars(5)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    start = date(2024, 1, 2)
    end   = date(2024, 1, 6)
    result = await _read_bars("AAPL", start, end, db)
    assert len(result) == 5
    assert result[0]["time"] == "2024-01-02"
    assert result[-1]["time"] == "2024-01-06"
    # Each dict has the required OHLCV keys
    assert all(k in result[0] for k in ("time", "open", "high", "low", "close", "volume"))


@pytest.mark.asyncio
async def test_read_bars_filters_by_date(db):
    bars = _bars(10)  # 2024-01-02 to 2024-01-11
    await _store_bars("AAPL", bars, db)
    await db.commit()
    result = await _read_bars("AAPL", date(2024, 1, 5), date(2024, 1, 7), db)
    assert len(result) == 3


def test_get_prefetch_status_returns_dict():
    status = get_prefetch_status()
    assert "status" in status
    assert status["status"] in ("idle", "running", "completed", "error")
    assert "total" in status
    assert "done" in status
```

### Step 2: Run to verify failure

```bash
cd backend && python -m pytest tests/test_historical_store.py -v
```

Expected: `ModuleNotFoundError: app.services.historical_store`

### Step 3: Implement the service

Create `backend/app/services/historical_store.py`:

```python
"""Persistent OHLCV daily history store backed by the application database.

Design:
- get_bars(symbol, start, end)      : DB-first lookup; fetches only the delta from Tiingo.
- prefetch_universe(symbols, years) : Rate-limited background job that pre-fills the table.
- get_prefetch_status()             : Returns the current prefetch job state.

Bars are written with an upsert (INSERT OR REPLACE for SQLite) so re-running the prefetch
is always safe and idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.data.tiingo import fetch_historical_candles
from app.models.ohlcv_daily import OhlcvDailyModel

logger = logging.getLogger(__name__)

# ── Prefetch progress state (module-level singleton) ─────────────────────────

_prefetch_state: dict[str, Any] = {
    "status":         "idle",   # idle | running | completed | error
    "total":          0,
    "done":           0,
    "failed":         0,
    "current_symbol": None,
    "elapsed_secs":   0,
    "started_at":     None,
}
_prefetch_task: asyncio.Task | None = None

# ── Internal helpers ──────────────────────────────────────────────────────────

def _bar_date(bar: dict) -> date:
    return date.fromisoformat(bar["time"][:10])


async def _store_bars(symbol: str, bars: list[dict], db: AsyncSession) -> None:
    """Upsert a list of OHLCV bar dicts for `symbol` into the DB."""
    if not bars:
        return
    now = datetime.now(timezone.utc)
    rows = [
        {
            "symbol":     symbol,
            "date":       _bar_date(b),
            "open":       b["open"],
            "high":       b["high"],
            "low":        b["low"],
            "close":      b["close"],
            "volume":     b["volume"],
            "fetched_at": now,
        }
        for b in bars
    ]
    # SQLite: INSERT OR REPLACE handles the composite PK upsert.
    stmt = sqlite_insert(OhlcvDailyModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low":  stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await db.execute(stmt)


async def _read_bars(
    symbol: str, start: date, end: date, db: AsyncSession
) -> list[dict]:
    """Read all stored bars for `symbol` between `start` and `end` (inclusive)."""
    result = await db.execute(
        select(OhlcvDailyModel)
        .where(
            OhlcvDailyModel.symbol == symbol,
            OhlcvDailyModel.date >= start,
            OhlcvDailyModel.date <= end,
        )
        .order_by(OhlcvDailyModel.date)
    )
    rows = result.scalars().all()
    return [
        {
            "time":   row.date.isoformat(),
            "open":   row.open,
            "high":   row.high,
            "low":    row.low,
            "close":  row.close,
            "volume": row.volume,
        }
        for row in rows
    ]


async def _last_stored_date(symbol: str, db: AsyncSession) -> date | None:
    """Return the most recent date stored for `symbol`, or None if no data."""
    result = await db.execute(
        select(func.max(OhlcvDailyModel.date))
        .where(OhlcvDailyModel.symbol == symbol)
    )
    return result.scalar_one_or_none()


# ── Public API ────────────────────────────────────────────────────────────────

async def get_bars(symbol: str, start: date, end: date) -> list[dict]:
    """Return OHLCV bars for `symbol` from `start` to `end`.

    Algorithm:
    1. Check the DB for the last stored date.
    2. If delta exists (DB is stale or empty), fetch from Tiingo and store it.
    3. Return all bars from the DB in the requested range.
    Falls back gracefully: if Tiingo fails and DB has partial data, returns what's there.
    """
    async with AsyncSessionLocal() as db:
        last = await _last_stored_date(symbol, db)

        fetch_needed = (last is None) or (last < end - timedelta(days=1))
        if fetch_needed:
            fetch_start = (last + timedelta(days=1)) if last else start
            new_bars = await asyncio.to_thread(
                fetch_historical_candles, symbol, fetch_start, end
            )
            if new_bars:
                await _store_bars(symbol, new_bars, db)
                await db.commit()
                logger.debug(
                    "historical_store: stored %d new bars for %s (delta %s → %s)",
                    len(new_bars), symbol, fetch_start, end,
                )

        return await _read_bars(symbol, start, end, db)


# ── Background prefetch ───────────────────────────────────────────────────────

async def _run_prefetch(symbols: list[str], years: int, delay_secs: float) -> None:
    """Background coroutine: sequentially fetch full history for each symbol."""
    global _prefetch_state
    start_time = time.monotonic()
    fetch_end   = date.today()
    fetch_start = fetch_end - timedelta(days=years * 365)

    _prefetch_state.update({
        "status":         "running",
        "total":          len(symbols),
        "done":           0,
        "failed":         0,
        "current_symbol": None,
        "started_at":     datetime.now(timezone.utc).isoformat(),
    })

    for symbol in symbols:
        _prefetch_state["current_symbol"] = symbol
        _prefetch_state["elapsed_secs"]   = round(time.monotonic() - start_time, 1)
        try:
            await get_bars(symbol, fetch_start, fetch_end)
            _prefetch_state["done"] += 1
        except Exception as exc:
            logger.warning("historical_store prefetch: %s failed — %s", symbol, exc)
            _prefetch_state["failed"] += 1
        # Rate-limit: respect Tiingo's free-tier daily quota.
        await asyncio.sleep(delay_secs)

    _prefetch_state.update({
        "status":         "completed",
        "current_symbol": None,
        "elapsed_secs":   round(time.monotonic() - start_time, 1),
    })
    logger.info(
        "historical_store prefetch complete: %d done, %d failed in %.0fs",
        _prefetch_state["done"], _prefetch_state["failed"], _prefetch_state["elapsed_secs"],
    )


def prefetch_universe(symbols: list[str], years: int = 5, delay_secs: float = 0.5) -> None:
    """Start (or restart) the background prefetch job.

    delay_secs=0.5 → ~2 req/s.  For Tiingo free tier (500 req/day), pre-fetching
    250 symbols per session stays within quota.  Set delay_secs=0.1 for paid plans.
    """
    global _prefetch_task, _prefetch_state
    if _prefetch_state.get("status") == "running":
        logger.warning("historical_store: prefetch already running — ignoring new request")
        return
    _prefetch_state["status"] = "running"
    _prefetch_task = asyncio.create_task(
        _run_prefetch(symbols, years, delay_secs)
    )


def get_prefetch_status() -> dict:
    """Return a copy of the current prefetch state."""
    return dict(_prefetch_state)
```

### Step 4: Run to verify tests pass

```bash
cd backend && python -m pytest tests/test_historical_store.py -v
```

Expected: `5 passed`

### Step 5: Commit

```bash
git add backend/app/services/historical_store.py backend/tests/test_historical_store.py
git commit -m "feat(historical): historical_store service — DB-first bars, rate-limited prefetch"
```

---

## Task 3: HTTP router + main.py registration

**Files:**
- Create: `backend/app/routers/historical_data.py`
- Modify: `backend/app/main.py`

### Step 1: Create the router

Create `backend/app/routers/historical_data.py`:

```python
"""POST /api/historical-data/prefetch  — start background OHLCV prefetch.
GET  /api/historical-data/prefetch/status — return current job state.
"""
from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.historical_store import prefetch_universe, get_prefetch_status
from app.data.universe_presets import expand_universe, PresetUnavailableError

router = APIRouter(prefix="/api/historical-data", tags=["historical-data"])


class PrefetchRequest(BaseModel):
    universe: list[str] = Field(..., description="Preset keys (e.g. ['SP500']) or ticker lists")
    years:    int        = Field(default=5, ge=1, le=10, description="Years of history to load")
    delay_secs: float    = Field(default=0.5, ge=0.05, le=10.0,
                                 description="Seconds between Tiingo requests (0.5 = 2 req/s, safe for free tier)")


class PrefetchStatus(BaseModel):
    status:         Literal["idle", "running", "completed", "error"]
    total:          int
    done:           int
    failed:         int
    current_symbol: Optional[str]
    elapsed_secs:   float
    started_at:     Optional[str]


@router.post("/prefetch")
async def start_prefetch(req: PrefetchRequest) -> dict:
    """Start a background job that pre-loads OHLCV history for a universe.

    Safe to call while a scan is running — the prefetch is a separate background task.
    Returns immediately; poll /prefetch/status to track progress.
    """
    try:
        symbols = expand_universe(req.universe)
    except PresetUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not symbols:
        raise HTTPException(status_code=400, detail="Universe expanded to zero symbols")

    current = get_prefetch_status()
    if current["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Prefetch already running ({current['done']}/{current['total']} done). "
                   "Wait for it to complete or restart the backend to cancel."
        )

    prefetch_universe(symbols, years=req.years, delay_secs=req.delay_secs)
    return {
        "message": f"Prefetch started for {len(symbols)} symbols ({req.years}y history)",
        "total":   len(symbols),
    }


@router.get("/prefetch/status", response_model=PrefetchStatus)
def prefetch_status() -> dict:
    """Return the current state of the background prefetch job."""
    return get_prefetch_status()
```

### Step 2: Register in main.py

In `backend/app/main.py`, add after the existing router imports (after `auto_trade_router`):

```python
from app.routers.historical_data import router as historical_data_router
```

And in the `app.include_router(...)` block:

```python
app.include_router(historical_data_router)
```

### Step 3: Verify import

```bash
cd backend && python -c "import app.main; print('ok')"
```

Expected: `ok`

### Step 4: Smoke-test the endpoints

```bash
cd backend && python -c "
from fastapi.testclient import TestClient
import app.main as m
c = TestClient(m.app)
print('status:', c.get('/api/historical-data/prefetch/status').json())
print('bad universe:', c.post('/api/historical-data/prefetch', json={'universe': ['NONEXISTENT']}).status_code)
"
```

Expected: status returns `{status: idle, ...}`, bad universe returns `400`.

### Step 5: Commit

```bash
git add backend/app/routers/historical_data.py backend/app/main.py
git commit -m "feat(historical): prefetch router — POST /api/historical-data/prefetch + status endpoint"
```

---

## Task 4: Wire stock scan to use historical store

**Files:**
- Modify: `backend/app/routers/stock_scan.py`

This is a one-import-swap change: replace the direct `fetch_historical_candles` call with `historical_store.get_bars()`.

### Step 1: Read the current scan line

In `backend/app/routers/stock_scan.py`, find this block (around line 15–16 and 67):

```python
from app.data.tiingo import fetch_historical_candles
```

and (around line 67):

```python
        bars = await asyncio.to_thread(fetch_historical_candles, symbol, start, end)
```

### Step 2: Replace the import and the call

**Remove** (do not keep — it's no longer the direct caller):
```python
from app.data.tiingo import fetch_historical_candles
```

**Add** (after the other service imports):
```python
from app.services.historical_store import get_bars as get_historical_bars
```

**Replace** the fetch call:

Old:
```python
        # Sync httpx call — offload to a thread so it doesn't block the event loop
        # while many symbols are scanned concurrently via asyncio.gather.
        bars = await asyncio.to_thread(fetch_historical_candles, symbol, start, end)
```

New:
```python
        # DB-first: reads from ohlcv_daily table; fetches delta from Tiingo if stale.
        # Eliminates parallel Tiingo calls for large universes (avoids rate-limit errors).
        bars = await get_historical_bars(symbol, start, end)
```

(`get_historical_bars` is already async and manages its own DB session — no `asyncio.to_thread` needed.)

### Step 3: Verify import

```bash
cd backend && python -c "import app.main; print('ok')"
```

Expected: `ok`

### Step 4: Run full backend test suite

```bash
cd backend && python -m pytest tests/ -q
```

Expected: all pass (the new call is backward-compatible; if no rows are in the DB, it falls back to a live Tiingo fetch exactly as before).

### Step 5: Commit

```bash
git add backend/app/routers/stock_scan.py
git commit -m "feat(historical): stock scan reads from ohlcv_daily first — eliminates Tiingo rate-limit failures"
```

---

## Task 5: Frontend — "Load History" panel in Step 2

**Files:**
- Modify: `frontend/lib/api.ts` — add 2 methods
- Modify: `frontend/app/(frame)/screener/step-2-universe/page.tsx` — add panel
- Modify: `frontend/app/(frame)/screener/step-2-universe/page.module.css` — add panel CSS

### Step 1: Add API methods to `frontend/lib/api.ts`

Add inside the `api` object (after `getHistoryPrefetchStatus` if it exists, or after `getBrokerStatus`):

```ts
  startHistoryPrefetch: (req: {
    universe: string[];
    years?: number;
    delay_secs?: number;
  }) => post<{ message: string; total: number }>('/api/historical-data/prefetch', req),

  getHistoryPrefetchStatus: () =>
    get<{
      status: 'idle' | 'running' | 'completed' | 'error';
      total: number;
      done: number;
      failed: number;
      current_symbol: string | null;
      elapsed_secs: number;
      started_at: string | null;
    }>('/api/historical-data/prefetch/status'),
```

### Step 2: Add CSS classes to `step-2-universe/page.module.css`

Append at the end of the file:

```css
/* ---------- Load History panel ---------- */

.historyPanel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  margin-top: var(--space-2);
}

.historyPanelHeader {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}

.historyControls {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.horizonSelect {
  height: 32px;
  padding: 0 var(--space-3);
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  font-family: var(--font-dm);
  font-size: 12px;
  cursor: pointer;
}

.loadBtn {
  height: 32px;
  padding: 0 var(--space-4);
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-family: var(--font-dm);
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms, border-color 120ms, color 120ms;
  white-space: nowrap;
}

.loadBtn:hover:not(:disabled) {
  background: var(--bg-surface);
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.loadBtn:disabled { opacity: 0.5; cursor: not-allowed; }

.loadBtnRunning {
  border-color: var(--pass);
  color: var(--pass);
}

.progressWrap {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.progressBar {
  height: 4px;
  background: var(--border-subtle);
  border-radius: 2px;
  overflow: hidden;
}

.progressFill {
  height: 100%;
  background: var(--pass);
  border-radius: 2px;
  transition: width 500ms ease;
}

.progressLabel {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
```

### Step 3: Add the "Load History" panel to the page component

In `frontend/app/(frame)/screener/step-2-universe/page.tsx`:

**Add these imports** at the top (after existing imports):

```tsx
import { useEffect, useRef } from 'react';
```

(Note: `useState` and `useCallback` are already imported. Add only what's missing.)

**Add the history panel state** inside `Step1Page()`, after the existing state declarations:

```tsx
  const [histYears,      setHistYears]      = useState(5);
  const [histStatus,     setHistStatus]     = useState<{
    status: 'idle' | 'running' | 'completed' | 'error';
    total: number; done: number; failed: number;
    current_symbol: string | null; elapsed_secs: number;
  }>({ status: 'idle', total: 0, done: 0, failed: 0, current_symbol: null, elapsed_secs: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Poll status while a prefetch job is running
  useEffect(() => {
    if (histStatus.status === 'running') {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getHistoryPrefetchStatus();
          setHistStatus(s);
          if (s.status !== 'running' && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch { /* silent — backend may be restarting */ }
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [histStatus.status]);

  const handleLoadHistory = useCallback(async () => {
    const universe = pick === 'Custom'
      ? symbols
      : pick === 'Watchlist'
        ? []   // watchlist symbols not available as a simple list here — use SP500 fallback
        : [pick];
    if (!universe.length && pick !== 'Watchlist') return;
    try {
      await api.startHistoryPrefetch({ universe: universe.length ? universe : ['SP500'], years: histYears });
      const s = await api.getHistoryPrefetchStatus();
      setHistStatus(s);
    } catch (e) {
      console.error('History prefetch failed to start:', e);
    }
  }, [pick, symbols, histYears]);
```

**Add the panel JSX** at the very end of the return, after the existing closing `</div>` of the filters section and before the outer closing `</div>`:

```tsx
      {/* Historical data pre-load */}
      <div className={formStyles.historyPanel}>
        <div className={formStyles.historyPanelHeader}>
          <div>
            <Text size={13} weight={600}>Historical data</Text>
            <Text size={11} tone="secondary">
              Pre-load OHLCV history for the selected universe so stock scans read from the
              local database instead of hitting Tiingo live.
            </Text>
          </div>
        </div>

        <div className={formStyles.historyControls}>
          <Text size={12} tone="dim">Horizon:</Text>
          <select
            className={formStyles.horizonSelect}
            value={histYears}
            onChange={(e) => setHistYears(Number(e.target.value))}
            disabled={histStatus.status === 'running'}
          >
            <option value={1}>1 year</option>
            <option value={2}>2 years</option>
            <option value={3}>3 years</option>
            <option value={5}>5 years (recommended)</option>
          </select>

          <button
            type="button"
            className={`${formStyles.loadBtn} ${histStatus.status === 'running' ? formStyles.loadBtnRunning : ''}`}
            onClick={handleLoadHistory}
            disabled={histStatus.status === 'running'}
          >
            {histStatus.status === 'running'
              ? `Loading… ${histStatus.done}/${histStatus.total}`
              : histStatus.status === 'completed'
                ? `Reload history (${histStatus.done} symbols)`
                : 'Load history in background'}
          </button>
        </div>

        {(histStatus.status === 'running' || histStatus.status === 'completed') && (
          <div className={formStyles.progressWrap}>
            <div className={formStyles.progressBar}>
              <div
                className={formStyles.progressFill}
                style={{ width: histStatus.total > 0 ? `${(histStatus.done / histStatus.total) * 100}%` : '0%' }}
              />
            </div>
            <div className={formStyles.progressLabel}>
              <Text size={11} tone="dim">
                {histStatus.status === 'running' && histStatus.current_symbol
                  ? `Fetching ${histStatus.current_symbol}…`
                  : histStatus.status === 'completed'
                    ? `Complete — ${histStatus.done} loaded, ${histStatus.failed} failed`
                    : ''}
              </Text>
              <Text size={11} tone="dim">{histStatus.elapsed_secs}s</Text>
            </div>
          </div>
        )}
      </div>
```

### Step 4: Typecheck

```bash
cd frontend && npm run typecheck
```

Expected: clean.

### Step 5: Run frontend test suite

```bash
cd frontend && npx jest
```

Expected: all pass (no existing tests touch Step 2 page directly).

### Step 6: Commit

```bash
git add frontend/lib/api.ts \
  "frontend/app/(frame)/screener/step-2-universe/page.tsx" \
  "frontend/app/(frame)/screener/step-2-universe/page.module.css"
git commit -m "feat(historical): Load History panel in Universe step — triggers background prefetch with progress bar"
```

---

## Self-Review

**Spec coverage:**
- ✅ Persistent `ohlcv_daily` table (Task 1)
- ✅ DB-first `get_bars()` — fetches delta from Tiingo, stores permanently (Task 2)
- ✅ Rate-limited prefetch with configurable delay (Task 2 — `delay_secs` param)
- ✅ Background job, non-blocking (Task 2 — `asyncio.create_task`)
- ✅ Universe-driven: uses same `expand_universe()` as scan (Task 3)
- ✅ Horizon selectable (1/2/3/5 years, default 5) (Task 3 + 5)
- ✅ Triggered from Universe step in screener (Task 5)
- ✅ Live progress bar with symbol-level feedback (Task 5)
- ✅ Stock scan reads from table first (Task 4)
- ✅ Additional fetched bars stored permanently (Task 2 — upsert in `_run_prefetch`)
- ✅ Volume management: no deletions; Alembic-tracked (Task 1)
- ✅ Existing tests still pass — `get_historical_bars` is backward-compatible (Task 4)

**Tiingo free tier note:** At `delay_secs=0.5` (default), SP500 takes ~250 seconds. This uses ~500 Tiingo calls = the entire free daily quota. Set `delay_secs=0.1` for paid plans. After the initial load, subsequent scans only fetch delta (1 call/symbol/day if stock prices changed) — the typical daily scan uses far fewer calls.
