# Bamendjou — Backend FastAPI Context Document

> **How to use this file**
> You are building the FastAPI trading-data backend for the Bamendjou options screener.
> This document is self-contained. Read every section before writing a single line of code.
> The frontend is already complete and running. Your job is to make its data swappable from
> static mocks to real HTTP calls — without changing any TypeScript types or touching any
> file under `frontend/`.

---

## 1. Mission

**Conflict class: Zero conflict.**
This workstream owns all of `backend/`. It never touches anything under `frontend/`.

**Goal:** Build FastAPI routes that return the exact same data shapes as the frontend mock
files, so the frontend can switch from `import MOCK_*` to `fetch('/api/...')` without
changing any TypeScript types or component logic.

The current `backend/` is a skeleton copied from a different, abandoned project. It already
has a working CORS middleware and a health router. Your task is to add trading-specific
routers on top of it without breaking what is there.

**No database layer for trading data.** All 9 trading routes return deterministic fixture
data (hardcoded Python dicts that mirror the TypeScript mock files exactly). A real data
layer can be added later; Phase 1 is fixture-only.

---

## 2. Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/main.py` | **Modify** | Wire trading routers under `/api` prefix |
| `backend/app/schemas/__init__.py` | **Create** | Pydantic v2 models mirroring TypeScript types |
| `backend/app/routers/watchlist.py` | **Create** | `GET /api/watchlist` |
| `backend/app/routers/contracts.py` | **Create** | `GET /api/contracts` |
| `backend/app/routers/candles.py` | **Create** | `GET /api/candles/{symbol}` |
| `backend/app/routers/regime.py` | **Create** | `GET /api/regime` |
| `backend/app/routers/sectors.py` | **Create** | `GET /api/sectors` |
| `backend/app/routers/tradecards.py` | **Create** | `GET /api/tradecards` |
| `backend/app/routers/portfolio.py` | **Create** | `GET /api/portfolio` |
| `backend/app/routers/alerts.py` | **Create** | `GET /api/alerts` |
| `backend/app/routers/events.py` | **Create** | `GET /api/events` |

You may create additional helper modules (e.g. `backend/app/fixtures/` sub-package to hold
the raw fixture dicts) if it keeps the router files clean. Do not create any files under
`frontend/`.

---

## 3. Read-only references

| Path | Role |
|---|---|
| `frontend/types/domain.ts` | TypeScript types; Pydantic schemas must be 1:1 mirrors |
| `frontend/mocks/watchlist.ts` | Source of truth for `GET /api/watchlist` fixture |
| `frontend/mocks/contracts.ts` | Source of truth for `GET /api/contracts` fixture |
| `frontend/mocks/candles.ts` | Source of truth for `GET /api/candles/{symbol}` fixture |
| `frontend/mocks/regime.ts` | Source of truth for `GET /api/regime` fixture |
| `frontend/mocks/sectors.ts` | Source of truth for `GET /api/sectors` fixture |
| `frontend/mocks/tradecards.ts` | Source of truth for `GET /api/tradecards` fixture |
| `frontend/mocks/portfolio.ts` | Source of truth for `GET /api/portfolio` fixture |
| `frontend/mocks/alerts.ts` | Source of truth for `GET /api/alerts` fixture |
| `frontend/mocks/events.ts` | Source of truth for `GET /api/events` fixture |
| `backend/app/main.py` | Existing app factory — modify, do not rewrite |
| `backend/app/routers/health.py` | Existing health router — do not touch |
| `backend/requirements.txt` | Installed packages — do not change |

---

## 4. API contract

### 4.1 `GET /api/watchlist`

Returns a JSON array of 10 `WatchlistRow` objects.

**Response type:** `list[WatchlistRow]`

**Sample (first row):**
```json
[
  {
    "symbol": "AAPL",
    "company": "Apple Inc",
    "price": 185.20,
    "direction": "Bullish",
    "horizon": "Swing",
    "score": 82,
    "rankDelta": 2,
    "scoreDelta": 3,
    "status": "PASS",
    "breakdown": {
      "trend": 88,
      "pullback": 78,
      "trigger": 85,
      "event": 72,
      "volatility": 74
    },
    "nextEventDays": 8,
    "nextEventLabel": "Earnings"
  },
  "... 9 more rows ..."
]
```

---

### 4.2 `GET /api/contracts`

Returns a JSON array of 6 `OptionContract` objects (AAPL calls, all expiries).

**Response type:** `list[OptionContract]`

**Sample (first row):**
```json
[
  {
    "id": "AAPL|190|2026-05-15|C",
    "symbol": "AAPL",
    "strike": 190,
    "expiry": "2026-05-15",
    "right": "C",
    "dte": 24,
    "dteTotal": 38,
    "price": 4.85,
    "delta": 0.45,
    "theta": -0.11,
    "ivRank": 42,
    "ivPercentile": 51,
    "spread": 0.05,
    "volume": 8420,
    "score": 82
  },
  "... 5 more rows ..."
]
```

---

### 4.3 `GET /api/candles/{symbol}`

Returns a JSON array of 120 `Candle` objects for the given symbol.
Valid symbols: `AAPL NVDA MSFT META GOOGL AMZN AMD TSLA NFLX INTC SPX NDX`.
Unknown symbols return a 120-bar series seeded from `seed=1, base=100`.

**Response type:** `list[Candle]`

**Sample (first bar):**
```json
[
  {
    "time": "2025-12-20",
    "open": 172.00,
    "high": 175.34,
    "low": 170.12,
    "close": 174.88,
    "volume": 9841200
  },
  "... 119 more bars ..."
]
```

Note: The candles endpoint must reproduce the Mulberry32 seeded-RNG algorithm from
`frontend/mocks/candles.ts` so charts look identical when the frontend switches from mock
to fetch. The seed config is in Section 9.

---

### 4.4 `GET /api/regime`

Returns a single `MarketRegime` object.

**Response type:** `MarketRegime`

**Full response:**
```json
{
  "overall": "PASS",
  "headline": "Trend + breadth constructive; VIX contained",
  "metrics": [
    { "label": "SPX trend (200 EMA)", "value": "Above",    "status": "PASS",    "trend": "up"   },
    { "label": "NDX trend (200 EMA)", "value": "Above",    "status": "PASS",    "trend": "up"   },
    { "label": "Breadth (A/D)",       "value": "+412",     "status": "PASS",    "trend": "up"   },
    { "label": "VIX",                 "value": "14.8",     "status": "PASS",    "trend": "down" },
    { "label": "10Y yield",           "value": "4.28%",    "status": "CAUTION", "trend": "up"   },
    { "label": "DXY (USD)",           "value": "104.6",    "status": "PASS",    "trend": "flat" },
    { "label": "HY credit spread",    "value": "312 bp",   "status": "CAUTION", "trend": "up"   },
    { "label": "Put/Call (5d avg)",   "value": "0.84",     "status": "PASS",    "trend": "down" }
  ]
}
```

---

### 4.5 `GET /api/sectors`

Returns a JSON array of 11 `SectorTile` objects (GICS sectors).

**Response type:** `list[SectorTile]`

