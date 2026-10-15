"""HISTORY floor, whole-window fallback, ingestion accounting and cache acceptance."""
import asyncio
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import confidence_cache as cc
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.routers import stock_scan
from app.services import historical_store as hs, history_backfill as history, ingestion_job as job
from app.services.bars_changed import _listeners


START = date(2015, 12, 21)
SEAM = date(2016, 1, 4)
END = date(2016, 2, 15)
NOW = datetime(2026, 10, 9, 23, tzinfo=timezone.utc)


def _bars(start=START, end=END, *, source="tiingo", factor=1.0, close=100.0):
    bars = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            bars.append({"time": day.isoformat(), "open": close, "high": close + 1,
                         "low": close - 1, "close": close, "volume": 100,
                         "adj_factor": factor, "split_factor": 1.0, "div_cash": 0.0,
                         "source": source})
        day += timedelta(days=1)
    return bars


@pytest_asyncio.fixture
async def factory(monkeypatch, tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
    monkeypatch.setattr(cc, "_DB_PATH", str(tmp_path / "confidence.db"))
    monkeypatch.setattr(cc, "_store", {})
    monkeypatch.setattr(cc, "_generation", 0)
    monkeypatch.setattr(cc, "_clear_generation", 0)
    monkeypatch.setattr(cc, "_symbol_generation", {})
    monkeypatch.setattr(stock_scan, "_BACKTEST_CACHE", {})
    cc._init_db()
    yield factory
    await engine.dispose()


async def _seed_floor(factory, *, checked_at=NOW, requested_start=START,
                      floor_date=SEAM, with_rows=True, older=False):
    async with factory() as db:
        if with_rows:
            await hs._store_bars("TEST", _bars(START if older else SEAM, source="alpaca"), db)
        db.add(State(symbol="TEST", floor_requested_start=requested_start,
                     floor_date=floor_date, floor_provider="tiingo", floor_checked_at=checked_at))
        await db.commit()


async def _snapshot(factory):
    async with factory() as db:
        rows = (await db.execute(select(M).order_by(M.symbol, M.date))).scalars().all()
        states = (await db.execute(select(State).order_by(State.symbol))).scalars().all()
        return (
            [(r.symbol, r.date, float(r.close), float(r.adj_factor), r.source, r.fetched_at)
             for r in rows],
            [(s.symbol, s.floor_requested_start, s.floor_date, s.floor_provider,
              s.floor_checked_at, s.seam_date, s.old_source, s.seam_signature) for s in states],
        )


@pytest.mark.parametrize("age", [timedelta(0), timedelta(days=30)])
@pytest.mark.asyncio
async def test_current_observed_floor_reuses_identical_retained_suffix_without_prefix_request(
    factory, monkeypatch, age,
):
    await _seed_floor(factory, checked_at=NOW - age)
    fallback = AsyncMock(side_effect=AssertionError("a current floor should suppress this prefix probe"))
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    result = await history.update_history("TEST", START, END, alpaca_bars=_bars(SEAM, source="alpaca"))
    assert result.floor_reached and not result.backfilled
    fallback.assert_not_awaited()
    async with factory() as db:
        state = await db.get(State, "TEST")
        assert state.floor_requested_start == START and state.floor_date == SEAM
        assert hs._as_utc(state.floor_checked_at) == NOW - age


@pytest.mark.parametrize("reason", ["expired", "wider", "force", "future", "no-retained-rows",
                                    "floor-date-changed", "older-segment"])
@pytest.mark.asyncio
async def test_floor_never_suppresses_expired_wider_forced_or_old_segment_refresh(
    factory, monkeypatch, reason,
):
    await _seed_floor(
        factory,
        checked_at=NOW - timedelta(days=30, seconds=1) if reason == "expired"
        else NOW + timedelta(seconds=1) if reason == "future" else NOW,
        floor_date=SEAM + timedelta(days=1) if reason == "floor-date-changed" else SEAM,
        with_rows=reason != "no-retained-rows", older=reason == "older-segment",
    )
    requested_start = START - timedelta(days=365) if reason == "wider" else START
    fallback = AsyncMock(return_value=_bars(requested_start))
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    await history.update_history("TEST", requested_start, END, alpaca_bars=_bars(SEAM, source="alpaca"),
                                 force_backfill=reason == "force")
    fallback.assert_awaited_once()
    assert fallback.call_args.args[:2] == ("TEST", requested_start)
    async with factory() as db:
        state = await db.get(State, "TEST")
        assert state.floor_requested_start == requested_start
        assert hs._as_utc(state.floor_checked_at) == NOW


@pytest.mark.parametrize("alpaca", [True, False], ids=["suffix", "no-alpaca"])
@pytest.mark.asyncio
async def test_empty_fallback_never_creates_a_floor_or_suppresses_the_next_retry(factory, monkeypatch, alpaca):
    fallback = AsyncMock(return_value=[])
    monkeypatch.setattr(history, "_fetch_fallback", fallback)
    for _ in range(2):
        with pytest.raises((history.HistorySeamMismatch, ValueError)):
            await history.update_history("TEST", START, END,
                                         alpaca_bars=_bars(SEAM, source="alpaca") if alpaca else [])
        assert await _snapshot(factory) == ([], [])
    assert fallback.await_count == 2


@pytest.mark.asyncio
async def test_tiingo_adjusted_mismatch_tries_yfinance_and_accepts_deliberate_factor_one(factory, monkeypatch):
    current = _bars(SEAM, source="alpaca")
    overlap_end = date.fromisoformat(current[4]["time"])
    calls = []

    async def tiingo(symbol, start, end, *, strict_adjustments):
        calls.append(("tiingo", symbol, start, end, strict_adjustments))
        return _bars(start, end, factor=0.9)

    def yfinance(symbol, start, end):
        calls.append(("yfinance", symbol, start, end))
        return _bars(start, end, source="yfinance")

    monkeypatch.setattr("app.data.tiingo.fetch_historical_candles", tiingo)
    monkeypatch.setattr(hs, "_yfinance_fetch", yfinance)
    result = await history.update_history("TEST", START, END, alpaca_bars=current)
    assert result.stored == len(_bars())
    assert calls == [("tiingo", "TEST", START, overlap_end + timedelta(days=1), True),
                     ("yfinance", "TEST", START, overlap_end + timedelta(days=1))]
    rows, states = await _snapshot(factory)
    assert {row[4] for row in rows if row[1] < SEAM} == {"yfinance"}
    assert {row[3] for row in rows} == {1.0}
    assert states[0][3] == "yfinance" and states[0][6] == "yfinance"


async def _warm_caches(bars):
    keys = {}
    for symbol in ["TEST", "TESTX", "OTHER"]:
        bt_key = stock_scan._backtest_key(symbol, "pullback_ema", "Bullish", bars)
        alternate_key = stock_scan._backtest_key(symbol, "breakout_base", "Bullish", bars)
        stock_scan._BACKTEST_CACHE[bt_key] = (f"{symbol} backtest", time.time() + 1000)
        stock_scan._BACKTEST_CACHE[alternate_key] = (f"{symbol} alternate", time.time() + 1000)
        conf_key = cc.cache_key(symbol, "Bullish", "Swing", scoring_mode="stock")
        await cc.set_cached(conf_key, {"confidence": 70})
        keys[symbol] = (bt_key, alternate_key, conf_key)
    return keys


def _persisted_confidence_keys():
    with sqlite3.connect(cc._DB_PATH) as connection:
        return {row[0] for row in connection.execute("SELECT cache_key FROM confidence_cache")}


@pytest.mark.asyncio
async def test_prefix_addition_evicts_warmed_backtest_and_confidence_with_unchanged_latest_twenty(
    factory, monkeypatch,
):
    current = _bars(SEAM, source="alpaca")
    assert len(current) > 20
    async with factory() as db:
        await hs._store_bars("TEST", current, db)
        await db.commit()
    keys = await _warm_caches(current)
    generation = cc.generation()
    assert _listeners["stock_backtests"] is stock_scan.evict_backtest_cache
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars()))
    result = await history.update_history("TEST", START, END, alpaca_bars=current)
    assert result.backfilled
    async with factory() as db:
        expanded = await hs._read_bars("TEST", START, END, db)
    assert stock_scan._backtest_key("TEST", "pullback_ema", "Bullish", expanded) == keys["TEST"][0]
    for key in keys["TEST"][:2]:
        assert stock_scan._get_backtest_cached(key) is None
    assert cc.get_cached(keys["TEST"][2]) is None
    assert keys["TEST"][2] not in _persisted_confidence_keys()
    for symbol in ["TESTX", "OTHER"]:
        assert stock_scan._get_backtest_cached(keys[symbol][0]) == f"{symbol} backtest"
        assert cc.get_cached(keys[symbol][2]) == {"confidence": 70}
    assert cc.invalidated_since("TEST", generation)
    assert not cc.invalidated_since("OTHER", generation)
    await cc.set_cached(keys["TEST"][2], {"confidence": 1}, bars_generation=generation)
    assert cc.get_cached(keys["TEST"][2]) is None
    assert keys["TEST"][2] not in _persisted_confidence_keys()


