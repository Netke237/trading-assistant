"""BG-SCHEDULE-MAINT: the weekly read-only history health check, its schedule,
and the nightly backtest-artifact expiry sweep."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services import history_health, historical_store, ingestion_scheduler
from app.services.history_gap_detector import get_nyse_trading_days

TODAY = date(2026, 6, 30)          # window = 2026-05-31 .. newest stored bar
FULL = get_nyse_trading_days(date(2026, 4, 1), date(2026, 6, 29))   # Juneteenth excluded


@pytest_asyncio.fixture
async def db(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'ohlcv.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history_health, "AsyncSessionLocal", factory)
    monkeypatch.setattr(historical_store, "find_stale_adjustment", AsyncMock(return_value=None))
    yield factory
    await engine.dispose()


async def _store(factory, symbol, days):
    async with factory() as s:
        for d in days:
            s.add(OhlcvDailyModel(symbol=symbol, date=d, open=1, high=1, low=1, close=1,
                                  volume=1, source="alpaca",
                                  fetched_at=datetime(2026, 6, 30, tzinfo=timezone.utc)))
        await s.commit()


@pytest.mark.asyncio
async def test_complete_history_reports_nothing(db):
    await _store(db, "SPY", FULL)
    await _store(db, "AAPL", FULL)
    report = await history_health.run_history_health_check(["SPY", "AAPL"], today=TODAY)
    assert report["window_end"] == "2026-06-29"
    assert not history_health.has_findings(report)


@pytest.mark.asyncio
async def test_recent_holes_and_a_missed_night_are_reported_old_holes_are_not(db):
    await _store(db, "SPY", FULL)
    old_hole, recent_hole, last = date(2026, 4, 15), date(2026, 6, 10), date(2026, 6, 29)
    await _store(db, "AAPL", [d for d in FULL if d not in (old_hole, recent_hole, last)])
    report = await history_health.run_history_health_check(["SPY", "AAPL"], today=TODAY)
    assert report["recent_gaps"] == {"AAPL": ["2026-06-10", "2026-06-29"]}


@pytest.mark.asyncio
async def test_new_listing_is_checked_only_from_its_first_bar(db):
    await _store(db, "SPY", FULL)
    await _store(db, "NEWCO", [d for d in FULL if d >= date(2026, 6, 15)])
    report = await history_health.run_history_health_check(["SPY", "NEWCO"], today=TODAY)
    assert report["recent_gaps"] == {}


@pytest.mark.asyncio
async def test_symbol_without_history_is_reported(db):
    await _store(db, "SPY", FULL)
    report = await history_health.run_history_health_check(["SPY", "GHOST"], today=TODAY)
    assert report["no_history"] == ["GHOST"]
    assert report["recent_gaps"] == {}


@pytest.mark.asyncio
async def test_symbols_outside_the_universe_are_ignored(db):
    await _store(db, "SPY", FULL)
    await _store(db, "DELISTED", FULL[:10])      # stopped weeks ago, not in the universe
    report = await history_health.run_history_health_check(["SPY"], today=TODAY)
    assert not history_health.has_findings(report)
    assert report["symbols_checked"] == 1


@pytest.mark.asyncio
async def test_stale_adjustment_is_reported_and_never_repaired(db, monkeypatch):
    await _store(db, "SPY", FULL)
    await _store(db, "AAPL", FULL)
    stale = historical_store.StaleReport(reasons=["jump"], earliest=date(2026, 5, 1))
    monkeypatch.setattr(historical_store, "find_stale_adjustment",
                        AsyncMock(side_effect=lambda sym, _db: stale if sym == "AAPL" else None))
    async with db() as s:
        before = (await s.execute(select(func.count()).select_from(OhlcvDailyModel))).scalar()
    report = await history_health.run_history_health_check(["SPY", "AAPL"], today=TODAY)
    assert report["stale_adjustments"] == [
        {"symbol": "AAPL", "reasons": ["jump"], "earliest": "2026-05-01"}]
    async with db() as s:
        after = (await s.execute(select(func.count()).select_from(OhlcvDailyModel))).scalar()
    assert after == before
    assert "refresh-adjustments" in history_health.format_report(report)


@pytest.mark.asyncio
async def test_notifies_only_when_something_is_wrong(db, monkeypatch):
    from app.services.notifications import dispatch
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(dispatch, "notify_enabled_channels", notify)
    await _store(db, "SPY", FULL)
    monkeypatch.setattr("app.services.ingestion_job.ingestion_universe", lambda: ["SPY"])
    await history_health.run_and_notify(today=TODAY)
    notify.assert_not_awaited()

    monkeypatch.setattr("app.services.ingestion_job.ingestion_universe", lambda: ["SPY", "GHOST"])
    await history_health.run_and_notify(today=TODAY)
    notify.assert_awaited_once()
    assert "GHOST" in notify.await_args.args[1]


def test_long_symbol_lists_are_capped():
    report = {"symbols_checked": 60, "window_end": "2026-06-29", "stale_adjustments": [],
              "recent_gaps": {}, "no_history": [f"S{i:02d}" for i in range(40)]}
    assert "(+15 more)" in history_health.format_report(report)


# ── schedule ──────────────────────────────────────────────────────────────────

class _FakeScheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, fn, trigger, id, replace_existing):
        self.jobs[id] = (fn, trigger)

    def remove_job(self, job_id):
        del self.jobs[job_id]


def test_weekly_check_rides_on_the_nightly_enabled_flag(monkeypatch):
    fake = _FakeScheduler()
    monkeypatch.setattr(ingestion_scheduler, "_get", lambda: fake)
    ingestion_scheduler.configure(True, "02:00")
    assert set(fake.jobs) == {"ingestion_nightly", "history_health_weekly"}
    fn, trigger = fake.jobs["history_health_weekly"]
    assert fn is ingestion_scheduler._run_weekly_health
    fields = {f.name: str(f) for f in trigger.fields}
    assert (fields["day_of_week"], fields["hour"], fields["minute"]) == ("sun", "3", "0")

    ingestion_scheduler.configure(False, "02:00")
    assert fake.jobs == {}


@pytest.mark.asyncio
async def test_weekly_job_swallows_failures(monkeypatch):
    monkeypatch.setattr(history_health, "run_and_notify", AsyncMock(side_effect=RuntimeError("db down")))
    await ingestion_scheduler._run_weekly_health()      # must not raise


# ── nightly backtest-artifact expiry sweep ───────────────────────────────────

@pytest.mark.asyncio
async def test_nightly_maintenance_runs_the_artifact_expiry_sweep(monkeypatch):
    from app.data import tiingo_budget
    from app.services import audit, backtest_artifacts, scan_schedule_store
    monkeypatch.setattr(audit, "rotate_audit_log", lambda: None)
    monkeypatch.setattr(audit, "prune_audit_log_archives", lambda years: None)
    monkeypatch.setattr(scan_schedule_store, "prune_scheduled_scan_runs", AsyncMock())
    monkeypatch.setattr(tiingo_budget, "prune_usage", AsyncMock())
    sweep = AsyncMock(return_value=3)
    monkeypatch.setattr(backtest_artifacts, "cleanup_expired", sweep)
    await ingestion_scheduler._run_nightly_maintenance()
    sweep.assert_awaited_once()


@pytest.mark.asyncio
async def test_artifact_sweep_failure_does_not_break_maintenance(monkeypatch):
    from app.data import tiingo_budget
    from app.services import audit, backtest_artifacts, scan_schedule_store
    monkeypatch.setattr(audit, "rotate_audit_log", lambda: None)
    monkeypatch.setattr(audit, "prune_audit_log_archives", lambda years: None)
    monkeypatch.setattr(scan_schedule_store, "prune_scheduled_scan_runs", AsyncMock())
    monkeypatch.setattr(tiingo_budget, "prune_usage", AsyncMock())
    monkeypatch.setattr(backtest_artifacts, "cleanup_expired",
                        AsyncMock(side_effect=backtest_artifacts.ArtifactStorageError("x")))
    await ingestion_scheduler._run_nightly_maintenance()   # must not raise
