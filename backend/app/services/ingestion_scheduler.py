"""APScheduler wrapper for the nightly OHLCV ingestion job."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduling_tz import get_or_rebuild_scheduler

logger = logging.getLogger(__name__)

_JOB_ID = "ingestion_nightly"
_scheduler: AsyncIOScheduler | None = None
_scheduler_tz_key: str | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler, _scheduler_tz_key
    _scheduler, _scheduler_tz_key = get_or_rebuild_scheduler(_scheduler, _scheduler_tz_key)
    return _scheduler


async def _run_nightly() -> None:
    logger.info("ingestion_scheduler: nightly run starting")
    from app.data.tiingo_budget import caller
    from app.services.ingestion_job import ingestion_universe, start_ingestion_task
    from app.services.history_retention import history_years
    # The task copies this context: its Tiingo requests count as "nightly"
    # and stop at the nightly share of the budget.
    with caller("nightly"):
        start_ingestion_task(ingestion_universe(), years=history_years())
    # Piggyback the audit.log rotation/pruning and the scheduled-scan-run
    # retention sweep onto this same nightly tick — neither needs its own
    # cron slot (Part 0/Part 3's resolved decision: a few hundred audit
    # lines/day, or a handful of scheduled-scan rows, doesn't need its own
    # cadence). Best-effort: a failure here must never abort ingestion.
    try:
        await _run_nightly_maintenance()
    except Exception as exc:
        logger.error("ingestion_scheduler: nightly maintenance failed — %s", exc)


async def _run_nightly_maintenance() -> None:
    """Audit-log rotation/pruning (Part 2) + scheduled-scan-run retention
    (Part 3), both driven by the same settings.yaml-backed retention knobs,
    + the 40-day Tiingo usage-ledger prune."""
    import asyncio
    from app.services.audit import rotate_audit_log, prune_audit_log_archives
    from app.services.scheduling_tz import _load_settings as _load_scheduling_settings

    cfg = _load_scheduling_settings()
    history_retention_years = int(cfg.get("history_retention_years", 10))
    await asyncio.to_thread(rotate_audit_log)
    await asyncio.to_thread(prune_audit_log_archives, history_retention_years)

    scheduled_scan_run_retention_days = int(cfg.get("scheduled_scan_run_retention_days", 90))
    try:
        from app.database import AsyncSessionLocal
        from app.services.scan_schedule_store import prune_scheduled_scan_runs
        async with AsyncSessionLocal() as db:
            await prune_scheduled_scan_runs(db, scheduled_scan_run_retention_days)
    except Exception as exc:
        logger.error("ingestion_scheduler: scheduled-scan-run pruning failed — %s", exc)

    try:
        from app.data import tiingo_budget
        await tiingo_budget.prune_usage()
    except Exception as exc:
        logger.error("ingestion_scheduler: provider usage pruning failed — %s", exc)


def configure(enabled: bool, time_str: str) -> None:
    """Install or remove the nightly cron job. Safe to call while scheduler is running."""
    sched = _get()
    try:
        sched.remove_job(_JOB_ID)
    except Exception:
        pass
    if enabled:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            logger.warning("ingestion_scheduler: invalid time %r, defaulting to 02:00", time_str)
            hour, minute = 2, 0
        sched.add_job(
            _run_nightly,
            CronTrigger(hour=hour, minute=minute),
            id=_JOB_ID,
            replace_existing=True,
        )
        logger.info("ingestion_scheduler: scheduled daily at %02d:%02d", hour, minute)
    else:
        logger.info("ingestion_scheduler: disabled")


def next_run_time() -> str | None:
    """ISO 8601 next fire time, or None if not scheduled / not enabled."""
    sched = _get()
    job = sched.get_job(_JOB_ID)
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def start() -> None:
    sched = _get()
    if not sched.running:
        sched.start()


def shutdown() -> None:
    sched = _get()
    if sched.running:
        sched.shutdown(wait=False)