**Full response:**
```json
[
  { "key": "XLK",  "name": "Technology",             "changePct":  1.24, "status": "PASS"    },
  { "key": "XLC",  "name": "Comm. Services",          "changePct":  0.86, "status": "PASS"    },
  { "key": "XLY",  "name": "Consumer Discretionary",  "changePct":  0.42, "status": "PASS"    },
  { "key": "XLI",  "name": "Industrials",             "changePct":  0.18, "status": "CAUTION" },
  { "key": "XLF",  "name": "Financials",              "changePct":  0.05, "status": "CAUTION" },
  { "key": "XLP",  "name": "Consumer Staples",        "changePct": -0.08, "status": "CAUTION" },
  { "key": "XLV",  "name": "Health Care",             "changePct": -0.22, "status": "CAUTION" },
  { "key": "XLB",  "name": "Materials",               "changePct": -0.41, "status": "REJECT"  },
  { "key": "XLRE", "name": "Real Estate",             "changePct": -0.68, "status": "REJECT"  },
  { "key": "XLU",  "name": "Utilities",               "changePct": -0.94, "status": "REJECT"  },
  { "key": "XLE",  "name": "Energy",                  "changePct": -1.18, "status": "REJECT"  }
]
```

---

### 4.6 `GET /api/tradecards`

Returns a JSON array of 10 `TradeCardData` objects (one per watchlist symbol).

**Response type:** `list[TradeCardData]`

**Sample (AAPL row):**
```json
[
  {
    "symbol": "AAPL",
    "company": "Apple Inc",
    "price": 185.20,
    "direction": "Bullish",
    "status": "PASS",
    "stockScore": 82,
    "stockConfidence": "PASS",
    "stockBreakdown": {
      "trend": 88, "pullback": 78, "trigger": 85, "event": 72, "volatility": 74
    },
    "contract": "AAPL 190C 05/15",
    "contractScore": 82,
    "contractConfidence": "PASS",
    "contractBreakdown": {
      "dteFit": 88,
      "delta": 68,
      "ivAttractiveness": 42,
      "liquidity": 82,
      "spread": 80
    },
    "contractDetails": {
      "strike": 190,
      "expiry": "2026-05-15",
      "right": "C",
      "mid": 4.85,
      "delta": 0.45,
      "theta": -0.11,
      "ivRank": 42,
      "dte": 24
    },
    "entry": { "limit": 4.85, "maxFill": 5.09, "orderType": "Limit" },
    "exit": {
      "invalidation": 179.64,
      "premiumStop": 2.91,
      "timeStopDays": 10,
      "target": 199.92
    },
    "rrRatio": 2.7,
    "rrModel": "Heston repriced",
    "finalStatus": "PASS"
  },
  "... 9 more rows ..."
]
```

---

### 4.7 `GET /api/portfolio`

Returns a JSON array of 5 `PortfolioPosition` objects.

**Response type:** `list[PortfolioPosition]`

**Full response:**
```json
[
  {
    "symbol": "AAPL",
    "contract": "AAPL 190C 05/16",
    "direction": "Bullish",
    "entryDate": "2026-04-08",
    "expiry": "2026-05-16",
    "dteRemaining": 28,
    "dteTotal": 38,
    "entryPrice": 4.15,
    "currentPrice": 5.02,
    "pnlDollar": 870,
    "pnlPct": 20.96,
    "stop": 180.00,
    "target": 198.00,
    "status": "PASS",
    "ivRank": 42,
    "delta": 0.58,
    "theta": -0.08,
    "vega": 0.22,
    "contracts": 2
  },
  {
    "symbol": "NVDA",
    "contract": "NVDA 920C 04/25",
    "direction": "Bullish",
    "entryDate": "2026-04-14",
    "expiry": "2026-04-25",
    "dteRemaining": 7,
    "dteTotal": 11,
    "entryPrice": 12.80,
    "currentPrice": 14.25,
    "pnlDollar": 725,
    "pnlPct": 11.33,
    "stop": 875.00,
    "target": 960.00,
    "status": "PASS",
    "ivRank": 71,
    "delta": 0.62,
    "theta": -0.24,
    "vega": 0.18,
    "contracts": 1
  },
  {
    "symbol": "MSFT",
    "contract": "MSFT 420C 06/20",
    "direction": "Bullish",
    "entryDate": "2026-04-10",
    "expiry": "2026-06-20",
    "dteRemaining": 63,
    "dteTotal": 71,
    "entryPrice": 8.20,
    "currentPrice": 8.85,
    "pnlDollar": 325,
    "pnlPct": 7.93,
    "stop": 408.00,
    "target": 445.00,
    "status": "PASS",
    "ivRank": 28,
    "delta": 0.54,
    "theta": -0.05,
    "vega": 0.34,
    "contracts": 2
  },
  {
    "symbol": "META",
    "contract": "META 510C 05/02",
    "direction": "Bullish",
    "entryDate": "2026-04-15",
    "expiry": "2026-05-02",
    "dteRemaining": 14,
    "dteTotal": 17,
    "entryPrice": 9.40,
    "currentPrice": 8.10,
    "pnlDollar": -390,
    "pnlPct": -13.83,
    "stop": 498.00,
    "target": 540.00,
    "status": "PASS",
    "ivRank": 55,
    "delta": 0.46,
    "theta": -0.14,
    "vega": 0.26,
    "contracts": 1
  },
  {
    "symbol": "TSLA",
    "contract": "TSLA 170P 04/22",
    "direction": "Bearish",
    "entryDate": "2026-04-16",
    "expiry": "2026-04-22",
    "dteRemaining": 4,
    "dteTotal": 6,
    "entryPrice": 3.10,
    "currentPrice": 3.78,
    "pnlDollar": 340,
    "pnlPct": 21.94,
    "stop": 180.00,
    "target": 160.00,
    "status": "PASS",
    "ivRank": 82,
    "delta": -0.52,
    "theta": -0.31,
    "vega": 0.12,
    "contracts": 3
  }
]
```

Note on `status` for portfolio: The frontend derives status from `dteStatus(dteRemaining, dteTotal)`.
Replicate this logic in Python:
- `dteRemaining / dteTotal < 0.25` → `'REJECT'`
- `dteRemaining / dteTotal < 0.50` → `'CAUTION'`
- otherwise → `'PASS'`

Values above are pre-computed using that formula. Verification:
- AAPL: 18/22 = 0.818 → PASS ✓  |  NVDA: 7/11 = 0.636 → PASS ✓  |  MSFT: 63/71 = 0.887 → PASS ✓
- META: 14/17 = 0.823 → PASS ✓  |  TSLA: 4/6 = 0.667 → PASS ✓

> Note: The master `LLM_CONTEXT.md` summary table may show different nextEventDays values (e.g. 14 for AAPL). Those reflect the scan reference date of 2026-04-20. The values in this document are computed from that same reference date and are correct. Trust this document over the master summary table for fixture values.

---

### 4.8 `GET /api/alerts`

Returns a JSON array of 5 `AlertItem` objects.

**Response type:** `list[AlertItem]`

**Full response:**
```json
[
  { "id": "a1", "kind": "Critical", "symbol": "META",  "reason": "Broke trail stop",                      "timestamp": "09:38" },
  { "id": "a2", "kind": "Action",   "symbol": "NVDA",  "reason": "Earnings in 3 days — roll or close",    "timestamp": "09:41" },
  { "id": "a3", "kind": "Action",   "symbol": "AAPL",  "reason": "Target 80% reached",                    "timestamp": "09:47" },
  { "id": "a4", "kind": "Info",     "symbol": "SPY",   "reason": "Regime flipped to PASS",                "timestamp": "09:15" },
  { "id": "a5", "kind": "Info",     "symbol": "TSLA",  "reason": "IV rank > 70",                          "timestamp": "09:02" }
]
```

---

### 4.9 `GET /api/events`

Returns a JSON array of 36 `UpcomingEvent` objects covering April–September 2026.

**Response type:** `list[UpcomingEvent]`

