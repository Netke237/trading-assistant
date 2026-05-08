---
workstream: WS-34
branch: feat/ws-34-persistence
phase: 1
depends_on: fix/ws-33-foundation (merged to main)
conflict_class: Zero — creates new DB models and new files; extends existing stubs
---

# WS-34: Backend Persistence + Audit Trail

## Mission

Replace the stub `GET /api/portfolio` and `GET /api/watchlist` endpoints (which currently return empty lists) with real SQLAlchemy-backed CRUD. Add a DB-backed audit table so human trade approvals have a traceable record with a `rec_id` that joins to the existing JSONL audit log.

**PRD coverage:** B2, B4, G2, FR-16, FR-43, FR-46

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `backend/app/models/portfolio.py` | Create | SQLAlchemy `PortfolioPosition` ORM model |
| `backend/app/models/watchlist.py` | Create | SQLAlchemy `WatchlistSymbol` ORM model |
| `backend/app/models/audit_event.py` | Create | SQLAlchemy `AuditEvent` ORM model |
| `backend/app/routers/portfolio.py` | Modify | Replace stub with real CRUD: GET list, POST add, DELETE remove |
| `backend/app/routers/watchlist.py` | Modify | Replace stub with real CRUD: GET list, POST add, DELETE remove |
| `backend/app/services/audit.py` | Modify | Add `log_approval()`, `log_rejection()`, `log_override()` alongside existing `log_event()` |
| `backend/migrations/` | Modify | Alembic migration for 3 new tables |
| `backend/tests/test_persistence.py` | Create | CRUD tests for portfolio, watchlist, and audit log |

**Do NOT touch any other files.**

---

## Read-Only References

Read these for patterns — do not modify:

- `backend/app/models/base.py` — SQLAlchemy `Base` class (has `id` UUID PK, `created_at`, `updated_at`)
- `backend/app/database.py` — `AsyncSessionLocal`, `get_db()` async session factory, `Base`
- `backend/app/routers/alerts.py` — existing router pattern to follow
- `frontend/lib/portfolioStore.ts` — `PortfolioPosition` TypeScript type (for field parity)
- `frontend/types/domain.ts` — `PortfolioPosition`, `TargetLevel` interfaces

---

## Critical: Base Class Issue

`backend/app/models/base.py` defines a `Base(DeclarativeBase)` with `id` and `created_at`.
`backend/app/database.py` defines a DIFFERENT `Base = declarative_base()` (older style).

**Use the `Base` from `database.py`** (not `models/base.py`) for the 3 new ORM models — it's what the existing `create_all()` call uses. Pattern:

```python
# backend/app/models/portfolio.py
from app.database import Base
from sqlalchemy import Column, String, Float, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone

class PortfolioPositionModel(Base):
    __tablename__ = "portfolio_positions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rec_id = Column(String, nullable=False, unique=True, index=True)
    symbol = Column(String, nullable=False)
    contract = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    entry_date = Column(String, nullable=False)
    stop = Column(Float, nullable=True)
    targets = Column(JSON, nullable=True, default=list)
    dte_total = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

---

## Endpoint Contracts

### Portfolio

```
GET  /api/portfolio              → List[PortfolioPositionSchema]
POST /api/portfolio              body: PortfolioPositionCreate → PortfolioPositionSchema (201)
DELETE /api/portfolio/{rec_id}   → 204  (no body)
```

Duplicate detection: if a `POST /api/portfolio` arrives with a `contract` string that already exists in the DB → return **409 Conflict** (do NOT create duplicate).

### Watchlist

```
GET    /api/watchlist           → List[str]  (list of symbol strings)
POST   /api/watchlist           body: {"symbol": "AAPL"} → 201
DELETE /api/watchlist/{symbol}  → 204
```

Current `GET /api/watchlist` returns `list[WatchlistRow]` — **change this** to `list[str]` (plain symbol list) to match what `watchlistStore.ts` expects.

### Pydantic Schemas (add to `backend/app/schemas/__init__.py` or a new `schemas/persistence.py`)

```python
class PortfolioPositionCreate(BaseModel):
    recId: str
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: str
    entryPrice: float
    qty: int = 1
    entryDate: str      # ISO date string
    stop: Optional[float] = None
    targets: list[dict] = []
    dteTotal: Optional[int] = None

class PortfolioPositionSchema(PortfolioPositionCreate):
    id: str
    createdAt: str

    model_config = ConfigDict(from_attributes=True)
