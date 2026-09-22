# backend/tests/test_strategy_watch_scheduler.py
from __future__ import annotations

from datetime import datetime

from app.services.scheduling_tz import MARKET_TZ


def _ny(y, m, d, hh, mm=0):
    """An aware instant on the market's own wall clock."""
    return datetime(y, m, d, hh, mm, tzinfo=MARKET_TZ)
from unittest.mock import AsyncMock, patch

import pytest

from app.services.strategy_watch_scheduler import StrategyWatchScheduler


# ── `_market_open`'s own boundaries ──────────────────────────────────────────
# AUTOTRADE-2B core round 1, finding F-8. This module's session test had NO
# test of its own: every test below patches `_market_open` wholesale, and
# mutating its 09:30 boundary failed exactly ONE test in the whole suite — one
# belonging to `auto_trader`'s money gate, which imports this function as
# `_market_session_open` for guard (i). A scheduler's private constant should
# not have another module's regression test as its sole pin.


@pytest.mark.parametrize("now,expected,why", [
    # 2026-06-10 is a Wednesday; 2026-06-13 a Saturday, 2026-06-14 a Sunday.
    (_ny(2026, 6, 10, 9, 29),  False, "one minute before the open"),
    (_ny(2026, 6, 10, 9, 30),  True,  "the open itself is INSIDE the session"),
    (_ny(2026, 6, 10, 12, 0),  True,  "mid-session"),
    (_ny(2026, 6, 10, 15, 59), True,  "one minute before the close"),
    (_ny(2026, 6, 10, 16, 0),  True,  "the close itself — the bound is `<=`, "
                                      "INCLUSIVE, and callers depend on which"),
    (_ny(2026, 6, 10, 16, 1),  False, "one minute after the close"),
    (_ny(2026, 6, 10, 0, 0),   False, "midnight"),
    (_ny(2026, 6, 13, 12, 0),  False, "Saturday mid-'session'"),
    (_ny(2026, 6, 14, 12, 0),  False, "Sunday mid-'session'"),
    # Tracked via a real IANA zone, so the offset moves with US DST and the
    # wall-clock boundaries do not. 2026-01-14 is a Wednesday in EST.
    (_ny(2026, 1, 14, 9, 30),  True,  "the open in EST, not EDT"),
    (_ny(2026, 1, 14, 16, 1),  False, "after the close in EST"),
])
def test_market_open_session_boundaries(now, expected, why):
    """The 09:30-16:00 America/New_York boundaries, pinned where they live."""
    from app.services.strategy_watch_scheduler import _market_open

    assert _market_open(now) is expected, why


@pytest.mark.asyncio
async def test_disabled_schedule_does_not_run():
    sched = StrategyWatchScheduler()
    with patch.object(sched, "_load_schedule",
                      return_value={"enabled": False, "mode": "eod",
                                    "eod_time": "16:15", "poll_hours": 4}), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 17, 0))  # Friday 5pm
    assert ran is False
    run.assert_not_called()


@pytest.mark.asyncio
async def test_eod_runs_once_after_time_then_not_again_same_day():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        first = await sched._maybe_run(now=datetime(2026, 6, 12, 16, 20))   # after 16:15
        second = await sched._maybe_run(now=datetime(2026, 6, 12, 18, 0))   # same day
    assert first is True
    assert second is False
    assert run.await_count == 1


@pytest.mark.asyncio
async def test_eod_does_not_run_before_time():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "eod", "eod_time": "16:15", "poll_hours": 4}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 15, 0))  # before 16:15
    assert ran is False
    run.assert_not_called()


@pytest.mark.asyncio
async def test_poll_respects_interval():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler._market_open", return_value=True), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        first = await sched._maybe_run(now=datetime(2026, 6, 12, 10, 0))
        too_soon = await sched._maybe_run(now=datetime(2026, 6, 12, 11, 0))   # +1h < 2h
        later = await sched._maybe_run(now=datetime(2026, 6, 12, 12, 30))     # +2.5h
    assert first is True and too_soon is False and later is True
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_poll_skips_when_market_closed():
    sched = StrategyWatchScheduler()
    cfg = {"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 2}
    with patch.object(sched, "_load_schedule", return_value=cfg), \
         patch("app.services.strategy_watch_scheduler._market_open", return_value=False), \
         patch("app.services.strategy_watch_scheduler.evaluate_and_notify",
               new_callable=AsyncMock) as run:
        ran = await sched._maybe_run(now=datetime(2026, 6, 12, 10, 0))
    assert ran is False
    run.assert_not_called()


def test_run_now_status_shape():
    sched = StrategyWatchScheduler()
    status = sched.get_status()
    assert set(status) >= {"running", "last_run_at", "mode", "enabled"}
