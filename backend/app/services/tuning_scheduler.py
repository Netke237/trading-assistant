"""APScheduler wrapper for the daily strategy tuning (WFO) job."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduling_tz import get_or_rebuild_scheduler

logger = logging.getLogger(__name__)

_JOB_ID = "tuning_daily"
_scheduler: AsyncIOScheduler | None = None
_scheduler_tz_key: str | None = None  # str(ZoneInfo) of the zone the current scheduler was built with


def _get() -> AsyncIOScheduler:
    global _scheduler, _scheduler_tz_key
    _scheduler, _scheduler_tz_key = get_or_rebuild_scheduler(_scheduler, _scheduler_tz_key)
    return _scheduler


async def _run_daily() -> None:
    logger.info("tuning_scheduler: daily WFO run starting")
    try:
        from app.routers import strategy_tuning as _st
        job_id = await _st.start_if_idle()
        if job_id:
            logger.info("tuning_scheduler: WFO job %s submitted", job_id)
        else:
            logger.info("tuning_scheduler: skipped — WFO run already active")
    except Exception as exc:
        logger.error("tuning_scheduler: failed to start WFO job — %s", exc)


_DEFAULT_DAYS_OF_WEEK = [5]  # Saturday-only default (Part 0: compute-heavy, weekly cadence)


def configure(enabled: bool, time_str: str, days_of_week: list[int] | None = None) -> None:
    sched = _get()
    try:
        sched.remove_job(_JOB_ID)
    except Exception:
        pass
    if enabled:
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            logger.warning("tuning_scheduler: invalid time %r, defaulting to 05:00", time_str)
            hour, minute = 5, 0
        dow = days_of_week if days_of_week else _DEFAULT_DAYS_OF_WEEK
        sched.add_job(
            _run_daily,
            CronTrigger(hour=hour, minute=minute, day_of_week=",".join(str(d) for d in dow)),
            id=_JOB_ID,
            replace_existing=True,
        )
        logger.info("tuning_scheduler: scheduled at %02d:%02d on days %s", hour, minute, dow)
    else:
        logger.info("tuning_scheduler: disabled")


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
