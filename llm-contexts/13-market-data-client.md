# LLM Context — Market Data Client (Workstream 13)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates two new files (`backend/app/data/__init__.py`, `backend/app/data/market.py`) and modifies `backend/requirements.txt`. It does not touch `frontend/`, any existing router, any fixture, or any schema file.

**Goal:**
Build a thin market-data client that later workstreams (WS-20, WS-22, WS-23) will import. It wraps `yfinance` to fetch OHLCV candles, current price, and option chain data. All functions return plain dicts or typed dicts that match the existing Pydantic schemas already defined in `backend/app/schemas/__init__.py`.

**What NOT to touch:**
- Any file under `frontend/`
- Any existing router (`backend/app/routers/`)
- Any existing fixture (`backend/app/fixtures/`)
- `backend/app/schemas/__init__.py` — read-only
- `backend/app/main.py` — read-only
- Any Alembic migration file

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/data/__init__.py` | **Create** | Empty package init |
| `backend/app/data/market.py` | **Create** | `fetch_candles`, `fetch_price`, `fetch_option_chain` |
| `backend/requirements.txt` | **Modify** | Add `yfinance==0.2.54` |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `backend/app/schemas/__init__.py` | `Candle` and `OptionContract` schemas — return dicts must match these shapes |
| `backend/app/fixtures/candles.py` | Understand candle dict shape (time, open, high, low, close, volume) |
| `backend/app/fixtures/contracts.py` | Understand option contract dict shape |

---

## Section 4 — Implementation

### 4.1 `backend/app/data/__init__.py`

```python
# empty
```

### 4.2 `backend/app/data/market.py`

```python
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

import yfinance as yf


def fetch_candles(symbol: str, bars: int = 120) -> list[dict]:
    """
    Returns up to `bars` daily OHLCV bars for `symbol`, newest last.
    Each dict: {time: str (YYYY-MM-DD), open, high, low, close: float, volume: int}
    Returns [] on any error (unknown symbol, network failure, etc.).
    """
    try:
        ticker = yf.Ticker(symbol)
        # Fetch ~6 months to guarantee 120 trading days
        hist = ticker.history(period="6mo", interval="1d", auto_adjust=True)
        if hist.empty:
            return []
        rows = []
        for ts, row in hist.tail(bars).iterrows():
            rows.append({
                "time":   ts.strftime("%Y-%m-%d"),
                "open":   round(float(row["Open"]),   2),
                "high":   round(float(row["High"]),   2),
                "low":    round(float(row["Low"]),    2),
                "close":  round(float(row["Close"]),  2),
                "volume": int(row["Volume"]),
            })
        return rows
    except Exception:
        return []


