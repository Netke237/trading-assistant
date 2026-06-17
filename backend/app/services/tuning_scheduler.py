"""APScheduler wrapper for the daily strategy tuning (WFO) job."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_JOB_ID = "tuning_daily"
_scheduler: AsyncIOScheduler | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
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
            logger.warning("tuning_scheduler: invalid time %r, defaulting to 02:00", time_str)
            hour, minute = 2, 0
        sched.add_job(
            _run_daily,
            CronTrigger(hour=hour, minute=minute),
            id=_JOB_ID,
            replace_existing=True,
        )
        logger.info("tuning_scheduler: scheduled daily at %02d:%02d", hour, minute)
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
