"""Long HISTORY writes stay below asyncpg's bind limit and remain one transaction.

PostgreSQL cases use only the explicitly supplied HISTORY_TEST_POSTGRES_URL and a
fresh per-test schema. Default runs exercise SQLite and skip PostgreSQL.
"""
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import alpaca, confidence_cache as cc
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.routers import stock_scan
from app.services import historical_store as hs, history_backfill as history


def _dates():
    dates = []
    day = date(2008, 1, 2)
    while len(dates) < 4433:
        if day.weekday() < 5:
            dates.append(day)
        day += timedelta(days=1)
    return dates


DATES = _dates()
START, END = DATES[0], DATES[-1]
SEAM_INDEX = 3300
NOW = datetime(2026, 10, 9, 23, tzinfo=timezone.utc)


def _bars(*, factor=1.0, source="tiingo", start_index=0):
    return [{"time": day.isoformat(), "open": 99.0, "high": 101.0, "low": 98.0,
             "close": 100.0, "volume": 1234, "adj_factor": factor,
             "split_factor": 1.0, "div_cash": 0.0, "source": source}
            for day in DATES[start_index:]]


@pytest_asyncio.fixture(params=["sqlite", "postgres"])
async def database(request, monkeypatch, tmp_path):
    schema = None
    if request.param == "postgres":
        url = os.getenv("HISTORY_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("HISTORY_TEST_POSTGRES_URL not supplied")
        schema = f"history_large_{uuid4().hex}"
        engine = create_async_engine(url, execution_options={"schema_translate_map": {None: schema}})
        from sqlalchemy.dialects.postgresql import insert
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from sqlalchemy.dialects.sqlite import insert
    # The application runtime may be pinned to SQLite by conftest. Select the
    # insert implementation from this explicitly created test engine instead.
    assert engine.dialect.name == ("postgresql" if request.param == "postgres" else "sqlite")
    monkeypatch.setattr(hs, "_dialect_insert", lambda: insert)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(OhlcvBase.metadata.create_all)
        monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
        monkeypatch.setattr(history, "AsyncSessionLocal", factory)
        monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
        monkeypatch.setattr(cc, "_DB_PATH", str(tmp_path / "confidence.db"))
        monkeypatch.setattr(cc, "_store", {})
        monkeypatch.setattr(cc, "_generation", 0)
        monkeypatch.setattr(cc, "_symbol_generation", {})
        monkeypatch.setattr(cc, "_clear_generation", 0)
        monkeypatch.setattr(stock_scan, "_BACKTEST_CACHE", {})
        cc._init_db()
        yield engine, factory
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


async def _snapshot(factory):
    async with factory() as db:
        rows = (await db.execute(select(M).order_by(M.date))).scalars().all()
        state = await db.get(State, "TEST")
        return (
            [(r.date, float(r.open), float(r.high), float(r.low), float(r.close),
              int(r.volume), float(r.adj_factor), r.source, r.fetched_at) for r in rows],
            None if state is None else (
                state.floor_requested_start, state.floor_date, state.floor_provider,
                state.floor_checked_at, state.seam_date, state.old_source, state.seam_signature),
        )


async def _seed_history(factory, monkeypatch):
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars()))
    result = await history.update_history(
        "TEST", START, END, alpaca_bars=_bars(source="alpaca", start_index=SEAM_INDEX)
    )
    assert result.stored == 4433
    async with factory() as db:
        state = await db.get(State, "TEST")
        assert state.seam_signature and state.seam_date == DATES[SEAM_INDEX]
        state.seam_signature = None  # A damaged proof requires the full production refresh.
        await db.commit()


async def _warm_caches():
    keys = {}
    for symbol in ["TEST", "OTHER"]:
        bt = stock_scan._backtest_key(symbol, "pullback_ema", "Bullish", _bars())
        stock_scan._BACKTEST_CACHE[bt] = (f"{symbol} stale backtest", time.time() + 1000)
        confidence = cc.cache_key(symbol, "Bullish", "Swing", scoring_mode="stock")
        await cc.set_cached(confidence, {"confidence": 70})
        keys[symbol] = (bt, confidence)
    return keys


def _confidence_rows():
    with sqlite3.connect(cc._DB_PATH) as connection:
        return set(connection.execute("SELECT cache_key, value, expires_at FROM confidence_cache"))


