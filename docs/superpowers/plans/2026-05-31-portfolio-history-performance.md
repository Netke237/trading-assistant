# Portfolio History & Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the portfolio from a delete-on-close list into a durable system that records every closed trade (with realized P&L), supports partial sells, shows day/week/month/year performance, and renders a toggleable two-line earnings graph on the dashboard.

**Architecture:** A new `closed_positions` table records each sell event (one row per partial or full close) so history is kept forever and only removed on explicit user action. A new `equity_snapshots` table records one total-account-value point per calendar day (upserted on each portfolio read) so the "total account value" line can be drawn over time. The backend exposes close/history/performance endpoints; the frontend gets a Close drawer (auto-filled, editable exit price + partial qty), Open/History tabs, a calendar-period performance strip, and a dashboard earnings card with an on/off toggle.

**Tech Stack:** FastAPI + async SQLAlchemy v2 + Alembic (SQLite dev DB), Pydantic v2; Next.js 15 + TypeScript + Zustand (persist) + lightweight-charts v5; pytest/pytest-asyncio + Jest.

**Key conventions to follow (already in this codebase):**
- Option P&L is always `(exit - entry) * 100 * qty` regardless of `direction` (these are long-premium positions; existing open-P&L code in `backend/app/routers/portfolio.py:50` does the same).
- New ORM models use **String ids** (`uuid.uuid4().hex`) like `app/models/alert.py`, NOT the postgresql UUID type, so SQLite behaves identically.
- Schemas are camelCase with a `from_orm_model` classmethod (see `PortfolioPositionSchema`).
- CSS Modules only; primitives `Text`/`Data`/`Title`; no card shadows; colors from CSS tokens.
- Commit after every green task. LOCAL commits only — do NOT push. Never stage `backend/config/settings.yaml`.

---

## File Structure

**Backend (create):**
- `backend/app/models/closed_position.py` — `ClosedPositionModel` (one row per sell event) + `EquitySnapshotModel`.
- `backend/app/services/portfolio_performance.py` — pure helpers: `realized_pnl()`, `bucket_realized_by_calendar()`, `cumulative_curve()`. No DB, no I/O → fully unit-testable.
- `backend/tests/test_portfolio_performance.py` — unit tests for the pure helpers.
- `backend/tests/test_portfolio_close_history.py` — integration tests (self-contained test app + in-memory DB) for the new endpoints.

**Backend (modify):**
- `backend/app/models/__init__.py` — register the two new models.
- `backend/app/schemas/__init__.py` — add `ClosePositionRequest`, `ClosedPositionSchema`, `PerformanceResponse`.
- `backend/app/routers/portfolio.py` — add close / history-list / history-delete / performance endpoints; upsert equity snapshot on `GET /portfolio`; add the inactive broker stub.

**Frontend (create):**
- `frontend/components/organisms/ClosePositionDrawer/index.tsx` (+ `.module.css`) — partial-qty + editable exit price + realized preview + inactive "send to broker" stub.
- `frontend/components/organisms/EarningsChart/index.tsx` (+ `.module.css`) — two-line lightweight-charts line chart.
- `frontend/lib/performanceStore.ts` — fetches history + performance from backend.

**Frontend (modify):**
- `frontend/lib/portfolioStore.ts` — replace delete-only `closePosition` with a backend close call (partial aware); add `closePositionRemote`.
- `frontend/app/(frame)/portfolio/page.tsx` — Open/History tabs, performance strip, wire ClosePositionDrawer.
- `frontend/app/(frame)/dashboard/page.tsx` (+ `page.module.css`) — earnings card with persisted on/off toggle.

---

## Phase A — Backend: history, partial close, performance

### Task A1: Pure performance helpers (TDD)

**Files:**
- Create: `backend/app/services/portfolio_performance.py`
- Test: `backend/tests/test_portfolio_performance.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_portfolio_performance.py
from datetime import date

from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve,
)


def test_realized_pnl_long_premium():
    # entry 1.00, exit 1.50, 2 contracts -> (1.50-1.00)*100*2 = 100.0, +50%
    dollar, pct = realized_pnl(entry_price=1.00, exit_price=1.50, qty=2)
    assert dollar == 100.0
    assert pct == 50.0


def test_realized_pnl_loss_and_zero_entry_guard():
    dollar, pct = realized_pnl(entry_price=2.00, exit_price=1.00, qty=1)
    assert dollar == -100.0
    assert pct == -50.0
    # entry 0 must not divide-by-zero
    d2, p2 = realized_pnl(entry_price=0.0, exit_price=1.0, qty=1)
    assert d2 == 100.0
    assert p2 == 0.0


def test_bucket_realized_by_calendar():
    today = date(2026, 5, 31)  # a Sunday
    rows = [
        {"exit_date": "2026-05-31", "realized_pnl_dollar": 100.0},  # today, this week, month, year
        {"exit_date": "2026-05-25", "realized_pnl_dollar": 50.0},   # this month + year, this week (Mon 25th)
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 25.0},   # this year only
        {"exit_date": "2025-12-31", "realized_pnl_dollar": 999.0},  # last year -> excluded everywhere
    ]
    b = bucket_realized_by_calendar(rows, today=today, week_starts_monday=True)
    assert b["today"] == 100.0
    assert b["week"] == 150.0     # 31st + 25th (week Mon 25 -> Sun 31)
    assert b["month"] == 150.0    # May rows
    assert b["year"] == 175.0     # 2026 rows


def test_cumulative_curve_sorted_and_running_total():
    rows = [
        {"exit_date": "2026-05-31", "realized_pnl_dollar": 100.0},
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 25.0},
        {"exit_date": "2026-04-10", "realized_pnl_dollar": 5.0},  # same day collapses
    ]
    curve = cumulative_curve(rows)
    assert curve == [
        {"date": "2026-04-10", "value": 30.0},
        {"date": "2026-05-31", "value": 130.0},
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_portfolio_performance.py -v`
Expected: FAIL (ModuleNotFoundError: app.services.portfolio_performance).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/portfolio_performance.py
"""Pure, DB-free helpers for portfolio realized-P&L math and calendar bucketing.

Kept side-effect free so they unit-test deterministically. The router layer
feeds these plain dicts (already read from the DB).
"""
from __future__ import annotations

