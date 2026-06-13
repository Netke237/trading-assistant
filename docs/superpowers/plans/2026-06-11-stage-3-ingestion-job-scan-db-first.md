# Stage 3: Ingestion Job + Startup Catch-up + DB-First Options Scan + Provenance Logging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Governor-paced nightly ingestion job that pre-fills the OHLCV DB for the full universe, wire a startup catch-up, switch the options scan from 503 Tradier-per-symbol OHLCV calls to DB-first reads, and add per-scan provenance logging.

**Architecture:** A new `ingestion_job.py` service runs Alpaca batch → per-symbol gap-fill → 6-year prune as one idempotent function. A new `ingestion.py` router exposes `POST /api/data/ingest` + status. `main.py`'s lifespan runs the job if the DB is stale. The options scan (`scan.py`) pre-fetches all symbol bars from `historical_store` before the symbol loop and passes them into `_process_symbol` via a `bars_map` dict — eliminating the per-symbol Tradier OHLCV calls. Each scan emits a structured provenance summary log.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy v2, pytest-asyncio, httpx (mocked in tests).

**Source spec:** `docs/superpowers/specs/2026-06-11-data-loading-and-provider-governor-design.md` §5.3, §5.7.

---

## File Structure

- **Create** `backend/app/services/ingestion_job.py` — batch ingestion, gap-fill, prune logic
- **Create** `backend/app/routers/ingestion.py` — `POST /api/data/ingest` + status endpoint
- **Modify** `backend/app/main.py` — register ingestion router, add startup catch-up
- **Modify** `backend/app/routers/scan.py` — DB-first bars pre-fetch, `bars_map` passed to `_process_symbol`, provenance log at end
- **Create** `backend/tests/test_ingestion_job.py` — unit tests for ingestion logic
- **Create** `backend/tests/test_ingestion_router.py` — unit tests for the HTTP endpoint

Run all commands from `backend/`. Test command: `python -m pytest tests/<file> -v`.

---

### Task 1: ingestion_job.py — batch ingestion + gap-fill + prune

**Files:**
- Create: `backend/app/services/ingestion_job.py`
- Create: `backend/tests/test_ingestion_job.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_ingestion_job.py`:

```python
"""Unit tests for the ingestion job."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ingestion_job import (
    IngestionResult,
    run_ingestion,
    _should_ingest,
)


@pytest.mark.asyncio
async def test_run_ingestion_returns_result():
    """Minimal happy path: Alpaca returns bars for all symbols, no gap-fill needed."""
    symbols = ["AAPL", "MSFT"]
    fake_bars = {
        "AAPL": [{"time": "2024-01-02", "open": 180.0, "high": 181.0, "low": 179.0,
                  "close": 180.5, "volume": 1_000_000, "adj_factor": 1.0,
                  "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca"}],
        "MSFT": [{"time": "2024-01-02", "open": 370.0, "high": 372.0, "low": 369.0,
                  "close": 371.0, "volume": 800_000, "adj_factor": 1.0,
                  "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca"}],
    }
    with patch("app.services.ingestion_job.fetch_daily_bars_batch", new_callable=AsyncMock) as mock_batch, \
         patch("app.services.ingestion_job.AsyncSessionLocal") as mock_session_cls:

        mock_batch.return_value = fake_bars

        # Mock the DB session as an async context manager
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await run_ingestion(symbols, years=1)

    assert isinstance(result, IngestionResult)
    assert result.total == 2
    assert result.alpaca_count >= 0
    assert result.failed == 0


def test_should_ingest_when_stale():
    """_should_ingest returns True if last_date is more than 1 trading day behind."""
    yesterday = date.today() - timedelta(days=2)  # clearly stale
    assert _should_ingest(yesterday) is True


def test_should_ingest_when_no_data():
    """_should_ingest returns True if no last_date."""
    assert _should_ingest(None) is True


def test_should_not_ingest_when_fresh():
    """_should_ingest returns False if last_date is today or yesterday."""
    today = date.today()
    assert _should_ingest(today) is False
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_ingestion_job.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ingestion_job'`

