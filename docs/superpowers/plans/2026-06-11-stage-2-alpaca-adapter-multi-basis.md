# Stage 2: Alpaca Data Adapter + Multi-Basis Migration + Fallback Router — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `adj_factor / split_factor / div_cash / source` columns to `ohlcv_daily`, wire Alpaca as the primary daily-bar source (per-symbol), and update `get_bars()` to use the chain Alpaca → Tiingo → yfinance so the scanner never hits the Tiingo unique-symbol cap.

**Architecture:** Four new columns make the DB store raw OHLCV + a multiplier; scanner reads `raw_close × adj_factor` = fully-adjusted price (identical to today). A new `backend/app/data/alpaca.py` adapter wraps the Alpaca v2 bars endpoint, Governor-paced. `get_bars()` in `historical_store.py` is updated to try Alpaca first, fall through to Tiingo, then yfinance — each via the Governor so rate limits are enforced. Existing rows get `adj_factor = 1.0` (they already store adjClose, so the invariant holds without a data fix-up).

**Tech Stack:** Python 3.14, FastAPI, httpx async, SQLAlchemy v2, Alembic, pytest-asyncio. Run all tests from `backend/`. Alembic commands use `python -m alembic -c migrations/alembic.ini`.

**Source spec:** `docs/superpowers/specs/2026-06-11-data-loading-and-provider-governor-design.md` (§5.2, §5.4).

---

## File Structure

- **Modify** `backend/app/models/ohlcv_daily.py` — add 4 new columns
- **Create** `backend/migrations/versions/<rev>_multi_basis_ohlcv_daily.py` — Alembic migration (generate via autogenerate, then hand-edit)
- **Modify** `backend/app/data/tiingo.py` — return raw prices + adj_factor, split_factor, div_cash instead of adjClose
- **Create** `backend/app/data/alpaca.py` — Alpaca v2 daily bars adapter, Governor-paced
- **Create** `backend/tests/test_alpaca_adapter.py` — unit tests for the Alpaca adapter (mock HTTP)
- **Modify** `backend/app/services/historical_store.py` — `_store_bars` accepts multi-basis fields; `_read_bars` returns `raw_close × adj_factor`; `get_bars` uses Alpaca → Tiingo → yfinance chain
- **Modify** `backend/tests/test_historical_store_guard.py` — update tests for new store behavior

Run all commands from `backend/`. Test command: `pytest tests/<file> -v`.

---

### Task 1: OhlcvDailyModel — add multi-basis columns + Alembic migration

**Files:**
- Modify: `backend/app/models/ohlcv_daily.py`
- Create: `backend/migrations/versions/<rev>_multi_basis_ohlcv_daily.py`
- Test: `backend/tests/test_historical_store.py` (run existing tests — they should still pass because the test DB is recreated from the updated model)

- [ ] **Step 1: Add the four columns to OhlcvDailyModel**

Open `backend/app/models/ohlcv_daily.py`. The `import` line and model body become:

```python
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase


class OhlcvBase(DeclarativeBase):
    """Standalone base for the ohlcv_daily table.
    Uses a composite (symbol, date) primary key — no UUID needed."""
    pass


class OhlcvDailyModel(OhlcvBase):
    """Persistent daily OHLCV bars.

    Composite primary key: (symbol, date).
    open/high/low/close/volume store RAW (unadjusted) prices.
    adj_factor: fully-adjusted / raw  (multiply raw_close × adj_factor for scanner input).
    split_factor: split-only adjustment factor.
    div_cash: dividend cash amount at this bar date.
    source: which provider wrote this row ('alpaca', 'tiingo', 'yfinance', 'tiingo_legacy').
    """

    __tablename__ = "ohlcv_daily"

    symbol       = Column(String(10),                   primary_key=True, nullable=False)
    date         = Column(Date,                          primary_key=True, nullable=False)
    open         = Column(Numeric(precision=12, scale=4), nullable=False)
    high         = Column(Numeric(precision=12, scale=4), nullable=False)
    low          = Column(Numeric(precision=12, scale=4), nullable=False)
    close        = Column(Numeric(precision=12, scale=4), nullable=False)
    volume       = Column(BigInteger, nullable=False)
    adj_factor   = Column(Numeric(precision=12, scale=8), nullable=True)
    split_factor = Column(Numeric(precision=12, scale=8), nullable=True)
    div_cash     = Column(Numeric(precision=12, scale=4), nullable=True)
    source       = Column(String(20), nullable=True)
    fetched_at   = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
```

