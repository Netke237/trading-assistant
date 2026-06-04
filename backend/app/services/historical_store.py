"""Persistent OHLCV daily history store backed by the application database.

Design:
- get_bars(symbol, start, end)      : DB-first lookup; fetches only the delta from Tiingo.
- prefetch_universe(symbols, years) : Rate-limited background job that pre-fills the table.
- get_prefetch_status()             : Returns the current prefetch job state.

Bars are written with an upsert (INSERT OR REPLACE for SQLite) so re-running the prefetch
is always safe and idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import os as _os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def _dialect_insert():
    """Return the correct dialect-specific insert for the current DATABASE_URL."""
    url = _os.environ.get("DATABASE_URL", "sqlite")
    if "postgresql" in url:
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert

from app.database import AsyncSessionLocal
from app.data.tiingo import fetch_historical_candles
from app.models.ohlcv_daily import OhlcvDailyModel

logger = logging.getLogger(__name__)

# ── Prefetch progress state (module-level singleton) ─────────────────────────

_prefetch_state: dict[str, Any] = {
    "status":         "idle",   # idle | running | completed | error
    "total":          0,
    "done":           0,
    "failed":         0,
    "current_symbol": None,
    "elapsed_secs":   0,
    "started_at":     None,
}
_prefetch_task: asyncio.Task | None = None

# ── Internal helpers ──────────────────────────────────────────────────────────

def _bar_date(bar: dict) -> date:
    return date.fromisoformat(bar["time"][:10])


async def _store_bars(symbol: str, bars: list[dict], db: AsyncSession) -> None:
    """Upsert a list of OHLCV bar dicts for `symbol` into the DB."""
    if not bars:
        return
    now = datetime.now(timezone.utc)
    rows = [
        {
            "symbol":     symbol,
            "date":       _bar_date(b),
            "open":       b["open"],
            "high":       b["high"],
            "low":        b["low"],
            "close":      b["close"],
            "volume":     b["volume"],
            "fetched_at": now,
        }
        for b in bars
    ]
    insert = _dialect_insert()
    stmt = insert(OhlcvDailyModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "date"],
        set_={
            "open":       stmt.excluded.open,
            "high":       stmt.excluded.high,
            "low":        stmt.excluded.low,
            "close":      stmt.excluded.close,
            "volume":     stmt.excluded.volume,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await db.execute(stmt)


async def _read_bars(
    symbol: str, start: date, end: date, db: AsyncSession
) -> list[dict]:
    """Read all stored bars for `symbol` between `start` and `end` (inclusive)."""
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
    return [
        {
            "time":   row.date.isoformat(),
            "open":   float(row.open),
            "high":   float(row.high),
            "low":    float(row.low),
            "close":  float(row.close),
            "volume": int(row.volume),
        }
        for row in rows
    ]


async def _last_stored_date(symbol: str, db: AsyncSession) -> date | None:
    """Return the most recent date stored for `symbol`, or None if no data."""
    result = await db.execute(
        select(func.max(OhlcvDailyModel.date))
        .where(OhlcvDailyModel.symbol == symbol)
    )
    return result.scalar_one_or_none()


# ── Public API ────────────────────────────────────────────────────────────────

async def get_bars(symbol: str, start: date, end: date) -> list[dict]:
    """Return OHLCV bars for `symbol` from `start` to `end`.

    Algorithm:
    1. Check the DB for the last stored date.
    2. If delta exists (DB is stale or empty), fetch from Tiingo and store it.
    3. Return all bars from the DB in the requested range.
    Falls back gracefully: if Tiingo fails and DB has partial data, returns what's there.
    """
    async with AsyncSessionLocal() as db:
        last = await _last_stored_date(symbol, db)

        fetch_needed = (last is None) or (last < end)
        if fetch_needed:
            fetch_start = (last + timedelta(days=1)) if last else start
            try:
                new_bars = await asyncio.to_thread(
                    fetch_historical_candles, symbol, fetch_start, end
                )
                if new_bars:
                    await _store_bars(symbol, new_bars, db)
                    await db.commit()
                    logger.debug(
                        "historical_store: stored %d new bars for %s (delta %s → %s)",
                        len(new_bars), symbol, fetch_start, end,
                    )
                else:
                    logger.debug(
                        "historical_store: no new bars returned for %s (Tiingo may have failed or symbol has no data for %s → %s)",
                        symbol, fetch_start, end,
                    )
            except Exception as exc:
                logger.warning("historical_store: Tiingo fetch failed for %s — %s", symbol, exc)

        return await _read_bars(symbol, start, end, db)


# ── Background prefetch ───────────────────────────────────────────────────────

async def _run_prefetch(symbols: list[str], years: int, delay_secs: float) -> None:
    """Background coroutine: sequentially fetch full history for each symbol."""
    global _prefetch_state
    start_time = time.monotonic()
    fetch_end   = date.today()
    fetch_start = fetch_end - timedelta(days=years * 365)

    _prefetch_state.update({
        "status":         "running",
        "total":          len(symbols),
        "done":           0,
        "failed":         0,
        "current_symbol": None,
        "started_at":     datetime.now(timezone.utc).isoformat(),
    })

    try:
        for symbol in symbols:
            _prefetch_state["current_symbol"] = symbol
            _prefetch_state["elapsed_secs"]   = round(time.monotonic() - start_time, 1)
            try:
                await get_bars(symbol, fetch_start, fetch_end)
                _prefetch_state["done"] += 1
            except Exception as exc:
                logger.warning("historical_store prefetch: %s failed — %s", symbol, exc)
                _prefetch_state["failed"] += 1
            # Rate-limit: respect Tiingo's free-tier daily quota.
            await asyncio.sleep(delay_secs)

        _prefetch_state.update({
            "status":         "completed",
            "current_symbol": None,
            "elapsed_secs":   round(time.monotonic() - start_time, 1),
        })
        logger.info(
            "historical_store prefetch complete: %d done, %d failed in %.0fs",
            _prefetch_state["done"], _prefetch_state["failed"], _prefetch_state["elapsed_secs"],
        )
    except Exception as exc:
        _prefetch_state.update({
            "status":         "error",
            "current_symbol": None,
            "elapsed_secs":   round(time.monotonic() - start_time, 1),
        })
        logger.error("historical_store prefetch crashed: %s", exc, exc_info=True)


def prefetch_universe(symbols: list[str], years: int = 5, delay_secs: float = 0.5) -> None:
    """Start (or restart) the background prefetch job.

    delay_secs=0.5 → ~2 req/s.  For Tiingo free tier (500 req/day), pre-fetching
    250 symbols per session stays within quota.  Set delay_secs=0.1 for paid plans.
    """
    global _prefetch_task, _prefetch_state
    if _prefetch_state.get("status") == "running":
        logger.warning("historical_store: prefetch already running — ignoring new request")
        return
    _prefetch_task = asyncio.create_task(
        _run_prefetch(symbols, years, delay_secs)
    )


def get_prefetch_status() -> dict:
    """Return a copy of the current prefetch state."""
    return dict(_prefetch_state)