@pytest.mark.parametrize("failure", ["missing-current", "seam-mismatch", "second-write-error"])
@pytest.mark.asyncio
async def test_failed_whole_symbol_update_preserves_rows_proof_and_warmed_caches(factory, monkeypatch, failure):
    monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars()))
    current = _bars(SEAM, source="alpaca")
    await history.update_history("TEST", START, END, alpaca_bars=current)
    before = await _snapshot(factory)
    keys = await _warm_caches(current)
    generation = cc.generation()
    if failure == "missing-current":
        current = current[:-1]
    elif failure == "seam-mismatch":
        current = _bars(SEAM, source="alpaca", factor=0.5)
    else:
        real_store = hs._store_bars
        writes = 0

        async def fail_second_write(*args):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise RuntimeError("synthetic second-segment DB error")
            return await real_store(*args)

        monkeypatch.setattr(hs, "_store_bars", fail_second_write)
        current = _bars(SEAM, source="alpaca", factor=0.5)
        monkeypatch.setattr(history, "_fetch_fallback", AsyncMock(return_value=_bars(factor=0.5)))
    with pytest.raises(RuntimeError if failure == "second-write-error" else history.HistorySeamMismatch):
        await history.update_history("TEST", START, END, alpaca_bars=current)
    assert await _snapshot(factory) == before
    assert cc.generation() == generation
    for symbol in keys:
        assert stock_scan._get_backtest_cached(keys[symbol][0]) == f"{symbol} backtest"
        assert stock_scan._get_backtest_cached(keys[symbol][1]) == f"{symbol} alternate"
        assert cc.get_cached(keys[symbol][2]) == {"confidence": 70}
        assert keys[symbol][2] in _persisted_confidence_keys()