```

**Field mapping note:** ORM uses snake_case (`entry_price`, `rec_id`), Pydantic uses camelCase (`entryPrice`, `recId`). Use `model_config = ConfigDict(populate_by_name=True)` and `alias` or `alias_generator` to bridge them.

---

## Audit Trail

`backend/app/services/audit.py` currently has `log_event()` which writes to a JSONL file. Add these **alongside** it (do NOT remove `log_event()`):

```python
# AuditEvent ORM model (backend/app/models/audit_event.py)
class AuditEventModel(Base):
    __tablename__ = "audit_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String, nullable=False)   # "approval" | "rejection" | "override"
    rec_id = Column(String, nullable=False, index=True)   # same format as JSONL rec_id
    recommendation_id = Column(String, nullable=False)     # same as rec_id (aliased)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

```python
# In audit.py — new async DB functions:
async def log_approval(rec_id: str, trade_card_data: dict, db: AsyncSession) -> None:
    """Write approval event to AuditEvent table. rec_id must use same format as new_rec_id()."""
    event = AuditEventModel(
        event_type="approval",
        rec_id=rec_id,
        recommendation_id=rec_id,
        payload=trade_card_data,
    )
    db.add(event)
    await db.commit()
    # Also write to JSONL for dual-system traceability:
    log_event("approval", rec_id, trade_card_data)

async def log_rejection(rec_id: str, reason: str, db: AsyncSession) -> None: ...
async def log_override(rec_id: str, override_data: dict, db: AsyncSession) -> None: ...
```

**Key invariant:** `rec_id` format is `REC-YYYYMMDD-XXXXXXXX` (from `new_rec_id()` in `audit.py`). Both JSONL and DB use the same `rec_id` string — a trace query can join on this key.

---

## Alembic Migration

Run from `backend/`:
```bash
alembic revision --autogenerate -m "add portfolio watchlist audit tables"
```

Verify the generated migration creates all 3 tables before committing it.

---

## Tests (`backend/tests/test_persistence.py`)

Use pytest with an in-memory SQLite async engine (override the `get_db` dependency). Write these test cases:

1. **Portfolio add/list**: POST a position → GET returns it
2. **Portfolio delete**: POST then DELETE by `rec_id` → GET returns empty list
3. **Portfolio restart persistence**: (conceptual — the add/list test covers this via the DB)
4. **Duplicate prevention**: POST same `contract` string twice → second returns 409
5. **Watchlist add/list/delete**: POST symbol → GET returns it → DELETE → GET returns empty
6. **Audit log write**: call `log_approval()` → AuditEvent row exists with correct `rec_id`
7. **`rec_id` dual-system match**: after `log_approval()`, the same `rec_id` appears in both the AuditEvent table and the JSONL audit.log

Run: `pytest tests/test_persistence.py -v` — all pass.

---

## Acceptance Criteria

- [ ] `GET /api/portfolio` after server restart returns positions written before restart
- [ ] `POST /api/portfolio` with duplicate `contract` string returns 409
- [ ] `AuditEvent` table has a row for every `log_approval()` call with valid `rec_id`
- [ ] `GET /api/watchlist` returns `list[str]` (not `list[WatchlistRow]`)
- [ ] `pytest tests/test_persistence.py` — all pass
- [ ] No files outside the Owned Files table were modified

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-34 (Backend Persistence + Audit Trail) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-34-persistence (already created — checkout before starting)
Base: main (WS-33 merged)

Read the full context doc before writing any code:
F:\Git\GitHub\Trading assistant\llm-contexts\01-ws34-persistence.md

Key files to read first (do not modify):
- backend/app/models/base.py
- backend/app/database.py
- backend/app/routers/alerts.py  (pattern reference)
- backend/app/services/audit.py  (extend, do NOT remove log_event())
- backend/app/schemas/__init__.py  (add new schemas here)
- frontend/types/domain.ts  (PortfolioPosition type for field parity)

Tasks in order:
1. Create ORM models: portfolio.py, watchlist.py, audit_event.py in backend/app/models/
2. Generate Alembic migration
3. Replace portfolio.py router stub with real CRUD
4. Replace watchlist.py router stub with real CRUD
5. Add log_approval/log_rejection/log_override to audit.py
6. Write test_persistence.py
7. Run: cd backend && pytest tests/test_persistence.py -v  (all must pass)

Return: one-paragraph summary of what you implemented and the pytest output.
```
