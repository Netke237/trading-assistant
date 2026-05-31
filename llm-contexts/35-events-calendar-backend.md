# Context Doc 35 — Events Calendar Backend

**Workstream:** Make `GET /api/events` return real upcoming events from Tradier
**Conflict class:** Zero conflict — modifies one backend file only

---

## 1. Mission

`GET /api/events` currently returns `[]` unconditionally. The calendar page needs real upcoming events (earnings, dividends) for symbols in the portfolio and watchlist. This workstream replaces the stub with logic that fetches events from Tradier for all watchlist + portfolio symbols and returns them as `UpcomingEvent` objects sorted by date. Do not touch schemas, other routers, or the Tradier data layer.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `backend/app/routers/events.py` | Modify | Fetch upcoming events for watchlist + portfolio symbols |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `backend/app/data/market.py` | `fetch_earnings_date(symbol) -> date \| None`, `fetch_dividend_date(symbol) -> date \| None` |
| `backend/app/schemas/__init__.py` | `UpcomingEvent` schema |
| `backend/app/models/portfolio.py` | `PortfolioPositionModel` — `.symbol` field |
| `backend/app/models/watchlist.py` | `WatchlistModel` — read its fields to know the symbol column name |
| `backend/app/database.py` | `get_db` |

---

## 4. Integration constraints

**`UpcomingEvent` schema:**
```python
class UpcomingEvent(BaseModel):
    date: str      # ISO date string "YYYY-MM-DD"
    symbol: str
    label: str     # "Earnings" | "Dividend" | other
    status: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
```

**Status by proximity (match existing Step 5 logic):**
- `days <= 3` → `'REJECT'` (imminent)
- `days <= 7` → `'CAUTION'` (near)
- `days > 7`  → `'PASS'` (distant)

**Tradier fetch functions (from `data/market.py`):**
```python
def fetch_earnings_date(symbol: str) -> date | None:
    # Returns next earnings date or None — uses Tradier beta fundamentals
    # Returns None on any error (not a raise)

def fetch_dividend_date(symbol: str) -> date | None:
    # Returns next ex-dividend date or None
    # Returns None on any error
```

Both are **synchronous** — do not `await` them.

**Querying symbols:**
```python
# Portfolio symbols
from app.models.portfolio import PortfolioPositionModel
port_result = await db.execute(select(PortfolioPositionModel))
port_symbols = {p.symbol for p in port_result.scalars().all()}

# Watchlist symbols — check models/watchlist.py for exact column name
# Likely: WatchlistModel.symbol
from app.models.watchlist import WatchlistModel
wl_result = await db.execute(select(WatchlistModel))
wl_symbols = {w.symbol for w in wl_result.scalars().all()}

all_symbols = list(port_symbols | wl_symbols)
```

**Deduplication rule:** If a symbol appears in both portfolio and watchlist, emit only one event per type (earnings or dividend) per symbol — not two.

---

## 5. Task spec

**What to build:**

Replace the `events.py` stub body with:
1. Inject `db: AsyncSession = Depends(get_db)`.
2. Query unique symbols from portfolio + watchlist (union, deduplicated).
3. For each symbol, call `fetch_earnings_date(symbol)` and `fetch_dividend_date(symbol)`.
4. For each non-None result, compute `days = (event_date - date.today()).days`.
5. Skip events in the past (`days < 0`).
6. Determine `status` from proximity thresholds.
7. Build `UpcomingEvent(date=event_date.isoformat(), symbol=symbol, label="Earnings" or "Dividend", status=status)`.
8. Return list sorted by `date` ascending.

**Acceptance criteria:**
- `GET /api/events` returns `[]` when portfolio and watchlist are empty.
- When portfolio has AAPL and Tradier returns an earnings date 5 days out, the response includes `{"date": "...", "symbol": "AAPL", "label": "Earnings", "status": "CAUTION"}`.
- Events in the past are excluded.
- If Tradier fetch fails for a symbol (`None` return), that symbol contributes no event — no crash.
- Response is sorted by date ascending.
- `pytest backend/tests/ -q` stays green.

**Performance note:** Tradier calls are sequential per symbol. For small watchlists this is fine. Do not add asyncio concurrency — keep it simple.

---

## 6. Hard rules

- Do not modify `fetch_earnings_date` or `fetch_dividend_date` — they already handle errors.
- Do not add new packages.
- Fetch functions are synchronous — call them directly, no `await`.
- Do not change the route path, HTTP method, or response model signature.
- Graceful degradation: if all fetches fail → return `[]`, not a 500.

---

## 7. Dev workflow

```bash
cd backend
python -m pytest tests/ -q   # must stay green

# Smoke test (requires Tradier API token in .env and a running DB)
uvicorn app.main:app --reload
curl http://localhost:8000/api/events
```

---

## 8. Copy/paste prompt

```
Read `llm-contexts/35-events-calendar-backend.md` fully before writing any code. It is your single source of truth.

You are implementing the events calendar backend endpoint for the Bamendjou options screener (FastAPI, Python 3.11, SQLAlchemy async).

Your owned files:
- backend/app/routers/events.py  (MODIFY)

Do not modify any file outside this list.

Task: Replace the stub body of GET /api/events with logic that collects unique symbols from the portfolio and watchlist DB tables, fetches upcoming earnings and dividend dates from Tradier for each, and returns them as UpcomingEvent objects sorted by date. Return [] on any failure.

After editing, run: python -m pytest backend/tests/ -q
Must stay green. Commit when done.
```
