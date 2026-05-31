# Context Doc 34 — Trade Card Backend

**Workstream:** Make `GET /api/tradecards` return real TradeCardData from the latest scan
**Conflict class:** Zero conflict — modifies one backend file only

---

## 1. Mission

`GET /api/tradecards` currently returns `[]` unconditionally. The scan router already produces `TradeCardData` objects and persists the full `ScanResult` as JSON in the `scan_sessions` DB table (row with `id="current"`). This workstream makes `GET /api/tradecards` read that persisted result and return its `candidates` list. Do not touch the scan router, schemas, or any other file.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `backend/app/routers/tradecards.py` | Modify | Read latest ScanResult from DB, return its candidates |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `backend/app/models/scan_session.py` | `ScanSession` ORM model — `id: str`, `last_result_json: str \| None` |
| `backend/app/schemas/__init__.py` | `TradeCardData`, `ScanResult` — understand the shape being deserialized |
| `backend/app/database.py` | `get_db` — async session dependency |
| `backend/app/routers/scan.py` | Lines 120–157: how `_upsert_session` saves and `restore_from_db` loads the JSON row |

---

## 4. Integration constraints

**How the scan result is persisted:**
- The scan router calls `_upsert_session(db, req, result, status)` which does `db.merge(ScanSession(id="current", last_result_json=result.model_dump_json(), ...))`.
- Single row — always `id = "current"`.
- `last_result_json` is a JSON string that deserializes to `ScanResult`.

**Reading it back:**
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.scan_session import ScanSession
from app.schemas import ScanResult, TradeCardData

result = await db.execute(select(ScanSession).where(ScanSession.id == "current"))
row = result.scalar_one_or_none()
if row is None or not row.last_result_json:
    return []
scan = ScanResult.model_validate_json(row.last_result_json)
return scan.candidates
```

**`ScanResult.candidates`** is `list[TradeCardData]` — already the correct response type.

**Response model is already declared** in `tradecards.py`:
```python
@router.get('/tradecards', response_model=list[TradeCardData])
```
Do not change the route path, method, or response model.

---

## 5. Key schemas (read-only, do not modify)

```python
# From backend/app/schemas/__init__.py

class TradeCardData(BaseModel):
    symbol: str
    company: str
    price: float
    direction: Literal['Bullish', 'Bearish']
    status: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
    stockScore: int
    stockConfidence: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
    stockBreakdown: ScoreBreakdown
    contract: str
    contractScore: int
    contractConfidence: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
    contractBreakdown: ContractScoreBreakdown
    contractDetails: Optional[ContractDetails] = None
    entry: TradeEntry
    exit: TradeExit
    nextEventDays: Optional[int] = None
    nextEventLabel: Optional[str] = None
    rrRatio: float
    rrModel: Literal['Heston repriced', 'Delta approximation']
    finalStatus: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']

class ScanResult(BaseModel):
    scan_id: str
    timestamp: str
    candidates: list[TradeCardData]   # ← what we return
    rejected: list[RejectedCandidate]
    state: ScanState
    ...
```

---

## 6. Task spec

**What to build:**

Replace the `tradecards.py` stub body with DB-backed logic:
1. Inject `db: AsyncSession = Depends(get_db)`.
2. Query `ScanSession` where `id = "current"`.
3. If no row or `last_result_json` is `None`, return `[]`.
4. Deserialize with `ScanResult.model_validate_json(row.last_result_json)`.
5. Return `scan.candidates`.

**Acceptance criteria:**
- `GET /api/tradecards` returns `[]` when no scan has been run yet.
- After `POST /api/scan` completes, `GET /api/tradecards` returns the same `candidates` list that the scan returned.
- Response validates against `list[TradeCardData]` (FastAPI will enforce this automatically).
- `pytest backend/tests/ -q` stays green.

**Edge cases:**
- `last_result_json` is an empty string or malformed JSON → catch `Exception`, return `[]`.
- `candidates` is an empty list (all symbols rejected) → return `[]` (valid).
- DB unreachable → FastAPI 500 is acceptable; do not swallow DB errors.

---

## 7. Hard rules

- Do not touch `scan.py`, `schemas/`, or any other file.
- Do not add a new in-memory cache — read directly from the DB each request.
- Do not change the route path (`/api/tradecards`), HTTP method, or response model.
- No new pip packages.
- `async def get_tradecards(db: AsyncSession = Depends(get_db))` — must be async since it uses `await db.execute(...)`.

---

## 8. Dev workflow

```bash
cd backend
python -m pytest tests/ -q   # must stay green

# Integration smoke test
uvicorn app.main:app --reload
# 1. POST /api/scan with a small universe
# 2. GET /api/tradecards — should return candidates from the scan
```

---

## 9. Copy/paste prompt

```
Read `llm-contexts/34-trade-card-backend.md` fully before writing any code. It is your single source of truth.

You are implementing the trade card backend endpoint for the Bamendjou options screener (FastAPI, Python 3.11, SQLAlchemy async).

Your owned files:
- backend/app/routers/tradecards.py  (MODIFY)

Do not modify any file outside this list.

Task: Replace the stub body of GET /api/tradecards with logic that reads the persisted ScanResult from the scan_sessions DB table (id="current") and returns its candidates list. Return [] if no scan exists yet.

After editing, run: python -m pytest backend/tests/ -q
Must stay green. Commit when done.
```