- [ ] **Step 2: Generate the Alembic migration**

```bash
python -m alembic -c migrations/alembic.ini revision --autogenerate -m "multi_basis_ohlcv_daily"
```

This creates a new file in `backend/migrations/versions/`. Open it and verify the upgrade/downgrade functions match the intent below. Replace the auto-generated body with:

```python
"""multi_basis_ohlcv_daily

Revision ID: <keep generated ID>
Revises: 3a503885d759
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa

revision = '<keep generated ID>'
down_revision = '3a503885d759'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ohlcv_daily', sa.Column('adj_factor',   sa.Numeric(precision=12, scale=8), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('split_factor', sa.Numeric(precision=12, scale=8), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('div_cash',     sa.Numeric(precision=12, scale=4), nullable=True))
    op.add_column('ohlcv_daily', sa.Column('source',       sa.String(length=20),              nullable=True))
    # Existing rows store adjClose in close — set adj_factor=1.0 so the
    # invariant raw_close × adj_factor = fully_adjusted_close holds.
    op.execute("UPDATE ohlcv_daily SET adj_factor = 1.0, split_factor = 1.0, div_cash = 0.0, source = 'tiingo_legacy' WHERE adj_factor IS NULL")


def downgrade() -> None:
    op.drop_column('ohlcv_daily', 'source')
    op.drop_column('ohlcv_daily', 'div_cash')
    op.drop_column('ohlcv_daily', 'split_factor')
    op.drop_column('ohlcv_daily', 'adj_factor')
```

- [ ] **Step 3: Run existing historical_store tests to confirm the model change doesn't break them**

```bash
pytest tests/test_historical_store.py -v
```