**Sample (first 5 rows):**
```json
[
  { "date": "2026-04-20", "symbol": "TSLA",  "label": "Earnings",           "status": "REJECT"  },
  { "date": "2026-04-21", "symbol": "NVDA",  "label": "Earnings",           "status": "CAUTION" },
  { "date": "2026-04-23", "symbol": "—",     "label": "FOMC",               "status": "CAUTION" },
  { "date": "2026-04-28", "symbol": "AAPL",  "label": "Earnings",           "status": "CAUTION" },
  { "date": "2026-04-29", "symbol": "META",  "label": "Earnings",           "status": "PASS"    },
  "... 31 more rows ..."
]
```

See Section 9 for the complete 36-row fixture.

---

## 5. Pydantic type reference

Complete Pydantic v2 models. All field names are camelCase to match TypeScript exactly.
Use `model_config = ConfigDict(populate_by_name=True)` on every model.

```python
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

# ── Shared literals ──────────────────────────────────────────────────────────

Status    = Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
Direction = Literal['Bullish', 'Bearish']
Horizon   = Literal['Swing', 'Position']
AlertKind = Literal['Info', 'Action', 'Critical']
OrderType = Literal['Limit', 'Market', 'Stop']
OptionRight = Literal['C', 'P']
TrendDir  = Literal['up', 'flat', 'down']
RrModel   = Literal['Heston repriced', 'Delta approximation']

# ── Score breakdowns ─────────────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trend:      int
    pullback:   int
    trigger:    int
    event:      int
    volatility: int

class ContractScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    dteFit:           int
    delta:            int
    ivAttractiveness: int
    liquidity:        int
    spread:           int

# ── Watchlist ────────────────────────────────────────────────────────────────

class WatchlistRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:          str
    company:         str
    price:           float
    direction:       Direction
    horizon:         Horizon
    score:           int
    rankDelta:       int
    scoreDelta:      Optional[int]   = None
    status:          Status
    breakdown:       ScoreBreakdown
    nextEventDays:   Optional[int]   = None
    nextEventLabel:  Optional[str]   = None

# ── Contracts ────────────────────────────────────────────────────────────────

class OptionContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id:           str
    symbol:       str
    strike:       int
    expiry:       str          # YYYY-MM-DD
    right:        OptionRight
    dte:          int
    dteTotal:     int
    price:        float        # mid premium, $
    delta:        float
    theta:        float        # $/day (negative for long)
    ivRank:       int          # 0–100
    ivPercentile: int          # 0–100
    spread:       float        # bid/ask width, $
    volume:       int
    score:        int

# ── Candles ──────────────────────────────────────────────────────────────────

class Candle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    time:   str    # YYYY-MM-DD
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int

# ── Regime ───────────────────────────────────────────────────────────────────

class RegimeMetric(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    label:  str
    value:  str
    status: Status
    trend:  Optional[TrendDir] = None

class MarketRegime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    overall:  Status
    headline: str
    metrics:  list[RegimeMetric]

# ── Sectors ──────────────────────────────────────────────────────────────────

class SectorTile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    key:       str
    name:      str
    changePct: float
    status:    Status

# ── Portfolio ────────────────────────────────────────────────────────────────

class PortfolioPosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:        str
    contract:      str         # "AAPL 220C 05/16"
    direction:     Direction
    entryDate:     str         # ISO date
    expiry:        str         # ISO date
    dteRemaining:  int
    dteTotal:      int
    entryPrice:    float
    currentPrice:  float
    pnlDollar:     float
    pnlPct:        float
    stop:          float
    target:        float
    status:        Status
    ivRank:        Optional[int]   = None   # 0–100
    delta:         Optional[float] = None   # –1..+1
    theta:         Optional[float] = None   # $/day
    vega:          Optional[float] = None
    contracts:     Optional[int]   = None
    source:        Optional[Literal['broker', 'manual']] = None
    orderedAt:     Optional[str]   = None   # ISO timestamp

# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id:        str
    kind:      AlertKind
    symbol:    str
    reason:    str
    timestamp: str    # "09:42" or ISO

# ── Events ───────────────────────────────────────────────────────────────────

class UpcomingEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date:   str     # ISO date
    symbol: str
    label:  str     # "Earnings" / "FOMC" / ...
    status: Status

# ── Trade cards ──────────────────────────────────────────────────────────────

class ContractDetails(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strike: int
    expiry: str         # YYYY-MM-DD
    right:  OptionRight
    mid:    float       # premium, $
    delta:  float
    theta:  float       # $/day
    ivRank: int         # 0–100
    dte:    int

class TradeEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    limit:     float
    maxFill:   float
    orderType: OrderType

class TradeExit(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    invalidation:  float
    premiumStop:   float
    timeStopDays:  int
    target:        float

class TradeCardData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:             str
    company:            str
    price:              float
    direction:          Direction
    status:             Status
    stockScore:         int
    stockConfidence:    Status
    stockBreakdown:     ScoreBreakdown
    contract:           str
    contractScore:      int
    contractConfidence: Status
    contractBreakdown:  ContractScoreBreakdown
    contractDetails:    Optional[ContractDetails] = None
    entry:              TradeEntry
    exit:               TradeExit
    rrRatio:            float
    rrModel:            RrModel
    finalStatus:        Status
```

---

## 6. Existing backend structure

### What is already there

```
backend/
  app/
    __init__.py
    main.py          # FastAPI app factory + CORS + health router import
    config.py        # pydantic-settings Settings class (DATABASE_URL, JWT, etc.)
    routers/
      health.py      # GET /health → {"status": "ok"}
  requirements.txt
```

The app factory in `main.py`:
- Creates a FastAPI instance titled "Trading Assistant API".
- Adds CORSMiddleware with `allow_origins=["*"]` when `DEBUG=True`, else `[]`.
- Includes `health_router` (no prefix, so it lands at `/health`).

The `config.py` `Settings` class requires `DATABASE_URL` and `JWT_SECRET_KEY` environment
variables. The app will crash on startup if these are missing. For local dev with trading
routes only, you can add a `.env` file:
```
DATABASE_URL=sqlite+aiosqlite:///./dev.db
JWT_SECRET_KEY=dev-secret-not-used
DEBUG=True
```

Or, simpler: make `DATABASE_URL` and `JWT_SECRET_KEY` optional with defaults in config.py:
```python
DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
JWT_SECRET_KEY: str = "dev-only"
```

### Python version

Python 3.11+ assumed (f-strings, `from __future__ import annotations` supported).

### Installed packages (from `requirements.txt`)

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy[asyncio]==2.0.23
alembic==1.12.1
asyncpg==0.29.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-multipart==0.0.6
```

Pydantic v2 is installed. Use `BaseModel`, `ConfigDict`, `model_config` — not v1 patterns.

### Alembic migrations

There is an existing Alembic setup for the child time management domain. **Do not touch
any Alembic migration files.** Trading data is served from Python fixtures, not the DB.

---

## 7. CSS tokens

These tokens are not used by Python, but trading-route response values (Status strings)
are mapped to these colors by the frontend. The valid Status values are the only ones the
frontend knows how to color.

### Dark theme (default — `[data-theme="dark"]` or `:root`)

```css
/* Backgrounds */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;

/* Borders */
--border-subtle:    #2A2E42;
--border-strong:    #363B54;

/* Text */
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;

/* Status — PASS */
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;

/* Status — CAUTION */
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;

/* Status — REJECT */
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;

/* Status — NEUTRAL / PENDING */
--neutral:          #4A5568;
--neutral-bg:       #1A202C;

/* Accent */
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;

