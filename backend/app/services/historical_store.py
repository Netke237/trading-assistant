"""Persistent OHLCV daily history store backed by the application database.

Design:
- get_bars(symbol, start, end)      : DB-first lookup; fetches the delta via Alpaca → Tiingo → yfinance.
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
from app.scoring.signal_confidence import compute_confidence
from app.data.confidence_cache import (
    cache_key as conf_cache_key, get_cached, set_cached,
)

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

# ── Trading-day helpers ───────────────────────────────────────────────────────

def most_recent_trading_day() -> date:
    """Return the most recent US market close date (Mon–Fri, no holiday check).

    On weekends returns the preceding Friday. During live market hours today
    is returned (data may still be updating).
    """
    today = date.today()
    weekday = today.weekday()   # 0=Mon … 6=Sun
    if weekday == 5:             # Saturday → Friday
        return today - timedelta(days=1)
    if weekday == 6:             # Sunday → Friday
        return today - timedelta(days=2)
    return today


def _prev_trading_day() -> date:
    """Return the last fully completed trading day (one session before today)."""
    d = most_recent_trading_day() - timedelta(days=1)
    while d.weekday() >= 5:  # skip Saturday (5) and Sunday (6)
        d -= timedelta(days=1)
    return d


# ── Internal helpers ──────────────────────────────────────────────────────────

def _bar_date(bar: dict) -> date:
    return date.fromisoformat(bar["time"][:10])


async def _store_bars(symbol: str, bars: list[dict], db: AsyncSession) -> None:
    """Upsert a list of OHLCV bar dicts for `symbol` into the DB.

    Bars may include multi-basis fields (adj_factor, split_factor, div_cash, source);
    if absent they default to None so legacy rows keep their tiingo_legacy backfill.
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
        fully_adj_close = round(raw_close * adj, 6) if adj is not None else raw_close
        out.append({
            "time":   row.date.isoformat(),
            "open":   float(row.open),
            "high":   float(row.high),
            "low":    float(row.low),
            "close":  fully_adj_close,
            "volume": int(row.volume),
        })
    return out


async def _last_stored_date(symbol: str, db: AsyncSession) -> date | None:
    """Return the most recent date stored for `symbol`, or None if no data."""
    result = await db.execute(
        select(func.max(OhlcvDailyModel.date))
        .where(OhlcvDailyModel.symbol == symbol)
    )
    return result.scalar_one_or_none()


def _yfinance_fetch(symbol: str, start: date, end: date) -> list[dict]:
    """yfinance daily bars — last-resort fallback. Returns adj prices (adj_factor=1.0)."""
    try:
        import io
        import contextlib
        import yfinance as yf
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            df = yf.download(
                symbol,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )
        if df is None or df.empty:
            return []
        import pandas as pd
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        rows = []
        for ts, row in df.iterrows():
            rows.append({
                "time":         ts.strftime("%Y-%m-%d"),
                "open":         round(float(row["Open"]),  4),
                "high":         round(float(row["High"]),  4),
                "low":          round(float(row["Low"]),   4),
                "close":        round(float(row["Close"]), 4),
                "volume":       int(row["Volume"]),
                "adj_factor":   1.0,
                "split_factor": 1.0,
                "div_cash":     0.0,
                "source":       "yfinance",
            })
        return rows
    except Exception as exc:
        logger.debug("_yfinance_fetch: failed for %s — %s", symbol, exc)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def get_bars(symbol: str, start: date, end: date) -> list[dict]:
    """Return OHLCV bars for `symbol` from `start` to `end`.

    Algorithm:
    1. Check the DB for the last stored date.
    2. If a delta exists (DB is stale or empty), fetch via Alpaca → Tiingo → yfinance (first success wins).
    3. Return all bars from the DB in the requested range.
    Falls back gracefully: if all providers fail and DB has partial data, returns what's there.
    """
    async with AsyncSessionLocal() as db:
        last = await _last_stored_date(symbol, db)

        fetch_needed = (last is None) or (last < min(end, _prev_trading_day()))
        if fetch_needed:
            fetch_start = (last + timedelta(days=1)) if last else start
            stored = False

            # 1. Alpaca (primary)
            try:
                from app.data.alpaca import fetch_daily_bars_single, get_alpaca_client
                alpaca_client = await get_alpaca_client()
                if alpaca_client is not None:
                    new_bars = await fetch_daily_bars_single(
                        symbol, fetch_start, end, client=alpaca_client
                    )
                    if new_bars:
                        await _store_bars(symbol, new_bars, db)
                        await db.commit()
                        logger.debug(
                            "historical_store: Alpaca stored %d bars for %s",
                            len(new_bars), symbol,
                        )
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
                        logger.debug(
                            "historical_store: Tiingo stored %d bars for %s",
                            len(new_bars), symbol,
                        )
                        stored = True
                except Exception as exc:
                    logger.warning("historical_store: Tiingo fetch failed for %s — %s", symbol, exc)

            # 3. yfinance last resort
            if not stored:
                try:
                    new_bars = await asyncio.to_thread(
                        _yfinance_fetch, symbol, fetch_start, end
                    )
                    if new_bars:
                        await _store_bars(symbol, new_bars, db)
                        await db.commit()
                        logger.debug(
                            "historical_store: yfinance stored %d bars for %s",
                            len(new_bars), symbol,
                        )
                except Exception as exc:
                    logger.warning(
                        "historical_store: yfinance fetch failed for %s — %s", symbol, exc
                    )

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
                bars = await get_bars(symbol, fetch_start, fetch_end)
                _prefetch_state["done"] += 1
                if bars:
                    _combos = [
                        (conf_cache_key(symbol, _d, _h), _d, _h)
                        for _d in ("Bullish", "Bearish")
                        for _h in ("Intraday", "Swing", "Position")
                        if get_cached(conf_cache_key(symbol, _d, _h)) is None
                    ]
                    if _combos:
                        _conf_tasks = [
                            asyncio.to_thread(
                                compute_confidence, bars,
                                direction=_d, horizon=_h,
                            )
                            for _, _d, _h in _combos
                        ]
                        _conf_results = await asyncio.gather(
                            *_conf_tasks, return_exceptions=True
                        )
                        for (_ck, _d, _h), _res in zip(_combos, _conf_results):
                            if isinstance(_res, BaseException):
                                logger.debug(
                                    "prefetch: confidence pre-warm failed %s/%s/%s — %s",
                                    symbol, _d, _h, _res,
                                )
                            else:
                                set_cached(_ck, {
                                    "confidence": _res.confidence,
                                    "sample_size": _res.sample_size,
                                })
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