from datetime import date, timedelta


def realized_pnl(entry_price: float, exit_price: float, qty: int) -> tuple[float, float]:
    """Long-premium realized P&L: (exit - entry) * 100 * qty. Percent guards entry==0."""
    dollar = round((exit_price - entry_price) * 100 * qty, 2)
    pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0
    return dollar, pct


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d[:10])
    except (ValueError, TypeError):
        return None


def bucket_realized_by_calendar(
    rows: list[dict], today: date, week_starts_monday: bool = True
) -> dict[str, float]:
    """Sum realized_pnl_dollar into today / this-week / this-month / this-year buckets.

    Calendar periods (not rolling): week = Mon..Sun containing `today`, month = 1st
    of `today`'s month onward, year = Jan 1 of `today`'s year onward.
    """
    if week_starts_monday:
        week_start = today - timedelta(days=today.weekday())
    else:
        week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    out = {"today": 0.0, "week": 0.0, "month": 0.0, "year": 0.0}
    for r in rows:
        d = _parse(r.get("exit_date", ""))
        if d is None:
            continue
        amt = float(r.get("realized_pnl_dollar", 0.0))
        if d == today:
            out["today"] += amt
        if week_start <= d <= today:
            out["week"] += amt
        if month_start <= d <= today:
            out["month"] += amt
        if year_start <= d <= today:
            out["year"] += amt
    return {k: round(v, 2) for k, v in out.items()}


def cumulative_curve(rows: list[dict]) -> list[dict]:
    """Cumulative realized P&L, one point per distinct exit date, ascending by date."""
    by_day: dict[str, float] = {}
    for r in rows:
        d = _parse(r.get("exit_date", ""))
        if d is None:
            continue
        key = d.isoformat()
        by_day[key] = by_day.get(key, 0.0) + float(r.get("realized_pnl_dollar", 0.0))
    running = 0.0
    curve: list[dict] = []
    for day in sorted(by_day):
        running = round(running + by_day[day], 2)
        curve.append({"date": day, "value": running})
    return curve
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_portfolio_performance.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/portfolio_performance.py backend/tests/test_portfolio_performance.py
git commit -m "feat(portfolio): pure realized-P&L + calendar bucketing helpers"
```

---

### Task A2: ORM models for closed positions + equity snapshots

**Files:**
- Create: `backend/app/models/closed_position.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Write the models**

```python
# backend/app/models/closed_position.py
from sqlalchemy import Column, String, Float, Integer, DateTime
from datetime import datetime, timezone

from app.database import Base


class ClosedPositionModel(Base):
    """One row per sell event. A partial close creates a row for the closed
    portion and leaves the open position (with reduced qty) in place."""
    __tablename__ = "closed_positions"

    id = Column(String(36), primary_key=True)
    rec_id = Column(String, nullable=False, index=True)   # links to original open position; NOT unique
    symbol = Column(String, nullable=False)
    contract = Column(String, nullable=False, index=True)  # NOT unique (partials / re-buys)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_date = Column(String, nullable=True)
    exit_price = Column(Float, nullable=False)
    exit_date = Column(String, nullable=False)            # 'YYYY-MM-DD'
    qty_closed = Column(Integer, nullable=False)
    realized_pnl_dollar = Column(Float, nullable=False)
    realized_pnl_pct = Column(Float, nullable=False)
    source = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EquitySnapshotModel(Base):
    """One total-account-value point per calendar day (upserted on portfolio read)."""
    __tablename__ = "equity_snapshots"

    id = Column(String(36), primary_key=True)
    snapshot_date = Column(String, nullable=False, unique=True, index=True)  # 'YYYY-MM-DD'
    realized_cumulative = Column(Float, nullable=False, default=0.0)
    open_value = Column(Float, nullable=False, default=0.0)
    total_value = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 2: Register the models**

Modify `backend/app/models/__init__.py` — add after the alert import line:

```python
from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel  # noqa: F401
```

- [ ] **Step 3: Verify import + table registration**

Run: `cd backend && python -c "import app.models; from app.database import Base; print('closed_positions' in Base.metadata.tables, 'equity_snapshots' in Base.metadata.tables)"`
Expected: `True True`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/closed_position.py backend/app/models/__init__.py
git commit -m "feat(portfolio): add closed_positions + equity_snapshots models"
```

---

### Task A3: Alembic migration for the new tables

**Files:**
- Create: `backend/migrations/versions/<autogen>_add_portfolio_history.py` (generated)

- [ ] **Step 1: Autogenerate the migration**

Run: `cd backend && alembic revision --autogenerate -m "add portfolio history and equity snapshots"`
Expected: a new file under `migrations/versions/` whose `upgrade()` calls `op.create_table('closed_positions', ...)` and `op.create_table('equity_snapshots', ...)`.

- [ ] **Step 2: Review the generated file**

Open the generated file. Confirm: both `create_table` calls present; indexes on `closed_positions.rec_id`, `closed_positions.contract`, `equity_snapshots.snapshot_date` (unique); `down_revision` points at the current head; `downgrade()` drops both tables. Remove any spurious unrelated ops autogenerate may have added (it should only touch the two new tables).

- [ ] **Step 3: Apply and verify**

Run: `cd backend && alembic upgrade head`
Expected: completes with no error. (Dev also creates tables via `create_all` on startup; the migration keeps Alembic history consistent.)

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/
git commit -m "feat(portfolio): migration for history + equity snapshot tables"
```

---

### Task A4: Schemas for close request / closed record / performance

**Files:**
- Modify: `backend/app/schemas/__init__.py`

- [ ] **Step 1: Add the schemas** (append near the other portfolio schemas, after `PortfolioPositionSchema`)

```python
class ClosePositionRequest(BaseModel):
    """Body for POST /api/portfolio/{rec_id}/close."""
    model_config = ConfigDict(populate_by_name=True)
    qtyToClose: Optional[int] = None        # None -> close the whole position
    exitPrice: Optional[float] = None       # None -> server fetches the live quote
    exitDate: Optional[str] = None          # None -> today (YYYY-MM-DD)
    # Reserved for the future broker feature (see router stub) — inactive for now.
    sendToBroker: bool = False


class ClosedPositionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    id: str
    recId: str
    symbol: str
    contract: str
    direction: str
    entryPrice: float
    entryDate: Optional[str] = None
    exitPrice: float
    exitDate: str
    qtyClosed: int
    realizedPnlDollar: float
    realizedPnlPct: float
    closedAt: str

    @classmethod
    def from_orm_model(cls, obj) -> "ClosedPositionSchema":
        return cls(
            id=str(obj.id),
            recId=obj.rec_id,
            symbol=obj.symbol,
            contract=obj.contract,
            direction=obj.direction,
            entryPrice=obj.entry_price,
            entryDate=obj.entry_date,
            exitPrice=obj.exit_price,
            exitDate=obj.exit_date,
            qtyClosed=obj.qty_closed,
            realizedPnlDollar=obj.realized_pnl_dollar,
            realizedPnlPct=obj.realized_pnl_pct,
            closedAt=obj.closed_at.isoformat() if obj.closed_at else "",
        )


class PerformancePoint(BaseModel):
    date: str
    value: float


class PerformanceResponse(BaseModel):
    realizedToday: float = 0.0
    realizedWeek: float = 0.0
    realizedMonth: float = 0.0
    realizedYear: float = 0.0
    realizedCurve: list[PerformancePoint] = []   # cumulative realized profit line
    equityCurve: list[PerformancePoint] = []      # total account value line (from snapshots)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "from app.schemas import ClosePositionRequest, ClosedPositionSchema, PerformanceResponse; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/__init__.py
