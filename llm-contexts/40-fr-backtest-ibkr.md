# Context Doc 40 — FR-BT: Backtesting with IBKR Historical Data

**Feature:** Backtesting — replay the scanner on a past date using historical IBKR data
**Status:** New requirement — not yet dispatched
**Priority:** Medium — requires IB Gateway running locally

---

## 1. What this feature does

Adds a "Backtest mode" to the existing screener. The user picks a past date in Step 1. The scanner runs exactly as it does today, but `fetch_candles()` and `fetch_option_chain()` are redirected to IBKR historical data instead of Tradier live data. Scan results are labelled with the backtest date and saved separately from the live scan. No frontend changes to Steps 2–7 — the same screener flow is reused.

---

## 2. Cost and infrastructure

| Component | Cost | Notes |
|---|---|---|
| **IB Gateway** | Free | Headless version of TWS. Runs locally. Comes with any IBKR account. Download: https://www.interactivebrokers.com/en/trading/ibgateway.php |
| **ib_insync** | Free, open source | `pip install ib_insync`. Python wrapper for TWS API. Far easier than official `ibapi`. |
| **Historical data from IBKR** | Included with live account | Daily OHLCV and options bars (bid/ask/mid) ~3 years back for liquid US stocks. Pacing limits: 60 requests per 10 minutes. |
| **Tiingo (alternative for stock candles)** | Free tier: EOD data back to 1962, 500 req/hour. Paid: $10/month for intraday. | Only needed if IBKR data is insufficient or IB Gateway is not running. |

**No new paid subscriptions are required** if you use IBKR exclusively. The only constraint is that IB Gateway must be running (logged in) when backtests execute.

---

## 3. Pre-condition

IB Gateway must be installed and running locally on port 4002 (paper) or 7497 (live — use paper for backtesting).

```bash
# Test connection
python -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',4002,clientId=99); print(ib.isConnected())"
```

---

## 4. Architecture

### New files to create

| File | Purpose |
|---|---|
| `backend/app/data/ibkr.py` | IBKR data adapter — `fetch_candles_ibkr(symbol, date)` + `fetch_chain_ibkr(symbol, date, right)` |
| `backend/app/routers/backtest.py` | `POST /api/backtest` endpoint — accepts date + universe, runs scan with IBKR data |
| `backend/tests/test_backtest.py` | Tests with mocked ib_insync calls |

### No changes to existing files except

- `backend/app/main.py` — register the new `/api/backtest` router
- `backend/requirements.txt` — add `ib_insync>=0.9`

---

## 5. Data adapter spec (`backend/app/data/ibkr.py`)

### `fetch_candles_ibkr(symbol: str, as_of_date: date) -> list[dict]`

Returns the same shape as `fetch_candles()` (list of `{"time", "open", "high", "low", "close", "volume"}`), covering 60 trading days ending on `as_of_date`.

```python
from ib_insync import IB, Stock, util
from datetime import date

def fetch_candles_ibkr(symbol: str, as_of_date: date) -> list[dict]:
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=10, timeout=10)
    contract = Stock(symbol, 'SMART', 'USD')
    ib.qualifyContracts(contract)
    end = as_of_date.strftime('%Y%m%d 23:59:59')
    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end,
        durationStr='3 M',
        barSizeSetting='1 day',
        whatToShow='TRADES',
        useRTH=True,
    )
    ib.disconnect()
    return [
        {"time": b.date.strftime('%Y-%m-%d'), "open": b.open, "high": b.high,
         "low": b.low, "close": b.close, "volume": int(b.volume)}
        for b in bars
    ]
```

### `fetch_chain_ibkr(symbol: str, as_of_date: date, right: str) -> list[dict]`

Reconstructs the options chain for `as_of_date`. Strategy:
1. Get valid expirations and strikes from `reqSecDefOptParams` (gives today's grid — safe assumption: standard expiry grids don't change for liquid stocks).
2. For each contract in the grid that had a DTE between 14 and 60 days from `as_of_date`, request a 1-day historical bar ending on `as_of_date`.
3. Filter to contracts that had non-zero volume that day.
4. Return same shape as `fetch_option_chain()`.

Pacing: batch requests; sleep 0.4s between each to stay within IBKR's 60 req/10 min limit.

```python
def fetch_chain_ibkr(symbol: str, as_of_date: date, right: str = 'C') -> list[dict]:
    # Returns list matching fetch_option_chain() shape:
    # [{"strike", "expiry", "price", "bid", "ask", "delta", "theta",
    #   "ivRank", "dte", "right", "volume", "spread"}]
    ...
```

**Limitation:** Delta and theta on historical bars must be approximated with Black-Scholes since IBKR does not return historical greeks in bar data. The existing `calibrate_heston()` already handles this.

---

## 6. Endpoint spec (`backend/app/routers/backtest.py`)

### `POST /api/backtest`

```python
class BacktestRequest(BaseModel):
    universe:  list[str]
    direction: Direction
    horizon:   Horizon
    date:      str          # YYYY-MM-DD — the simulation date
    overrides: dict = {}

class BacktestResult(BaseModel):
    scan_id:   str
    date:      str
    candidates: list[TradeCardData]
    rejected:   list[RejectedCandidate]
```

Implementation: identical to `POST /api/scan` but:
- Replace `fetch_candles(symbol)` with `fetch_candles_ibkr(symbol, backtest_date)`
- Replace `fetch_option_chain(symbol)` with `fetch_chain_ibkr(symbol, backtest_date)`
- Replace `fetch_price(symbol)` with the closing price on `backtest_date` from IBKR candles
- Do NOT write to the `scan_sessions` DB table (backtest results are separate)
- Tag `scan_id` with `BT-{date}-{uuid4()[:8]}`

### Error handling

- If IB Gateway is not running: return HTTP 503 with `{"detail": "IB Gateway not reachable on port 4002. Start IB Gateway first."}`
- If IBKR has no data for the date (weekend, holiday, too old): return HTTP 422 with reason

---

## 7. Acceptance criteria

- `POST /api/backtest` with `date=2024-06-15` returns candidates using historical data from that date.
- Returns HTTP 503 with a clear message if IB Gateway is not running.
- Does not overwrite the live scan session in the DB.
- `pytest backend/tests/ -v` — all existing tests pass; new tests mock ib_insync and cover the happy path + 503 case.
- No changes to existing scan logic, scoring, or schema.

---

## 8. Frontend (not in scope for this workstream)

The backtest endpoint exists as a raw API call in this workstream. A future workstream adds:
- A "Backtest" toggle in Step 1 with a date picker
- The Step 7 result labelled "BACKTEST — 2024-06-15"
- A backtest history list (covered by FR-HIST)

---

## 9. Hard rules

- Do not modify `app/routers/scan.py` or any existing data adapter.
- `ib_insync` connection must be opened and closed per request — do not hold a persistent connection.
- Pacing sleep (0.4s between option bar requests) is mandatory to avoid IBKR pacing violations.
- Paper trading port (4002) only — never connect to live port (7496) from the backend.
