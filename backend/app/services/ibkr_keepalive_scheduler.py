"""APScheduler wrapper for periodic IBKR Client Portal Gateway keep-alive.

The IBKR Client Portal Gateway drops the session after ~5 minutes without a
/tickle call, independently of how often the app happens to fetch market data
or place orders. This ticks both the live and paper gateways every 45 seconds
so a dropped connection is caught within one interval instead of silently
going stale until the next scan or order attempt fails.

Known limitation (not automated here): IBKR also requires a fresh interactive
brokerage-session login (2FA) roughly once every 24h. That cannot be
automated without storing 2FA credentials, which this app does not do —
if the gateway shows "not authenticated" in logs, a manual re-login to the
Client Portal Gateway is required.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_JOB_ID = "ibkr_keepalive"
_INTERVAL_SECONDS = 45
_scheduler: BackgroundScheduler | None = None


def _get() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
    return _scheduler


def _tick() -> None:
    from app.data.ibkr import ibkr_available
    from app.data.ibkr_paper import paper_gateway_available

    if not ibkr_available():
        logger.warning("ibkr_keepalive: live gateway not authenticated")
    if not paper_gateway_available():
        logger.warning("ibkr_keepalive: paper gateway not authenticated")


def start() -> None:
    sched = _get()
    if not sched.running:
        sched.add_job(
            _tick,
            IntervalTrigger(seconds=_INTERVAL_SECONDS),
            id=_JOB_ID,
            replace_existing=True,
        )
        sched.start()
        logger.info("ibkr_keepalive_scheduler: started, interval=%ds", _INTERVAL_SECONDS)


def shutdown() -> None:
    global _scheduler
    sched = _get()
    if sched.running:
        # Unlike the AsyncIOScheduler-based schedulers elsewhere in this codebase
        # (edgar_scheduler, sp500_scheduler, tuning_scheduler, ingestion_scheduler),
        # BackgroundScheduler.shutdown() always joins its worker thread internally,
        # regardless of wait=False. That means this call still briefly blocks the
        # calling thread (FastAPI's async lifespan handler). Expected to return
        # quickly since the tick interval is short and jobs are fast.
        sched.shutdown(wait=False)
    # Drop the cached instance so a later start() always builds a fresh scheduler
    # rather than depending on a shut-down instance's restart behavior.
    _scheduler = None