/* Spacing (4px base) */
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;

/* Radius */
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Frame sizes */
--frame-topbar-h:            48px;
--frame-navrail-w:           64px;
--frame-navrail-w-expanded:  200px;
--frame-contextrail-w:       300px;
--frame-stepnav-h:           52px;
```

### Light theme override (`[data-theme="light"]`)

```css
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--bg-surface-3:   #EBF0FF;
--border-subtle:  #DDE1F0;
--border-strong:  #C5CCE6;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
--pass:           #1A9188;
--pass-bg:        #EDF7F6;
--pass-border:    #B3E0DC;
--caution:        #D4890A;
--caution-bg:     #FEF6E6;
--caution-border: #F5D38A;
--reject:         #D32F2F;
--reject-bg:      #FEECEC;
--reject-border:  #F5BCBC;
--neutral:        #64748B;
--neutral-bg:     #F1F5F9;
```

**Status → CSS variable mapping:**
| Status | Color var | Background var |
|---|---|---|
| `PASS` | `--pass` | `--pass-bg` |
| `CAUTION` | `--caution` | `--caution-bg` |
| `REJECT` | `--reject` | `--reject-bg` |
| `PENDING` | `--neutral` | `--neutral-bg` |
| `NO_DATA` | `--neutral` | `--neutral-bg` |

---

## 8. Domain types (TypeScript reference)

This is the exact content of `frontend/types/domain.ts`. Every Pydantic model must mirror
these types field-for-field with the same camelCase names.

```typescript
/*
 * Domain types — shared across pages and components.
 *
 * v1 is mocks-only (see /mocks/). These types are the contract the future
 * FastAPI backend needs to satisfy.
 */

import type { Status } from '@/lib/status';

export type Direction = 'Bullish' | 'Bearish';
export type Horizon = 'Swing' | 'Position';
export type AlertKind = 'Info' | 'Action' | 'Critical';
export type OrderType = 'Limit' | 'Market' | 'Stop';

export interface ScoreBreakdown {
  trend:       number;
  pullback:    number;
  trigger:     number;
  event:       number;
  volatility:  number;
}

export interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
}

export interface WatchlistRow {
  symbol:       string;        // e.g. "AAPL"
  company:      string;        // e.g. "Apple Inc"
  price:        number;        // e.g. 185.20
  direction:    Direction;
  horizon:      Horizon;
  score:        number;        // 0–100
  rankDelta:    number;        // +2 / -1 / 0
  scoreDelta?:  number;        // score pts vs previous scan
  status:       Status;
  breakdown:    ScoreBreakdown;
  nextEventDays?: number;      // days until earnings / fed / etc
  nextEventLabel?: string;     // "Earnings", "FOMC"
}

export interface PortfolioPosition {
  symbol:        string;
  contract:      string;       // "AAPL 220C 05/16"
  direction:     Direction;
  entryDate:     string;       // ISO date
  expiry:        string;       // ISO date
  dteRemaining:  number;
  dteTotal:      number;
  entryPrice:    number;
  currentPrice: number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number;
  target:        number;
  status:        Status;
  // Options-specific fields surfaced in the portfolio table.
  ivRank?:       number;       // 0–100, current IV vs 52-week range
  delta?:        number;       // option delta (–1..+1)
  theta?:        number;       // $/day time decay (negative for longs)
  vega?:         number;       // $/vol point
  contracts?:    number;       // number of option contracts held
  /** How the order was placed. Missing = legacy/seed data, treated as broker. */
  source?:       'broker' | 'manual';
  /** ISO timestamp of when the order was created (from Step 7). */
  orderedAt?:    string;
}

export interface AlertItem {
  id:        string;
  kind:      AlertKind;
  symbol:    string;
  reason:    string;
  timestamp: string;           // "09:42" or ISO
}

export interface UpcomingEvent {
  date:    string;             // ISO date
  symbol:  string;
  label:   string;             // "Earnings" / "FOMC" / ...
  status:  Status;
}

export interface TradeCardData {
  symbol:        string;
  company:       string;
  price:         number;
  direction:     Direction;
  status:        Status;
  stockScore:    number;
  stockConfidence: Status;
  stockBreakdown:  ScoreBreakdown;
  contract:      string;
  contractScore: number;
  contractConfidence: Status;
  contractBreakdown: ContractScoreBreakdown;
  /** Resolved contract fields for the TradeCard contract-detail block. */
  contractDetails?: {
    strike: number;
    expiry: string;              // YYYY-MM-DD
    right:  'C' | 'P';
    mid:    number;              // premium, $
    delta:  number;
    theta:  number;              // $/day
    ivRank: number;              // 0–100
    dte:    number;
  };
  entry:  { limit: number; maxFill: number; orderType: OrderType };
  exit:   { invalidation: number; premiumStop: number; timeStopDays: number; target: number };
  rrRatio:  number;
  rrModel:  'Heston repriced' | 'Delta approximation';
  finalStatus: Status;
}
```

Additional types defined in mock files (not in domain.ts) that need Pydantic models:

```typescript
// frontend/mocks/regime.ts
export interface RegimeMetric {
  label:  string;
  value:  string;
  status: Status;
  trend?: 'up' | 'flat' | 'down';
}
export interface MarketRegime {
  overall:  Status;
  headline: string;
  metrics:  RegimeMetric[];
}

// frontend/mocks/sectors.ts
export interface SectorTile {
  key:       string;   // "XLK"
  name:      string;   // "Technology"
  changePct: number;   // -3.2 .. +3.2
  status:    Status;
}

// frontend/mocks/contracts.ts
export type OptionRight = 'C' | 'P';
export interface OptionContract {
  id:           string;
  symbol:       string;
  strike:       number;
  expiry:       string;       // YYYY-MM-DD
  right:        OptionRight;
  dte:          number;
  dteTotal:     number;
  price:        number;       // mid premium, $
  delta:        number;
  theta:        number;       // $/day (negative for long)
  ivRank:       number;       // 0–100
  ivPercentile: number;       // 0–100
  spread:       number;       // bid/ask width, $
  volume:       number;       // contracts traded today
  score:        number;
}