def _assert_adjusted(bars):
    assert len(bars) == 4433
    assert bars[0]["time"] == START.isoformat() and bars[-1]["time"] == END.isoformat()
    assert {(b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars} == {
        (9.9, 10.1, 9.8, 10.0, 1234)
    }


@pytest.mark.asyncio
async def test_4433_row_upsert_returns_every_date_and_caller_owns_commit(database):
    engine, factory = database
    async with factory() as db:
        dates = await hs._store_bars("TEST", _bars(factor=0.1), db)
        assert dates == set(DATES)
        assert db.in_transaction()
        await db.rollback()
    assert await _snapshot(factory) == ([], None)
    async with factory() as db:
        assert await hs._store_bars("TEST", _bars(factor=0.1), db) == set(DATES)
        await db.commit()
    async with factory() as db:
        _assert_adjusted(await hs._read_bars("TEST", START, END, db))


@pytest.mark.parametrize("path", ["production", "injected-window"])
@pytest.mark.asyncio
async def test_long_refresh_rewrites_all_4433_adjusted_closes_from_100_to_10(database, monkeypatch, path):
    engine, factory = database
    await _seed_history(factory, monkeypatch)
    keys = await _warm_caches()
    async with factory() as db:
        before = await hs._read_bars("TEST", START, END, db)
        assert len(before) == 4433 and {b["close"] for b in before} == {100.0}
    if path == "production":
        monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars(factor=0.1)))
        monkeypatch.setattr(alpaca, "get_alpaca_client", AsyncMock(return_value=object()))
        fetch = AsyncMock(return_value=_bars(factor=0.1, source="alpaca", start_index=SEAM_INDEX))
        monkeypatch.setattr(alpaca, "fetch_daily_bars_single", fetch)
        result = await hs.refresh_adjustments(["TEST"])
        assert fetch.await_args.kwargs["strict_adjustments"] is True
    else:
        fetch = AsyncMock(return_value=_bars(factor=0.1))
        result = await hs.refresh_adjustments(["TEST"], fetch=fetch)
        fetch.assert_awaited_once_with("TEST", START, END)
    assert result["refreshed"] == ["TEST"] and result["failed"] == []
    async with factory() as db:
        _assert_adjusted(await hs._read_bars("TEST", START, END, db))
        assert await hs.find_stale_adjustment("TEST", db) is None
    assert stock_scan._get_backtest_cached(keys["TEST"][0]) is None
    assert cc.get_cached(keys["TEST"][1]) is None
    assert stock_scan._get_backtest_cached(keys["OTHER"][0]) == "OTHER stale backtest"
    assert cc.get_cached(keys["OTHER"][1]) == {"confidence": 70}


@pytest.mark.asyncio
async def test_error_after_first_upsert_chunk_preserves_all_rows_metadata_and_caches(database, monkeypatch):
    engine, factory = database
    await _seed_history(factory, monkeypatch)
    before = await _snapshot(factory)
    keys = await _warm_caches()
    confidence_rows = _confidence_rows()
    generation = cc.generation()
    backtests = dict(stock_scan._BACKTEST_CACHE)
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars(factor=0.1)))
    monkeypatch.setattr(alpaca, "get_alpaca_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", AsyncMock(
        return_value=_bars(factor=0.1, source="alpaca", start_index=SEAM_INDEX)))
    insert_calls = 0

    def fail_second_chunk(connection, cursor, statement, parameters, context, executemany):
        nonlocal insert_calls
        if statement.lstrip().upper().startswith("INSERT INTO") and "ohlcv_daily" in statement:
            insert_calls += 1
            if insert_calls == 2:
                raise RuntimeError("synthetic DB failure after the first completed upsert chunk")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_second_chunk)
    try:
        result = await hs.refresh_adjustments(["TEST"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_second_chunk)
    assert insert_calls == 2
    assert result["failed"] == ["TEST"] and result["refreshed"] == []
    assert await _snapshot(factory) == before
    assert stock_scan._BACKTEST_CACHE == backtests
    assert cc.generation() == generation and _confidence_rows() == confidence_rows
    for symbol in keys:
        assert stock_scan._get_backtest_cached(keys[symbol][0]) == f"{symbol} stale backtest"
        assert cc.get_cached(keys[symbol][1]) == {"confidence": 70}


@pytest.mark.parametrize("fallback_available", [False, True])
@pytest.mark.asyncio
async def test_get_bars_rolls_back_rejected_provider_chunks_before_fallback(
    database, monkeypatch, fallback_available
):
    engine, factory = database
    keys = await _warm_caches()
    confidence_rows = _confidence_rows()
    generation = cc.generation()
    backtests = dict(stock_scan._BACKTEST_CACHE)
    rejected = _bars(factor=0.1, source="alpaca")[:600]
    # A real NOT NULL violation in chunk two leaves chunk one pending on SQLite
    # and aborts the transaction on PostgreSQL. Neither can enter the next attempt.
    rejected[500]["volume"] = None
    fallback = _bars(factor=0.2)[500:600] if fallback_available else []
    monkeypatch.setattr(alpaca, "get_alpaca_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", AsyncMock(return_value=rejected))
    monkeypatch.setattr(hs, "fetch_historical_candles", AsyncMock(return_value=fallback))
    monkeypatch.setattr(hs, "_yfinance_fetch", lambda *args: [])

    bars = await hs.get_bars("TEST", START, DATES[599])
    snapshot, state = await _snapshot(factory)
    assert state is None
    async with factory() as db:
        persisted = await hs._read_bars("TEST", START, DATES[599], db)
    assert persisted == bars
    if fallback_available:
        assert len(bars) == 100
        assert [b["time"] for b in bars] == [d.isoformat() for d in DATES[500:600]]
        assert {b["close"] for b in bars} == {20.0}
        assert {row[7] for row in snapshot} == {"tiingo"}
        assert stock_scan._get_backtest_cached(keys["TEST"][0]) is None
        assert cc.get_cached(keys["TEST"][1]) is None
    else:
        assert bars == [] and snapshot == []
        assert stock_scan._BACKTEST_CACHE == backtests
        assert cc.generation() == generation and _confidence_rows() == confidence_rows
        assert cc.get_cached(keys["TEST"][1]) == {"confidence": 70}
    assert stock_scan._get_backtest_cached(keys["OTHER"][0]) == "OTHER stale backtest"
    assert cc.get_cached(keys["OTHER"][1]) == {"confidence": 70}
