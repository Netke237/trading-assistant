"""Nightly/manual OHLCV ingestion job.

Runs as a single idempotent operation:
  1. Batch Alpaca fetch for the whole universe.
  2. Per-symbol coherent older-prefix + current-suffix validation and atomic write.
  3. Prune rows older than `years` years to bound table size.
  4. Update the ingestion state singleton so callers can track progress.

Entry point: `await run_ingestion(symbols)` (configured horizon, default 17 years).

A symbol whose seam is refused is rebuilt from one provider in the same pass
(`rebuild_single_provider`, trigger "seam_refusal"); `rebuild=True` rebuilds every
requested symbol instead of updating it (trigger "request").
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.data import universe_exclusions
from app.database import AsyncSessionLocal
from app.data.alpaca import fetch_daily_bars_batch, get_alpaca_client
from app.models.ohlcv_daily import OhlcvDailyModel, OhlcvHistoryStateModel
from app.services.historical_store import _last_stored_date, most_recent_trading_day
from app.services.history_backfill import (
    HistorySeamMismatch,
    SingleProviderRefused,
    rebuild_single_provider,
    update_history,
)
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
    "rebuilt":        0,
    "rebuilt_symbols": [],
    "rebuild_details": {},
    "rebuild_refused": 0,
    "rebuild_refused_symbols": [],
    "rebuild_errors": {},
    "single_provider_updated": 0,
    "single_provider_failed_symbols": [],
    "single_provider_errors": {},
}
_task: asyncio.Task | None = None
_ALPACA_CHUNK = 100

# Startup decides "the DB is stale" from this symbol, so every run must refresh it.
STALENESS_REFERENCE = "SPY"


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
    rebuilt:       int = 0
    rebuilt_symbols: list[str] = field(default_factory=list)
    rebuild_details: dict[str, dict] = field(default_factory=dict)
    rebuild_refused: int = 0
    rebuild_refused_symbols: list[str] = field(default_factory=list)
    rebuild_errors: dict[str, str] = field(default_factory=dict)
    single_provider_updated: int = 0
    single_provider_failed_symbols: list[str] = field(default_factory=list)
    single_provider_errors: dict[str, str] = field(default_factory=dict)


def get_ingestion_state() -> dict:
    """Return a snapshot of the current ingestion state."""
    return dict(_state)


async def single_provider_symbols() -> dict:
    """Symbols whose retained series comes from one provider (survives restarts)."""
    async with AsyncSessionLocal() as db:
        states = (await db.execute(
            select(OhlcvHistoryStateModel)
            .where(OhlcvHistoryStateModel.basis_provider.is_not(None))
            .order_by(OhlcvHistoryStateModel.symbol)
        )).scalars().all()
    return {
        s.symbol: {
            "provider":   s.basis_provider,
            "rebuilt_at": s.basis_rebuilt_at.isoformat() if s.basis_rebuilt_at else None,
            "floor_date": s.floor_date.isoformat() if s.floor_date else None,
        }
        for s in states
    }


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def _record_rebuilt(sym: str, result, trigger: str) -> None:
    _state["rebuilt"] += 1
    _state["rebuilt_symbols"].append(sym)
    _state["rebuild_details"][sym] = {
        "provider":          result.provider,
        "trigger":           trigger,
        "rows_before":       result.rows_before,
        "rows_after":        result.rows_after,
        "first_date_before": _iso(result.first_date_before),
        "first_date_after":  _iso(result.first_date_after),
        "last_date_after":   _iso(result.last_date_after),
    }


def _record_rebuild_refused(sym: str, exc: SingleProviderRefused) -> None:
    _state["failed"] += 1
    _state["rebuild_refused"] += 1
    _state["rebuild_refused_symbols"].append(sym)
    _state["rebuild_errors"][sym] = str(exc)


def _without_scan_exclusions(symbols: list[str]) -> list[str]:
    """Drop `scope: scan` exclusions; fail open (unfiltered) if the list cannot be loaded."""
    try:
        kept, excluded = universe_exclusions.filter_symbols(symbols, purpose="scan")
    except Exception as exc:
        logger.warning("ingestion: exclusion list unavailable, ingesting the full universe — %s", exc)
        return symbols
    logger.info(
        "ingestion: skipping %d excluded symbols (scope: scan): %s",
        len(excluded), ", ".join(e.symbol for e in excluded),
    )
    return kept


def ingestion_universe() -> list[str]:
    """Nightly and startup universe: the staleness reference, then SP500+NDX100+DOW30.

    The reference goes first so the Tiingo symbol budget is not spent before it.
    `scope: scan` exclusions (ended price feeds) are skipped; the reference never is.
    A manual ingest request does not go through here and is never filtered.
    """
    try:
        from app.data.universe_presets import expand_universe
        presets = expand_universe(["SP500"]) + expand_universe(["NDX100"]) + expand_universe(["DOW30"])
    except Exception:
        presets = []
    rest = [s for s in dict.fromkeys(presets) if s != STALENESS_REFERENCE]
    return [STALENESS_REFERENCE, *_without_scan_exclusions(rest)]


async def startup_catch_up() -> bool:
    """Start an ingestion run if the staleness reference is stale; True if one started."""
    async with AsyncSessionLocal() as db:
        last = await _last_stored_date(STALENESS_REFERENCE, db)
    if not _should_ingest(last):
        return False
    universe = ingestion_universe()
    start_ingestion_task(universe, years=6)
    logger.info(
        "startup: DB stale (last %s date=%s), started ingestion for %d symbols",
        STALENESS_REFERENCE, last, len(universe),
    )
    return True


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
    rebuild: bool = False,
) -> IngestionResult:
    """Run a full ingestion pass for `symbols`.

    Stage Alpaca, validate fallback history, and commit each coherent symbol.
    A seam refusal is followed by one single-provider rebuild of that symbol;
    `rebuild=True` rebuilds every symbol from one provider instead of updating it.
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
        "rebuilt":        0,
        "rebuilt_symbols": [],
        "rebuild_details": {},
        "rebuild_refused": 0,
        "rebuild_refused_symbols": [],
        "rebuild_errors": {},
        "single_provider_updated": 0,
        "single_provider_failed_symbols": [],
        "single_provider_errors": {},
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
                if rebuild:
                    try:
                        rebuilt = await rebuild_single_provider(sym, fetch_start, fetch_end)
                    except SingleProviderRefused as refused:
                        _record_rebuild_refused(sym, refused)
                        errors.append(f"{sym}: rebuild refused — {refused}")
                    else:
                        _record_rebuilt(sym, rebuilt, "request")
                else:
                    result = await update_history(sym, fetch_start, fetch_end,
                                                  alpaca_bars=alpaca_result.get(sym, []),
                                                  force_backfill=force_backfill)
                    if result.provider is not None:
                        _state["single_provider_updated"] += 1
                    elif alpaca_result.get(sym):
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
                # A seam-refused symbol gets no bars at all; one coherent single-provider
                # series is strictly better, and the next run keeps it on that provider.
                try:
                    rebuilt = await rebuild_single_provider(sym, fetch_start, fetch_end)
                except SingleProviderRefused as refused:
                    _record_rebuild_refused(sym, refused)
                    errors.append(f"{sym}: seam mismatch — {exc}; rebuild refused — {refused}")
                except Exception as rebuild_exc:
                    logger.warning("ingestion: history failed for %s — %s", sym, rebuild_exc)
                    errors.append(f"{sym}: history error — {rebuild_exc}")
                    _state["failed"] += 1
                else:
                    _record_rebuilt(sym, rebuilt, "seam_refusal")
            except SingleProviderRefused as exc:
                # A single-provider symbol's own update; never rebuilt in the same pass.
                _state["failed"] += 1
                _state["single_provider_failed_symbols"].append(sym)
                _state["single_provider_errors"][sym] = str(exc)
                logger.warning("ingestion: single-provider update refused for %s — %s", sym, exc)
                errors.append(f"{sym}: single-provider update refused — {exc}")
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
        rebuilt=_state["rebuilt"],
        rebuilt_symbols=list(_state["rebuilt_symbols"]),
        rebuild_details={sym: dict(d) for sym, d in _state["rebuild_details"].items()},
        rebuild_refused=_state["rebuild_refused"],
        rebuild_refused_symbols=list(_state["rebuild_refused_symbols"]),
        rebuild_errors=dict(_state["rebuild_errors"]),
        single_provider_updated=_state["single_provider_updated"],
        single_provider_failed_symbols=list(_state["single_provider_failed_symbols"]),
        single_provider_errors=dict(_state["single_provider_errors"]),
    )


def start_ingestion_task(symbols: list[str], years: int | None = None,
                         force_backfill: bool = False, rebuild: bool = False) -> bool:
    """Create an asyncio Task for run_ingestion (fire-and-forget).

    Must be called from inside a running event loop (FastAPI lifespan or endpoint).
    """
    global _task
    if (_task is not None and not _task.done()) or _state.get("status") == "running":
        logger.warning("ingestion: already running — ignoring new request")
        return False
    kwargs: dict[str, Any] = {"years": years, "force_backfill": force_backfill}
    if rebuild:
        kwargs["rebuild"] = True
    _task = asyncio.create_task(run_ingestion(symbols, **kwargs))
    return True
