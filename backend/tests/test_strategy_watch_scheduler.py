# backend/tests/test_strategy_watch_scheduler.py
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.strategy_watch_scheduler import StrategyWatchScheduler


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
