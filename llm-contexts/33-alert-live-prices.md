# Context Doc 33 — Alert Live Prices

**Workstream:** Wire Tradier live price feed into `/api/alerts`
**Conflict class:** Zero conflict — modifies one backend file only

---

## 1. Mission

The alert generator already checks stop/target/time-stop thresholds correctly, but `current_prices` is always an empty dict, so price-based alerts (TP_HIT, STOP_REACHED) never fire. This workstream fetches live stock quotes from Tradier for every symbol in the portfolio before passing them to `generate_alerts`. Do not change any other router, service, or schema.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `backend/app/routers/alerts.py` | Modify | Fetch live prices for portfolio symbols before calling generate_alerts |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `backend/app/services/alert_generator.py` | Understand what generate_alerts expects: `current_prices: dict[str, float]`, `current_option_prices: dict[str, float] \| None` |
| `backend/app/data/market.py` | `fetch_quotes(symbols: list[str]) -> dict[str, {"last": float, "prevclose": float}]` and `fetch_price(symbol) -> float \| None` |
| `backend/app/schemas/__init__.py` | `AlertItem`, `PortfolioPositionSchema` |
| `backend/app/models/portfolio.py` | `PortfolioPositionModel` — has `.symbol` and `.contract` fields |
| `backend/app/database.py` | `get_db` dependency |

---

## 4. Integration constraints

**Database query pattern (existing in codebase):**
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.portfolio import PortfolioPositionModel

result = await db.execute(select(PortfolioPositionModel))
positions = result.scalars().all()
symbols = list({p.symbol for p in positions})
```

**fetch_quotes signature (from `data/market.py`):**
```python
def fetch_quotes(symbols: list[str]) -> dict[str, dict]:
    # Returns: { "AAPL": {"last": 185.20, "prevclose": 183.10}, ... }
    # Returns {} on any network/API error — handle gracefully
```

**generate_alerts signature (from `services/alert_generator.py`):**
```python
async def generate_alerts(
    db: AsyncSession,
    current_prices: dict[str, float],               # symbol → last price
    current_option_prices: dict[str, float] | None = None,  # contract_id → price
) -> list[AlertItem]
```

**What to pass for `current_prices`:** Extract `.last` from each quote dict:
```python
current_prices = {sym: q["last"] for sym, q in quotes.items()}
```

**What to pass for `current_option_prices`:** Leave as `None` for now (option price feed is a separate workstream). The TODO comment for that is in the alert_generator.

---

## 5. Task spec

**What to build:**

In `backend/app/routers/alerts.py`:
1. Query all portfolio positions from the DB to collect unique symbols.
2. Call `fetch_quotes(symbols)` — synchronous function, call directly (not `await`).
3. Build `current_prices: dict[str, float]` from the result.
4. Pass it to `generate_alerts(db, current_prices)`.
5. If `fetch_quotes` returns `{}` (network failure), pass empty dict as before — do not raise.

**Acceptance criteria:**
- `/api/alerts` returns TP_HIT or STOP_REACHED alerts when portfolio positions cross thresholds and Tradier API responds.
- When Tradier is unavailable (`fetch_quotes` returns `{}`), returns `[]` without raising an exception.
- `current_option_prices` remains `None` (not wired in this workstream).
- No new imports beyond what `data.market` and `models.portfolio` already provide.
- `pytest backend/tests/ -q` stays green.

**Edge case:** Empty portfolio — `symbols` is `[]`. `fetch_quotes([])` returns `{}`. That's fine, just pass it through.

---

## 6. Hard rules

- No new dependencies (no `pip install`).
- No new schemas — `AlertItem` already handles all alert types.
- `fetch_quotes` is synchronous — do not `await` it.
- Do not modify `generate_alerts` — it already handles `None` prices gracefully.
- Do not catch and swallow DB exceptions — only network/Tradier errors are silenced (that happens inside `fetch_quotes`).

---

## 7. Dev workflow

```bash
cd backend
# Run existing tests — must stay green
python -m pytest tests/ -q

# Smoke test (requires Tradier API token in .env and a running DB)
uvicorn app.main:app --reload
curl http://localhost:8000/api/alerts
```

---

## 8. Copy/paste prompt

```
Read `llm-contexts/33-alert-live-prices.md` fully before writing any code. It is your single source of truth.

You are implementing live price wiring for the alerts endpoint of the Bamendjou options screener (FastAPI, Python 3.11, SQLAlchemy async).

Your owned files:
- backend/app/routers/alerts.py  (MODIFY)

Do not modify any file outside this list.

Task: Modify GET /api/alerts to query portfolio symbols from the DB, call fetch_quotes() from app.data.market, and pass the resulting price dict into generate_alerts() so that TP_HIT and STOP_REACHED alerts fire on real prices.

After editing, run: python -m pytest backend/tests/ -q
Must stay green. Commit when done.
```