- [ ] **Step 3: Create `backend/app/services/ingestion_job.py`**

```python
"""Nightly/manual OHLCV ingestion job.

Runs as a single idempotent operation:
  1. Batch Alpaca fetch for the whole universe.
  2. Per-symbol gap-fill via the existing get_bars() fallback chain (Tiingo → yfinance)
     for symbols Alpaca didn't return or returned incomplete data for.
  3. Prune rows older than `years` years to bound table size.
  4. Update the ingestion state singleton so callers can track progress.

Entry point: `await run_ingestion(symbols, years=6)`
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.database import AsyncSessionLocal
from app.data.alpaca import fetch_daily_bars_batch, get_alpaca_client
from app.services.historical_store import _store_bars, _last_stored_date, most_recent_trading_day
from sqlalchemy import delete, func, select

logger = logging.getLogger(__name__)

# ── Ingestion state singleton ─────────────────────────────────────────────────

_state: dict[str, Any] = {
    "status":         "idle",   # idle | running | completed | error
    "total":          0,
    "done":           0,
    "failed":         0,
    "alpaca_count":   0,
    "gapfill_count":  0,
    "pruned_rows":    0,
    "current_symbol": None,
    "started_at":     None,
    "finished_at":    None,
    "error":          None,
}
_task: asyncio.Task | None = None


@dataclass
class IngestionResult:
    total:         int
    alpaca_count:  int
    gapfill_count: int
    pruned_rows:   int
    failed:        int
    errors:        list[str] = field(default_factory=list)


def get_ingestion_state() -> dict:
    """Return a snapshot of the current ingestion state."""
    return dict(_state)


def _should_ingest(last_date: date | None) -> bool:
    """Return True if the DB needs a refresh (no data or last date is before most recent close)."""
    if last_date is None:
        return True
    return last_date < most_recent_trading_day() - timedelta(days=1)


async def _prune_old_rows(years: int) -> int:
    """Delete rows older than `years` years. Returns number of rows deleted."""
    cutoff = date.today() - timedelta(days=years * 365)
    from app.models.ohlcv_daily import OhlcvDailyModel
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(OhlcvDailyModel).where(OhlcvDailyModel.date < cutoff)
        )
        await db.commit()
        return result.rowcount


async def run_ingestion(
    symbols: list[str],
    years: int = 6,
) -> IngestionResult:
    """Run a full ingestion pass for `symbols`.

    Fetches up to `years` years of daily bars. Alpaca batch first; per-symbol
    gap-fill (via get_bars fallback chain) for any symbols Alpaca missed.
    Prunes rows older than `years` years when done.
    """
    global _state
    from datetime import datetime, timezone as _tz

    _state.update({
        "status":         "running",
        "total":          len(symbols),
        "done":           0,
        "failed":         0,
        "alpaca_count":   0,
        "gapfill_count":  0,
        "pruned_rows":    0,
        "current_symbol": None,
        "started_at":     datetime.now(_tz.utc).isoformat(),
        "finished_at":    None,
        "error":          None,
    })

    errors: list[str] = []
    alpaca_count = 0
    gapfill_count = 0
    fetch_end = date.today()
    fetch_start = fetch_end - timedelta(days=years * 365)

    try:
        # ── Step 1: Alpaca batch fetch ────────────────────────────────────────
        alpaca_client = await get_alpaca_client()
        alpaca_result: dict[str, list[dict]] = {}
        if alpaca_client is not None:
            try:
                # Alpaca allows up to 200 req/min; for large universes split into chunks
                # Each chunk is one paginated API call — the Governor enforces the rate.
                _CHUNK = 100
                for i in range(0, len(symbols), _CHUNK):
                    chunk = symbols[i:i + _CHUNK]
                    partial = await fetch_daily_bars_batch(chunk, fetch_start, fetch_end, client=alpaca_client)
                    alpaca_result.update(partial)
            except Exception as exc:
                logger.warning("ingestion: Alpaca batch fetch failed — %s", exc)
        else:
            logger.info("ingestion: Alpaca unconfigured, skipping batch fetch")

        # ── Step 2: Store Alpaca bars + gap-fill missing symbols ─────────────
        alpaca_symbols = set(alpaca_result.keys())
        missing_symbols = [s for s in symbols if s not in alpaca_symbols or not alpaca_result[s]]

        # Store Alpaca bars
        async with AsyncSessionLocal() as db:
            for sym, bars in alpaca_result.items():
                if bars:
                    try:
                        await _store_bars(sym, bars, db)
                        alpaca_count += 1
                    except Exception as exc:
                        logger.warning("ingestion: store failed for %s — %s", sym, exc)
                        errors.append(f"{sym}: store error — {exc}")
            await db.commit()

        # Gap-fill via historical_store.get_bars() (Tiingo → yfinance fallback)
        from app.services.historical_store import get_bars as _get_bars
        for sym in missing_symbols:
            _state["current_symbol"] = sym
            try:
                bars = await _get_bars(sym, fetch_start, fetch_end)
                if bars:
                    gapfill_count += 1
                    logger.debug("ingestion: gap-filled %s (%d bars)", sym, len(bars))
            except Exception as exc:
                logger.warning("ingestion: gap-fill failed for %s — %s", sym, exc)
                errors.append(f"{sym}: gap-fill error — {exc}")
                _state["failed"] += 1
            _state["done"] += 1

        # ── Step 3: Prune old rows ───────────────────────────────────────────
        pruned = await _prune_old_rows(years)
        _state["pruned_rows"] = pruned

        _state.update({
            "status":         "completed",
            "done":           len(symbols),
            "alpaca_count":   alpaca_count,
            "gapfill_count":  gapfill_count,
            "pruned_rows":    pruned,
            "current_symbol": None,
            "finished_at":    datetime.now(_tz.utc).isoformat(),
        })
        logger.info(
            "ingestion complete: %d symbols, alpaca=%d, gapfill=%d, pruned=%d, failed=%d",
            len(symbols), alpaca_count, gapfill_count, pruned, _state["failed"],
        )

    except Exception as exc:
        _state.update({
            "status": "error",
            "error":  str(exc),
            "finished_at": datetime.now(_tz.utc).isoformat(),
        })
        logger.error("ingestion crashed: %s", exc, exc_info=True)
        errors.append(f"crash: {exc}")

    return IngestionResult(
        total=len(symbols),
        alpaca_count=alpaca_count,
        gapfill_count=gapfill_count,
        pruned_rows=_state.get("pruned_rows", 0),
        failed=_state["failed"],
        errors=errors,
    )


def start_ingestion_task(symbols: list[str], years: int = 6) -> None:
    """Fire-and-forget: create an asyncio Task for `run_ingestion`.

    Call from inside an already-running event loop (e.g. FastAPI lifespan or endpoint).
    """
    global _task
    if _state.get("status") == "running":
        logger.warning("ingestion: already running — ignoring new request")
        return
    _task = asyncio.create_task(run_ingestion(symbols, years=years))
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_ingestion_job.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/services/ingestion_job.py backend/tests/test_ingestion_job.py
git commit -m "feat(ingestion): batch ingestion job with Alpaca batch, gap-fill, and 6-year prune"
```

