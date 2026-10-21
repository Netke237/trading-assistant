"""Part 3 — the two scheduling engines for ScanScheduleEntry ('fixed_time'
and 'loop'), and the shared dispatch/execution/observability path both
converge on (_run_scheduled_entry).

Both patterns converge on identical execution — they only differ in *when*
they decide to fire. Manual runs (RunScanButton) never touch anything in
this module.
"""
from __future__ import annotations

import asyncio
import html
import json
from app.services.scan_report_lifecycle import run_reported_scan, persisted_result
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduling_tz import get_or_rebuild_scheduler
from app.services.scan_window import window_is_open
from app.services.scan_schedule_store import (
    scan_schedule_store, record_scheduled_scan_run, get_latest_successful_run,
)

logger = logging.getLogger(__name__)

# Serializes SCHEDULED runs only — manual runs (RunScanButton) stay
# interactive and unblocked, as today. In-process only: does not serialize
# across multiple worker processes (same caveat as the tuning-job lock in
# main.py — see the WEB_CONCURRENCY warning there, which names this
# semaphore too).
_SCHEDULED_SCAN_SEMAPHORE = asyncio.Semaphore(1)

_scheduler: AsyncIOScheduler | None = None
_scheduler_tz_key: str | None = None


def _get_scan_schedule_scheduler() -> AsyncIOScheduler:
    global _scheduler, _scheduler_tz_key
    _scheduler, _scheduler_tz_key = get_or_rebuild_scheduler(_scheduler, _scheduler_tz_key)
    return _scheduler


def sync_fixed_time_jobs() -> None:
    """Rebuild the live job set from scan_schedule_store — one CronTrigger
    job per enabled pattern='fixed_time' entry, id = the entry's own id.
    Called on every create/edit/delete (3.3) so a save takes effect
    immediately, same "reconfigure immediately" convention as every other
    scheduler in this codebase."""
    sched = _get_scan_schedule_scheduler()
    for job in sched.get_jobs():
        sched.remove_job(job.id)
    for entry in scan_schedule_store.list():
        if entry.get("enabled") and entry.get("pattern") == "fixed_time":
            try:
                hour, minute = map(int, str(entry["fire_time"]).split(":"))
            except Exception:
                logger.warning("scan_schedule: entry %s has invalid fire_time %r, skipping",
                                entry.get("id"), entry.get("fire_time"))
                continue
            days = entry.get("days_of_week") or [0, 1, 2, 3, 4]
            sched.add_job(
                _run_scheduled_entry_job,
                CronTrigger(hour=hour, minute=minute, day_of_week=",".join(str(d) for d in days)),
                args=[entry["id"]],
                id=entry["id"],
                replace_existing=True,
            )


async def _run_scheduled_entry_job(entry_id: str) -> None:
    """APScheduler job callback wrapper — swallow-and-log so a scheduled
    firing can never propagate an unhandled exception into APScheduler's own
    job-execution machinery."""
    try:
        await _run_scheduled_entry(entry_id)
    except Exception:
        logger.error("scan_schedule: unhandled error running entry %s", entry_id, exc_info=True)


def shutdown_fixed_time_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)


async def _notify_scan_schedule_error(label: str, error: str) -> None:
    from app.services.notifications.dispatch import notify_enabled_channels
    subject = f"Scheduled scan failed: {label}"
    plain = f"Scan entry '{label}' failed: {error}"
    # Telegram's HTML parse_mode only recognizes a small tag allowlist — reuse
    # the same html.escape() convention strategy_watch_evaluator.py's
    # notification builder uses, not a reimplementation.
    html_body = f"<b>Scheduled scan failed</b>\nScan entry '{html.escape(label)}' failed: {html.escape(error)}"
    try:
        await notify_enabled_channels(subject, plain, html_body)
    except Exception:
        logger.error("scan_schedule: failure notification itself failed for %s", label, exc_info=True)


