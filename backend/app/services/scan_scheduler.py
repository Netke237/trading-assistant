from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable

from app.schemas import ScanResult, ScanHistoryEntry


class ScanScheduler:
    """
    Background scan scheduler.

    Runs an async loop: execute scan → sleep for cadence → repeat.
    Stores the last result in memory so consecutive runs can compute deltas.
    """

    def __init__(self, cadence_minutes: int = 60):
        self.cadence = cadence_minutes
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
            "running": self._running and not self._cancelled,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "next_run_at": self._next_run_at.isoformat() if self._next_run_at else None,
            "cadence_minutes": self.cadence,
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
            self._last_run_at = datetime.now(timezone.utc)
            self._next_run_at = self._last_run_at + timedelta(minutes=self.cadence)

            try:
                result = await self._scan_fn()
            except asyncio.CancelledError:
                self._running = False
                raise
            except Exception:
                self._running = False
                # Log failure but keep loop alive
                continue

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
