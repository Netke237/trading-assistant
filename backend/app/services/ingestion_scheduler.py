"""APScheduler wrapper for the nightly OHLCV ingestion job."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_JOB_ID = "ingestion_nightly"
_scheduler: AsyncIOScheduler | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def _run_nightly() -> None:
    logger.info("ingestion_scheduler: nightly run starting")
    try:
        from app.data.universe_presets import expand_universe
        universe = list(dict.fromkeys(
            expand_universe(["SP500"]) + expand_universe(["NDX100"]) + expand_universe(["DOW30"])
        ))
    except Exception:
        universe = ["SPY"]
    from app.services.ingestion_job import start_ingestion_task
    start_ingestion_task(universe, years=6)


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
            logger.warning("ingestion_scheduler: invalid time %r, defaulting to 03:00", time_str)
            hour, minute = 3, 0
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
