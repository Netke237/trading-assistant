"""Nightly/manual OHLCV ingestion job.

Runs as a single idempotent operation:
  1. Batch Alpaca fetch for the whole universe.
  2. Per-symbol coherent older-prefix + current-suffix validation and atomic write,
     in two passes (plan 2026-10-19-history-incremental-nightly 2.7):
     - Pass 1, no Tiingo: every symbol through ``update_history(..., tiingo_allowed=False)``.
       ``SUFFIX_ONLY`` / ``RESCALE`` / ``SINGLE_PROVIDER_CURRENT`` / yfinance-basis symbols
       are written; a symbol whose classification needs Tiingo comes back ``"deferred"``
       (nothing written) and is queued for pass 2 by its deferred kind.
     - Pass 2, the Tiingo queue in priority order: the staleness reference (SPY) first
       whatever its kind, then ``SINGLE_PROVIDER_*``, ``FULL``, ``CONFIRM`` and last the
       revalidations (``select_revalidations`` over pass 1's revalidation-due results, each
       admitted only while ``tiingo_budget.ensure_room(symbol, "nightly")`` has room). A
       budget refusal never stops the pass: each symbol runs its own path and fallbacks.
     Every carry-over between nights is read from stored rows and ``ohlcv_history_state``;
     the queue only decides *when* a symbol runs, and it is classified again at its turn.
  3. Prune rows older than `years` years to bound table size.
  4. Update the ingestion state singleton (incl. the run counters) so callers can track progress.

Entry point: `await run_ingestion(symbols)` (configured horizon, default 17 years).

A symbol whose seam is refused is rebuilt from one provider (`rebuild_single_provider`,
trigger "seam_refusal") — in pass 2, since the rebuild asks Tiingo first. `rebuild=True`
rebuilds every requested symbol instead of updating it (trigger "request");
`force_backfill=True` keeps one full pass in input order (every symbol takes its full path).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.data import tiingo_budget, universe_exclusions
from app.database import AsyncSessionLocal
from app.data.alpaca import fetch_daily_bars_batch, get_alpaca_client
from app.models.ohlcv_daily import OhlcvDailyModel, OhlcvHistoryStateModel
from app.services import history_incremental as hi
from app.services.historical_store import _last_stored_date, most_recent_trading_day
from app.services.history_backfill import (
    HistorySeamMismatch,
    SingleProviderRefused,
    rebuild_single_provider,
    update_history,
)
from app.services.history_retention import effective_years
from app.services.scheduling_tz import _load_settings

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

# ── Run counters (plan section 4 "Visible") ───────────────────────────────────
# Reset at the start of every run; absent from `_state` until the first run. Each action
# counter counts executed writes by their ``HistoryUpdateResult`` (action, reason):
#
#   suffix_only                      action SUFFIX_ONLY (incl. the confirm_retry and
#                                    revalidate_no_reply downgrades)
#   prefix_rescaled                  action RESCALE
#   adjustment_changed               action RESCALE, or FULL for a T5 change (_T5_FULL_REASONS)
#   prefix_refetched                 action FULL / CONFIRM / REVALIDATE (the full prefix path)
#   prefix_confirmed                 action CONFIRM
#   confirm_retry                    reason confirm_retry (a CONFIRM written SUFFIX_ONLY)
#   lag_window_full                  reason T6_lag_window
#   single_provider_recent           action SINGLE_PROVIDER_RECENT
#   single_provider_skipped_current  action SINGLE_PROVIDER_CURRENT
#   revalidated                      action REVALIDATE
#   revalidation_skipped_budget      a selected revalidation refused by ensure_room
#   tiingo_requests / tiingo_bytes   this run's own Tiingo HTTP attempts as recorded by the
#                                    ledger (run-scoped tally; other code's concurrent
#                                    requests are not counted); None when the ledger failed
#                                    to record one of them
#
# A revalidated symbol was also written SUFFIX_ONLY in pass 1, so it counts in both.
RUN_COUNTERS = ("suffix_only", "adjustment_changed", "prefix_refetched", "prefix_rescaled",
                "prefix_confirmed", "confirm_retry", "lag_window_full", "single_provider_recent",
                "single_provider_skipped_current", "revalidated", "revalidation_skipped_budget",
                "tiingo_requests", "tiingo_bytes")
_LEDGER_COUNTERS = ("tiingo_requests", "tiingo_bytes")
_K = hi.NightlyKind
_PREFIX_PATH = {_K.FULL.value, _K.CONFIRM.value, _K.REVALIDATE.value}
_T5_FULL_REASONS = frozenset({"non_uniform_ratio", "unexplained_adjustment",
                              "ratio_product_mismatch", "event_before_fetch", "raw_close_changed"})

# Pass-2 priority of a deferred result, keyed by its deferred kind (``reason``); the
# staleness reference goes first whatever its kind. A pass-1 seam refusal's rebuild runs
# at FULL's priority (it is a whole-window fetch).
_PRIORITY_REFERENCE = 1
_PRIORITY = {_K.SINGLE_PROVIDER_RECENT.value: 2, _K.SINGLE_PROVIDER_FULL.value: 2,
             _K.FULL.value: 3, _K.CONFIRM.value: 4, _K.REVALIDATE.value: 5}
_PRIORITY_REBUILD = 3
_PRIORITY_REVALIDATE = 5


def counters_for(action: str | None, reason: str | None) -> list[str]:
    """The action counters one executed ``update_history`` result increments."""
    out = []
    if action == _K.SUFFIX_ONLY.value:
        out.append("suffix_only")
    if action == _K.RESCALE.value:
        out += ["prefix_rescaled", "adjustment_changed"]
    if action in _PREFIX_PATH:
        out.append("prefix_refetched")
    if action == _K.FULL.value and reason in _T5_FULL_REASONS:
        out.append("adjustment_changed")
    if action == _K.CONFIRM.value:
        out.append("prefix_confirmed")
    if action == _K.REVALIDATE.value:
        out.append("revalidated")
    if reason == "confirm_retry":
        out.append("confirm_retry")
    if reason == "T6_lag_window":
        out.append("lag_window_full")
    if action == _K.SINGLE_PROVIDER_RECENT.value:
        out.append("single_provider_recent")
    if action == _K.SINGLE_PROVIDER_CURRENT.value:
        out.append("single_provider_skipped_current")
    return out


def _ledger_counters(usage: tiingo_budget.RunUsage) -> tuple[int | None, int | None]:
    """The run's (tiingo_requests, tiingo_bytes); (None, None) when the ledger failed to
    record one of its attempts, so the true numbers are unknown."""
    if usage.unrecorded:
        logger.warning("ingestion: tiingo usage ledger missed an attempt, counters unknown")
        return None, None
    return usage.requests, usage.bytes


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
    counters: dict[str, int | None] = field(default_factory=dict)   # RUN_COUNTERS


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
    from app.data.tiingo_budget import caller
    with caller("nightly"):   # automatic run: Tiingo stops at the nightly share
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

    Stage Alpaca, validate fallback history, and commit each coherent symbol: pass 1 without
    Tiingo, then the Tiingo queue in priority order (module docstring). A seam refusal is
    followed by one single-provider rebuild of that symbol; `rebuild=True` rebuilds every
    symbol from one provider instead of updating it.
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
        **{key: 0 for key in RUN_COUNTERS if key not in _LEDGER_COUNTERS},
        **dict.fromkeys(_LEDGER_COUNTERS),
    })

    errors: list[str] = []
    tally = {"alpaca": 0, "gapfill": 0}
    fetch_end = date.today()
    fetch_start = fetch_end - timedelta(days=years * 365)
    alpaca_result: dict[str, list[dict]] = {}

    def record(sym: str, result, *, first: bool) -> None:
        """Book one executed result. `first`: the symbol's own write tonight (False for a
        pass-2 revalidation of a symbol pass 1 already wrote)."""
        if first:
            if result.provider is not None:
                _state["single_provider_updated"] += 1
            elif alpaca_result.get(sym):
                tally["alpaca"] += 1
            else:
                tally["gapfill"] += 1
        for name in ("backfilled", "floor_reached"):
            if getattr(result, name) and sym not in _state[name + "_symbols"]:
                _state[name] += 1
                _state[name + "_symbols"].append(sym)
        for key in counters_for(result.action, result.reason):
            _state[key] += 1

    def record_seam_mismatch(sym: str, exc: HistorySeamMismatch) -> None:
        _state["seam_mismatch"] += 1
        _state["seam_mismatch_symbols"].append(sym)
        if exc.ratio is not None:
            _state["seam_ratios"][sym] = exc.ratio

    async def rebuild_after_seam(sym: str, exc: HistorySeamMismatch) -> None:
        # A seam-refused symbol gets no bars at all; one coherent single-provider
        # series is strictly better, and the next run keeps it on that provider.
        _state["current_symbol"] = sym
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

    async def run_update(sym: str, *, tiingo_allowed: bool, revalidate: bool = False,
                         first: bool = True):
        """One `update_history` call with the run's error handling.

        Returns the result (written, or "deferred"); None after a handled failure; or, in
        pass 1 (`tiingo_allowed=False`), the HistorySeamMismatch whose rebuild must wait
        for pass 2 because the rebuild asks Tiingo first.
        """
        _state["current_symbol"] = sym
        try:
            result = await update_history(sym, fetch_start, fetch_end,
                                          alpaca_bars=alpaca_result.get(sym, []),
                                          force_backfill=force_backfill, params=params,
                                          revalidate=revalidate, tiingo_allowed=tiingo_allowed)
        except HistorySeamMismatch as exc:
            record_seam_mismatch(sym, exc)
            if not tiingo_allowed:
                return exc
            await rebuild_after_seam(sym, exc)
            return None
        except SingleProviderRefused as exc:
            # A single-provider symbol's own update; never rebuilt in the same pass.
            _state["failed"] += 1
            _state["single_provider_failed_symbols"].append(sym)
            _state["single_provider_errors"][sym] = str(exc)
            logger.warning("ingestion: single-provider update refused for %s — %s", sym, exc)
            errors.append(f"{sym}: single-provider update refused — {exc}")
            return None
        except Exception as exc:
            logger.warning("ingestion: history failed for %s — %s", sym, exc)
            errors.append(f"{sym}: history error — {exc}")
            _state["failed"] += 1
            return None
        if getattr(result, "action", None) != "deferred":
            record(sym, result, first=first)
        return result

    async def rebuild_requested(sym: str) -> None:
        _state["current_symbol"] = sym
        try:
            try:
                rebuilt = await rebuild_single_provider(sym, fetch_start, fetch_end)
            except SingleProviderRefused as refused:
                _record_rebuild_refused(sym, refused)
                errors.append(f"{sym}: rebuild refused — {refused}")
            else:
                _record_rebuilt(sym, rebuilt, "request")
        except HistorySeamMismatch as exc:
            record_seam_mismatch(sym, exc)
            await rebuild_after_seam(sym, exc)
        except Exception as exc:
            logger.warning("ingestion: history failed for %s — %s", sym, exc)
            errors.append(f"{sym}: history error — {exc}")
            _state["failed"] += 1

    # Every Tiingo attempt of this run (and of the tasks it creates) lands in `usage`.
    with tiingo_budget.run_usage() as usage:
        try:
            # Invalid `history_incremental` config fails the run here, naming the key,
            # before any provider request or write.
            params = hi.load_params(_load_settings())

            # ── Step 1: Alpaca batch fetch ────────────────────────────────────────
            alpaca_client = await get_alpaca_client()
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
            if rebuild:
                for sym in symbols:
                    await rebuild_requested(sym)
                    _state["done"] += 1
            elif force_backfill:
                # Manual full re-fetch: every symbol takes its full path, in input order.
                for sym in symbols:
                    await run_update(sym, tiingo_allowed=True)
                    _state["done"] += 1
            else:
                # Pass 2 queue entries: (priority, sequence, symbol, kind, seam exception).
                queue: list[tuple[int, int, str, str, HistorySeamMismatch | None]] = []
                due: list[tuple[str, int]] = []

                def enqueue(sym: str, priority: int, kind: str, exc=None) -> None:
                    if sym == STALENESS_REFERENCE:
                        priority = _PRIORITY_REFERENCE
                    queue.append((priority, len(queue), sym, kind, exc))

                # ── Pass 1: no Tiingo request ────────────────────────────────────
                for sym in symbols:
                    outcome = await run_update(sym, tiingo_allowed=False)
                    if isinstance(outcome, HistorySeamMismatch):
                        enqueue(sym, _PRIORITY_REBUILD, "rebuild", outcome)
                        continue
                    if getattr(outcome, "action", None) == "deferred":
                        enqueue(sym, _PRIORITY.get(outcome.reason, _PRIORITY[_K.FULL.value]), "update")
                        continue
                    if (getattr(outcome, "revalidation_due", False) is True
                            and outcome.prefix_age_days is not None):
                        due.append((sym, outcome.prefix_age_days))
                    _state["done"] += 1
                for sym in hi.select_revalidations(due, params.revalidate_per_night):
                    enqueue(sym, _PRIORITY_REVALIDATE, "revalidate")
                queue.sort(key=lambda entry: entry[:2])

                # ── Pass 2: the Tiingo queue, in priority order ──────────────────
                for _, _, sym, kind, exc in queue:
                    if kind == "update":
                        await run_update(sym, tiingo_allowed=True)
                        _state["done"] += 1
                    elif kind == "rebuild":
                        await rebuild_after_seam(sym, exc)
                        _state["done"] += 1
                    else:
                        # Already written SUFFIX_ONLY in pass 1; re-fetched only with budget room.
                        _state["current_symbol"] = sym
                        try:
                            await tiingo_budget.ensure_room(sym, "nightly")
                        except Exception as refused:
                            _state["revalidation_skipped_budget"] += 1
                            logger.info("ingestion: revalidation of %s skipped — %s", sym, refused)
                            continue
                        await run_update(sym, tiingo_allowed=True, revalidate=True, first=False)

            # ── Step 4: Prune old rows ─────────────────────────────────────────────
            pruned = await _prune_old_rows(years) if symbols else 0
            _state["pruned_rows"] = pruned

            requests, size = _ledger_counters(usage)
            _state.update({
                "status":         "completed",
                "done":           len(symbols),
                "alpaca_count":   tally["alpaca"],
                "gapfill_count":  tally["gapfill"],
                "pruned_rows":    pruned,
                "current_symbol": None,
                "finished_at":    datetime.now(timezone.utc).isoformat(),
                "tiingo_requests": requests,
                "tiingo_bytes":   size,
            })
            logger.info(
                "ingestion complete: %d symbols, alpaca=%d, gapfill=%d, pruned=%d, failed=%d, %s",
                len(symbols), tally["alpaca"], tally["gapfill"], pruned, _state["failed"],
                ", ".join(f"{key}={_state[key]}" for key in RUN_COUNTERS),
            )

        except Exception as exc:
            requests, size = _ledger_counters(usage)
            _state.update({
                "status":      "error",
                "error":       str(exc),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "tiingo_requests": requests,
                "tiingo_bytes": size,
            })
            logger.error("ingestion crashed: %s", exc, exc_info=True)
            errors.append(f"crash: {exc}")

    return IngestionResult(
        total=len(symbols),
        alpaca_count=tally["alpaca"],
        gapfill_count=tally["gapfill"],
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
        counters={key: _state[key] for key in RUN_COUNTERS},
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