@pytest.fixture
def job_mocks(monkeypatch):
    monkeypatch.setattr(job, "_state", {"status": "idle"})
    monkeypatch.setattr(job, "_task", None)
    monkeypatch.setattr(job, "effective_years", lambda years: 17)
    client = object()
    monkeypatch.setattr(job, "get_alpaca_client", AsyncMock(return_value=client))
    batch = AsyncMock(return_value={"A": _bars(SEAM, source="alpaca")})
    update = AsyncMock()
    prune = AsyncMock(return_value=3)
    monkeypatch.setattr(job, "fetch_daily_bars_batch", batch)
    monkeypatch.setattr(job, "update_history", update)
    monkeypatch.setattr(job, "rebuild_single_provider",
                        AsyncMock(side_effect=history.SingleProviderRefused("synthetic refusal")))
    monkeypatch.setattr(job, "_prune_old_rows", prune)
    return batch, update, prune, client


@pytest.mark.asyncio
async def test_ingestion_counts_unique_requested_symbols_and_resets_every_run(job_mocks):
    batch, update, prune, client = job_mocks

    async def outcome(symbol, *args, **kwargs):
        if symbol == "A":
            return history.HistoryUpdateResult(1, True, False)
        if symbol == "B":
            return history.HistoryUpdateResult(1, False, True)
        if symbol == "C":
            raise history.HistorySeamMismatch("synthetic overlap mismatch", 1.02)
        if symbol == "D":
            raise ValueError("empty provider response")
        return history.HistoryUpdateResult(1, False, False)

    update.side_effect = outcome
    first = await job.run_ingestion([" a ", "A", " b", "C", " D ", "", " "], force_backfill=True)
    first_state = job.get_ingestion_state()
    assert (first.total, first.failed, first.alpaca_count, first.gapfill_count, first.pruned_rows) == (4, 2, 1, 1, 3)
    assert first.backfilled == 1 and first.backfilled_symbols == ["A"]
    assert first.floor_reached == 1 and first.floor_reached_symbols == ["B"]
    assert first.seam_mismatch == 1 and first.seam_mismatch_symbols == ["C"]
    assert first.seam_ratios == {"C": 1.02}
    assert len(first.errors) == 2
    assert [call.args[0] for call in update.await_args_list] == ["A", "B", "C", "D"]
    assert all(call.kwargs["force_backfill"] is True for call in update.await_args_list)
    assert batch.await_args.kwargs == {"client": client, "strict_adjustments": True}
    assert batch.await_args.args[0] == ["A", "B", "C", "D"]
    assert first_state["done"] == 4 and first_state["failed"] == 2
    assert first_state["backfilled_symbols"] == ["A"] and first_state["backfilled"] == 1
    assert first_state["floor_reached_symbols"] == ["B"] and first_state["floor_reached"] == 1
    assert first_state["seam_mismatch_symbols"] == ["C"] and first_state["seam_mismatch"] == 1
    second = await job.run_ingestion(["NEXT"])
    state = job.get_ingestion_state()
    assert (second.total, second.failed, second.alpaca_count, second.gapfill_count) == (1, 0, 0, 1)
    assert second.errors == [] and second.seam_ratios == {}
    for name in ["backfilled", "floor_reached", "seam_mismatch"]:
        assert getattr(second, name) == 0 and getattr(second, name + "_symbols") == []
        assert state[name] == 0 and state[name + "_symbols"] == []
    assert state["done"] == 1 and state["failed"] == 0 and state["error"] is None
    assert state["status"] == "completed" and state["current_symbol"] is None
    assert first.backfilled == 1 and first.backfilled_symbols == ["A"] and first.seam_ratios == {"C": 1.02}
    assert first_state["backfilled_symbols"] == ["A"]
    assert prune.await_count == 2
    assert all(call.args == (17,) for call in prune.await_args_list)