git commit -m "feat(portfolio): schemas for close/history/performance"
```

---

### Task A5: Close endpoint (full + partial) with broker stub

**Files:**
- Modify: `backend/app/routers/portfolio.py`
- Test: `backend/tests/test_portfolio_close_history.py`

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/test_portfolio_close_history.py
"""Integration tests for the portfolio close/history/performance endpoints.

Self-contained: builds a small app with ONLY the portfolio router, backed by an
in-memory SQLite DB with the real Base metadata, and stubs the live Tradier quote
so exit-price auto-fill is deterministic.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


async def _add(client, contract="AAPL|185|2026-09-18|C", qty=5, entry=1.00, rec="REC-1"):
    # Avoid the risk-engine 422 by using a large portfolio value.
    body = {"recId": rec, "symbol": "AAPL", "contract": contract, "direction": "Bullish",
            "entryPrice": entry, "qty": qty, "entryDate": "2026-05-01",
            "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 1_000_000}
    r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_full_close_records_history_and_removes_open(client):
    await _add(client, qty=3, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": None, "exitPrice": 1.50, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["qtyClosed"] == 3
    assert rec["realizedPnlDollar"] == 150.0   # (1.50-1.00)*100*3
    assert rec["realizedPnlPct"] == 50.0
    # open position gone
    assert await (await client.get("/api/portfolio")).json() == []  # type: ignore
    # history has the one record
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["recId"] == "REC-1"


@pytest.mark.asyncio
async def test_partial_close_reduces_qty_and_keeps_open(client):
    await _add(client, qty=5, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": 2, "exitPrice": 2.00, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    assert r.json()["qtyClosed"] == 2
    open_positions = (await client.get("/api/portfolio")).json()
    assert len(open_positions) == 1
    assert open_positions[0]["qty"] == 3        # 5 - 2 remaining
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["qtyClosed"] == 2


@pytest.mark.asyncio
async def test_close_auto_fills_exit_price_from_quote(client):
    await _add(client, qty=1, entry=1.00)
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               return_value={"price": 1.80}):
        r = await client.post("/api/portfolio/REC-1/close", json={})
    assert r.status_code == 201, r.text
    assert r.json()["exitPrice"] == 1.80
    assert r.json()["realizedPnlDollar"] == 80.0


@pytest.mark.asyncio
async def test_close_missing_position_404(client):
    r = await client.post("/api/portfolio/NOPE/close", json={"exitPrice": 1.0})
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_portfolio_close_history.py -v`
Expected: FAIL (404/405 — close & history routes don't exist yet).

- [ ] **Step 3: Implement the close + history endpoints**

In `backend/app/routers/portfolio.py`, add imports at the top (keep existing ones):

```python
import uuid
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select, delete

from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel
from app.schemas import (
    PortfolioPositionCreate, PortfolioPositionSchema,
    ClosePositionRequest, ClosedPositionSchema,
    PerformanceResponse, PerformancePoint,
)
from app.services.portfolio_performance import (
    realized_pnl, bucket_realized_by_calendar, cumulative_curve,
)
```

Add this inactive broker stub near the top of the module (below the router definition):

```python
# ── Broker integration (NOT ACTIVE YET) ───────────────────────────────────────
# Future feature: when a trade is closed, optionally route the closing order to
# the connected broker — mirrors the "Send basket to broker" flow in Step 7,
# which is wired in the UI but not yet executed against a live broker. This stub
# is intentionally a no-op so the request shape (ClosePositionRequest.sendToBroker)
# and call site already exist; flip the body on when the broker API lands.
def _maybe_send_close_to_broker(closed: ClosedPositionModel, send: bool) -> None:
    if not send:
        return
    # TODO(broker): submit the closing order to the broker API. Inactive for now.
    return
```

Add the close endpoint:

```python
@router.post('/portfolio/{rec_id}/close',
             response_model=ClosedPositionSchema,
             status_code=status.HTTP_201_CREATED)
async def close_position(
    rec_id: str,
    body: ClosePositionRequest,
    db: AsyncSession = Depends(get_db),
) -> ClosedPositionSchema:
    position = (await db.execute(
        select(PortfolioPositionModel).where(PortfolioPositionModel.rec_id == rec_id)
    )).scalar_one_or_none()
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Position with rec_id '{rec_id}' not found.")

    # qty to close: default = full; clamp 1..position.qty
    qty_to_close = body.qtyToClose if body.qtyToClose is not None else position.qty
    qty_to_close = max(1, min(int(qty_to_close), position.qty))

    # exit price: explicit, else fetch the live quote, else 422
    exit_price = body.exitPrice
    if exit_price is None:
        async with httpx.AsyncClient(timeout=10) as client:
            quote = await fetch_contract_quote_async(client, position.contract)
        exit_price = (quote or {}).get("price") if isinstance(quote, dict) else None
        if not exit_price:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Could not fetch a live exit price — please enter one.",
            )

    exit_date = body.exitDate or date.today().isoformat()
    dollar, pct = realized_pnl(position.entry_price, float(exit_price), qty_to_close)

    closed = ClosedPositionModel(
        id=uuid.uuid4().hex,
        rec_id=position.rec_id,
        symbol=position.symbol,
        contract=position.contract,
        direction=position.direction,
        entry_price=position.entry_price,
        entry_date=position.entry_date,
        exit_price=float(exit_price),
        exit_date=exit_date,
        qty_closed=qty_to_close,
        realized_pnl_dollar=dollar,
        realized_pnl_pct=pct,
        source=getattr(position, "source", None),
    )
    db.add(closed)

    # Reduce or remove the open position
    if qty_to_close >= position.qty:
        await db.delete(position)
    else:
        position.qty -= qty_to_close

    await db.commit()
    await db.refresh(closed)

    _maybe_send_close_to_broker(closed, body.sendToBroker)
    return ClosedPositionSchema.from_orm_model(closed)


@router.get('/portfolio/history', response_model=list[ClosedPositionSchema])
async def get_history(db: AsyncSession = Depends(get_db)) -> list[ClosedPositionSchema]:
    rows = (await db.execute(
        select(ClosedPositionModel).order_by(ClosedPositionModel.closed_at.desc())
    )).scalars().all()
    return [ClosedPositionSchema.from_orm_model(r) for r in rows]


@router.delete('/portfolio/history/{history_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_history(history_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = (await db.execute(
        select(ClosedPositionModel).where(ClosedPositionModel.id == history_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"History entry '{history_id}' not found.")
    await db.delete(row)
    await db.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && python -m pytest tests/test_portfolio_close_history.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/portfolio.py backend/tests/test_portfolio_close_history.py
git commit -m "feat(portfolio): close endpoint (full+partial), history list/delete, broker stub"
```

---

### Task A6: Performance endpoint + equity snapshot upsert

**Files:**
- Modify: `backend/app/routers/portfolio.py`
- Test: `backend/tests/test_portfolio_close_history.py` (append)

- [ ] **Step 1: Add failing tests** (append to the test file)

```python
@pytest.mark.asyncio
async def test_performance_buckets_and_curve(client):
    await _add(client, qty=4, entry=1.00, rec="REC-A")
    # close 2 today at 1.50 -> +100
    await client.post("/api/portfolio/REC-A/close",
                      json={"qtyToClose": 2, "exitPrice": 1.50, "exitDate": "2026-05-31"})
    perf = (await client.get("/api/portfolio/performance")).json()
    assert perf["realizedYear"] == 100.0
    assert perf["realizedCurve"][-1]["value"] == 100.0


@pytest.mark.asyncio
async def test_get_portfolio_upserts_one_snapshot_per_day(client):
    await _add(client, qty=1, entry=1.00)
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               return_value={"price": 1.20}):
        await client.get("/api/portfolio")
        await client.get("/api/portfolio")  # second call same day must not duplicate
    perf = (await client.get("/api/portfolio/performance")).json()
    # exactly one equity point for today
    assert len(perf["equityCurve"]) == 1
    # total = realized(0) + open(1.20*100*1 = 120)
    assert perf["equityCurve"][0]["value"] == 120.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_portfolio_close_history.py -k "performance or snapshot" -v`
Expected: FAIL (no `/performance` route; no snapshot upsert).

- [ ] **Step 3: Implement snapshot upsert helper + performance endpoint**

Add to `backend/app/routers/portfolio.py`:

```python
async def _upsert_equity_snapshot(db: AsyncSession, open_value: float) -> None:
    """Record/refresh today's total-account-value point (one row per calendar day)."""
    today = date.today().isoformat()
    realized_cum = sum(
        r.realized_pnl_dollar
        for r in (await db.execute(select(ClosedPositionModel))).scalars().all()
    )
    total = round(realized_cum + open_value, 2)
    snap = (await db.execute(
        select(EquitySnapshotModel).where(EquitySnapshotModel.snapshot_date == today)
    )).scalar_one_or_none()
    if snap is None:
        db.add(EquitySnapshotModel(
            id=uuid.uuid4().hex, snapshot_date=today,
            realized_cumulative=round(realized_cum, 2),
            open_value=round(open_value, 2), total_value=total,
        ))
    else:
        snap.realized_cumulative = round(realized_cum, 2)
        snap.open_value = round(open_value, 2)
        snap.total_value = total
    await db.commit()
```

In the existing `get_portfolio` function, just before `return schemas`, add:

```python
    open_value = sum(s.currentPrice * 100 * s.qty for s in schemas)
    await _upsert_equity_snapshot(db, open_value)
```

Add the performance endpoint:

```python
@router.get('/portfolio/performance', response_model=PerformanceResponse)
async def get_performance(db: AsyncSession = Depends(get_db)) -> PerformanceResponse:
    closed = (await db.execute(select(ClosedPositionModel))).scalars().all()
    rows = [{"exit_date": c.exit_date, "realized_pnl_dollar": c.realized_pnl_dollar}
            for c in closed]
    buckets = bucket_realized_by_calendar(rows, today=date.today())
    realized_curve = cumulative_curve(rows)

    snaps = (await db.execute(
        select(EquitySnapshotModel).order_by(EquitySnapshotModel.snapshot_date)
    )).scalars().all()
    equity_curve = [PerformancePoint(date=s.snapshot_date, value=s.total_value) for s in snaps]

    return PerformanceResponse(
        realizedToday=buckets["today"], realizedWeek=buckets["week"],
        realizedMonth=buckets["month"], realizedYear=buckets["year"],
        realizedCurve=[PerformancePoint(**p) for p in realized_curve],
        equityCurve=equity_curve,
    )
```

- [ ] **Step 4: Run the whole backend portfolio test set**

Run: `cd backend && python -m pytest tests/test_portfolio_close_history.py tests/test_portfolio_performance.py -v`
Expected: PASS (all).

- [ ] **Step 5: Full backend suite (no regressions)**

Run: `cd backend && python -m pytest -q`
Expected: previous green count + the new tests, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/portfolio.py backend/tests/test_portfolio_close_history.py
git commit -m "feat(portfolio): performance endpoint + daily equity snapshot upsert"
```

---

## Phase B — Frontend: close flow, history, performance strip

### Task B1: Performance store (history + performance fetch)

**Files:**
- Create: `frontend/lib/performanceStore.ts`

- [ ] **Step 1: Implement the store**

```ts
// frontend/lib/performanceStore.ts
import { create } from 'zustand';

export interface ClosedPosition {
  id: string;
  recId: string;
  symbol: string;
  contract: string;
  direction: string;
  entryPrice: number;
  entryDate?: string;
  exitPrice: number;
  exitDate: string;
  qtyClosed: number;
  realizedPnlDollar: number;
  realizedPnlPct: number;
  closedAt: string;
}

export interface PerfPoint { date: string; value: number }

export interface Performance {
  realizedToday: number;
  realizedWeek: number;
  realizedMonth: number;
  realizedYear: number;
  realizedCurve: PerfPoint[];
  equityCurve: PerfPoint[];
}

const EMPTY_PERF: Performance = {
  realizedToday: 0, realizedWeek: 0, realizedMonth: 0, realizedYear: 0,
  realizedCurve: [], equityCurve: [],
};

const BASE = () => process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

interface PerfState {
  history: ClosedPosition[];
  performance: Performance;
  fetchHistory: () => Promise<void>;
  fetchPerformance: () => Promise<void>;
  removeHistory: (id: string) => Promise<void>;
}

export const usePerformanceStore = create<PerfState>((set, get) => ({
  history: [],
  performance: EMPTY_PERF,
  fetchHistory: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/history`);
      if (res.ok) set({ history: await res.json() });
    } catch { /* backend offline */ }
  },
  fetchPerformance: async () => {
    try {
      const res = await fetch(`${BASE()}/api/portfolio/performance`);
      if (res.ok) set({ performance: await res.json() });
    } catch { /* backend offline */ }
  },
  removeHistory: async (id) => {
    try {
      await fetch(`${BASE()}/api/portfolio/history/${id}`, { method: 'DELETE' });
      set({ history: get().history.filter((h) => h.id !== id) });
    } catch { /* backend offline */ }
  },
}));
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/performanceStore.ts
git commit -m "feat(portfolio): performance store (history + performance fetch)"
```

---

### Task B2: portfolioStore — backend-backed close (partial aware)

**Files:**
- Modify: `frontend/lib/portfolioStore.ts`

- [ ] **Step 1: Add the remote close action**

In the `PortfolioStoreState` interface add:

```ts
  closePositionRemote: (
    recId: string,
    opts: { qtyToClose?: number | null; exitPrice?: number | null; exitDate?: string | null; sendToBroker?: boolean },
  ) => Promise<boolean>;
```

In the store body (next to `closePosition`) add:

```ts
      closePositionRemote: async (recId, opts) => {
        try {
          const res = await fetch(`${_BASE_URL()}/api/portfolio/${recId}/close`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              qtyToClose: opts.qtyToClose ?? null,
              exitPrice: opts.exitPrice ?? null,
              exitDate: opts.exitDate ?? null,
              sendToBroker: opts.sendToBroker ?? false,
            }),
          });
          if (!res.ok) return false;
          // Re-pull authoritative open positions (partial closes change qty)
          await usePortfolioStore.getState().syncFromBackend();
          return true;
        } catch {
          return false;
        }
      },
```

Note: keep the existing local `closePosition(contract)` for offline/local-only flows; the page will prefer `closePositionRemote`.

Also: `syncFromBackend` currently only sets positions when the list is non-empty (`if (positions.length > 0)`). Change it to always set so a full close that empties the portfolio is reflected:

```ts
      syncFromBackend: async () => {
        try {
          const res = await fetch(`${_BASE_URL()}/api/portfolio`);
          if (!res.ok) return;
          const positions: BackendPosition[] = await res.json();
          set({ positions: positions.map(fromBackend) });
        } catch {
          // network unavailable — keep localStorage state
        }
      },
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/portfolioStore.ts
git commit -m "feat(portfolio): backend-backed partial/full close in store"
```

---

### Task B3: ClosePositionDrawer organism

**Files:**
- Create: `frontend/components/organisms/ClosePositionDrawer/index.tsx`
- Create: `frontend/components/organisms/ClosePositionDrawer/ClosePositionDrawer.module.css`

- [ ] **Step 1: Implement the component**

```tsx
// frontend/components/organisms/ClosePositionDrawer/index.tsx
'use client';

/*
 * ClosePositionDrawer — sell/close UI for one portfolio position.
 * - Partial sells: qty defaults to full, capped at contracts held.
 * - Exit price pre-filled with the live current price, fully editable.
 * - Realized P&L preview updates live.
 * - "Also send to broker" is intentionally DISABLED (coming soon), mirroring
 *   the Step 7 Send-basket-to-broker feature that is wired but not yet live.
 */

import { useState } from 'react';
import { Text, Data } from '@/components/primitives';
import type { PortfolioPosition } from '@/types/domain';
import styles from './ClosePositionDrawer.module.css';

interface Props {
  position: PortfolioPosition;
  onCancel: () => void;
  onConfirm: (opts: { qtyToClose: number; exitPrice: number; exitDate: string }) => void;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function ClosePositionDrawer({ position, onCancel, onConfirm }: Props) {
  const held = position.contracts ?? 1;
  const [qty, setQty] = useState<number>(held);
  const [exitPrice, setExitPrice] = useState<number>(position.currentPrice || position.entryPrice);
  const [exitDate, setExitDate] = useState<string>(todayIso());

  const realizedDollar = Math.round((exitPrice - position.entryPrice) * 100 * qty);
  const realizedPct = position.entryPrice
    ? ((exitPrice - position.entryPrice) / position.entryPrice) * 100
    : 0;
  const tone = realizedDollar > 0 ? 'pass' : realizedDollar < 0 ? 'reject' : undefined;

  return (
    <div className={styles.drawer}>
      <div className={styles.header}>
        <Text size={12} weight={400}>Close {position.contract}</Text>
        <button type="button" className={styles.close} onClick={onCancel} aria-label="Cancel close">×</button>
      </div>

      <div className={styles.grid}>
        <label className={styles.field}>
          <Text size={11} tone="secondary">Contracts to sell (of {held})</Text>
          <input
            type="number" min={1} max={held} step={1} className={styles.input}
            value={qty}
            onChange={(e) => setQty(Math.max(1, Math.min(held, Math.round(Number(e.target.value) || 1))))}
            aria-label="Contracts to sell"
          />
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Exit price (per contract)</Text>
          <input
            type="number" min={0} step={0.05} className={styles.input}
            value={exitPrice}
            onChange={(e) => setExitPrice(Math.max(0, Number(e.target.value) || 0))}
            aria-label="Exit price"
          />
          <Text size={10} tone="dim">Pre-filled with the live price — edit to match your broker fill.</Text>
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Exit date</Text>
          <input
            type="date" className={styles.input}
            value={exitDate}
            onChange={(e) => setExitDate(e.target.value || todayIso())}
            aria-label="Exit date"
          />
        </label>

        <div className={styles.field}>
          <Text size={11} tone="secondary">Realized P&L</Text>
          <Data size={16} weight={600} tone={tone}>
            {realizedDollar > 0 ? '+' : ''}${realizedDollar}
            {'  '}({realizedPct > 0 ? '+' : ''}{realizedPct.toFixed(1)}%)
          </Data>
        </div>
      </div>

      <label className={styles.brokerStub} title="Coming soon — broker routing is not active yet">
        <input type="checkbox" disabled aria-label="Also send close to broker (coming soon)" />
        <Text size={11} tone="dim">Also send to broker (coming soon)</Text>
      </label>

      <div className={styles.footer}>
        <button type="button" className={styles.btn} onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className={`${styles.btn} ${styles.btnPrimary}`}
          onClick={() => onConfirm({ qtyToClose: qty, exitPrice, exitDate })}
        >
          {qty >= held ? 'Close position' : `Sell ${qty} of ${held}`}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add the stylesheet**

```css
/* frontend/components/organisms/ClosePositionDrawer/ClosePositionDrawer.module.css */
.drawer { border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--bg-surface); padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-3); }
.header { display: flex; align-items: center; justify-content: space-between; }
.close { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 18px; line-height: 1; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
.field { display: flex; flex-direction: column; gap: 4px; }
.input { background: var(--bg-base); border: 1px solid var(--border-subtle); border-radius: 6px; color: var(--text-primary); padding: 6px 8px; font-size: 13px; font-variant-numeric: tabular-nums; }
.brokerStub { display: flex; align-items: center; gap: 8px; opacity: 0.6; cursor: not-allowed; }
.footer { display: flex; justify-content: flex-end; gap: var(--space-2); }
.btn { border: 1px solid var(--border-subtle); background: var(--bg-base); color: var(--text-primary); border-radius: 6px; padding: 6px 14px; font-size: 13px; cursor: pointer; }
.btnPrimary { background: var(--accent); border-color: var(--accent); color: #fff; }
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/ClosePositionDrawer/
git commit -m "feat(portfolio): ClosePositionDrawer (partial qty, editable exit, broker stub)"
```

---

### Task B4: Portfolio page — Open/History tabs, performance strip, wire close

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`
- Modify: `frontend/app/(frame)/portfolio/page.module.css`

- [ ] **Step 1: Wire the new pieces into the page**

Changes to `page.tsx`:
1. Add imports:
```tsx
import { ClosePositionDrawer } from '@/components/organisms/ClosePositionDrawer';
import { usePerformanceStore } from '@/lib/performanceStore';
```
2. In `PortfolioPage`, add state + store wiring:
```tsx
  const [tab, setTab] = useState<'open' | 'history'>('open');
  const [closing, setClosing] = useState<string | null>(null); // contract being closed
  const closeRemote = usePortfolioStore((s) => s.closePositionRemote);
  const history = usePerformanceStore((s) => s.history);
  const performance = usePerformanceStore((s) => s.performance);
  const fetchHistory = usePerformanceStore((s) => s.fetchHistory);
  const fetchPerformance = usePerformanceStore((s) => s.fetchPerformance);
  const removeHistory = usePerformanceStore((s) => s.removeHistory);

  useEffect(() => { fetchHistory(); fetchPerformance(); }, [fetchHistory, fetchPerformance]);
```
3. Replace the existing `closePosition` handler with a remote-backed one:
```tsx
  const confirmClose = async (p: PortfolioPosition, opts: { qtyToClose: number; exitPrice: number; exitDate: string }) => {
    const ok = await closeRemote(p.recId, opts);
    if (ok) { setClosing(null); fetchHistory(); fetchPerformance(); }
  };
```
4. Render a tab strip + performance strip above the table:
```tsx
      <div className={styles.tabs}>
        <button type="button" className={tab === 'open' ? styles.tabActive : styles.tab} onClick={() => setTab('open')}>
          Open ({positions.length})
        </button>
        <button type="button" className={tab === 'history' ? styles.tabActive : styles.tab} onClick={() => setTab('history')}>
          History ({history.length})
        </button>
      </div>

      <div className={styles.perfStrip}>
        <PerfStat label="Today"  value={performance.realizedToday} />
        <PerfStat label="Week"   value={performance.realizedWeek} />
        <PerfStat label="Month"  value={performance.realizedMonth} />
        <PerfStat label="Year"   value={performance.realizedYear} />
      </div>
```
5. Wrap the existing open-positions table block in `{tab === 'open' && ( ... )}`. In the EditDrawer's "Close position" button, instead of removing directly, open the close drawer: change `onRemove={() => closePosition(p.contract)}` to `onRemove={() => { setEditing(null); setClosing(p.contract); }}`.
6. After the table, render the close drawer for the active row:
```tsx
      {tab === 'open' && closing && (() => {
        const p = positions.find((x) => x.contract === closing);
        return p ? (
          <ClosePositionDrawer
            position={p}
            onCancel={() => setClosing(null)}
            onConfirm={(opts) => confirmClose(p, opts)}
          />
        ) : null;
      })()}
```
7. Add the History tab body:
```tsx
      {tab === 'history' && (
        <div className={styles.historyWrap}>
          {history.length === 0 ? (
            <Text size={13} tone="secondary">No closed trades yet.</Text>
          ) : history.map((h) => (
            <div key={h.id} className={styles.historyRow}>
              <Data size={13} weight={500}>{h.symbol}</Data>
              <Text size={12} tone="secondary">{h.contract}</Text>
              <Text size={11} tone="dim">{h.qtyClosed}x · {h.entryPrice.toFixed(2)} → {h.exitPrice.toFixed(2)}</Text>
              <Text size={11} tone="dim">{h.exitDate}</Text>
              <Data size={13} weight={600} tone={h.realizedPnlDollar > 0 ? 'pass' : h.realizedPnlDollar < 0 ? 'reject' : undefined}>
                {h.realizedPnlDollar > 0 ? '+' : ''}${Math.round(h.realizedPnlDollar)}
              </Data>
              <button type="button" className={styles.historyRemove} onClick={() => removeHistory(h.id)} aria-label={`Remove ${h.symbol} from history`} title="Remove from history">×</button>
            </div>
          ))}
        </div>
      )}
```
8. Add the `PerfStat` helper at the bottom of the file:
```tsx
function PerfStat({ label, value }: { label: string; value: number }) {
  const tone = value > 0 ? 'pass' : value < 0 ? 'reject' : undefined;
  return (
    <div className={styles.perfStat}>
      <Text size={11} tone="secondary">{label}</Text>
      <Data size={16} weight={600} tone={tone}>{value > 0 ? '+' : ''}${Math.round(value)}</Data>
    </div>
  );
}
```

- [ ] **Step 2: Add styles** (append to `page.module.css`)

```css
.tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); }
.tab, .tabActive { border: 1px solid var(--border-subtle); background: var(--bg-surface); color: var(--text-secondary); border-radius: 6px; padding: 6px 14px; font-size: 13px; cursor: pointer; }
.tabActive { color: var(--text-primary); border-color: var(--accent); }
.perfStrip { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-3); margin-bottom: var(--space-4); }
.perfStat { display: flex; flex-direction: column; gap: 2px; border: 1px solid var(--border-subtle); border-radius: 8px; padding: var(--space-2) var(--space-3); }
.historyWrap { display: flex; flex-direction: column; gap: 6px; }
.historyRow { display: grid; grid-template-columns: 64px 1.6fr 1fr 96px 80px 28px; align-items: center; gap: var(--space-2); border: 1px solid var(--border-subtle); border-radius: 6px; padding: 8px 10px; }
.historyRemove { background: none; border: none; color: var(--text-secondary); cursor: pointer; font-size: 16px; }
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/portfolio/page.tsx" "frontend/app/(frame)/portfolio/page.module.css"
git commit -m "feat(portfolio): Open/History tabs, performance strip, close drawer wiring"
```

---

## Phase C — Dashboard earnings graph (toggleable, two lines)

### Task C1: EarningsChart organism (lightweight-charts two-line)

**Files:**
- Create: `frontend/components/organisms/EarningsChart/index.tsx`
- Create: `frontend/components/organisms/EarningsChart/EarningsChart.module.css`

- [ ] **Step 1: Implement the chart** (mirror the lightweight-charts v5 setup used in `CandlestickChart`)

```tsx
// frontend/components/organisms/EarningsChart/index.tsx
'use client';

/*
 * EarningsChart — two lightweight-charts line series:
 *  - Realized profit (cumulative, from closed trades)
 *  - Total account value (realized + open mark, from daily equity snapshots)
 * Reads theme tokens at mount, like CandlestickChart.
 */

import { useEffect, useRef } from 'react';
import { createChart, LineSeries, type IChartApi, type Time } from 'lightweight-charts';
import { useThemeStore } from '@/lib/theme';
import type { PerfPoint } from '@/lib/performanceStore';
import styles from './EarningsChart.module.css';

interface Props {
  realizedCurve: PerfPoint[];
  equityCurve: PerfPoint[];
  height?: number;
}

function token(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function toLine(points: PerfPoint[]) {
  // lightweight-charts wants ascending unique times; backend already sorts.
  return points.map((p) => ({ time: p.date as Time, value: p.value }));
}

export function EarningsChart({ realizedCurve, equityCurve, height = 260 }: Props) {
  const theme = useThemeStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const chart: IChartApi = createChart(el, {
      height,
      layout: {
        background: { color: token('--bg-surface') || '#1E2335' },
        textColor: token('--text-secondary') || '#787B86',
      },
      grid: {
        vertLines: { color: token('--border-subtle') || '#2A2E42' },
        horzLines: { color: token('--border-subtle') || '#2A2E42' },
      },
      rightPriceScale: { borderColor: token('--border-subtle') || '#2A2E42' },
      timeScale: { borderColor: token('--border-subtle') || '#2A2E42' },
    });

    const equity = chart.addSeries(LineSeries, {
      color: token('--accent') || '#4C8DFF', lineWidth: 2, title: 'Account value',
    });
    const realized = chart.addSeries(LineSeries, {
      color: token('--pass') || '#27c08a', lineWidth: 2, title: 'Realized',
    });

    equity.setData(toLine(equityCurve));
    realized.setData(toLine(realizedCurve));
    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => { ro.disconnect(); chart.remove(); };
  }, [realizedCurve, equityCurve, height, theme]);

  return <div ref={containerRef} className={styles.chart} />;
}
```

- [ ] **Step 2: Add the stylesheet**

```css
/* frontend/components/organisms/EarningsChart/EarningsChart.module.css */
.chart { width: 100%; }
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean. (If `LineSeries`/`addSeries` types differ in the installed lightweight-charts version, match the exact import/use already working in `CandlestickChart` — `addSeries(CandlestickSeries, …)` confirms the v5 `addSeries(SeriesDefinition, …)` API.)

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/EarningsChart/
git commit -m "feat(dashboard): EarningsChart two-line organism"
```

---

### Task C2: Dashboard earnings card with persisted on/off toggle

**Files:**
- Modify: `frontend/app/(frame)/dashboard/page.tsx`
- Modify: `frontend/app/(frame)/dashboard/page.module.css`

- [ ] **Step 1: Wire the card**

In `dashboard/page.tsx`:
1. Add imports:
```tsx
import { EarningsChart } from '@/components/organisms/EarningsChart';
import { usePerformanceStore } from '@/lib/performanceStore';
import { SectionCard } from '@/components/molecules/SectionCard'; // already imported
```
2. Add state + fetch (persist toggle to localStorage so it survives reloads):
```tsx
  const performance = usePerformanceStore((s) => s.performance);
  const fetchPerformance = usePerformanceStore((s) => s.fetchPerformance);
  const [showEarnings, setShowEarnings] = useState<boolean>(false);

  useEffect(() => {
    setShowEarnings(localStorage.getItem('bamendjou:showEarnings') === '1');
    fetchPerformance();
  }, [fetchPerformance]);

  const toggleEarnings = () => {
    setShowEarnings((v) => {
      const next = !v;
      localStorage.setItem('bamendjou:showEarnings', next ? '1' : '0');
      return next;
    });
  };
```
3. Add the card to the layout (e.g. just below the regime banner, before `bentoTop`):
```tsx
      <SectionCard
        title="Earnings"
        action={{ label: showEarnings ? 'Hide graph' : 'Show graph', onClick: toggleEarnings }}
      >
        {showEarnings ? (
          performance.equityCurve.length === 0 && performance.realizedCurve.length === 0 ? (
            <Text size={12} tone="dim">No earnings data yet — close a trade to start the curve.</Text>
          ) : (
            <EarningsChart
              realizedCurve={performance.realizedCurve}
              equityCurve={performance.equityCurve}
            />
          )
        ) : (
          <Text size={12} tone="dim">Graph hidden. Use “Show graph” to display realized profit and account value over time.</Text>
        )}
      </SectionCard>
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Run the frontend test suite (no regressions)**

Run: `cd frontend && npm run test`
Expected: existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/dashboard/page.tsx" "frontend/app/(frame)/dashboard/page.module.css"
git commit -m "feat(dashboard): toggleable earnings card (realized + account value)"
```

---

## Phase D — Verification & audit

### Task D1: Full verification

- [ ] **Step 1: Backend suite**

Run: `cd backend && python -m pytest -q`
Expected: 0 failed (prior green count + new tests).

- [ ] **Step 2: Frontend typecheck + tests**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: typecheck clean; tests pass.

- [ ] **Step 3: Manual smoke (optional, with backend running)**

Start backend + `npm run dev`; add a position from Step 7, close part of it on the Portfolio page (confirm exit price pre-fills and is editable, realized preview is correct), verify it appears under History and the open row qty dropped, check the performance strip updates, and toggle the dashboard Earnings graph on/off.

### Task D2: Audit subagent (REQUIRED)

- [ ] Dispatch a fresh subagent with the systematic-debugging + verification-before-completion skills to audit the whole change: confirm (a) no mock/test data on the runtime path, (b) the broker stub is inert and clearly marked, (c) realized-P&L math matches the open-P&L convention, (d) partial-close qty accounting is correct and can't go negative, (e) the equity snapshot is one-per-day, (f) `settings.yaml` was never staged, (g) full backend suite + frontend typecheck are green. The subagent reports a punch list; fix any issues before declaring done. Keep all commits LOCAL — do not push.

---

## Self-Review (completed)

- **Spec coverage:** history kept by default + manual remove (A2/A5/B4) ✓; sell/close with positive/negative result (A5/B3) ✓; partial sells (A5/B3/B4) ✓; exit price auto + editable (A5/B3) ✓; day/week/month/year calendar performance (A1/A6/B4) ✓; two-line earnings graph toggle on dashboard (C1/C2) ✓; keep-by-default + optional remove (A5 history-delete + B4 remove button) ✓; future send-to-broker stub clearly inactive (A4 field + A5 `_maybe_send_close_to_broker` + B3 disabled checkbox) ✓.
- **Placeholder scan:** no TBD/“add error handling” placeholders; every code/test step has real content.
- **Type consistency:** `closePositionRemote` signature matches its call in B4; `PerfPoint`/`Performance`/`ClosedPosition` names consistent across B1/C1/C2; backend `ClosedPositionSchema` camelCase fields match the frontend `ClosedPosition` interface; `realized_pnl`/`bucket_realized_by_calendar`/`cumulative_curve` names consistent A1↔A6.
```
