"""HISTORY-INGEST-GAPS piece 1: class-share tickers reach Tiingo and yfinance dashed.

BRK.B / BF.B are stored with a dot; Tiingo and yfinance only answer for BRK-B / BF-B.
The stored symbol, state row and every key stay dotted.
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.data import tiingo
from app.data.provider_symbols import dash_class_ticker
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel as M, OhlcvHistoryStateModel as State
from app.services import historical_store as hs

START = date(2016, 1, 4)
END = date(2016, 1, 8)
NOW = datetime(2026, 10, 9, 23, tzinfo=timezone.utc)


def days(start=START, end=END):
    out = []
    while start <= end:
        if start.weekday() < 5:
            out.append(start)
        start += timedelta(days=1)
    return out


def tiingo_rows():
    return [{"date": f"{d.isoformat()}T00:00:00+00:00", "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.0, "volume": 1000, "adjClose": 90.0,
             "splitFactor": 1.0, "divCash": 0.0} for d in days()]


def tiingo_get(answer_for: str, calls: list):
    def get(url, **kwargs):
        calls.append(url)
        request = httpx.Request("GET", url)
        if url.endswith(f"/tiingo/daily/{answer_for}/prices"):
            return httpx.Response(200, json=tiingo_rows(), request=request)
        return httpx.Response(404, json={"detail": "Not found."}, request=request)
    return get


def yf_frame():
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in days()])
    return pd.DataFrame({"Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.0,
                         "Volume": 500}, index=index)


def yf_download(answer_for: str, calls: list):
    def download(ticker, **kwargs):
        calls.append(ticker)
        return yf_frame() if ticker == answer_for else pd.DataFrame()
    return download


@pytest.fixture(autouse=True)
def governed(monkeypatch):
    """Pass-through governor (the real one paces Tiingo calls ~72 s apart)."""
    seen = []

    class Gov:
        async def call(self, provider, request, *, symbol):
            seen.append((provider, symbol))
            return await request()

    monkeypatch.setattr(tiingo, "get_governor", lambda: Gov())
    return seen


def test_dash_class_ticker():
    assert dash_class_ticker("BRK.B") == "BRK-B"
    assert dash_class_ticker(" bf.b ") == "BF-B"
    assert dash_class_ticker("AAPL") == "AAPL"
    assert dash_class_ticker("^GSPC") == "^GSPC"


@pytest.mark.asyncio
async def test_tiingo_adapter_requests_dashed_class_ticker():
    calls = []
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("BRK-B", calls)):
        bars = await tiingo.fetch_historical_candles("BRK.B", START, END, strict_adjustments=True)
    assert calls and all(url.endswith("/tiingo/daily/BRK-B/prices") for url in calls)
    assert [b["time"] for b in bars] == [d.isoformat() for d in days()]
    assert all("symbol" not in b for b in bars)


@pytest.mark.asyncio
async def test_tiingo_adapter_leaves_plain_ticker_alone():
    calls = []
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("AAPL", calls)):
        assert await tiingo.fetch_historical_candles("AAPL", START, END)
    assert calls[0].endswith("/tiingo/daily/AAPL/prices")


@pytest.mark.asyncio
async def test_tiingo_governor_is_keyed_on_provider_ticker(governed):
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("BRK-B", [])):
        assert await tiingo.fetch_historical_candles("BRK.B", START, END)
    assert governed == [("tiingo", "BRK-B")]


def test_yfinance_adapter_requests_dashed_class_ticker(monkeypatch):
    import yfinance
    calls = []
    monkeypatch.setattr(yfinance, "download", yf_download("BF-B", calls))
    bars = hs._yfinance_fetch("BF.B", START, END + timedelta(days=1))
    assert calls == ["BF-B"]
    assert [b["time"] for b in bars] == [d.isoformat() for d in days()]
    assert all("symbol" not in b for b in bars)


@pytest_asyncio.fixture
async def factory(monkeypatch):
    from app.services import history_backfill as history
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(history, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(hs, "_utcnow", lambda: NOW)
    monkeypatch.setattr(history, "notify_bars_changed", MagicMock())
    yield factory
    await engine.dispose()


async def stored(factory):
    async with factory() as db:
        rows = (await db.execute(select(M.symbol, M.date, M.source).order_by(M.date))).all()
        states = (await db.execute(select(State.symbol, State.basis_provider))).all()
    return rows, states


@pytest.mark.asyncio
async def test_rebuild_from_tiingo_stores_under_dotted_symbol(factory, monkeypatch):
    import yfinance
    from app.services import history_backfill as history
    tiingo_calls, yf_calls = [], []
    monkeypatch.setattr(yfinance, "download", yf_download("BRK-B", yf_calls))
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("BRK-B", tiingo_calls)):
        result = await history.rebuild_single_provider("BRK.B", START, END)
    assert result.provider == "tiingo"
    rows, states = await stored(factory)
    assert {r.symbol for r in rows} == {"BRK.B"}
    assert [r.date for r in rows] == days()
    assert states == [("BRK.B", "tiingo")]
    assert yf_calls == []
    history.notify_bars_changed.assert_called_once_with("BRK.B")


@pytest.mark.asyncio
async def test_rebuild_falls_back_to_yfinance_under_dotted_symbol(factory, monkeypatch):
    import yfinance
    from app.services import history_backfill as history
    yf_calls = []
    monkeypatch.setattr(yfinance, "download", yf_download("BF-B", yf_calls))
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("NOPE", [])):
        result = await history.rebuild_single_provider("BF.B", START, END)
    assert result.provider == "yfinance"
    assert yf_calls == ["BF-B"]
    rows, states = await stored(factory)
    assert {r.symbol for r in rows} == {"BF.B"} and {r.source for r in rows} == {"yfinance"}
    assert states == [("BF.B", "yfinance")]


@pytest.mark.asyncio
async def test_on_demand_chain_reaches_tiingo_for_dotted_symbol(factory, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("app.data.alpaca.get_alpaca_client", AsyncMock(return_value=None))
    with patch("app.data.tiingo.httpx.get", side_effect=tiingo_get("BRK-B", [])):
        bars = await hs._fetch_chain("BRK.B", START, END + timedelta(days=1),
                                     providers=("tiingo",))
    assert bars and [b["time"] for b in bars] == [d.isoformat() for d in days()]
