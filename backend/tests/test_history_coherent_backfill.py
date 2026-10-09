from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs

START = date(2015, 12, 21)
SEAM = date(2016, 1, 4)
END = date(2016, 1, 11)


def days(start, end):
    result = []
    while start <= end:
        if start.weekday() < 5:
            result.append(start)
        start += timedelta(days=1)
    return result


def bars(start=START, end=END, *, source="tiingo", factor=1.0, close=100.0):
    return [{"time": d.isoformat(), "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": 100,
             "adj_factor": factor, "split_factor": 1.0, "div_cash": 0.0,
             "source": source} for d in days(start, end)]


@pytest_asyncio.fixture
async def factory(monkeypatch):
    from app.services import history_backfill as history
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: datetime(2026, 10, 9, 23, tzinfo=timezone.utc))
    yield factory
    await engine.dispose()


async def snapshot(factory):
    async with factory() as db:
        rows = (await db.execute(select(M).order_by(M.date))).scalars().all()
        return [(r.date, float(r.close), float(r.adj_factor), r.source) for r in rows]


@pytest.mark.asyncio
async def test_prefix_is_added_even_when_current_suffix_is_fresh(factory, monkeypatch):
    from app.services import history_backfill as history
    async with factory() as db:
        await hs._store_bars("TEST", bars(SEAM, source="alpaca"), db)
        await db.commit()
    fallback = AsyncMock(return_value=bars())
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    result = await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    assert result.backfilled
    result_rows = await snapshot(factory)
    assert result_rows[0][0] == START
    assert {r[3] for r in result_rows if r[0] < SEAM} == {"tiingo"}
    async with factory() as db:
        state = await db.get(State, "TEST")
        assert state.seam_date == SEAM and state.seam_signature


@pytest.mark.asyncio
async def test_equal_raw_prices_with_different_adjustment_basis_preserve_history(factory, monkeypatch):
    from app.services import history_backfill as history
    async with factory() as db:
        await hs._store_bars("TEST", bars(SEAM, source="alpaca"), db)
        await db.commit()
    before = await snapshot(factory)
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars(factor=0.1)))
    with pytest.raises(history.HistorySeamMismatch):
        await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    assert await snapshot(factory) == before


@pytest.mark.asyncio
async def test_later_split_refreshes_old_and_current_segments(factory, monkeypatch):
    from app.services import history_backfill as history
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()))
    await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars(factor=0.1)))
    await history.update_history("TEST", START, END,
                                 alpaca_bars=bars(SEAM, source="alpaca", factor=0.1))
    async with factory() as db:
        adjusted = await hs._read_bars("TEST", START, END, db)
    assert {r["close"] for r in adjusted} == {10.0}


@pytest.mark.asyncio
async def test_missing_existing_old_date_refuses_both_segments(factory, monkeypatch):
    from app.services import history_backfill as history
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()))
    await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    before = await snapshot(factory)
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()[1:]))
    with pytest.raises(history.HistorySeamMismatch):
        await history.update_history("TEST", START, END,
                                     alpaca_bars=bars(SEAM, source="alpaca", factor=0.1))
    assert await snapshot(factory) == before


@pytest.mark.asyncio
async def test_failure_between_writes_rolls_back_bars_and_metadata(factory, monkeypatch):
    from app.services import history_backfill as history
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()))
    real_store = hs._store_bars
    count = 0

    async def failing_store(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic write failure")
        return await real_store(*args)

    monkeypatch.setattr(hs, "_store_bars", failing_store)
    with pytest.raises(RuntimeError):
        await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    assert await snapshot(factory) == []
    async with factory() as db:
        assert await db.get(State, "TEST") is None


@pytest.mark.asyncio
async def test_production_refresh_refetches_the_older_span_and_revalidates_proof(factory, monkeypatch):
    from app.services import history_backfill as history
    from app.data import alpaca
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=bars()))
    await history.update_history("TEST", START, END, alpaca_bars=bars(SEAM, source="alpaca"))
    async with factory() as db:
        state = await db.get(State, "TEST")
        state.seam_signature = None
        await db.commit()
    fallback = AsyncMock(return_value=bars(factor=0.1))
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    monkeypatch.setattr(alpaca, "get_alpaca_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single",
                        AsyncMock(return_value=bars(SEAM, source="alpaca", factor=0.1)))
    result = await hs.refresh_adjustments(["TEST"])
    assert result["refreshed"] == ["TEST"] and not result["failed"]
    assert fallback.call_args.args[1] == START
    async with factory() as db:
        adjusted = await hs._read_bars("TEST", START, END, db)
        assert {row["close"] for row in adjusted} == {10.0}
        assert await hs.find_stale_adjustment("TEST", db) is None
