from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def test_retention_default_and_configured_floor(monkeypatch):
    from app.services import history_retention as retention
    monkeypatch.setattr(retention, "_load_settings", lambda: {})
    assert retention.history_years() == 17
    assert retention.effective_years(1) == 17
    monkeypatch.setattr(retention, "_load_settings", lambda: {"scheduling": {"history_years": 19}})
    assert retention.effective_years(6) == 19
    assert retention.effective_years(20) == 20


@pytest.mark.parametrize("value", [True, 0, 21, "bad", 17.5, None])
def test_invalid_persisted_retention_is_non_destructive(monkeypatch, value):
    from app.services import history_retention as retention
    monkeypatch.setattr(retention, "_load_settings", lambda: {"scheduling": {"history_years": value}})
    assert retention.history_years() == 17


@pytest.mark.asyncio
async def test_short_manual_prune_retains_seventeen_years(monkeypatch):
    from app.services import history_retention as retention, ingestion_job
    from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M
    monkeypatch.setattr(retention, "_load_settings", lambda: {})
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(OhlcvBase.metadata.create_all)
        kept = date.today() - timedelta(days=17 * 365 - 37)
        pruned = date.today() - timedelta(days=17 * 365 + 37)
        async with factory() as db:
            db.add_all([M(symbol="TEST", date=d, open=10, high=11, low=9, close=10,
                          volume=100, adj_factor=1, source="alpaca",
                          fetched_at=datetime.now(timezone.utc)) for d in (kept, pruned)])
            await db.commit()
        monkeypatch.setattr(ingestion_job, "AsyncSessionLocal", factory)
        assert await ingestion_job._prune_old_rows(1) == 1
        async with factory() as db:
            assert (await db.execute(select(M.date))).scalars().all() == [kept]
    finally:
        await engine.dispose()


def test_legacy_timezone_save_preserves_retention_and_other_keys(monkeypatch):
    from app.routers import risk_settings as router
    data = {"scheduling": {"timezone": "UTC", "history_years": 19}, "other": "keep"}
    saved = {}
    monkeypatch.setattr(router, "_load_settings", lambda: data)
    monkeypatch.setattr(router, "_save_settings", lambda value: saved.update(value))
    result = router.put_scheduling(router.SchedulingConfig(timezone="Europe/Berlin"))
    assert saved["scheduling"] == {"timezone": "Europe/Berlin", "history_years": 19}
    assert saved["other"] == "keep"
    assert result.history_years == 19
    router.put_scheduling(router.SchedulingConfig(timezone="UTC", history_years=20))
    assert saved["scheduling"]["history_years"] == 20


@pytest.mark.asyncio
async def test_manual_api_exposes_effective_horizon(monkeypatch):
    from app.routers import ingestion as router
    from app.services import history_retention as retention
    monkeypatch.setattr(retention, "_load_settings", lambda: {})
    start = Mock()
    monkeypatch.setattr(router, "start_ingestion_task", start)
    result = await router.trigger_ingest(router.IngestRequest(symbols=["TEST"], years=1))
    assert result["years"] == 17
    assert start.call_args.kwargs["years"] == 17
    assert router.IngestRequest(symbols=["TEST"], years=20).years == 20
    with pytest.raises(ValidationError):
        router.IngestRequest(symbols=["TEST"], years=21)


@pytest.mark.asyncio
async def test_nightly_uses_same_retention(monkeypatch):
    from app.services import history_retention as retention, ingestion_job, ingestion_scheduler
    from app.data import universe_presets
    monkeypatch.setattr(retention, "_load_settings", lambda: {"scheduling": {"history_years": 19}})
    monkeypatch.setattr(universe_presets, "expand_universe", lambda presets: ["TEST"])
    start = Mock()
    monkeypatch.setattr(ingestion_job, "start_ingestion_task", start)
    monkeypatch.setattr(ingestion_scheduler, "_run_nightly_maintenance", AsyncMock())
    await ingestion_scheduler._run_nightly()
    start.assert_called_once_with(["SPY", "TEST"], years=19)