---

### Task 2: ingestion.py router + startup catch-up in main.py

**Files:**
- Create: `backend/app/routers/ingestion.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_ingestion_router.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_ingestion_router.py`:

```python
"""Tests for the ingestion router."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_ingest_post_triggers_job(app):
    with patch("app.routers.ingestion.start_ingestion_task") as mock_start:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/data/ingest", json={"symbols": ["AAPL", "MSFT"], "years": 1})
    assert resp.status_code == 202
    mock_start.assert_called_once()
    body = resp.json()
    assert body["status"] == "started"
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_ingest_status_returns_state(app):
    with patch("app.routers.ingestion.get_ingestion_state") as mock_state:
        mock_state.return_value = {
            "status": "completed", "total": 5, "done": 5, "failed": 0,
            "alpaca_count": 4, "gapfill_count": 1, "pruned_rows": 12,
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["alpaca_count"] == 4
```

- [ ] **Step 2: Check if `create_app` exists in main.py**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant/backend"
grep -n "create_app\|def create_app" app/main.py
```

If `create_app` doesn't exist, add it at the end of `main.py`:
```python
def create_app() -> FastAPI:
    return app
```

- [ ] **Step 3: Run tests — confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_ingestion_router.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.ingestion'`

- [ ] **Step 4: Create `backend/app/routers/ingestion.py`**

