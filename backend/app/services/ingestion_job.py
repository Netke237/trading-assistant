"""Nightly/manual OHLCV ingestion job.

Runs as a single idempotent operation:
  1. Batch Alpaca fetch for the whole universe.
  2. Per-symbol coherent older-prefix + current-suffix validation and atomic write.
  3. Prune rows older than `years` years to bound table size.
  4. Update the ingestion state singleton so callers can track progress.

Entry point: `await run_ingestion(symbols)` (configured horizon, default 17 years).
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
from app.services.historical_store import most_recent_trading_day
from app.services.history_backfill import update_history, HistorySeamMismatch
from app.services.history_retention import effective_years

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
    backfilled:    int = 0
    seam_mismatch: int = 0
    floor_reached: int = 0
    backfilled_symbols:    list[str] = field(default_factory=list)
    seam_mismatch_symbols: list[str] = field(default_factory=list)
    floor_reached_symbols: list[str] = field(default_factory=list)
    seam_ratios:   dict[str, float] = field(default_factory=dict)


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
    cutoff = date.today() - timedelta(days=effective_years(years) * 365)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(OhlcvDailyModel).where(OhlcvDailyModel.date < cutoff)
        )
        await db.commit()
        return result.rowcount


async def run_ingestion(
    symbols: list[str],
    years: int | None = None,
    force_backfill: bool = False,
) -> IngestionResult:
    """Run a full ingestion pass for `symbols`.

    Stage Alpaca, validate fallback history, and commit each coherent symbol.
    """
    global _state
    years = effective_years(years)
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))

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
        "years":          years,
        "backfilled":     0,
        "backfilled_symbols": [],
        "seam_mismatch":  0,
        "seam_mismatch_symbols": [],
        "floor_reached":  0,
        "floor_reached_symbols": [],
        "seam_ratios":    {},
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
                    partial = await fetch_daily_bars_batch(chunk, fetch_start, fetch_end,
                                                          client=alpaca_client, strict_adjustments=True)
                    alpaca_result.update(partial)
            except Exception as exc:
                logger.warning("ingestion: Alpaca batch fetch failed — %s", exc)
        else:
            logger.info("ingestion: Alpaca unconfigured, skipping batch fetch")

        # No suffix is persisted before its retained prefix has been validated.
        for sym in symbols:
            _state["current_symbol"] = sym
            try:
                result = await update_history(sym, fetch_start, fetch_end,
                                              alpaca_bars=alpaca_result.get(sym, []),
                                              force_backfill=force_backfill)
                if alpaca_result.get(sym):
                    alpaca_count += 1
                else:
                    gapfill_count += 1
                for name in ("backfilled", "floor_reached"):
                    if getattr(result, name):
                        _state[name] += 1
                        _state[name + "_symbols"].append(sym)
            except HistorySeamMismatch as exc:
                _state["seam_mismatch"] += 1
                _state["seam_mismatch_symbols"].append(sym)
                if exc.ratio is not None:
                    _state["seam_ratios"][sym] = exc.ratio
                _state["failed"] += 1
                errors.append(f"{sym}: seam mismatch — {exc}")
            except Exception as exc:
                logger.warning("ingestion: history failed for %s — %s", sym, exc)
                errors.append(f"{sym}: history error — {exc}")
                _state["failed"] += 1
            _state["done"] += 1

        # ── Step 4: Prune old rows ─────────────────────────────────────────────
        pruned = await _prune_old_rows(years) if symbols else 0
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
        backfilled=_state["backfilled"],
        seam_mismatch=_state["seam_mismatch"],
        floor_reached=_state["floor_reached"],
        backfilled_symbols=list(_state["backfilled_symbols"]),
        seam_mismatch_symbols=list(_state["seam_mismatch_symbols"]),
        floor_reached_symbols=list(_state["floor_reached_symbols"]),
        seam_ratios=dict(_state["seam_ratios"]),
    )


def start_ingestion_task(symbols: list[str], years: int | None = None,
                         force_backfill: bool = False) -> bool:
    """Create an asyncio Task for run_ingestion (fire-and-forget).

    Must be called from inside a running event loop (FastAPI lifespan or endpoint).
    """
    global _task
    if (_task is not None and not _task.done()) or _state.get("status") == "running":
        logger.warning("ingestion: already running — ignoring new request")
        return False
    _task = asyncio.create_task(run_ingestion(symbols, years=years, force_backfill=force_backfill))
    return True
