from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Callable, Awaitable

_logger = logging.getLogger(__name__)

from app.schemas import ScanResult, ScanHistoryEntry
from app.schemas.schedule import ScheduleConfig


class ScanScheduler:
    """
    Background scan scheduler.

    Runs an async loop: execute scan → sleep for cadence → repeat.
    Respects a ScheduleConfig to enforce day-of-week and hour windows.
    Stores the last result in memory so consecutive runs can compute deltas.
    """

    def __init__(self, cadence_minutes: int = 60):
        self.cadence = cadence_minutes
        self._cfg: ScheduleConfig | None = None
        self._task: asyncio.Task | None = None
        self._last_result: ScanResult | None = None
        self._history: list[ScanHistoryEntry] = []
        self._running = False
        self._cancelled = False
        self._last_run_at: datetime | None = None
        self._next_run_at: datetime | None = None
        self._scan_fn: Callable[[], Awaitable[ScanResult]] | None = None

    def bind(self, scan_fn: Callable[[], Awaitable[ScanResult]]) -> None:
        """Attach the coroutine that performs a single scan."""
        self._scan_fn = scan_fn

    def configure(self, cfg: ScheduleConfig) -> None:
        """Apply a ScheduleConfig; also updates the cadence."""
        self._cfg = cfg
        self.cadence = cfg.cadence_minutes

    def _should_run_now(self) -> bool:
        """Return True if the current wall-clock time is inside the configured window."""
        if self._cfg is None:
            return True
        tz = ZoneInfo(self._cfg.timezone_name)
        now = datetime.now(tz)
        if now.weekday() not in self._cfg.days_of_week:
            return False
        return self._cfg.window_start_hour <= now.hour < self._cfg.window_end_hour

    async def start(self) -> None:
        """Start the scheduler loop in a background task."""
        if self._task is not None and not self._task.done():
            return
        self._cancelled = False
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the scheduler loop."""
        self._cancelled = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._running = False

    def get_status(self) -> dict:
        """Return scheduler status for the status endpoint."""
        return {
            "running":         self._running and not self._cancelled,
            "last_run_at":     self._last_run_at.isoformat() if self._last_run_at else None,
            "next_run_at":     self._next_run_at.isoformat() if self._next_run_at else None,
            "cadence_minutes": self.cadence,
            "schedule":        self._cfg.model_dump() if self._cfg else None,
        }

    def get_last_result(self) -> ScanResult | None:
        return self._last_result

    def set_cadence(self, minutes: int) -> None:
        self.cadence = max(5, min(1440, minutes))
        # Next run is recomputed on the following iteration

    async def _loop(self) -> None:
        if self._scan_fn is None:
            raise RuntimeError("ScanScheduler: no scan function bound")

        while not self._cancelled:
            try:
                should_run = self._should_run_now()
            except Exception:
                should_run = True  # bad timezone or config — fall back to always run
            if not should_run:
                try:
                    await asyncio.sleep(900)  # re-check every 15 min when outside window
                except asyncio.CancelledError:
                    self._running = False
                    raise
                continue

            self._last_run_at = datetime.now(timezone.utc)
            self._next_run_at = self._last_run_at + timedelta(minutes=self.cadence)

            try:
                result = await self._scan_fn()
            except asyncio.CancelledError:
                self._running = False
                raise
            except Exception as _exc:
                _logger.exception("Scheduled scan failed: %s", _exc)
            else:
                self._last_result = result
                self._history.append(
                    ScanHistoryEntry(
                        scan_id=result.scan_id,
                        timestamp=result.timestamp,
                        candidate_count=len(result.candidates),
                        rejected_count=len(result.rejected),
                        state=result.state,
                    )
                )

            # Sleep until next run
            now = datetime.now(timezone.utc)
            sleep_seconds = (self._next_run_at - now).total_seconds()
            if sleep_seconds > 0:
                try:
                    await asyncio.sleep(sleep_seconds)
                except asyncio.CancelledError:
                    self._running = False
                    raise

        self._running = False