```python
"""Ingestion router — manual trigger and status endpoint.

POST /api/data/ingest  → trigger an ingestion run (fire-and-forget)
GET  /api/data/ingest/status → current job state
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.ingestion_job import start_ingestion_task, get_ingestion_state

router = APIRouter(prefix="/api/data", tags=["ingestion"])


class IngestRequest(BaseModel):
    symbols: list[str]
    years: int = Field(default=6, ge=1, le=10)


@router.post("/ingest", status_code=202)
async def trigger_ingest(req: IngestRequest) -> dict:
    """Trigger a background ingestion run. Returns immediately."""
    start_ingestion_task(req.symbols, years=req.years)
    return {"status": "started", "total": len(req.symbols), "years": req.years}


@router.get("/ingest/status")
async def ingest_status() -> dict:
    """Return the current ingestion job state."""
    return get_ingestion_state()
```

- [ ] **Step 5: Register the router in `main.py`**

In `backend/app/main.py`, add the import with the other router imports:
```python
from app.routers.ingestion import router as ingestion_router
```

And register it in the FastAPI app (after the other `app.include_router(...)` calls):
```python
app.include_router(ingestion_router)
```

- [ ] **Step 6: Add startup catch-up to `main.py` lifespan**

In the `lifespan` function's startup section (just before `yield`), add:

```python
    # Startup catch-up: if DB is stale (no data or last bar > 1 day old), trigger ingestion.
    try:
        from app.services.ingestion_job import _should_ingest, start_ingestion_task
        from app.services.historical_store import _last_stored_date
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as _db:
            _last = await _last_stored_date("SPY", _db)  # SPY as a proxy for freshness
        if _should_ingest(_last):
            from app.data.universe import expand_universe
            _universe = expand_universe("SP500") + expand_universe("NDX100") + expand_universe("DOW30")
            _universe = list(dict.fromkeys(_universe))  # dedup, preserve order
            start_ingestion_task(_universe, years=6)
            logger.info("startup: DB stale (last SPY date=%s), started ingestion for %d symbols", _last, len(_universe))
    except Exception as _exc:
        logger.warning("startup catch-up failed: %s", _exc)
```

Add `import logging` at the top of main.py if not already present. Add `logger = logging.getLogger(__name__)`.

- [ ] **Step 7: Check that `expand_universe` exists and how it works**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
grep -rn "def expand_universe\|expand_universe" app/data/ --include="*.py" | head -10
```

If `expand_universe` is not in `app/data/universe.py`, check `app/data/` for a universe helper:
```bash
ls app/data/
```

Use whatever function expands "SP500" / "NDX100" / "DOW30" into symbol lists. If not found, use a simple fallback:
```python
_universe = ["SPY"]  # minimal fallback; real universe populated via POST /api/data/ingest
```

- [ ] **Step 8: Run tests — confirm PASS**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_ingestion_router.py -v
```

Expected: 2 passed.

- [ ] **Step 9: Run full suite**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest -q
```

Expected: all pass.

- [ ] **Step 10: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/routers/ingestion.py backend/app/main.py backend/tests/test_ingestion_router.py
git commit -m "feat(ingestion): manual trigger endpoint + startup catch-up"
```

