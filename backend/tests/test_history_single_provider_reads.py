"""HISTORY-SINGLE-PROVIDER-REBUILD T4 (plan 2.3): on-demand reads keep the basis.

A symbol whose ``ohlcv_history_state.basis_provider`` is ``tiingo`` / ``yfinance`` holds a
series from that one provider. ``get_bars``' scan-time delta fetch must ask only that
provider (no Alpaca rows appended between nightly runs); every other symbol keeps the
Alpaca -> Tiingo -> yfinance chain unchanged.

D = Wednesday 2026-06-10, clock 23:00 UTC (19:00 ET, D settled).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs

SYM = "TEST"
D = date(2026, 6, 10)
D1 = date(2026, 6, 9)
D2 = date(2026, 6, 8)
START = date(2026, 5, 18)


def days(start, end):
    out = []
    while start <= end:
        if start.weekday() < 5:
            out.append(start)
        start += timedelta(days=1)
    return out


def bars(start, end, *, source, close=100.0):
    return [{"time": d.isoformat(), "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 100, "adj_factor": 1.0, "split_factor": 1.0,
             "div_cash": 0.0, "source": source} for d in days(start, end)]


@pytest_asyncio.fixture
async def world(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: datetime(2026, 6, 10, 23, tzinfo=timezone.utc))

    import app.data.alpaca as alpaca
    calls: list[str] = []

    async def _client():
        calls.append("alpaca_client")
        return object()

    async def _alpaca(symbol, start, end, client=None):
        calls.append("alpaca")
        return bars(start, min(end, D), source="alpaca", close=200.0)

    async def _tiingo(symbol, start, end):
        calls.append("tiingo")
        return tiingo_reply(start, end)

    def _yf(symbol, start, end):
        calls.append("yfinance")
        return yf_reply(start, end)

    tiingo_reply = MagicMock(side_effect=lambda s, e: bars(s, min(e, D), source="tiingo", close=150.0))
    yf_reply = MagicMock(side_effect=lambda s, e: bars(s, min(e, D), source="yfinance", close=175.0))
    monkeypatch.setattr(alpaca, "get_alpaca_client", _client)
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", _alpaca)
    monkeypatch.setattr(hs, "fetch_historical_candles", _tiingo)
    monkeypatch.setattr(hs, "_yfinance_fetch", _yf)

    class W:
        pass
    w = W()
    w.factory, w.calls, w.tiingo_reply, w.yf_reply = factory, calls, tiingo_reply, yf_reply
    yield w
    await engine.dispose()


async def seed(w, *, source, basis_provider, state=True):
    async with w.factory() as db:
        await hs._store_bars(SYM, bars(START, D2, source=source), db)
        if state:
            db.add(State(symbol=SYM, basis_provider=basis_provider))
        await db.commit()


async def stored(w):
    async with w.factory() as db:
        rows = (await db.execute(select(M).where(M.symbol == SYM).order_by(M.date))).scalars().all()
        return {r.date: r.source for r in rows}


@pytest.mark.asyncio
async def test_1_tiingo_basis_fetches_only_tiingo_and_stores_tiingo(world):
    await seed(world, source="tiingo", basis_provider="tiingo")
    out = await hs.get_bars(SYM, START, D)
    assert world.calls == ["tiingo"]
    rows = await stored(world)
    assert rows[D1] == "tiingo" and rows[D] == "tiingo"
    assert set(rows.values()) == {"tiingo"}
    assert out[-1]["time"] == D.isoformat()


@pytest.mark.asyncio
async def test_1b_yfinance_basis_fetches_only_yfinance(world):
    await seed(world, source="yfinance", basis_provider="yfinance")
    await hs.get_bars(SYM, START, D)
    assert world.calls == ["yfinance"]
    assert set((await stored(world)).values()) == {"yfinance"}


@pytest.mark.asyncio
async def test_2_tiingo_empty_has_no_alpaca_fallback(world):
    await seed(world, source="tiingo", basis_provider="tiingo")
    world.tiingo_reply.side_effect = lambda s, e: []
    out = await hs.get_bars(SYM, START, D)
    assert world.calls == ["tiingo"]
    rows = await stored(world)
    assert max(rows) == D2 and set(rows.values()) == {"tiingo"}
    assert [b["time"] for b in out] == [d.isoformat() for d in days(START, D2)]


@pytest.mark.parametrize("state", [False, True])
@pytest.mark.asyncio
async def test_3_normal_symbol_keeps_alpaca_tiingo_yfinance_order(world, state):
    await seed(world, source="alpaca", basis_provider=None, state=state)
    await hs.get_bars(SYM, START, D)
    assert world.calls == ["alpaca_client", "alpaca"]
    assert (await stored(world))[D] == "alpaca"


@pytest.mark.parametrize("state", [False, True])
@pytest.mark.asyncio
async def test_3b_normal_symbol_falls_through_in_order(world, monkeypatch, state):
    import app.data.alpaca as alpaca
    await seed(world, source="alpaca", basis_provider=None, state=state)

    async def _empty(symbol, start, end, client=None):
        world.calls.append("alpaca")
        return []
    monkeypatch.setattr(alpaca, "fetch_daily_bars_single", _empty)
    world.tiingo_reply.side_effect = lambda s, e: []
    await hs.get_bars(SYM, START, D)
    assert world.calls == ["alpaca_client", "alpaca", "tiingo", "yfinance"]
    assert (await stored(world))[D] == "yfinance"