# NO-LIVE-QUOTE (plan 3f): appended to the success notice of an options run
# whose every rejected name was rejected only for no_live_quote.
NO_LIVE_QUOTE_NOTICE_CLAUSE = "ran outside market hours — no live option quotes"


def _ran_without_live_quotes(candidate_count: int, rejected_count: int, no_live_quote_names: int) -> bool:
    """True when an options run found nothing and EVERY rejected name was
    rejected only because none of its contracts had a live quote
    (ScanResult.noLiveQuoteNames, counted by the scan core -- no reason string
    is parsed here). A run with a candidate had a live quote somewhere, so the
    clause would be false there."""
    return (
        candidate_count == 0
        and rejected_count > 0
        and no_live_quote_names == rejected_count
    )


async def _notify_scan_schedule_success(
    label: str, candidate_count: int, *, no_live_quotes: bool = False,
) -> None:
    from app.services.notifications.dispatch import notify_enabled_channels
    subject = f"Scheduled scan complete: {label}"
    plain = f"Scan entry '{label}': {candidate_count} candidate(s) found"
    html_body = f"<b>Scheduled scan complete</b>\nScan entry '{html.escape(label)}': {candidate_count} candidate(s) found"
    if no_live_quotes:
        plain += f" — {NO_LIVE_QUOTE_NOTICE_CLAUSE}"
        html_body += f" — {html.escape(NO_LIVE_QUOTE_NOTICE_CLAUSE)}"
    try:
        await notify_enabled_channels(subject, plain, html_body)
    except Exception:
        logger.error("scan_schedule: success notification itself failed for %s", label, exc_info=True)


class _LegacyCapUnitsError(ValueError):
    """Stored cap amounts need explicit profile confirmation before replay."""


async def _run_scheduled_entry(entry_id: str) -> None:
    """The single dispatch path both the 'fixed_time' and 'loop' patterns
    converge on. Never calls run_scan()/run_stock_scan() — always the
    globals-free _execute_scan_core/_execute_stock_scan_core — and never
    touches _last_request/_last_result/_last_stock_request/_last_stock_result
    or the auto-trader."""
    entry = scan_schedule_store.get(entry_id)
    if entry is None:
        # Entry deleted between the trigger firing and the handler running —
        # an entirely expected race, not an error.
        logger.info("scan_schedule: entry %s no longer exists, skipping", entry_id)
        return
    if not entry.get("enabled"):
        logger.info("scan_schedule: entry %s is disabled, skipping", entry_id)
        return

    label = entry.get("label", entry_id)
    mode = entry.get("mode")
    no_live_quotes = False

    async with _SCHEDULED_SCAN_SEMAPHORE:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            try:
                previous_row = await get_latest_successful_run(db, entry_id)
                if mode == "options":
                    from app.schemas import ScanRequest, ScanResult
                    from app.routers.scan import _execute_scan_core
                    req = ScanRequest.model_validate(entry["resolved_request"])
                    if req.cap_filter_units_version != 1 and any(
                        cap is not None and cap != 0
                        for cap in (req.min_cap_usd, req.max_cap_usd)
                    ):
                        raise _LegacyCapUnitsError(
                            "Re-save the Search Profile and confirm market-cap filter units "
                            "before running this schedule."
                        )
                    # Step 3's min_stock_score is stocks-only, but entries saved
                    # before the options resolver stripped it (open question #57)
                    # still carry it, and contract_validator would apply it as
                    # the contract hard-reject floor. Entries are replayed as
                    # stored, so drop it here rather than in contract_validator,
                    # whose direct callers set it on purpose.
                    req.overrides.pop("min_stock_score", None)
                    previous_result = (
                        ScanResult.model_validate_json(previous_row.result_json)
                        if previous_row and previous_row.result_json else None
                    )
                    result = await run_reported_scan(req, category="options", trigger="scheduled",
                        callback=lambda: _execute_scan_core(req, db, previous_result=previous_result))
                    result_json = json.dumps(persisted_result(result), allow_nan=False)
                    candidate_count = len(result.candidates)
                    no_live_quotes = _ran_without_live_quotes(
                        candidate_count, len(result.rejected), result.noLiveQuoteNames,
                    )
                elif mode == "stocks":
                    from app.schemas.stock_scan import StockScanRequest
                    from app.schemas.stock_scan import StockScanResult
                    from app.routers.stock_scan import _execute_stock_scan_core
                    req = StockScanRequest.model_validate(entry["resolved_request"])
                    previous_result = (
                        StockScanResult.model_validate_json(previous_row.result_json)
                        if previous_row and previous_row.result_json else None
                    )
                    result = await run_reported_scan(req, category=req.category, trigger="scheduled",
                        callback=lambda: _execute_stock_scan_core(req, db, previous_result=previous_result))
                    result_json = json.dumps(persisted_result(result), allow_nan=False)
                    candidate_count = len(result.candidates)
                else:
                    raise ValueError(f"unknown schedule entry mode {mode!r}")
            except Exception as exc:
                error = str(exc) if isinstance(exc, _LegacyCapUnitsError) else "scan_failed"
                logger.error("scan_schedule: entry %s (%s) failed: %s", entry_id, label, error)
                await record_scheduled_scan_run(
                    db, schedule_entry_id=entry_id, mode=mode or "unknown",
                    status="error", error=error,
                )
                await _notify_scan_schedule_error(label, error)
                return

            await record_scheduled_scan_run(
                db, schedule_entry_id=entry_id, mode=mode,
                status="success", result_json=result_json,
            )
            await _notify_scan_schedule_success(
                label, candidate_count, no_live_quotes=no_live_quotes,
            )