def fetch_price(symbol: str) -> Optional[float]:
    """
    Returns the latest closing price for `symbol`, or None on failure.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d", interval="1d", auto_adjust=True)
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        return None


def fetch_option_chain(symbol: str, expiry: Optional[str] = None) -> list[dict]:
    """
    Returns call contracts for `symbol`.
    If `expiry` is given (YYYY-MM-DD), fetches that expiry only.
    Otherwise fetches the nearest available expiry.
    Each dict matches the OptionContract schema fields:
      id, symbol, strike, expiry, right, dte, dteTotal,
      price, delta, theta, ivRank, ivPercentile, spread, volume, score
    `ivRank`, `ivPercentile`, `delta`, `theta`, `score` default to 0 when unavailable
    (yfinance does not provide greeks directly; downstream scoring fills them).
    Returns [] on any error.
    """
    try:
        ticker = yf.Ticker(symbol)
        exps = ticker.options
        if not exps:
            return []

        target_exp = expiry if expiry in exps else exps[0]
        chain = ticker.option_chain(target_exp)
        calls = chain.calls

        today = date.today()
        try:
            exp_date = date.fromisoformat(target_exp)
        except ValueError:
            return []
        dte = max(0, (exp_date - today).days)

        result = []
        for _, row in calls.iterrows():
            strike = float(row.get("strike", 0))
            bid    = float(row.get("bid", 0) or 0)
            ask    = float(row.get("ask", 0) or 0)
            mid    = round((bid + ask) / 2, 2) if ask > 0 else 0.0
            spread = round(ask - bid, 2) if ask > 0 else 0.0
            volume = int(row.get("volume", 0) or 0)
            oi     = int(row.get("openInterest", 0) or 0)
            iv     = float(row.get("impliedVolatility", 0) or 0)

            if ask <= 0 or math.isnan(ask):
                continue  # hard-reject: no valid ask

            result.append({
                "id":           f"{symbol}|{int(strike)}|{target_exp}|C",
                "symbol":       symbol,
                "strike":       int(strike),
                "expiry":       target_exp,
                "right":        "C",
                "dte":          dte,
                "dteTotal":     dte,   # same as dte for fresh fetch; scorer may update
                "price":        mid,
                "delta":        0.0,   # requires BS/Heston — filled by WS-14/WS-21
                "theta":        0.0,   # requires BS/Heston — filled by WS-14/WS-21
                "ivRank":       int(round(iv * 100)),  # raw IV as proxy until real IV rank available
                "ivPercentile": 0,     # not available from yfinance
                "spread":       spread,
                "volume":       volume,
                "score":        0,     # filled by contract validator (WS-22)
            })
        return result
    except Exception:
        return []
```

### 4.3 `backend/requirements.txt` — add one line

Add after the existing `python-multipart` line:
```
yfinance==0.2.54
```

---

## Section 5 — Pydantic schema reference (read-only, do not modify)

```python
# Relevant shapes from backend/app/schemas/__init__.py

class Candle(BaseModel):
    time:   str    # YYYY-MM-DD
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int

class OptionContract(BaseModel):
    id:           str
    symbol:       str
    strike:       int
    expiry:       str
    right:        OptionRight   # 'C' | 'P'
    dte:          int
    dteTotal:     int
    price:        float
    delta:        float
    theta:        float
    ivRank:       int
    ivPercentile: int
    spread:       float
    volume:       int
    score:        int
```

The dicts returned by `market.py` must be structurally compatible with these models.
Fields that yfinance cannot provide (`delta`, `theta`, `ivPercentile`, `score`) default to `0` and are filled by downstream workstreams.

---

## Section 6 — Task spec

### Acceptance criteria

1. `fetch_candles('AAPL', 120)` returns a list of dicts, each with keys `time`, `open`, `high`, `low`, `close`, `volume`. Length is between 1 and 120.
2. `fetch_candles('XXXXINVALID', 120)` returns `[]` without raising.
3. `fetch_price('AAPL')` returns a positive float.
4. `fetch_price('XXXXINVALID')` returns `None` without raising.
5. `fetch_option_chain('AAPL')` returns a non-empty list; each item has an `id` in the format `AAPL|<strike>|<expiry>|C`.
6. `fetch_option_chain('XXXXINVALID')` returns `[]` without raising.
7. `python -c "from app.data.market import fetch_candles, fetch_price, fetch_option_chain; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
pip install yfinance==0.2.54
python -c "
from app.data.market import fetch_candles, fetch_price, fetch_option_chain
c = fetch_candles('AAPL', 5)
print('candles ok:', len(c), 'bars, first:', c[0] if c else 'empty')
p = fetch_price('AAPL')
print('price ok:', p)
chain = fetch_option_chain('AAPL')
print('chain ok:', len(chain), 'calls, first id:', chain[0]['id'] if chain else 'empty')
bad = fetch_candles('XXXXINVALID')
print('bad symbol ok:', bad)
"
```

---

## Section 7 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify any existing router, fixture, or schema file.
3. Do NOT add a database layer. All functions are stateless HTTP/network calls.
4. Every function must be safe to call: catch all exceptions and return `[]` or `None`.
5. All field names in returned dicts must be camelCase — matching the Pydantic schema field names exactly.
6. Do NOT add `yfinance` to any other requirements file or `pyproject.toml`.
7. `yfinance==0.2.54` is the pinned version. Do not use a floating version specifier.

---

## Section 8 — Dev workflow

```bash
cd backend
pip install yfinance==0.2.54
python -c "from app.data.market import fetch_candles, fetch_price, fetch_option_chain; print('OK')"
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-13-market-data.

Read `llm-contexts/13-market-data-client.md` fully before writing any code.
It is your single source of truth.

You are implementing the market data client for the Bamendjou options screener
(FastAPI / Python 3.11 / yfinance).

Your owned files:
  - backend/app/data/__init__.py          (CREATE — empty)
  - backend/app/data/market.py            (CREATE)
  - backend/requirements.txt              (MODIFY — add yfinance==0.2.54)

Do not modify any file outside this list.

Task: Create fetch_candles(), fetch_price(), and fetch_option_chain() functions
that wrap yfinance. All functions must catch exceptions and return [] or None
on any error. Return dicts whose field names match the Pydantic schemas in
backend/app/schemas/__init__.py.

After implementation run the verification block in Section 6.
Commit after all checks pass.
```
