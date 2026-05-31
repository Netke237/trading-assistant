# Context Doc 36 — Regime Depth

**Workstream:** Expand `GET /api/regime` from VIX-only to multi-metric (SPX, NDX, VIX)
**Conflict class:** Zero conflict — modifies one backend file only

---

## 1. Mission

`GET /api/regime` currently returns a single metric (VIX) and derives `overall` from VIX alone. The PRD (FR-10) and the frontend Step 3 display expect a metric grid with SPX trend, NDX trend, and VIX at minimum. This workstream expands the regime router to fetch SPX and NDX prices vs. their 200-day EMA, add them as `RegimeMetric` entries, and compute `overall` as the worst of the three signals. Do not touch schemas, the data layer, or any other router.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `backend/app/routers/regime.py` | Modify | Fetch SPX + NDX candles, compute 200 EMA, add metrics, derive overall |

---

## 3. Read-only references

| File | Reason |
|---|---|
| `backend/app/data/market.py` | `fetch_candles(symbol, bars=120) -> list[dict]` and `fetch_price(symbol) -> float \| None` |
| `backend/app/schemas/__init__.py` | `MarketRegime`, `RegimeMetric` — their exact field names |

---

## 4. Integration constraints

**Schemas (do not modify):**
```python
class RegimeMetric(BaseModel):
    label: str
    value: str
    status: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
    trend: Optional[Literal['up', 'flat', 'down']] = None

class MarketRegime(BaseModel):
    overall: Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
    headline: str
    metrics: list[RegimeMetric]
```

**fetch_candles output:**
```python
# Each dict: {"time": "YYYY-MM-DD", "open": float, "high": float, "low": float, "close": float, "volume": int}
# Returns [] on error — handle gracefully
# bars=200 is safe (returns up to 200 trading days)
```

**Tradier symbols for indices:**
- SPX: `"SPX"` (Tradier uses `SPX` not `^GSPC`)
- NDX: `"NDX"` (Tradier uses `NDX` not `^NDX`)
- VIX: `"VIX"` (already working)

---

## 5. Task spec

**EMA computation:**
Implement a simple EMA with `period=200`. Only the final value matters (the current EMA).
```python
def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period  # seed with SMA of first `period` bars
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema
```

**SPX/NDX status rules:**
- Price > EMA → `'PASS'`, trend `'up'`
- Price between 0.97×EMA and EMA (within 3% below) → `'CAUTION'`, trend `'flat'`
- Price < 0.97×EMA → `'REJECT'`, trend `'down'`
- Data unavailable → `'PENDING'`, trend `None`

**VIX status rules (existing logic — keep):**
- VIX < 20 → `'PASS'`, trend `'down'`
- VIX 20–30 → `'CAUTION'`, trend `'flat'`
- VIX > 30 → `'REJECT'`, trend `'up'`

**`overall` logic:**
Worst of SPX status, NDX status, VIX status.
Priority order (worst first): `REJECT > CAUTION > PENDING > PASS`.
```python
_PRIORITY = {"REJECT": 0, "CAUTION": 1, "PENDING": 2, "NO_DATA": 2, "PASS": 3}
overall = min([spx_status, ndx_status, vix_status], key=lambda s: _PRIORITY.get(s, 2))
```

**Headline:** Compose a plain-English sentence summarizing the signals.
Example: `"SPX above 200 EMA · NDX above 200 EMA · VIX 14.8 — PASS environment"`
Or on CAUTION: `"NDX near 200 EMA — monitor closely"`

**Metric labels (match frontend mock labels exactly):**
```
"SPX trend (200 EMA)"
"NDX trend (200 EMA)"
"VIX"
```

**`value` field examples:**
- SPX/NDX: `"Above"` / `"Near"` / `"Below"` (not the actual price — keeps it readable)
- VIX: the numeric value as string, e.g. `"14.8"`

**Acceptance criteria:**
- `GET /api/regime` returns at least 3 metrics: SPX, NDX, VIX.
- `overall` is `REJECT` if any of the three is `REJECT`.
- If SPX candle fetch fails, SPX metric has `status: "PENDING"` and overall is computed from available signals only.
- If all three fetches fail, returns CAUTION with an empty or partial metrics list (never crashes).
- Existing VIX-only test in `backend/tests/` must still pass or be updated to match the new 3-metric response.
- `pytest backend/tests/ -q` stays green.

**Performance:** `fetch_candles` for two symbols + `fetch_price` for VIX = 3 sequential HTTP calls. Acceptable for now. Do not add concurrency.

---

## 6. Hard rules

- Do not import numpy, pandas, or any new package — use only stdlib `statistics` or hand-rolled EMA.
- Do not modify `fetch_candles` or `fetch_price`.
- The `PENDING` status is valid when data is unavailable — use it rather than raising.
- `overall` must never be `NO_DATA` — only `PASS | CAUTION | REJECT | PENDING`.
- No new files — keep all logic inside `regime.py`.

---

## 7. Dev workflow

```bash
cd backend
python -m pytest tests/ -q   # check if any existing regime test needs updating

# Smoke test (requires Tradier API token in .env)
uvicorn app.main:app --reload
curl http://localhost:8000/api/regime | python -m json.tool
# Expect: overall, headline, and metrics array with 3 items
```

---

## 8. Existing test to check

Search `backend/tests/` for any test referencing `/api/regime` or `get_regime`. If the test asserts `len(metrics) == 1`, update it to `len(metrics) == 3` (or `>= 1` if partial). Do not delete regime tests.

---

## 9. Copy/paste prompt

```
Read `llm-contexts/36-regime-depth.md` fully before writing any code. It is your single source of truth.

You are expanding the market regime endpoint for the Bamendjou options screener (FastAPI, Python 3.11).

Your owned files:
- backend/app/routers/regime.py  (MODIFY)

Do not modify any file outside this list.

Task: Expand GET /api/regime from VIX-only to a 3-metric response (SPX trend vs 200 EMA, NDX trend vs 200 EMA, VIX). Compute `overall` as the worst of the three signals. Handle missing data gracefully — return PENDING for unavailable metrics, never crash.

After editing, run: python -m pytest backend/tests/ -q
Fix any regime test that breaks due to the new metric count. Commit when done.
```
