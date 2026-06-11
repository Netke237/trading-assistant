"""Nightly/manual OHLCV ingestion job.

Runs as a single idempotent operation:
  1. Batch Alpaca fetch for the whole universe.
  2. Per-symbol gap-fill via the existing get_bars() fallback chain (Tiingo -> yfinance)
     for symbols Alpaca didn't return or returned incomplete data for.
  3. Prune rows older than `years` years to bound table size.
  4. Update the ingestion state singleton so callers can track progress.

Entry point: `await run_ingestion(symbols, years=6)`
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.data.alpaca import fetch_daily_bars_batch, get_alpaca_client
from app.models.ohlcv_daily import OhlcvDailyModel
from app.services.historical_store import _store_bars, get_bars, most_recent_trading_day

logger = logging.getLogger(__name__)

# ── Ingestion state singleton ─────────────────────────────────────────────────

_state: dict[str, Any] = {
    "status":         "idle",
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
_ALPACA_CHUNK = 100


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
    """Return True if the DB needs a refresh (no data or last date is stale)."""
    if last_date is None:
        return True
    return last_date < most_recent_trading_day() - timedelta(days=1)


async def _prune_old_rows(years: int) -> int:
    """Delete rows older than `years` years. Returns number of rows deleted."""
    cutoff = date.today() - timedelta(days=years * 365)
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

    _state.update({
        "status":         "running",
        "total":          len(symbols),
        "done":           0,
        "failed":         0,
        "alpaca_count":   0,
        "gapfill_count":  0,
        "pruned_rows":    0,
        "current_symbol": None,
        "started_at":     datetime.now(timezone.utc).isoformat(),
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
                for i in range(0, len(symbols), _ALPACA_CHUNK):
                    chunk = symbols[i:i + _ALPACA_CHUNK]
                    partial = await fetch_daily_bars_batch(chunk, fetch_start, fetch_end, client=alpaca_client)
                    alpaca_result.update(partial)
            except Exception as exc:
                logger.warning("ingestion: Alpaca batch fetch failed — %s", exc)
        else:
            logger.info("ingestion: Alpaca unconfigured, skipping batch fetch")

        # ── Step 2: Store Alpaca bars ─────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            for sym, bars in alpaca_result.items():
                if bars:
                    try:
                        await _store_bars(sym, bars, db)
                        alpaca_count += 1
                        _state["done"] += 1
                    except Exception as exc:
                        logger.warning("ingestion: store failed for %s — %s", sym, exc)
                        errors.append(f"{sym}: store error — {exc}")
                        _state["failed"] += 1
            await db.commit()

        # ── Step 3: Gap-fill missing symbols via historical_store.get_bars() ──
        alpaca_symbols = set(s for s, bars in alpaca_result.items() if bars)
        missing = [s for s in symbols if s not in alpaca_symbols]
        for sym in missing:
            _state["current_symbol"] = sym
            try:
                bars = await get_bars(sym, fetch_start, fetch_end)
                if bars:
                    gapfill_count += 1
                    logger.debug("ingestion: gap-filled %s (%d bars)", sym, len(bars))
            except Exception as exc:
                logger.warning("ingestion: gap-fill failed for %s — %s", sym, exc)
                errors.append(f"{sym}: gap-fill error — {exc}")
                _state["failed"] += 1
            _state["done"] += 1

        # ── Step 4: Prune old rows ─────────────────────────────────────────────
        pruned = await _prune_old_rows(years)
        _state["pruned_rows"] = pruned

        _state.update({
            "status":         "completed",
            "done":           len(symbols),
            "alpaca_count":   alpaca_count,
            "gapfill_count":  gapfill_count,
            "pruned_rows":    pruned,
            "current_symbol": None,
            "finished_at":    datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "ingestion complete: %d symbols, alpaca=%d, gapfill=%d, pruned=%d, failed=%d",
            len(symbols), alpaca_count, gapfill_count, pruned, _state["failed"],
        )

    except Exception as exc:
        _state.update({
            "status":      "error",
            "error":       str(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
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
    """Create an asyncio Task for run_ingestion (fire-and-forget).

    Must be called from inside a running event loop (FastAPI lifespan or endpoint).
    """
    global _task
    if _state.get("status") == "running":
        logger.warning("ingestion: already running — ignoring new request")
        return
    _task = asyncio.create_task(run_ingestion(symbols, years=years))