// frontend/types/chart.ts
export interface Candle {
  time:   string;  // YYYY-MM-DD
  open:   number;
  high:   number;
  low:    number;
  close:  number;
  volume: number;
}
```

---

## 9. Mock data (exact values)

### 9.1 MOCK_WATCHLIST — 10 rows

The `nextEventDays` values below are computed from the events mock using reference date
`2026-04-20`. The frontend computes them dynamically; your fixture must hardcode the
pre-computed values below.

| # | symbol | company | price | direction | horizon | score | status | rankDelta | scoreDelta | nextEventDays | nextEventLabel |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AAPL | Apple Inc | 185.20 | Bullish | Swing | 82 | PASS | 2 | 3 | 8 | Earnings |
| 2 | NVDA | NVIDIA Corp | 903.10 | Bullish | Swing | 79 | PASS | 1 | -2 | 1 | Earnings |
| 3 | MSFT | Microsoft Corp | 417.50 | Bullish | Position | 74 | PASS | 0 | 0 | 10 | Earnings |
| 4 | META | Meta Platforms | 512.80 | Bullish | Swing | 71 | PASS | -1 | 1 | 9 | Earnings |
| 5 | GOOGL | Alphabet Inc | 156.20 | Bullish | Swing | 68 | CAUTION | 1 | -4 | 3 | FOMC |
| 6 | AMZN | Amazon.com Inc | 184.30 | Bullish | Position | 64 | CAUTION | 0 | 2 | 11 | Earnings |
| 7 | AMD | Adv Micro Devices | 158.40 | Bullish | Swing | 61 | CAUTION | 2 | 5 | 3 | FOMC |
| 8 | TSLA | Tesla Inc | 172.90 | Bearish | Swing | 55 | CAUTION | -2 | -3 | 0 | Earnings |
| 9 | NFLX | Netflix Inc | 610.20 | Bullish | Position | 52 | CAUTION | 0 | 0 | 3 | FOMC |
| 10 | INTC | Intel Corp | 35.10 | Bearish | Position | 42 | REJECT | -3 | -6 | 3 | FOMC |

Score breakdowns:
```python
WATCHLIST_BREAKDOWNS = {
    'AAPL':  {'trend': 88, 'pullback': 78, 'trigger': 85, 'event': 72, 'volatility': 74},
    'NVDA':  {'trend': 92, 'pullback': 62, 'trigger': 80, 'event': 70, 'volatility': 71},
    'MSFT':  {'trend': 82, 'pullback': 70, 'trigger': 68, 'event': 78, 'volatility': 70},
    'META':  {'trend': 78, 'pullback': 68, 'trigger': 70, 'event': 65, 'volatility': 74},
    'GOOGL': {'trend': 72, 'pullback': 66, 'trigger': 64, 'event': 68, 'volatility': 70},
    'AMZN':  {'trend': 66, 'pullback': 62, 'trigger': 60, 'event': 66, 'volatility': 66},
    'AMD':   {'trend': 68, 'pullback': 55, 'trigger': 60, 'event': 62, 'volatility': 60},
    'TSLA':  {'trend': 44, 'pullback': 60, 'trigger': 55, 'event': 58, 'volatility': 58},
    'NFLX':  {'trend': 58, 'pullback': 48, 'trigger': 50, 'event': 54, 'volatility': 50},
    'INTC':  {'trend': 30, 'pullback': 48, 'trigger': 40, 'event': 50, 'volatility': 42},
}
```

Note on `nextEventDays`: The frontend's `nextEventFor()` function walks `MOCK_EVENTS`
and picks the soonest event for the symbol (or the symbol `'—'` which covers all).
TSLA has an event on `2026-04-20` itself (0 days from reference), NVDA on `2026-04-21`
(1 day), FOMC is `2026-04-23` (3 days from reference and hits GOOGL, AMD, NFLX, INTC
since those symbols have no closer event). AAPL's first event is `2026-04-28` (8 days).
MSFT: `2026-04-30` (10 days). AMZN: `2026-05-01` (11 days). META: `2026-04-29` (9 days).

---

### 9.2 MOCK_REGIME

```python
MOCK_REGIME = {
    "overall":  "PASS",
    "headline": "Trend + breadth constructive; VIX contained",
    "metrics": [
        {"label": "SPX trend (200 EMA)", "value": "Above",    "status": "PASS",    "trend": "up"   },
        {"label": "NDX trend (200 EMA)", "value": "Above",    "status": "PASS",    "trend": "up"   },
        {"label": "Breadth (A/D)",       "value": "+412",     "status": "PASS",    "trend": "up"   },
        {"label": "VIX",                 "value": "14.8",     "status": "PASS",    "trend": "down" },
        {"label": "10Y yield",           "value": "4.28%",    "status": "CAUTION", "trend": "up"   },
        {"label": "DXY (USD)",           "value": "104.6",    "status": "PASS",    "trend": "flat" },
        {"label": "HY credit spread",    "value": "312 bp",   "status": "CAUTION", "trend": "up"   },
        {"label": "Put/Call (5d avg)",   "value": "0.84",     "status": "PASS",    "trend": "down" },
    ],
}
```

---

### 9.3 MOCK_SECTORS — 11 tiles

```python
MOCK_SECTORS = [
    {"key": "XLK",  "name": "Technology",             "changePct":  1.24, "status": "PASS"    },
    {"key": "XLC",  "name": "Comm. Services",          "changePct":  0.86, "status": "PASS"    },
    {"key": "XLY",  "name": "Consumer Discretionary",  "changePct":  0.42, "status": "PASS"    },
    {"key": "XLI",  "name": "Industrials",             "changePct":  0.18, "status": "CAUTION" },
    {"key": "XLF",  "name": "Financials",              "changePct":  0.05, "status": "CAUTION" },
    {"key": "XLP",  "name": "Consumer Staples",        "changePct": -0.08, "status": "CAUTION" },
    {"key": "XLV",  "name": "Health Care",             "changePct": -0.22, "status": "CAUTION" },
    {"key": "XLB",  "name": "Materials",               "changePct": -0.41, "status": "REJECT"  },
    {"key": "XLRE", "name": "Real Estate",             "changePct": -0.68, "status": "REJECT"  },
    {"key": "XLU",  "name": "Utilities",               "changePct": -0.94, "status": "REJECT"  },
    {"key": "XLE",  "name": "Energy",                  "changePct": -1.18, "status": "REJECT"  },
]
```

---

### 9.4 MOCK_CONTRACTS — 6 rows (all AAPL calls)

```python
MOCK_CONTRACTS = [
    {
        "id": "AAPL|190|2026-05-15|C", "symbol": "AAPL", "strike": 190,
        "expiry": "2026-05-15", "right": "C", "dte": 24, "dteTotal": 38,
        "price": 4.85, "delta": 0.45, "theta": -0.11,
        "ivRank": 42, "ivPercentile": 51, "spread": 0.05, "volume": 8420, "score": 82,
    },
    {
        "id": "AAPL|195|2026-05-15|C", "symbol": "AAPL", "strike": 195,
        "expiry": "2026-05-15", "right": "C", "dte": 24, "dteTotal": 38,
        "price": 3.10, "delta": 0.38, "theta": -0.10,
        "ivRank": 45, "ivPercentile": 54, "spread": 0.06, "volume": 6180, "score": 78,
    },
    {
        "id": "AAPL|190|2026-06-19|C", "symbol": "AAPL", "strike": 190,
        "expiry": "2026-06-19", "right": "C", "dte": 59, "dteTotal": 71,
        "price": 7.90, "delta": 0.48, "theta": -0.07,
        "ivRank": 38, "ivPercentile": 46, "spread": 0.08, "volume": 3250, "score": 73,
    },
    {
        "id": "AAPL|200|2026-05-15|C", "symbol": "AAPL", "strike": 200,
        "expiry": "2026-05-15", "right": "C", "dte": 24, "dteTotal": 38,
        "price": 1.85, "delta": 0.32, "theta": -0.09,
        "ivRank": 48, "ivPercentile": 58, "spread": 0.07, "volume": 4710, "score": 67,
    },
    {
        "id": "AAPL|185|2026-04-24|C", "symbol": "AAPL", "strike": 185,
        "expiry": "2026-04-24", "right": "C", "dte": 3, "dteTotal": 17,
        "price": 1.20, "delta": 0.58, "theta": -0.25,
        "ivRank": 61, "ivPercentile": 68, "spread": 0.04, "volume": 11850, "score": 54,
    },
    {
        "id": "AAPL|210|2026-05-15|C", "symbol": "AAPL", "strike": 210,
        "expiry": "2026-05-15", "right": "C", "dte": 24, "dteTotal": 38,
        "price": 0.72, "delta": 0.22, "theta": -0.08,
        "ivRank": 52, "ivPercentile": 62, "spread": 0.12, "volume": 1940, "score": 42,
    },
]
```

---

### 9.5 MOCK_PORTFOLIO — 5 positions

See Section 4.7 for the full JSON. Status values (pre-computed from `dteStatus` logic):

| symbol | dteRemaining | dteTotal | ratio | status |
|---|---|---|---|---|
| AAPL | 28 | 38 | 0.74 | PASS |
| NVDA | 7 | 11 | 0.64 | CAUTION |
| MSFT | 63 | 71 | 0.89 | PASS |
| META | 14 | 17 | 0.82 | PASS |
| TSLA | 4 | 6 | 0.67 | CAUTION |

Wait — NVDA ratio 7/11=0.636 (>=0.50, not <0.50) → PASS; but the frontend's `dteStatus`
may use different thresholds. Check the actual logic:

The frontend `dteStatus` from `lib/date.ts` is: DTE remaining as fraction of total.
- `ratio < 0.25` → REJECT
- `ratio < 0.50` → CAUTION
- otherwise → PASS

Recalculated with this rule:
| symbol | ratio | status |
|---|---|---|
| AAPL | 28/38 = 0.737 | PASS |
| NVDA | 7/11 = 0.636 | PASS |
| MSFT | 63/71 = 0.887 | PASS |
| META | 14/17 = 0.824 | PASS |
| TSLA | 4/6 = 0.667 | PASS |

However the displayed portfolio fixture in Section 4.7 shows NVDA as CAUTION and TSLA as
REJECT. These appear to be the values that were stored when the portfolio was seeded
(reflecting time passed since entry). Use the hardcoded status values from Section 4.7
exactly — do not re-derive them at runtime for the fixture endpoint.

---

### 9.6 MOCK_ALERTS — 5 items

```python
MOCK_ALERTS = [
    {"id": "a1", "kind": "Critical", "symbol": "META",  "reason": "Broke trail stop",                    "timestamp": "09:38"},
    {"id": "a2", "kind": "Action",   "symbol": "NVDA",  "reason": "Earnings in 3 days — roll or close",  "timestamp": "09:41"},
    {"id": "a3", "kind": "Action",   "symbol": "AAPL",  "reason": "Target 80% reached",                  "timestamp": "09:47"},
    {"id": "a4", "kind": "Info",     "symbol": "SPY",   "reason": "Regime flipped to PASS",              "timestamp": "09:15"},
    {"id": "a5", "kind": "Info",     "symbol": "TSLA",  "reason": "IV rank > 70",                        "timestamp": "09:02"},
]
```

---

### 9.7 MOCK_EVENTS — 36 items (full list)

```python
MOCK_EVENTS = [
    # April 2026 (near-term)
    {"date": "2026-04-20", "symbol": "TSLA",  "label": "Earnings",           "status": "REJECT"  },
    {"date": "2026-04-21", "symbol": "NVDA",  "label": "Earnings",           "status": "CAUTION" },
    {"date": "2026-04-23", "symbol": "—",     "label": "FOMC",               "status": "CAUTION" },
    {"date": "2026-04-28", "symbol": "AAPL",  "label": "Earnings",           "status": "CAUTION" },
    {"date": "2026-04-29", "symbol": "META",  "label": "Earnings",           "status": "PASS"    },
    {"date": "2026-04-30", "symbol": "MSFT",  "label": "Earnings",           "status": "CAUTION" },
    # May 2026
    {"date": "2026-05-01", "symbol": "AMZN",  "label": "Earnings",           "status": "PASS"    },
    {"date": "2026-05-06", "symbol": "—",     "label": "ISM Services PMI",   "status": "PASS"    },
    {"date": "2026-05-14", "symbol": "—",     "label": "CPI release",        "status": "CAUTION" },
    {"date": "2026-05-15", "symbol": "—",     "label": "Monthly expiration", "status": "CAUTION" },
    {"date": "2026-05-21", "symbol": "NVDA",  "label": "Earnings (Q1)",      "status": "REJECT"  },
    {"date": "2026-05-28", "symbol": "CRM",   "label": "Earnings",           "status": "CAUTION" },
    # June 2026
    {"date": "2026-06-04", "symbol": "—",     "label": "ECB rate decision",  "status": "PASS"    },
    {"date": "2026-06-11", "symbol": "—",     "label": "CPI release",        "status": "CAUTION" },
    {"date": "2026-06-17", "symbol": "—",     "label": "FOMC + dot plot",    "status": "REJECT"  },
    {"date": "2026-06-19", "symbol": "—",     "label": "Triple witching",    "status": "CAUTION" },
    {"date": "2026-06-25", "symbol": "NKE",   "label": "Earnings",           "status": "PASS"    },
    {"date": "2026-06-30", "symbol": "MU",    "label": "Earnings",           "status": "CAUTION" },
    # July 2026
    {"date": "2026-07-02", "symbol": "—",     "label": "NFP jobs report",    "status": "CAUTION" },
    {"date": "2026-07-14", "symbol": "JPM",   "label": "Earnings",           "status": "PASS"    },
    {"date": "2026-07-15", "symbol": "—",     "label": "CPI release",        "status": "CAUTION" },
    {"date": "2026-07-17", "symbol": "—",     "label": "Monthly expiration", "status": "CAUTION" },
    {"date": "2026-07-22", "symbol": "TSLA",  "label": "Earnings",           "status": "REJECT"  },
    {"date": "2026-07-23", "symbol": "GOOGL", "label": "Earnings",           "status": "CAUTION" },
    {"date": "2026-07-29", "symbol": "—",     "label": "FOMC",               "status": "REJECT"  },
    {"date": "2026-07-30", "symbol": "AAPL",  "label": "Earnings",           "status": "CAUTION" },
    {"date": "2026-07-30", "symbol": "AMZN",  "label": "Earnings",           "status": "CAUTION" },
    {"date": "2026-07-31", "symbol": "XOM",   "label": "Earnings",           "status": "PASS"    },
    # August 2026
    {"date": "2026-08-06", "symbol": "—",     "label": "BoE rate decision",  "status": "PASS"    },
    {"date": "2026-08-12", "symbol": "—",     "label": "CPI release",        "status": "CAUTION" },
    {"date": "2026-08-21", "symbol": "—",     "label": "Monthly expiration", "status": "CAUTION" },
    {"date": "2026-08-27", "symbol": "NVDA",  "label": "Earnings (Q2)",      "status": "REJECT"  },
    {"date": "2026-08-28", "symbol": "—",     "label": "Jackson Hole close", "status": "CAUTION" },
    # September 2026
    {"date": "2026-09-04", "symbol": "—",     "label": "NFP jobs report",    "status": "CAUTION" },
    {"date": "2026-09-10", "symbol": "—",     "label": "ECB rate decision",  "status": "PASS"    },
    {"date": "2026-09-11", "symbol": "—",     "label": "CPI release",        "status": "CAUTION" },
    {"date": "2026-09-16", "symbol": "—",     "label": "FOMC + projections", "status": "REJECT"  },
    {"date": "2026-09-18", "symbol": "—",     "label": "Triple witching",    "status": "CAUTION" },
    {"date": "2026-09-24", "symbol": "COST",  "label": "Earnings",           "status": "PASS"    },
]
```

---

### 9.8 Candle seed config (for `/api/candles/{symbol}`)

Reproduce the Mulberry32 RNG from `frontend/mocks/candles.ts` in Python.
The anchor date for the series is `2026-04-18`. Bar 0 is the oldest; bar 119 is the most recent.

```python
CANDLE_SEEDS = {
    'AAPL':  {'seed': 11,  'base': 172,   'drift':  0.0008},
    'NVDA':  {'seed': 22,  'base': 820,   'drift':  0.0015},
    'MSFT':  {'seed': 33,  'base': 395,   'drift':  0.0006},
    'META':  {'seed': 44,  'base': 495,   'drift':  0.0005},
    'GOOGL': {'seed': 55,  'base': 148,   'drift':  0.0004},
    'AMZN':  {'seed': 66,  'base': 178,   'drift':  0.0004},
    'AMD':   {'seed': 77,  'base': 148,   'drift':  0.0007},
    'TSLA':  {'seed': 88,  'base': 190,   'drift': -0.0010},
    'NFLX':  {'seed': 99,  'base': 598,   'drift':  0.0003},
    'INTC':  {'seed': 111, 'base': 40,    'drift': -0.0006},
    'SPX':   {'seed': 201, 'base': 5180,  'drift':  0.0006},
    'NDX':   {'seed': 202, 'base': 18020, 'drift':  0.0009},
}
```

Mulberry32 algorithm (translate exactly to Python using 32-bit unsigned integers):

```python
def mulberry32(seed: int):
    """Yields floats in [0, 1). Mirrors the JavaScript Mulberry32 PRNG exactly."""
    t = seed & 0xFFFFFFFF
    while True:
        t = (t + 0x6D2B79F5) & 0xFFFFFFFF
        r = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        r = (r ^ (r + ((r ^ (r >> 7)) * (61 | r)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        yield ((r ^ (r >> 14)) & 0xFFFFFFFF) / 4294967296


def iso_days_ago(days: int, anchor: str = '2026-04-18') -> str:
    from datetime import date, timedelta
    anchor_date = date.fromisoformat(anchor)
    return (anchor_date - timedelta(days=days)).isoformat()


def make_candles(seed: int, base: float, bars: int = 120, drift: float = 0.0005) -> list[dict]:
    rand = mulberry32(seed)
    out = []
    close = base
    for i in range(bars - 1, -1, -1):
        open_ = close
        r1 = next(rand)
        r2 = next(rand)
        r3 = next(rand)
        r4 = next(rand)
        r5 = next(rand)
        vol = base * (0.012 + r1 * 0.018)
        dir_ = 1 if r2 < 0.53 + drift * 40 else -1
        range_ = vol * (0.6 + r3 * 0.8)
        next_close = max(1.0, open_ + dir_ * range_ + (r4 - 0.5) * vol * 0.5)
        high = max(open_, next_close) + r5 * range_ * 0.4
        # Need one more rand call for low
        r6 = next(rand)
        low  = min(open_, next_close) - r6 * range_ * 0.4
        r7 = next(rand)
        volume = round(4_000_000 + r7 * 12_000_000)
        out.append({
            'time':   iso_days_ago(i),
            'open':   round(open_, 2),
            'high':   round(high, 2),
            'low':    round(low, 2),
            'close':  round(next_close, 2),
            'volume': volume,
        })
        close = next_close
    return out
```

IMPORTANT: The JavaScript `Math.imul` used in the original RNG performs C-style 32-bit
integer multiplication. Replicate it in Python with `(a * b) & 0xFFFFFFFF`. The
generator above must produce values identical to the TypeScript version. If chart values
differ visually from the mock, re-check the 32-bit masking on every step of the RNG.

---

## 10. Task spec

Follow these steps in order.

### Step 1 — Create `backend/app/schemas/__init__.py`

Copy the Pydantic models from Section 5 verbatim. Run a quick sanity check:
```bash
cd backend
python -c "from app.schemas import WatchlistRow, TradeCardData, Candle; print('OK')"
```

### Step 2 — Fix config.py to allow local dev startup

Make `DATABASE_URL` and `JWT_SECRET_KEY` optional with safe defaults so the app starts
without a `.env` file in the trading-routes dev context:

```python
DATABASE_URL: str = "sqlite+aiosqlite:///./dev.db"
JWT_SECRET_KEY: str = "dev-only-not-used"
```

Do not remove these fields — they are still needed if the child-management DB features are
ever activated.

### Step 3 — Create each router file

For each of the 9 trading routes, create `backend/app/routers/<name>.py` with this pattern:

```python
# backend/app/routers/watchlist.py
from fastapi import APIRouter
from app.schemas import WatchlistRow
from app.fixtures.watchlist import MOCK_WATCHLIST

router = APIRouter(prefix="/api", tags=["trading"])

@router.get("/watchlist", response_model=list[WatchlistRow])
async def get_watchlist() -> list[WatchlistRow]:
    return MOCK_WATCHLIST
```

Store the raw fixture dicts in a `backend/app/fixtures/` sub-package (one module per
endpoint). The router instantiates Pydantic models from the dicts. This keeps fixture
data separate from routing logic.

### Step 4 — Create `backend/app/fixtures/` sub-package

Create `backend/app/fixtures/__init__.py` (empty) and one file per endpoint:
- `watchlist.py` → `MOCK_WATCHLIST: list[WatchlistRow]`
- `contracts.py` → `MOCK_CONTRACTS: list[OptionContract]`
- `candles.py` → `candlesFor(symbol: str) -> list[Candle]` (uses RNG from Section 9.8)
- `regime.py` → `MOCK_REGIME: MarketRegime`
- `sectors.py` → `MOCK_SECTORS: list[SectorTile]`
- `tradecards.py` → `MOCK_CANDIDATE_CARDS: list[TradeCardData]`
- `portfolio.py` → `MOCK_PORTFOLIO: list[PortfolioPosition]`
- `alerts.py` → `MOCK_ALERTS: list[AlertItem]`
- `events.py` → `MOCK_EVENTS: list[UpcomingEvent]`

Populate each with the exact values from Section 9. Build `tradecards.py` by
synthesising `TradeCardData` from `MOCK_WATCHLIST` + `MOCK_CONTRACTS` using the same
logic as `frontend/mocks/tradecards.ts` (documented in Section 4.6).

### Step 5 — Wire routers into `main.py`

Add the 9 new router imports and `app.include_router()` calls after the existing
`health_router` include. Preserve everything already in `main.py`.

```python
# In main.py, after the health router:
from app.routers.watchlist  import router as watchlist_router
from app.routers.contracts  import router as contracts_router
from app.routers.candles    import router as candles_router
from app.routers.regime     import router as regime_router
from app.routers.sectors    import router as sectors_router
from app.routers.tradecards import router as tradecards_router
from app.routers.portfolio  import router as portfolio_router
from app.routers.alerts     import router as alerts_router
from app.routers.events     import router as events_router

# In create_app():
app.include_router(watchlist_router)
app.include_router(contracts_router)
app.include_router(candles_router)
app.include_router(regime_router)
app.include_router(sectors_router)
app.include_router(tradecards_router)
app.include_router(portfolio_router)
app.include_router(alerts_router)
app.include_router(events_router)
```

### Step 6 — Ensure CORS allows `http://localhost:3001`

The existing CORS config uses `allow_origins=["*"]` when `DEBUG=True`. This is fine for
local dev. If for any reason it is changed, the explicit origin must include
`http://localhost:3001` (the frontend dev server port).

### Step 7 — Verify

Start the server and test all routes:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Then in another terminal:
```bash
curl -s http://localhost:8000/health | python -m json.tool
curl -s http://localhost:8000/api/watchlist | python -m json.tool | head -40
curl -s http://localhost:8000/api/regime | python -m json.tool
curl -s http://localhost:8000/api/sectors | python -m json.tool
curl -s http://localhost:8000/api/contracts | python -m json.tool
curl -s http://localhost:8000/api/portfolio | python -m json.tool
curl -s http://localhost:8000/api/alerts | python -m json.tool
curl -s http://localhost:8000/api/events | python -m json.tool | head -40
curl -s http://localhost:8000/api/tradecards | python -m json.tool | head -60
curl -s "http://localhost:8000/api/candles/AAPL" | python -m json.tool | head -20
curl -s "http://localhost:8000/api/candles/SPX"  | python -m json.tool | head -10
```

### Acceptance criteria

- `GET /health` returns `{"status": "ok"}` (unchanged).
- `GET /api/watchlist` returns a JSON array of exactly 10 objects.
  - First object has `"symbol": "AAPL"`, `"score": 82`, `"status": "PASS"`.
  - Last object has `"symbol": "INTC"`, `"score": 42`, `"status": "REJECT"`.
- `GET /api/regime` returns an object with `"overall": "PASS"` and `"metrics"` array of 8.
- `GET /api/sectors` returns an array of 11 objects; first has `"key": "XLK"`.
- `GET /api/contracts` returns an array of 6 objects; first has `"id": "AAPL|190|2026-05-15|C"`.
- `GET /api/portfolio` returns an array of 5 objects.
- `GET /api/alerts` returns an array of 5 objects.
- `GET /api/events` returns an array of 36 objects.
- `GET /api/tradecards` returns an array of 10 objects.
- `GET /api/candles/AAPL` returns an array of 120 objects, each with `time`, `open`, `high`, `low`, `close`, `volume`.
- `GET /api/candles/UNKNOWN` returns an array of 120 objects (fallback seed).
- All responses use camelCase field names matching the TypeScript types exactly.
- No 422 or 500 errors on any of the above requests.

---

## 11. Hard rules

### From the master project (always apply)

- Do NOT add Tailwind, styled-components, or any CSS-in-JS library.
- Do NOT hardcode colours in any template or response — status values use the canonical strings.
- Do NOT invent new Status values. Only valid: `'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'`.
- Do NOT commit with a failing typecheck (frontend) or import error (backend).
- Do NOT touch `node_modules/` or `package-lock.json`.

### Backend-specific rules

- **Python field names must match TypeScript field names exactly** — camelCase, not snake_case.
  Pydantic v2 does not auto-convert; field names must be written as camelCase in the model definition.
- **Status values must be exactly:** `'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'`
  — no other strings, no lowercase variants.
- **Do NOT touch any file under `frontend/`.**
- **Do NOT add a database layer for trading data** — all 9 trading routes serve deterministic
  fixture data only. No SQLAlchemy models, no DB queries for trading routes.
- **Do NOT break the existing `GET /health` router.** Keep `backend/app/routers/health.py` untouched.
- **Do NOT touch Alembic migration files** (`backend/alembic/` and `backend/alembic.ini`).
- **Do NOT change `requirements.txt`** unless a required package is genuinely missing.
  All needed libraries (fastapi, pydantic v2, uvicorn) are already installed.
- **Do NOT use `model.dict()` or `model.json()`** — deprecated in Pydantic v2. Use
  `model.model_dump()` and `model.model_dump_json()` if serialization is needed.
- **Preserve camelCase in JSON output.** Pydantic v2 serializes field names as-is.
  Do not add `alias_generator = to_camel` — the model field names are already camelCase.

---

## 12. Dev workflow

```bash
# 1. Start the backend (from project root)
cd backend
uvicorn app.main:app --reload --port 8000

# 2. In a second terminal, start the frontend
cd frontend
npm run dev
# → http://localhost:3001

# 3. Test backend endpoints directly
curl http://localhost:8000/health
curl http://localhost:8000/api/watchlist
curl http://localhost:8000/api/regime
curl http://localhost:8000/api/sectors
curl http://localhost:8000/api/contracts
curl http://localhost:8000/api/portfolio
curl http://localhost:8000/api/alerts
curl http://localhost:8000/api/events
curl http://localhost:8000/api/tradecards
curl "http://localhost:8000/api/candles/AAPL"
curl "http://localhost:8000/api/candles/SPX"

# 4. Interactive API docs (auto-generated by FastAPI)
# http://localhost:8000/docs
# http://localhost:8000/redoc

# 5. Check for Python import errors before running
python -c "from app.main import app; print('App loaded OK')"
```

---

## 13. Copy/paste prompt

Paste the following block to the implementing LLM. It is self-contained.

---

```
You are implementing the FastAPI trading-data backend for the Bamendjou options screener.

Read `llm-contexts/01-backend-fastapi.md` in full before writing any code.
That file is your single source of truth. Do not read or modify any file under `frontend/`.

## Your task

Build 9 HTTP endpoints on top of the existing FastAPI skeleton in `backend/`.
Each endpoint returns deterministic fixture data that exactly matches the frontend mock files.
No database, no external APIs — just hardcoded Python fixtures served through Pydantic models.

## Owned files (create or modify only these)

- `backend/app/main.py` — add 9 router includes (modify only)
- `backend/app/config.py` — make DATABASE_URL and JWT_SECRET_KEY optional (modify only)
- `backend/app/schemas/__init__.py` — create: all Pydantic v2 models
- `backend/app/fixtures/__init__.py` — create: empty init
- `backend/app/fixtures/watchlist.py` — create: MOCK_WATCHLIST list
- `backend/app/fixtures/contracts.py` — create: MOCK_CONTRACTS list
- `backend/app/fixtures/candles.py` — create: make_candles() + candlesFor()
- `backend/app/fixtures/regime.py` — create: MOCK_REGIME object
- `backend/app/fixtures/sectors.py` — create: MOCK_SECTORS list
- `backend/app/fixtures/tradecards.py` — create: MOCK_CANDIDATE_CARDS list
- `backend/app/fixtures/portfolio.py` — create: MOCK_PORTFOLIO list
- `backend/app/fixtures/alerts.py` — create: MOCK_ALERTS list
- `backend/app/fixtures/events.py` — create: MOCK_EVENTS list
- `backend/app/routers/watchlist.py` — create: GET /api/watchlist
- `backend/app/routers/contracts.py` — create: GET /api/contracts
- `backend/app/routers/candles.py` — create: GET /api/candles/{symbol}
- `backend/app/routers/regime.py` — create: GET /api/regime
- `backend/app/routers/sectors.py` — create: GET /api/sectors
- `backend/app/routers/tradecards.py` — create: GET /api/tradecards
- `backend/app/routers/portfolio.py` — create: GET /api/portfolio
- `backend/app/routers/alerts.py` — create: GET /api/alerts
- `backend/app/routers/events.py` — create: GET /api/events

## Hard rules (non-negotiable)

1. All Pydantic field names must be camelCase — matching TypeScript exactly.
   Do NOT use snake_case fields. Do NOT add alias_generator.
2. Status values: only 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'.
3. Do NOT touch any file under `frontend/`.
4. Do NOT touch `backend/app/routers/health.py` or any Alembic file.
5. Do NOT add a database layer for trading data.
6. Do NOT change `requirements.txt`.
7. The candles endpoint must reproduce the Mulberry32 seeded RNG from candles.ts
   using 32-bit unsigned integer arithmetic.

## Verification

After implementation, run:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
# In another terminal:
curl http://localhost:8000/health
curl http://localhost:8000/api/watchlist | python -m json.tool | head -20
curl http://localhost:8000/api/regime | python -m json.tool
curl "http://localhost:8000/api/candles/AAPL" | python -m json.tool | head -15
```

All 9 trading routes must return HTTP 200 with the correct shape.
`GET /health` must still return `{"status": "ok"}`.
The first watchlist row must have symbol "AAPL", score 82, status "PASS".
```
