"""HISTORY-SINGLE-PROVIDER-REBUILD T3: ingestion trigger, request flag and status."""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs, history_backfill as history, ingestion_job as job

# Noon UTC: the host calendar date is the same in every timezone from UTC-11 to UTC+11,
# and the previous weekday has settled (16:00 ET + 2 h) while today has not.
NOW1 = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)   # Tuesday; Monday 10-12 settled
NOW2 = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)   # Wednesday; Tuesday 10-13 settled
SEAM = date(2026, 9, 1)
STALE = date(2026, 10, 9)


def days(start, end):
    out = []
    while start <= end:
        if start.weekday() < 5:
            out.append(start)
        start += timedelta(days=1)
    return out


def bars(start, end, *, source, factor=1.0, close=100.0):
    return [{"time": d.isoformat(), "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 100, "adj_factor": factor, "split_factor": 1.0,
             "div_cash": 0.0, "source": source} for d in days(start, end)]


@pytest_asyncio.fixture
async def env(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = {"now": NOW1}

    class FixedDate(date):
        @classmethod
        def today(cls):
            return clock["now"].astimezone().date()

    for module in (history, hs, job):
        monkeypatch.setattr(module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: clock["now"])
    monkeypatch.setattr(job, "date", FixedDate)
    monkeypatch.setattr(job, "effective_years", lambda years=None: 1)
    monkeypatch.setattr(job, "_state", dict(job._state))
    monkeypatch.setattr(history, "notify_bars_changed", MagicMock())

    provider = {"tiingo_factor": 0.9, "tiingo_close": 100.0, "alpaca_factor": 1.0}

    async def tiingo_fetch(symbol, start, end, *, strict_adjustments):
        return bars(start, end, source="tiingo", factor=provider["tiingo_factor"],
                    close=provider["tiingo_close"])

    tiingo_mock = AsyncMock(side_effect=tiingo_fetch)
    yf_mock = MagicMock(return_value=[])
    monkeypatch.setattr(tiingo, "fetch_historical_candles", tiingo_mock)
    monkeypatch.setattr(hs, "_yfinance_fetch", yf_mock)

    async def batch(chunk, start, end, *, client, strict_adjustments):
        return {s: bars(SEAM, end, source="alpaca", factor=provider["alpaca_factor"]) for s in chunk}

    batch_mock = AsyncMock(side_effect=batch)
    monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(job, "fetch_daily_bars_batch", batch_mock)
    yield {"factory": factory, "clock": clock, "provider": provider,
           "tiingo": tiingo_mock, "tiingo_fetch": tiingo_fetch, "yfinance": yf_mock, "batch": batch_mock}
    await engine.dispose()


async def seed_alpaca(factory, symbol, end=STALE):
    async with factory() as db:
        await hs._store_bars(symbol, bars(SEAM, end, source="alpaca"), db)
        await db.commit()


async def snapshot(factory, since=None):
    async with factory() as db:
        query = select(M).order_by(M.symbol, M.date)
        if since is not None:
            query = query.where(M.date >= since)
        rows = (await db.execute(query)).scalars().all()
        states = (await db.execute(select(State).order_by(State.symbol))).scalars().all()
        cols = [c.name for c in M.__table__.columns]
        scols = [c.name for c in State.__table__.columns]
        return ([tuple(getattr(r, c) for c in cols) for r in rows],
                [tuple(getattr(s, c) for c in scols) for s in states])


async def rows(factory, symbol):
    async with factory() as db:
        return (await db.execute(select(M).where(M.symbol == symbol).order_by(M.date))).scalars().all()


@pytest.mark.asyncio
async def test_seam_refused_symbol_is_counted_and_rebuilt_not_failed(env):
    factory = env["factory"]
    await seed_alpaca(factory, "TEST")
    result = await job.run_ingestion(["TEST"])
    state = job.get_ingestion_state()
    fetch_end = NOW1.astimezone().date()
    fetch_start = fetch_end - timedelta(days=365)
    assert result.seam_mismatch == 1 and result.seam_mismatch_symbols == ["TEST"]
    assert result.seam_ratios == {"TEST": pytest.approx(0.9)}
    assert result.failed == 0 and state["failed"] == 0
    assert result.rebuilt == 1 and result.rebuilt_symbols == ["TEST"]
    assert result.rebuild_refused == 0 and result.rebuild_refused_symbols == []
    stored = await rows(factory, "TEST")
    first, last = stored[0].date, stored[-1].date
    assert {r.source for r in stored} == {"tiingo"}
    assert last == date(2026, 10, 12)
    assert result.rebuild_details == {"TEST": {
        "provider": "tiingo", "trigger": "seam_refusal",
        "rows_before": len(days(SEAM, STALE)), "rows_after": len(stored),
        "first_date_before": SEAM.isoformat(), "first_date_after": first.isoformat(),
        "last_date_after": last.isoformat(),
    }}
    assert first == days(fetch_start, fetch_end)[0]
    for key in ("rebuilt", "rebuilt_symbols", "rebuild_details", "rebuild_refused",
                "rebuild_refused_symbols", "rebuild_errors", "single_provider_updated",
                "single_provider_failed_symbols", "single_provider_errors"):
        assert state[key] == getattr(result, key)
    assert result.alpaca_count == 0 and result.single_provider_updated == 0
    assert result.errors == []
    singles = await job.single_provider_symbols()
    assert set(singles) == {"TEST"}
    assert singles["TEST"]["provider"] == "tiingo"
    assert singles["TEST"]["floor_date"] == first.isoformat()
    assert datetime.fromisoformat(singles["TEST"]["rebuilt_at"]) is not None


@pytest.mark.asyncio
async def test_next_normal_ingestion_updates_rebuilt_symbol_from_its_provider(env):
    factory = env["factory"]
    await seed_alpaca(factory, "TEST")
    first = await job.run_ingestion(["TEST"])
    assert first.rebuilt_symbols == ["TEST"]
    env["clock"]["now"] = NOW2
    env["yfinance"].reset_mock()
    second = await job.run_ingestion(["TEST"])
    assert second.seam_mismatch == 0 and second.seam_mismatch_symbols == []
    assert second.failed == 0 and second.errors == []
    assert second.single_provider_updated == 1
    assert second.alpaca_count == 0 and second.gapfill_count == 0
    assert second.rebuilt == 0 and second.rebuild_details == {}
    stored = await rows(factory, "TEST")
    assert stored[-1].date == date(2026, 10, 13) and stored[-1].source == "tiingo"
    assert {r.source for r in stored} == {"tiingo"}
    env["yfinance"].assert_not_called()


@pytest.mark.asyncio
async def test_refused_rebuild_after_seam_refusal_fails_and_leaves_rows(env):
    factory = env["factory"]
    env["provider"]["tiingo_factor"] = 1.0
    env["provider"]["tiingo_close"] = 102.0
    await seed_alpaca(factory, "TEST")
    before = await snapshot(factory)
    result = await job.run_ingestion(["TEST"])
    assert result.seam_mismatch == 1
    assert result.failed == 1
    assert result.rebuilt == 0 and result.rebuilt_symbols == []
    assert result.rebuild_refused == 1 and result.rebuild_refused_symbols == ["TEST"]
    assert "tiingo:" in result.rebuild_errors["TEST"] and "yfinance:" in result.rebuild_errors["TEST"]
    assert await snapshot(factory) == before
    [line] = [e for e in result.errors if e.startswith("TEST:")]
    assert "seam mismatch — adjusted seam differs" in line
    assert "rebuild refused — tiingo: close differs" in line
    assert "yfinance: no settled bars" in line
    assert await job.single_provider_symbols() == {}


@pytest.mark.asyncio
async def test_single_provider_update_refused_is_reported_without_rebuild(env):
    factory = env["factory"]
    await seed_alpaca(factory, "TEST")
    await job.run_ingestion(["TEST"])
    env["clock"]["now"] = NOW2
    env["tiingo"].side_effect = RuntimeError("tiingo down")
    env["yfinance"].reset_mock()
    env["yfinance"].return_value = bars(SEAM, date(2026, 10, 13), source="yfinance")
    # The run prunes rows older than its own one-year cutoff; everything kept is unchanged.
    cutoff = NOW2.astimezone().date() - timedelta(days=365)
    before = await snapshot(factory, since=cutoff)
    result = await job.run_ingestion(["TEST"])
    assert result.failed == 1
    assert result.single_provider_failed_symbols == ["TEST"]
    assert result.single_provider_updated == 0
    assert result.rebuilt == 0 and result.rebuild_refused == 0
    assert result.errors == ["TEST: single-provider update refused — tiingo: tiingo down"]
    env["yfinance"].assert_not_called()
    assert await snapshot(factory) == before
    assert await snapshot(factory, since=cutoff) == before


@pytest.mark.asyncio
async def test_single_provider_refusal_reason_is_in_status_and_log(env, app, caplog):
    """HISTORY-INGEST-GAPS piece 2: the reason is visible per symbol, then reset."""
    factory = env["factory"]
    await seed_alpaca(factory, "TEST")
    await seed_alpaca(factory, "OTHER")
    await job.run_ingestion(["TEST", "OTHER"])
    env["clock"]["now"] = NOW2
    env["tiingo"].side_effect = RuntimeError("tiingo down")
    with caplog.at_level("WARNING", logger="app.services.ingestion_job"):
        result = await job.run_ingestion(["TEST", "OTHER"])
    reasons = {"TEST": "tiingo: tiingo down", "OTHER": "tiingo: tiingo down"}
    assert result.single_provider_failed_symbols == ["TEST", "OTHER"]
    assert result.single_provider_errors == reasons
    assert job.get_ingestion_state()["single_provider_errors"] == reasons
    logged = [r.getMessage() for r in caplog.records if r.name == "app.services.ingestion_job"]
    assert "ingestion: single-provider update refused for TEST — tiingo: tiingo down" in logged
    assert "ingestion: single-provider update refused for OTHER — tiingo: tiingo down" in logged
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        status = (await ac.get("/api/data/ingest/status")).json()
    assert status["single_provider_errors"] == reasons
    assert status["single_provider_failed_symbols"] == ["TEST", "OTHER"]
    assert set(status["single_provider_symbols"]) == {"TEST", "OTHER"}

    env["tiingo"].side_effect = env["tiingo_fetch"]
    after = await job.run_ingestion(["TEST", "OTHER"])
    assert after.failed == 0 and after.single_provider_updated == 2
    assert after.single_provider_errors == {}
    assert job.get_ingestion_state()["single_provider_errors"] == {}


@pytest.mark.asyncio
async def test_rebuild_request_rebuilds_symbol_that_is_not_seam_refused(env, monkeypatch):
    factory = env["factory"]
    env["provider"]["tiingo_factor"] = 1.0
    await seed_alpaca(factory, "TEST")
    update = AsyncMock(side_effect=AssertionError("rebuild=True must not call update_history"))
    monkeypatch.setattr(job, "update_history", update)
    result = await job.run_ingestion(["TEST"], rebuild=True)
    update.assert_not_awaited()
    env["batch"].assert_awaited()
    assert result.failed == 0 and result.seam_mismatch == 0
    assert result.rebuilt_symbols == ["TEST"]
    assert result.rebuild_details["TEST"]["trigger"] == "request"
    assert result.rebuild_details["TEST"]["provider"] == "tiingo"
    assert {r.source for r in await rows(factory, "TEST")} == {"tiingo"}


@pytest.mark.asyncio
async def test_refused_rebuild_request_is_recorded_under_rebuild_refused(env, monkeypatch):
    factory = env["factory"]
    env["tiingo"].side_effect = RuntimeError("tiingo down")
    await seed_alpaca(factory, "TEST")
    result = await job.run_ingestion(["TEST"], rebuild=True)
    assert result.failed == 1
    assert result.rebuild_refused_symbols == ["TEST"]
    assert result.errors == [f"TEST: rebuild refused — {result.rebuild_errors['TEST']}"]
    assert "tiingo down" in result.rebuild_errors["TEST"]


@pytest.mark.asyncio
async def test_spy_rebuilt_and_current_does_not_trigger_startup_catch_up(env):
    factory = env["factory"]
    await seed_alpaca(factory, "SPY")
    async with factory() as db:
        assert job._should_ingest(await hs._last_stored_date("SPY", db)) is True
    result = await job.run_ingestion(["SPY"])
    assert result.rebuilt_symbols == ["SPY"]
    async with factory() as db:
        last = await hs._last_stored_date("SPY", db)
    assert last == date(2026, 10, 12)
    assert hs.most_recent_trading_day() == date(2026, 10, 13)
    assert job._should_ingest(last) is False


def test_ingestion_universe_puts_reference_first_without_duplicates(monkeypatch):
    """HISTORY-INGEST-GAPS piece 3: SPY is refreshed by every nightly/startup run."""
    from app.data import universe_presets
    presets = {"SP500": ["AAA", "BBB"], "NDX100": ["BBB", "CCC"], "DOW30": ["SPY", "AAA"]}
    monkeypatch.setattr(universe_presets, "expand_universe", lambda keys: presets[keys[0]])
    assert job.STALENESS_REFERENCE == "SPY"
    assert job.ingestion_universe() == ["SPY", "AAA", "BBB", "CCC"]


def test_ingestion_universe_falls_back_to_reference(monkeypatch):
    from app.data import universe_presets

    def boom(keys):
        raise RuntimeError("csv missing")

    monkeypatch.setattr(universe_presets, "expand_universe", boom)
    assert job.ingestion_universe() == ["SPY"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stale, started", [(True, True), (False, False)])
async def test_startup_catch_up_includes_reference(env, monkeypatch, stale, started):
    from app.data import universe_presets
    factory = env["factory"]
    await seed_alpaca(factory, "SPY", end=STALE if stale else date(2026, 10, 12))
    monkeypatch.setattr(universe_presets, "expand_universe", lambda keys: ["TEST"])
    start = MagicMock(return_value=True)
    monkeypatch.setattr(job, "start_ingestion_task", start)
    assert await job.startup_catch_up() is started
    if started:
        start.assert_called_once_with(["SPY", "TEST"], years=6)
    else:
        start.assert_not_called()


@pytest.mark.asyncio
async def test_nightly_run_refreshes_single_provider_reference(env, monkeypatch):
    from app.data import universe_presets
    from app.services import ingestion_scheduler
    factory = env["factory"]
    await seed_alpaca(factory, "SPY")
    await job.run_ingestion(["SPY"])          # SPY becomes single-provider (Tiingo)
    env["clock"]["now"] = NOW2
    async with factory() as db:
        assert job._should_ingest(await hs._last_stored_date("SPY", db)) is True
    await seed_alpaca(factory, "TEST", end=date(2026, 10, 13))
    monkeypatch.setattr(universe_presets, "expand_universe", lambda keys: ["TEST"])
    monkeypatch.setattr(ingestion_scheduler, "_run_nightly_maintenance", AsyncMock())
    monkeypatch.setattr(job, "_task", None)
    await ingestion_scheduler._run_nightly()
    await job._task
    state = job.get_ingestion_state()
    assert state["status"] == "completed" and state["failed"] == 0
    assert state["single_provider_updated"] == 1
    async with factory() as db:
        last = await hs._last_stored_date("SPY", db)
    assert last == date(2026, 10, 13)
    assert job._should_ingest(last) is False


@pytest.mark.asyncio
async def test_state_has_new_keys_before_any_run():
    state = job.get_ingestion_state()
    for key in ("rebuilt", "rebuilt_symbols", "rebuild_details", "rebuild_refused",
                "rebuild_refused_symbols", "rebuild_errors", "single_provider_updated",
                "single_provider_failed_symbols", "single_provider_errors"):
        assert key in state


@pytest.mark.asyncio
async def test_start_ingestion_task_passes_rebuild(monkeypatch):
    calls = []

    async def fake_run(symbols, **kwargs):
        calls.append((symbols, kwargs))

    monkeypatch.setattr(job, "_state", {"status": "idle"})
    monkeypatch.setattr(job, "_task", None)
    monkeypatch.setattr(job, "run_ingestion", fake_run)
    assert job.start_ingestion_task(["SPY"], years=6, rebuild=True)
    await job._task
    assert calls == [(["SPY"], {"years": 6, "force_backfill": False, "rebuild": True})]


@pytest.fixture
def app():
    from app.main import create_app
    return create_app()


@pytest.mark.asyncio
@pytest.mark.parametrize("body, expected", [
    ({"symbols": ["SPY"], "rebuild": True}, True),
    ({"symbols": ["SPY"]}, False),
])
async def test_ingest_post_passes_rebuild_flag(app, body, expected):
    with patch("app.routers.ingestion.start_ingestion_task", return_value=True) as start:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/data/ingest", json=body)
    assert resp.status_code == 202
    assert start.call_args.kwargs["rebuild"] is expected
    assert resp.json()["rebuild"] is expected


@pytest.mark.asyncio
async def test_ingest_status_includes_single_provider_symbols(app):
    singles = {"SPY": {"provider": "tiingo", "rebuilt_at": "2026-10-13T12:00:00+00:00",
                       "floor_date": "2025-10-13"}}
    with patch("app.routers.ingestion.get_ingestion_state", return_value={"status": "idle"}), \
         patch("app.routers.ingestion.single_provider_symbols", AsyncMock(return_value=singles)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "idle", "single_provider_symbols": singles}


@pytest.mark.asyncio
async def test_ingest_status_survives_single_provider_query_error(app):
    with patch("app.routers.ingestion.get_ingestion_state", return_value={"status": "idle"}), \
         patch("app.routers.ingestion.single_provider_symbols",
               AsyncMock(side_effect=RuntimeError("db down"))):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/data/ingest/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "idle", "single_provider_symbols": {}}
