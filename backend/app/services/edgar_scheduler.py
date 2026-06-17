"""APScheduler wrapper for the nightly EDGAR fundamentals prefetch."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_JOB_ID = "edgar_nightly"
_scheduler: AsyncIOScheduler | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def _run_nightly() -> None:
    logger.info("edgar_scheduler: nightly prefetch starting")
    try:
        from app.data.universe_presets import expand_universe
        symbols = list(dict.fromkeys(
            expand_universe(["SP500"]) + expand_universe(["NDX100"]) + expand_universe(["DOW30"])
        ))
    except Exception:
        symbols = ["SPY", "QQQ", "AAPL", "MSFT"]
    try:
        from app.services.fundamentals_store import prefetch_universe
        # prefetch_universe is blocking (calls asyncio.run internally) — run in thread pool
        await asyncio.to_thread(prefetch_universe, symbols)
        logger.info("edgar_scheduler: nightly prefetch complete")
    except Exception as exc:
        logger.error("edgar_scheduler: nightly prefetch failed — %s", exc)


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
            logger.warning("edgar_scheduler: invalid time %r, defaulting to 04:00", time_str)
            hour, minute = 4, 0
        sched.add_job(
            _run_nightly,
            CronTrigger(hour=hour, minute=minute),
            id=_JOB_ID,
            replace_existing=True,
        )
        logger.info("edgar_scheduler: scheduled daily at %02d:%02d", hour, minute)
    else:
        logger.info("edgar_scheduler: disabled")


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