Expected: all existing tests pass (the test fixture creates a fresh DB from the updated model, so new columns are present with NULLs — existing tests don't touch them).

If `tests/test_historical_store.py` doesn't exist yet, skip this step and proceed.

- [ ] **Step 4: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/models/ohlcv_daily.py backend/migrations/versions/
git commit -m "feat(db): add adj_factor, split_factor, div_cash, source to ohlcv_daily"
```

---

### Task 2: Update tiingo.py — return raw prices + multi-basis fields

Currently `tiingo.py` maps `adjOpen → open`, `adjClose → close` etc. — so stored `close` is already adjusted and `adj_factor = 1.0`. We now return the **raw** prices and include the adjustment factors so the caller can store them properly.

**Files:**
- Modify: `backend/app/data/tiingo.py`

- [ ] **Step 1: Update `fetch_historical_candles` to return multi-basis bars**

Replace the body of `fetch_historical_candles` in `backend/app/data/tiingo.py`:

```python
from __future__ import annotations

import os
from datetime import date
from typing import Optional

import httpx

TIINGO_BASE_URL = "https://api.tiingo.com"
TIINGO_TOKEN = os.getenv("TIINGO_API_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Token {TIINGO_TOKEN}",
        "Content-Type": "application/json",
    }


def fetch_historical_candles(
    symbol: str,
    start: date,
    end: date,
) -> list[dict]:
    """Returns daily OHLCV bars for `symbol` between `start` and `end` (inclusive).

    Each dict: {time, open, high, low, close, volume: raw values;
                adj_factor, split_factor, div_cash: adjustment metadata;
                source: 'tiingo'}
    adj_factor = adjClose / close (multiply raw close × adj_factor to get fully-adjusted).
    Returns [] on any error.
    """
    try:
        resp = httpx.get(
            f"{TIINGO_BASE_URL}/tiingo/daily/{symbol}/prices",
            headers=_headers(),
            params={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "resampleFreq": "daily",
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = []
        for bar in resp.json():
            raw_close = float(bar.get("close", 0) or 0)
            adj_close = float(bar.get("adjClose", raw_close) or raw_close)
            adj_factor = round(adj_close / raw_close, 8) if raw_close != 0 else 1.0
            rows.append({
                "time":         bar["date"][:10],
                "open":         round(float(bar.get("open", 0) or 0),   2),
                "high":         round(float(bar.get("high", 0) or 0),   2),
                "low":          round(float(bar.get("low",  0) or 0),   2),
                "close":        round(raw_close,                         2),
                "volume":       int(bar.get("volume", 0) or 0),
                "adj_factor":   adj_factor,
                "split_factor": round(float(bar.get("splitFactor", 1.0) or 1.0), 8),
                "div_cash":     round(float(bar.get("divCash",      0.0) or 0.0), 4),
                "source":       "tiingo",
            })
        return rows
    except Exception:
        return []
```

- [ ] **Step 2: Verify there are no unit tests that expect the old adjClose format**

```bash
grep -r "adjClose\|adjOpen\|adjHigh\|adjLow" tests/ --include="*.py"
```

Expected: no matches. If matches found, update the tests to expect raw prices.

- [ ] **Step 3: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/data/tiingo.py
git commit -m "feat(tiingo): return raw prices + adj_factor/split_factor/div_cash"
```

---

### Task 3: Alpaca daily bars adapter

**Files:**
- Create: `backend/app/data/alpaca.py`
- Create: `backend/tests/test_alpaca_adapter.py`

Alpaca's data endpoint is always `https://data.alpaca.markets` (same for paper and live accounts). Auth uses the credential store's `alpaca_live` slot if key_id is set, otherwise `alpaca_paper`. The Governor rate-limits via `get_governor().call("alpaca", coro)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_alpaca_adapter.py`:

```python
"""Unit tests for the Alpaca daily bars adapter (no live network)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.data.alpaca import (
    AlpacaClient,
    fetch_daily_bars_single,
    get_alpaca_client,
    _normalize_bars,
)


def _alpaca_resp(bars_by_symbol: dict, next_token: str | None = None) -> httpx.Response:
    """Build a fake Alpaca bars response."""
    request = httpx.Request("GET", "https://data.alpaca.markets/v2/stocks/bars")
    body = {"bars": bars_by_symbol, "next_page_token": next_token}
    return httpx.Response(200, json=body, request=request)


RAW_BAR = {
    "t": "2024-01-02T05:00:00Z",
    "o": 185.0, "h": 186.0, "l": 184.0, "c": 185.5, "v": 1_000_000,
    "n": 50000, "vw": 185.2,
}
ADJ_BAR = {
    "t": "2024-01-02T05:00:00Z",
    "o": 190.0, "h": 191.0, "l": 189.0, "c": 190.2, "v": 1_000_000,
    "n": 50000, "vw": 190.0,
}


def test_normalize_bars_computes_adj_factor():
    raw_bars = {"AAPL": [RAW_BAR]}
    adj_bars = {"AAPL": [ADJ_BAR]}
    result = _normalize_bars(raw_bars, adj_bars)
    assert len(result["AAPL"]) == 1
    bar = result["AAPL"][0]
    assert bar["time"] == "2024-01-02"
    assert bar["close"] == 185.5   # raw
    assert abs(bar["adj_factor"] - round(190.2 / 185.5, 8)) < 1e-6
    assert bar["source"] == "alpaca"


def test_normalize_bars_handles_missing_adj():
    # adj_bars has no entry for a symbol → adj_factor defaults to 1.0
    raw_bars = {"MSFT": [RAW_BAR]}
    adj_bars: dict = {}
    result = _normalize_bars(raw_bars, adj_bars)
    assert result["MSFT"][0]["adj_factor"] == 1.0


@pytest.mark.asyncio
async def test_get_alpaca_client_returns_none_when_unconfigured():
    with patch("app.data.alpaca.credential_store") as cs:
        cs.get.return_value = {"key_id": "", "secret_key": "", "base_url": ""}
        client = await get_alpaca_client()
    assert client is None


@pytest.mark.asyncio
async def test_fetch_daily_bars_single_returns_bars():
    from datetime import date
    raw_resp = _alpaca_resp({"AAPL": [RAW_BAR]})
    adj_resp = _alpaca_resp({"AAPL": [ADJ_BAR]})

    fake_client = MagicMock(spec=AlpacaClient)
    fake_client.fetch_raw = AsyncMock(return_value={"AAPL": [RAW_BAR]})
    fake_client.fetch_adj = AsyncMock(return_value={"AAPL": [ADJ_BAR]})

    bars = await fetch_daily_bars_single("AAPL", date(2024, 1, 1), date(2024, 1, 31), client=fake_client)
    assert len(bars) == 1
    assert bars[0]["time"] == "2024-01-02"
    assert bars[0]["source"] == "alpaca"
```

- [ ] **Step 2: Run — confirm FAILS**

```bash
pytest tests/test_alpaca_adapter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.alpaca'`

- [ ] **Step 3: Write the Alpaca adapter**

Create `backend/app/data/alpaca.py`:

```python
"""Alpaca daily bars adapter — Governor-paced, multi-basis.

Data API endpoint is always https://data.alpaca.markets (same for paper and live).
Credentials are read from the credential store (alpaca_live preferred, alpaca_paper fallback).
All calls pass through the Governor so the 200 req/min bucket is enforced.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app.services.credential_store import credential_store
from app.data.governor import get_governor, RateLimited

logger = logging.getLogger(__name__)

_DATA_BASE = "https://data.alpaca.markets"
_BARS_ENDPOINT = f"{_DATA_BASE}/v2/stocks/bars"


class AlpacaClient:
    """Thin wrapper around Alpaca v2 bars endpoint."""

    def __init__(self, key_id: str, secret_key: str) -> None:
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        }

    async def _get_bars_page(
        self, symbols: list[str], adjustment: str, start: date, end: date, page_token: str | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "adjustment": adjustment,
            "feed": "iex",
            "limit": 10_000,
        }
        if page_token:
            params["page_token"] = page_token
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_BARS_ENDPOINT, headers=self._headers, params=params)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", 1.0))
            raise RateLimited("429 from Alpaca", retry_after=retry_after)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_all_pages(
        self, symbols: list[str], adjustment: str, start: date, end: date
    ) -> dict[str, list[dict]]:
        """Fetch all pages for the given adjustment type. Returns symbol → raw bar list."""
        result: dict[str, list] = {}
        page_token: str | None = None
        while True:
            data = await get_governor().call(
                "alpaca",
                lambda pt=page_token: self._get_bars_page(symbols, adjustment, start, end, pt),
            )
            for sym, bars in (data.get("bars") or {}).items():
                result.setdefault(sym, []).extend(bars)
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return result

    async def fetch_raw(self, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
        return await self._fetch_all_pages(symbols, "raw", start, end)

    async def fetch_adj(self, symbols: list[str], start: date, end: date) -> dict[str, list[dict]]:
        return await self._fetch_all_pages(symbols, "all", start, end)


async def get_alpaca_client() -> AlpacaClient | None:
    """Return a configured AlpacaClient, or None if no keys are set."""
    for slot in ("alpaca_live", "alpaca_paper"):
        creds = credential_store.get(slot) or {}
        if creds.get("key_id") and creds.get("secret_key"):
            return AlpacaClient(key_id=creds["key_id"], secret_key=creds["secret_key"])
    return None


def _normalize_bars(
    raw_bars_by_symbol: dict[str, list[dict]],
    adj_bars_by_symbol: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Merge raw + adjusted bar lists into the multi-basis format.

    Returns symbol → list of bars with:
      time, open, high, low, close, volume (raw values)
      adj_factor = adj_close / raw_close
      source = 'alpaca'
    """
    result: dict[str, list[dict]] = {}
    for sym, raw_list in raw_bars_by_symbol.items():
        adj_list = adj_bars_by_symbol.get(sym, [])
        # Build a timestamp → adjClose map for fast lookup
        adj_map = {b["t"]: float(b.get("c", 0) or 0) for b in adj_list}
        bars: list[dict] = []
        for rb in raw_list:
            ts = rb["t"]
            raw_close = float(rb.get("c", 0) or 0)
            adj_close = adj_map.get(ts, raw_close)
            adj_factor = round(adj_close / raw_close, 8) if raw_close != 0 else 1.0
            bars.append({
                "time":         ts[:10],       # YYYY-MM-DD
                "open":         round(float(rb.get("o", 0) or 0), 4),
                "high":         round(float(rb.get("h", 0) or 0), 4),
                "low":          round(float(rb.get("l",  0) or 0), 4),
                "close":        round(raw_close,                    4),
                "volume":       int(rb.get("v", 0) or 0),
                "adj_factor":   adj_factor,
                "split_factor": 1.0,   # Alpaca doesn't separate split vs div; use adj_factor
                "div_cash":     0.0,
                "source":       "alpaca",
            })
        result[sym] = bars
    return result


async def fetch_daily_bars_batch(
    symbols: list[str], start: date, end: date, client: AlpacaClient | None = None
) -> dict[str, list[dict]]:
    """Fetch daily bars for multiple symbols from Alpaca.

    Returns symbol → list of multi-basis bars (raw prices + adj_factor).
    Symbols not returned by Alpaca are absent from the result dict.
    """
    if client is None:
        client = await get_alpaca_client()
    if client is None:
        return {}
    try:
        raw_bars = await client.fetch_raw(symbols, start, end)
        adj_bars = await client.fetch_adj(symbols, start, end)
        return _normalize_bars(raw_bars, adj_bars)
    except Exception as exc:
        logger.warning("Alpaca batch fetch failed: %s", exc)
        return {}


async def fetch_daily_bars_single(
    symbol: str, start: date, end: date, client: AlpacaClient | None = None
) -> list[dict]:
    """Fetch daily bars for a single symbol from Alpaca."""
    result = await fetch_daily_bars_batch([symbol], start, end, client=client)
    return result.get(symbol, [])
```

- [ ] **Step 4: Run — confirm PASSES**

```bash
pytest tests/test_alpaca_adapter.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/data/alpaca.py backend/tests/test_alpaca_adapter.py
git commit -m "feat(alpaca): async daily bars adapter with multi-basis output"
```

---

### Task 4: Update historical_store — multi-basis _store_bars/_read_bars + Alpaca→Tiingo→yfinance chain

**Files:**
- Modify: `backend/app/services/historical_store.py`
- Modify: `backend/tests/test_historical_store_guard.py`

Key changes:
- `_store_bars()`: include adj_factor, split_factor, div_cash, source in upsert (all nullable; falls back to adj_factor=1.0 if bar dict doesn't carry them)
- `_read_bars()`: multiply `close × adj_factor` (if adj_factor is not None, else use close as-is)
- `get_bars()`: try Alpaca first via `fetch_daily_bars_single`, then Tiingo, then yfinance

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_historical_store_guard.py` with:

```python
"""Guard tests: _store_bars writes multi-basis fields; _read_bars returns adjusted prices."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services.historical_store import _store_bars, _read_bars


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_store_bars_writes_multi_basis_fields(session):
    bars = [{
        "time": "2024-01-02",
        "open": 185.0, "high": 186.0, "low": 184.0, "close": 185.5,
        "volume": 1_000_000,
        "adj_factor": 1.025, "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca",
    }]
    await _store_bars("AAPL", bars, session)
    await session.commit()

    from sqlalchemy import select
    result = await session.execute(select(OhlcvDailyModel).where(OhlcvDailyModel.symbol == "AAPL"))
    row = result.scalars().first()
    assert row is not None
    assert float(row.close) == 185.5
    assert abs(float(row.adj_factor) - 1.025) < 1e-6
    assert row.source == "alpaca"


@pytest.mark.asyncio
async def test_read_bars_returns_adjusted_close(session):
    # Store a bar with raw close=100, adj_factor=1.1 → expect read_close = 110.0
    bars = [{
        "time": "2024-01-02",
        "open": 98.0, "high": 102.0, "low": 97.0, "close": 100.0,
        "volume": 500_000,
        "adj_factor": 1.1, "split_factor": 1.0, "div_cash": 0.0, "source": "tiingo",
    }]
    await _store_bars("TSLA", bars, session)
    await session.commit()

    result = await _read_bars("TSLA", date(2024, 1, 1), date(2024, 1, 31), session)
    assert len(result) == 1
    assert abs(result[0]["close"] - 110.0) < 0.01   # 100 × 1.1


@pytest.mark.asyncio
async def test_read_bars_legacy_row_uses_close_directly(session):
    # A row with adj_factor=NULL (legacy tiingo_legacy) → close returned as-is
    bars = [{
        "time": "2023-01-03",
        "open": 130.0, "high": 131.0, "low": 129.0, "close": 130.5,
        "volume": 800_000,
        # no adj_factor key → defaults to None in _store_bars
    }]
    await _store_bars("AAPL", bars, session)
    await session.commit()

    result = await _read_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31), session)
    assert len(result) == 1
    assert result[0]["close"] == 130.5  # no multiplication
```

- [ ] **Step 2: Run — confirm FAILS**

```bash
pytest tests/test_historical_store_guard.py -v
```

Expected: FAIL — `_store_bars` doesn't accept multi-basis fields yet; `_read_bars` doesn't multiply by adj_factor.

- [ ] **Step 3: Update `_store_bars` in historical_store.py**

In `backend/app/services/historical_store.py`, replace the `_store_bars` function (lines ~87–118):

```python
async def _store_bars(symbol: str, bars: list[dict], db: AsyncSession) -> None:
    """Upsert a list of OHLCV bar dicts for `symbol` into the DB.

    Bars may include multi-basis fields (adj_factor, split_factor, div_cash, source);
    if absent they default to None so legacy rows keep their tiingo_legacy fallback.
    """
    if not bars:
        return
    now = datetime.now(timezone.utc)
    rows = [
        {
            "symbol":       symbol,
            "date":         _bar_date(b),
            "open":         b["open"],
            "high":         b["high"],
            "low":          b["low"],
            "close":        b["close"],
            "volume":       b["volume"],
            "adj_factor":   b.get("adj_factor"),
            "split_factor": b.get("split_factor"),
            "div_cash":     b.get("div_cash"),
            "source":       b.get("source"),
            "fetched_at":   now,
        }
        for b in bars
    ]
    insert = _dialect_insert()
    stmt = insert(OhlcvDailyModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_={
            "open":         stmt.excluded.open,
            "high":         stmt.excluded.high,
            "low":          stmt.excluded.low,
            "close":        stmt.excluded.close,
            "volume":       stmt.excluded.volume,
            "adj_factor":   stmt.excluded.adj_factor,
            "split_factor": stmt.excluded.split_factor,
            "div_cash":     stmt.excluded.div_cash,
            "source":       stmt.excluded.source,
            "fetched_at":   stmt.excluded.fetched_at,
        },
    )
    await db.execute(stmt)
```

- [ ] **Step 4: Update `_read_bars` in historical_store.py**

Replace the `_read_bars` function (lines ~121–145):

```python
async def _read_bars(
    symbol: str, start: date, end: date, db: AsyncSession
) -> list[dict]:
    """Read all stored bars for `symbol` between `start` and `end` (inclusive).

    Returns fully-adjusted close: raw_close × adj_factor.
    If adj_factor is NULL (legacy tiingo_legacy rows), close is returned as-is.
    """
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
    out = []
    for row in rows:
        raw_close = float(row.close)
        adj = float(row.adj_factor) if row.adj_factor is not None else None
        fully_adj_close = round(raw_close * adj, 4) if adj is not None else raw_close
        out.append({
            "time":   row.date.isoformat(),
            "open":   float(row.open),
            "high":   float(row.high),
            "low":    float(row.low),
            "close":  fully_adj_close,
            "volume": int(row.volume),
        })
    return out
```

- [ ] **Step 5: Update `get_bars` to use Alpaca → Tiingo → yfinance chain**

In `historical_store.py`, add the import at the top of the file:

```python
from app.data.alpaca import fetch_daily_bars_single
```

Replace the `fetch_needed` block inside `get_bars()` (the `if fetch_needed:` block):

```python
    if fetch_needed:
        fetch_start = (last + timedelta(days=1)) if last else start
        stored = False

        # 1. Try Alpaca (primary)
        try:
            from app.data.alpaca import fetch_daily_bars_single, get_alpaca_client
            alpaca_client = await get_alpaca_client()
            if alpaca_client is not None:
                new_bars = await fetch_daily_bars_single(symbol, fetch_start, end, client=alpaca_client)
                if new_bars:
                    await _store_bars(symbol, new_bars, db)
                    await db.commit()
                    logger.debug("historical_store: Alpaca stored %d bars for %s", len(new_bars), symbol)
                    stored = True
        except Exception as exc:
            logger.warning("historical_store: Alpaca fetch failed for %s — %s", symbol, exc)

        # 2. Tiingo fallback
        if not stored:
            try:
                new_bars = await asyncio.to_thread(
                    fetch_historical_candles, symbol, fetch_start, end
                )
                if new_bars:
                    await _store_bars(symbol, new_bars, db)
                    await db.commit()
                    logger.debug("historical_store: Tiingo stored %d bars for %s", len(new_bars), symbol)
                    stored = True
            except Exception as exc:
                logger.warning("historical_store: Tiingo fetch failed for %s — %s", symbol, exc)

        # 3. yfinance last resort
        if not stored:
            try:
                import yfinance as yf
                yf_bars = await asyncio.to_thread(
                    lambda: _yfinance_fetch(symbol, fetch_start, end)
                )
                if yf_bars:
                    await _store_bars(symbol, yf_bars, db)
                    await db.commit()
                    logger.debug("historical_store: yfinance stored %d bars for %s", len(yf_bars), symbol)
            except Exception as exc:
                logger.warning("historical_store: yfinance fetch failed for %s — %s", symbol, exc)
```

Also add the yfinance helper function at the bottom of the module (before the prefetch section):

```python
def _yfinance_fetch(symbol: str, start: date, end: date) -> list[dict]:
    """yfinance daily bars — last-resort fallback. Returns adj prices (adj_factor=1.0)."""
    try:
        import yfinance as yf
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            df = yf.download(symbol, start=start.isoformat(), end=end.isoformat(),
                             progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        rows = []
        for ts, row in df.iterrows():
            rows.append({
                "time":         ts.strftime("%Y-%m-%d"),
                "open":         round(float(row["Open"]),   4),
                "high":         round(float(row["High"]),   4),
                "low":          round(float(row["Low"]),    4),
                "close":        round(float(row["Close"]),  4),
                "volume":       int(row["Volume"]),
                "adj_factor":   1.0,   # yfinance auto_adjust=True already adjusts
                "split_factor": 1.0,
                "div_cash":     0.0,
                "source":       "yfinance",
            })
        return rows
    except Exception:
        return []
```

- [ ] **Step 6: Run the guard tests to confirm they pass**

```bash
pytest tests/test_historical_store_guard.py -v
```

Expected: 3 passed

- [ ] **Step 7: Run the full backend suite**

```bash
pytest -q
```

Expected: ~502+ passed, 3 skipped, 0 failures.

If test_historical_store.py tests fail because bars no longer return adjClose as close, investigate: the old fixture may need updating to inject multi-basis bars. Fix any such failures before committing.

- [ ] **Step 8: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/historical_store.py backend/tests/test_historical_store_guard.py
git commit -m "feat(store): multi-basis _store_bars/_read_bars + Alpaca→Tiingo→yfinance chain"
```

---

## Self-Review

**Spec coverage (§5.2, §5.4):**
- ✅ `adj_factor / split_factor / div_cash / source` columns added (Task 1)
- ✅ Scanner reads fully-adjusted via `close × adj_factor` (Task 4 `_read_bars`)
- ✅ Raw prices stored (Tasks 2 + 3 store raw `close`)
- ✅ Alpaca primary → Tiingo → yfinance chain (Task 4 `get_bars`)
- ✅ Governor-gated Alpaca calls via `get_governor().call("alpaca", coro)` (Task 3)
- ✅ Existing rows backward compatible via `adj_factor = 1.0` backfill (Task 1 migration + Task 4 NULL guard)
- ✅ `source` column populated by all three adapters
- ✅ Tiingo returns raw prices + adj_factor (Task 2)

**Not in scope (deferred to Stage 3):**
- Batch multi-symbol ingestion (nightly job)
- Provenance logging in scan output
- Scan-path switch to DB-first (scans still call `get_bars()` on-demand)
- Retention/prune job
- adj_factor recomputation on new dividends

**Placeholder scan:** None found. All steps have complete code.

**Type consistency:** `_store_bars(symbol, bars, db)`, `_read_bars(symbol, start, end, db)`, `get_bars(symbol, start, end)`, `fetch_daily_bars_single(symbol, start, end, client?)`, `_normalize_bars(raw, adj)`, `get_alpaca_client()` — consistent across all tasks.