class ScanScheduleLoopRunner:
    """One shared background task, modeled on the retired ScanScheduler's
    _loop() tick structure — ticks every 60s, and for each enabled
    pattern='loop' entry independently tracks its own last_run_at (in-memory,
    not persisted — a missed tick on restart just resets that entry's
    cadence timer, an acceptable low-stakes edge case for a repeating scan).

    Per-entry fault isolation: this iterates a list inside one task — a
    materially larger blast radius than one-task-per-config — so each
    entry's fire attempt is wrapped in its own try/except so one
    misbehaving entry can never prevent any other entry, or the next tick,
    from running.
    """

    _TICK_SECONDS = 60

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self._last_run_at: dict[str, datetime] = {}

    async def _tick(self) -> None:
        for entry in scan_schedule_store.list():
            if not entry.get("enabled") or entry.get("pattern") != "loop":
                continue
            entry_id = entry["id"]
            try:
                if not window_is_open(
                    entry["window_start_hour"], entry["window_end_hour"],
                    entry.get("days_of_week") or [0, 1, 2, 3, 4],
                    _entry_timezone(),
                ):
                    continue
                cadence = entry.get("cadence_minutes") or 60
                last = self._last_run_at.get(entry_id)
                now = datetime.now(timezone.utc)
                if last is not None and (now - last).total_seconds() < cadence * 60:
                    continue
                self._last_run_at[entry_id] = now
                await _run_scheduled_entry(entry_id)
            except Exception:
                logger.error("scan_schedule: loop-pattern entry %s tick failed", entry_id, exc_info=True)

    async def _loop(self) -> None:
        while not self._cancelled:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("scan_schedule: loop runner tick failed", exc_info=True)
            try:
                await asyncio.sleep(self._TICK_SECONDS)
            except asyncio.CancelledError:
                raise

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancelled = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None


def _entry_timezone() -> str:
    """loop-pattern entries fire in the operator timezone — same convention
    as every other non-market-hours job in this plan (Part 1, §1.3)."""
    from app.services.scheduling_tz import operator_timezone_name
    return operator_timezone_name()


scan_schedule_loop_runner = ScanScheduleLoopRunner()
