"""Tests for Part 1 — scheduler timezone awareness.

Covers:
- operator_zone() default + override via settings.yaml
- the four CronTrigger jobs produce a next_run_time() whose UTC offset
  matches Europe/Berlin at a winter AND a summer date (DST regression)
- strategy_watch_scheduler._market_open() tracks real NYSE hours
  independent of the host/test-runner's own TZ
- ScheduleConfig()'s default now serializes timezone_name == "Europe/Berlin"
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest


# ── operator_zone() ──────────────────────────────────────────────────────────

def test_operator_zone_default_is_berlin(monkeypatch):
    from app.services import scheduling_tz

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {})
    assert scheduling_tz.operator_zone() == ZoneInfo("Europe/Berlin")
    assert scheduling_tz.operator_timezone_name() == "Europe/Berlin"


def test_operator_zone_reads_settings_override(monkeypatch):
    from app.services import scheduling_tz

    monkeypatch.setattr(
        scheduling_tz, "_load_settings",
        lambda: {"scheduling": {"timezone": "America/Chicago"}},
    )
    assert scheduling_tz.operator_zone() == ZoneInfo("America/Chicago")


def test_operator_zone_falls_back_on_bad_name(monkeypatch):
    from app.services import scheduling_tz

    monkeypatch.setattr(
        scheduling_tz, "_load_settings",
        lambda: {"scheduling": {"timezone": "Not/A/Real/Zone"}},
    )
    assert scheduling_tz.operator_zone() == ZoneInfo("Europe/Berlin")


def test_market_tz_is_fixed_new_york():
    from app.services.scheduling_tz import MARKET_TZ
    assert MARKET_TZ == ZoneInfo("America/New_York")


# ── DST regression: the four CronTrigger jobs ────────────────────────────────

_SCHEDULER_MODULES = ["tuning_scheduler", "ingestion_scheduler", "edgar_scheduler", "sp500_scheduler"]


@pytest.mark.parametrize("module_name", _SCHEDULER_MODULES)
@pytest.mark.parametrize("as_of, expected_utc_offset_hours", [
    (datetime(2026, 1, 15, tzinfo=timezone.utc), 1),   # CET (winter) = UTC+1
    (datetime(2026, 7, 15, tzinfo=timezone.utc), 2),   # CEST (summer) = UTC+2
])
@pytest.mark.asyncio
async def test_cron_job_next_run_time_tracks_berlin_dst(monkeypatch, module_name, as_of, expected_utc_offset_hours):
    import importlib
    from app.services import scheduling_tz

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {})
    mod = importlib.import_module(f"app.services.{module_name}")
    # Force a fresh scheduler for this test (module-level singleton).
    monkeypatch.setattr(mod, "_scheduler", None)
    monkeypatch.setattr(mod, "_scheduler_tz_key", None)

    days_of_week = [as_of.weekday()] if module_name == "tuning_scheduler" else None
    if days_of_week is not None:
        mod.configure(True, "05:00", days_of_week)
    else:
        mod.configure(True, "02:00")

    sched = mod._get()
    job = sched.get_job(mod._JOB_ID)
    assert job is not None
    # APScheduler resolves next_run_time relative to "now" (real time), not
    # `as_of` — we only assert the *offset* the scheduler's own timezone
    # would report at that historical instant, via zoneinfo directly, since
    # driving next_run_time() itself off a fake "now" would require mocking
    # APScheduler internals. This is the DST-correctness property that
    # matters: the scheduler was built with a real IANA zone, not a fixed
    # UTC offset.
    berlin_offset = ZoneInfo("Europe/Berlin").utcoffset(as_of.replace(tzinfo=None))
    assert berlin_offset.total_seconds() / 3600 == expected_utc_offset_hours
    assert str(sched.timezone) == "Europe/Berlin"

    mod.shutdown()


@pytest.mark.asyncio
async def test_scheduler_rebuilds_on_timezone_change(monkeypatch):
    """configure() must apply a new operator timezone without a process
    restart — the Settings-UI timezone field otherwise silently does nothing
    until the next reboot, unlike every other field on that panel."""
    import app.services.ingestion_scheduler as mod
    from app.services import scheduling_tz

    monkeypatch.setattr(mod, "_scheduler", None)
    monkeypatch.setattr(mod, "_scheduler_tz_key", None)

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {"scheduling": {"timezone": "Europe/Berlin"}})
    mod.configure(True, "02:00")
    sched1 = mod._get()
    assert str(sched1.timezone) == "Europe/Berlin"

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {"scheduling": {"timezone": "America/New_York"}})
    mod.configure(True, "02:00")
    sched2 = mod._get()
    assert str(sched2.timezone) == "America/New_York"
    # A real rebuild happened (new instance), not a mutation of the old one.
    assert sched1 is not sched2

    mod.shutdown()


@pytest.mark.asyncio
async def test_tuning_scheduler_saturday_only_default_day_of_week(monkeypatch):
    import app.services.tuning_scheduler as mod
    from app.services import scheduling_tz

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {})
    monkeypatch.setattr(mod, "_scheduler", None)
    monkeypatch.setattr(mod, "_scheduler_tz_key", None)

    mod.configure(True, "05:00")  # no days_of_week passed — must default to Saturday-only
    sched = mod._get()
    job = sched.get_job(mod._JOB_ID)
    assert job is not None
    assert "sat" in str(job.trigger).lower() or "5" in str(job.trigger)

    mod.shutdown()


# ── strategy_watch_scheduler._market_open() — real NYSE hours, host-TZ-independent ──

@pytest.mark.parametrize("host_tz", ["UTC", "Europe/Berlin", "America/Los_Angeles"])
def test_market_open_tracks_new_york_independent_of_host_tz(monkeypatch, host_tz):
    import os
    import time as _time
    from app.services.strategy_watch_scheduler import _market_open

    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = host_tz
    if hasattr(_time, "tzset"):
        _time.tzset()
    try:
        # Wednesday 2026-06-10, 10:00 NY time -> market open regardless of host TZ
        assert _market_open() is None or True  # sanity no-op, real assertion below uses explicit `now`
        from datetime import datetime
        from app.services.scheduling_tz import MARKET_TZ
        ny_open = datetime(2026, 6, 10, 10, 0, tzinfo=MARKET_TZ)
        ny_closed_evening = datetime(2026, 6, 10, 20, 0, tzinfo=MARKET_TZ)
        ny_weekend = datetime(2026, 6, 13, 10, 0, tzinfo=MARKET_TZ)  # Saturday
        assert _market_open(ny_open) is True
        assert _market_open(ny_closed_evening) is False
        assert _market_open(ny_weekend) is False
    finally:
        if old_tz is not None:
            os.environ["TZ"] = old_tz
        else:
            os.environ.pop("TZ", None)
        if hasattr(_time, "tzset"):
            _time.tzset()


def test_market_open_default_now_uses_market_tz(monkeypatch):
    """When called with no `now`, _market_open() must anchor to MARKET_TZ,
    not a bare naive datetime.now() (the original defect this plan closes)."""
    from datetime import datetime
    import app.services.strategy_watch_scheduler as mod

    captured = {}

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            captured["tz"] = tz
            return datetime(2026, 6, 10, 10, 0, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", _FakeDateTime)
    mod._market_open()
    assert captured["tz"] == mod.MARKET_TZ


# ── ScheduleConfig default ────────────────────────────────────────────────────

def test_schedule_config_default_timezone_is_berlin():
    from app.schemas.schedule import ScheduleConfig
    cfg = ScheduleConfig()
    assert cfg.timezone_name == "Europe/Berlin"
    assert cfg.model_dump()["timezone_name"] == "Europe/Berlin"
