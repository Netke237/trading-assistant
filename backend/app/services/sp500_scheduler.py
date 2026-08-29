"""APScheduler wrapper for the daily S&P 500 liquidity update."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduling_tz import get_or_rebuild_scheduler

logger = logging.getLogger(__name__)

_JOB_ID = "sp500_daily"
_scheduler: AsyncIOScheduler | None = None
_scheduler_tz_key: str | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler, _scheduler_tz_key
    _scheduler, _scheduler_tz_key = get_or_rebuild_scheduler(_scheduler, _scheduler_tz_key)
    return _scheduler


async def _run_daily() -> None:
    logger.info("sp500_scheduler: daily update starting")
    from app.services.sp500_update_service import start_update_task
    started = start_update_task()
    if not started:
        logger.info("sp500_scheduler: skipped — update already in progress")


def configure(enabled: bool, time_str: str) -> None:
    sched = _get()
    try:
        sched.remove_job(_JOB_ID)
    except Exception:
        pass
    if enabled:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            logger.warning("sp500_scheduler: invalid time %r, defaulting to 04:00", time_str)
            hour, minute = 4, 0
        sched.add_job(
            _run_daily,
            CronTrigger(hour=hour, minute=minute),
            id=_JOB_ID,
            replace_existing=True,
        )
        logger.info("sp500_scheduler: scheduled daily at %02d:%02d", hour, minute)
    else:
        logger.info("sp500_scheduler: disabled")


def next_run_time() -> str | None:
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
