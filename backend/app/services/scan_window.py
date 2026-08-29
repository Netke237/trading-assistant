"""Pure window/day-of-week gate, extracted from the retired ScanScheduler's
_should_run_now() so both the (deleted) old mechanism's logic and Part 3's
ScanScheduleLoopRunner share one implementation, not a shared instance.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def window_is_open(
    window_start_hour: int,
    window_end_hour: int,
    days_of_week: list[int],
    timezone_name: str,
    now: datetime | None = None,
) -> bool:
    """True if the current wall-clock time (in `timezone_name`) falls within
    [window_start_hour, window_end_hour) on one of `days_of_week`
    (0=Mon…6=Sun, matching datetime.weekday())."""
    tz = ZoneInfo(timezone_name)
    now = now.astimezone(tz) if now is not None else datetime.now(tz)
    if now.weekday() not in days_of_week:
        return False
    return window_start_hour <= now.hour < window_end_hour