@pytest.mark.parametrize("symbols", [[], ["", " "]])
@pytest.mark.asyncio
async def test_empty_ingestion_never_prunes_or_launches_symbol_work(job_mocks, symbols):
    batch, update, prune, client = job_mocks
    result = await job.run_ingestion(symbols)
    batch.assert_not_awaited()
    update.assert_not_awaited()
    prune.assert_not_awaited()
    assert (result.total, result.failed, result.pruned_rows) == (0, 0, 0)
    assert job.get_ingestion_state()["done"] == 0


@pytest.mark.asyncio
async def test_two_immediate_ingestion_starts_cannot_launch_duplicate_tasks(job_mocks, monkeypatch):
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = []

    async def paused_run(symbols, **kwargs):
        calls.append((symbols, kwargs))
        job._state["status"] = "running"
        started.set()
        await finish.wait()
        job._state["status"] = "completed"

    monkeypatch.setattr(job, "run_ingestion", paused_run)
    assert job.start_ingestion_task(["A"], years=17, force_backfill=True)
    task = job._task
    try:
        assert job.get_ingestion_state()["status"] == "idle"
        assert not job.start_ingestion_task(["B"], years=20)
        await started.wait()
        assert calls == [(["A"], {"years": 17, "force_backfill": True})]
        assert not job.start_ingestion_task(["C"], years=20)
    finally:
        finish.set()
        await task
    assert job.start_ingestion_task(["NEXT"], years=17)
    await job._task
    assert len(calls) == 2