---

### Task 3: Switch options scan to DB-first OHLCV + provenance logging

This task changes `backend/app/routers/scan.py` so the options scan pre-fetches all symbol bars from `historical_store` before the symbol loop, passes them into `_process_symbol` via `bars_map`, and logs a provenance summary at the end of each scan.

**Files:**
- Modify: `backend/app/routers/scan.py`

The key change: in `_process_symbol`, `candles` is currently fetched via `fetch_candles_async`. We add a `bars_map` parameter. When `bars_map` is provided and has an entry for the symbol, use those bars directly instead of calling Tradier.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_scan_db_first.py`:

```python
"""Test that _process_symbol uses DB bars when bars_map is provided."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from app.routers.scan import _process_symbol
from app.schemas import RejectedCandidate


FAKE_BARS = [
    {"time": "2024-01-02", "open": 180.0, "high": 182.0, "low": 179.0, "close": 181.0, "volume": 1_000_000}
    for _ in range(252)
]


@pytest.mark.asyncio
async def test_process_symbol_uses_bars_map_not_tradier():
    """When bars_map is provided, fetch_candles_async must NOT be called."""
    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=sem)
    sem.__aexit__ = AsyncMock(return_value=False)

    with patch("app.routers.scan.fetch_candles_async") as mock_candles, \
         patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0), \
         patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="Apple"), \
         patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}), \
         patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)), \
         patch("app.routers.scan.score_stock") as mock_score:

        mock_score.return_value = MagicMock(status="REJECT", score=20, components={})

        result = await _process_symbol(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            client=AsyncMock(),
            sem=sem,
            scan_id="test-scan-1",
            bars_map={"AAPL": FAKE_BARS},
        )

    # fetch_candles_async must NOT have been called — bars came from bars_map
    mock_candles.assert_not_called()
    # Should still return a result (pass or reject based on score)
    assert result is not None
```

- [ ] **Step 2: Run test — confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_scan_db_first.py -v
```

Expected: FAIL — either `bars_map` parameter doesn't exist or `fetch_candles_async` is still called.

- [ ] **Step 3: Modify `_process_symbol` in scan.py to accept `bars_map`**

Find the `_process_symbol` function signature (around line 186–200 in the WIP file). Add `bars_map: dict | None = None` to the parameters. Then change the candle fetch logic:

**Current code (in Pass 1 section around lines 209–226):**
```python
    async with sem:
        if prefetched_price:
            candles, company, fund_data = await asyncio.gather(
                fetch_candles_async(client, symbol),
                fetch_company_name_async(client, symbol),
                fetch_fundamentals_calendar(client, symbol),
            )
            price = prefetched_price
        else:
            candles, price, company, fund_data = await asyncio.gather(
                fetch_candles_async(client, symbol),
                fetch_price_async(client, symbol),
                fetch_company_name_async(client, symbol),
                fetch_fundamentals_calendar(client, symbol),
            )
```

**New code:**
```python
    async with sem:
        # Use pre-fetched bars from DB when available — avoids per-symbol Tradier OHLCV calls.
        db_bars = (bars_map or {}).get(symbol) if bars_map else None
        if prefetched_price:
            if db_bars is not None:
                company, fund_data = await asyncio.gather(
                    fetch_company_name_async(client, symbol),
                    fetch_fundamentals_calendar(client, symbol),
                )
                candles = db_bars
            else:
                candles, company, fund_data = await asyncio.gather(
                    fetch_candles_async(client, symbol),
                    fetch_company_name_async(client, symbol),
                    fetch_fundamentals_calendar(client, symbol),
                )
            price = prefetched_price
        else:
            if db_bars is not None:
                (price, company, fund_data) = await asyncio.gather(
                    fetch_price_async(client, symbol),
                    fetch_company_name_async(client, symbol),
                    fetch_fundamentals_calendar(client, symbol),
                )
                candles = db_bars
            else:
                candles, price, company, fund_data = await asyncio.gather(
                    fetch_candles_async(client, symbol),
                    fetch_price_async(client, symbol),
                    fetch_company_name_async(client, symbol),
                    fetch_fundamentals_calendar(client, symbol),
                )
```

- [ ] **Step 4: Update the main scan function to pre-fetch bars and pass `bars_map`**

Find the main scan endpoint function (`async def scan(...)` or `async def run_scan(...)`) where `_process_symbol` is called in a loop. Look for where the list of tasks is built (something like `asyncio.gather(*[_process_symbol(sym, ...) for sym in symbols])`).

Before that loop, add a DB pre-fetch:

```python
    # Pre-fetch OHLCV bars from DB for all symbols — replaces per-symbol Tradier calls.
    from app.services.historical_store import get_bars as _get_bars
    from datetime import date as _date, timedelta as _td
    _bar_end = _date.today()
    _bar_start = _bar_end - _td(days=int(1.75 * 252))  # ~1.75 calendar days per trading day
    _bars_tasks = {sym: _get_bars(sym, _bar_start, _bar_end) for sym in symbols}
    _bars_results = await asyncio.gather(*_bars_tasks.values(), return_exceptions=True)
    bars_map = {
        sym: result
        for sym, result in zip(_bars_tasks.keys(), _bars_results)
        if isinstance(result, list) and result
    }
    _bars_from_db = len(bars_map)
    _bars_missed = len(symbols) - _bars_from_db
```

Then pass `bars_map=bars_map` to each `_process_symbol` call.

- [ ] **Step 5: Add provenance log at end of scan**

After the `asyncio.gather` that collects all `_process_symbol` results, add:

```python
    # Per-scan provenance summary
    _log.info(
        "SCAN %s data-provenance: bars_from_db=%d bars_missed=%d symbols=%d",
        scan_id, _bars_from_db, _bars_missed, len(symbols),
    )
```

- [ ] **Step 6: Run the new test and verify it passes**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_scan_db_first.py -v
```

Expected: 1 passed.

- [ ] **Step 7: Run full test suite**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest -q
```

Expected: all pass, 0 failures.

If existing scan tests break because `_process_symbol` now has a new `bars_map` parameter, those tests may need to be updated to pass `bars_map=None` or `bars_map={}`. Investigate and fix any failures.

- [ ] **Step 8: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/routers/scan.py backend/tests/test_scan_db_first.py
git commit -m "feat(scan): DB-first OHLCV for options scan + provenance log"
```

---

## Self-Review

**Spec coverage (§5.3, §5.7):**
- ✅ Batch Alpaca ingestion (Task 1)
- ✅ Per-symbol gap-fill via existing `get_bars()` chain (Task 1)
- ✅ 6-year retention prune (Task 1 `_prune_old_rows`)
- ✅ Manual trigger endpoint `POST /api/data/ingest` (Task 2)
- ✅ Startup catch-up (Task 2 lifespan)
- ✅ DB-first reads for options scan OHLCV (Task 3) — stock scan already DB-first from Stage 2
- ✅ Provenance logging per scan (Task 3 provenance log)
- ✅ `ingestion_job._should_ingest()` guards against redundant re-runs (Task 1)

**Not in scope (deferred):**
- Nightly scheduler trigger (OS task / Windows Task Scheduler — outside the app per spec §10)
- `adj_factor` recomputation on new dividends (spec §10)
- Configurable ingestion universe UI (spec mentions config; defaulting to SP500∪NDX100∪DOW30 in startup is sufficient)
- IV rank, earnings calendar, market cap ingestion steps (§5.3 steps 3–6) — heavy; separate concern

**Placeholder scan:** None found.

**Type consistency:** `run_ingestion(symbols: list[str], years: int) → IngestionResult`, `start_ingestion_task(symbols, years)`, `get_ingestion_state() → dict`, `_should_ingest(last_date: date | None) → bool`, `_process_symbol(..., bars_map: dict | None = None)` — consistent across tasks.
