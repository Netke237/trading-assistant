# backend/app/services/strategy_watch_scheduler.py
"""Background cadence loop for strategy-watch evaluation.

Modeled on scan_scheduler.ScanScheduler: one asyncio loop that ticks every
_TICK_SECONDS and decides whether to run evaluate_and_notify(), based on the
schedule config (EOD time-of-day, or every N hours during market hours).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime

from app.services.strategy_watch_evaluator import evaluate_and_notify
from app.services.strategy_watch_store import strategy_watch_store

logger = logging.getLogger(__name__)

_TICK_SECONDS = 300  # 5 minutes


def _market_open(now: datetime | None = None) -> bool:
    """True on a weekday between 09:30 and 16:00 (naive local time; coarse by design)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)


class StrategyWatchScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._cancelled = False
        self._last_run_at: datetime | None = None
        self._last_eod_run_date: date | None = None

    def _load_schedule(self) -> dict:
        return strategy_watch_store.get_schedule()

    async def _maybe_run(self, now: datetime | None = None) -> bool:
        """Decide and possibly run one evaluation. Returns True if it ran."""
        now = now or datetime.now()
        cfg = self._load_schedule()
        if not cfg.get("enabled"):
            return False
        # max(0, ...) defends against a manually-edited strategy_watches.yaml
        # (this schedule dict is loaded straight from YAML on startup, bypassing
        # the /schedule PUT endpoint's Pydantic ge=0 validation).
        sustain_minutes = max(0, int(cfg.get("sustain_minutes", 0)))

        mode = cfg.get("mode", "eod")
        if mode == "eod":
            hh, mm = (int(x) for x in str(cfg.get("eod_time", "16:15")).split(":"))
            if now.weekday() >= 5:
                return False
            if now.time() < dtime(hh, mm):
                return False
            if self._last_eod_run_date == now.date():
                return False
            await evaluate_and_notify(sustain_minutes)
            self._last_run_at = now
            self._last_eod_run_date = now.date()
            return True

        # poll mode
        if not _market_open(now):
            return False
        interval_h = float(cfg.get("poll_hours", 4))
        if self._last_run_at is not None:
            elapsed_h = (now - self._last_run_at).total_seconds() / 3600.0
            if elapsed_h < interval_h:
                return False
        await evaluate_and_notify(sustain_minutes)
        self._last_run_at = now
        return True

    async def _loop(self) -> None:
        while not self._cancelled:
            try:
                await self._maybe_run()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("strategy-watch scheduler tick failed", exc_info=True)
            try:
                await asyncio.sleep(_TICK_SECONDS)
            except asyncio.CancelledError:
                raise
        self._running = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._cancelled = False
        self._running = True
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
        self._running = False

    async def run_now(self) -> list:
        """Manual trigger — bypasses schedule gates. Returns fired events."""
        # Manual runs bypass the sustain window by design — the user explicitly
        # requested an immediate evaluation, so sustain_minutes is not applied here.
        events = await evaluate_and_notify()
        self._last_run_at = datetime.now()
        return events

    def get_status(self) -> dict:
        cfg = self._load_schedule()
        return {
            "running": self._running and not self._cancelled,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "mode": cfg.get("mode"),
            "enabled": cfg.get("enabled"),
        }


strategy_watch_scheduler = StrategyWatchScheduler()
