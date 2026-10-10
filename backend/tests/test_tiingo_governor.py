"""Offline acceptance of Tiingo pacing, budget and shared rate-limit failures."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.data import tiingo
from app.data import governor as g
from app.services import history_backfill as history, historical_store as hs

START, END = date(2020, 1, 1), date(2020, 1, 10)
ROW = {"date": "2020-01-02", "open": 99, "high": 101, "low": 98,
       "close": 100, "adjClose": 50, "volume": 100}


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    original_sleep = asyncio.sleep
    async def sleep(delay):
        now[0] += delay
        await original_sleep(0)
    monkeypatch.setattr(g.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(g.asyncio, "sleep", sleep)
    return now


def response(status=200, retry=None):
    return httpx.Response(status, json=[ROW], headers={} if retry is None else {"Retry-After": retry},
                          request=httpx.Request("GET", "https://api.tiingo.com/test"))


def install(monkeypatch, gov, get):
    monkeypatch.setattr(tiingo, "get_governor", lambda: gov)
    monkeypatch.setattr(tiingo.httpx, "get", get)


@pytest.mark.asyncio
async def test_public_adapter_paces_every_call_and_retains_adjusted_prices(monkeypatch, clock):
    gov = g.Governor.for_testing("tiingo", rate=1 / 72, capacity=2)
    times = []
    def get(*args, **kwargs):
        times.append(clock[0])
        return response()
    install(monkeypatch, gov, get)
    for _ in range(4):
        bars = await tiingo.fetch_historical_candles("TEST", START, END, strict_adjustments=True)
        assert bars[0]["close"] == 100 and bars[0]["adj_factor"] == 0.5
    assert times == [1000, 1000, 1072, 1144]


@pytest.mark.asyncio
async def test_budget_blocks_new_symbols_but_allows_repeat_after_normalization(monkeypatch):
    gov = g.Governor.for_testing("tiingo", rate=100000, capacity=100000)
    gov._providers["tiingo"].budget = g.SymbolBudget(2)
    get = Mock(return_value=response())
    install(monkeypatch, gov, get)
    for symbol in [" one ", "TWO", "ONE"]:
        assert await tiingo.fetch_historical_candles(symbol, START, END)
    with pytest.raises(g.ProviderUnavailable, match="symbol budget exhausted"):
        await tiingo.fetch_historical_candles("THREE", START, END)
    assert get.call_count == 3


@pytest.mark.asyncio
async def test_exhausted_429_preserved_and_cooldown_blocks_next_caller(monkeypatch, clock):
    gov = g.Governor.for_testing("tiingo", rate=100000, capacity=100000, fail_threshold=100)
    calls = []
    def get(*args, **kwargs):
        calls.append(clock[0])
        return response(429, "120") if len(calls) <= 4 else response()
    install(monkeypatch, gov, get)
    with pytest.raises(g.RateLimited) as exc:
        await tiingo.fetch_historical_candles("ONE", START, END)
    assert exc.value.retry_after == 120
    deadline = gov._providers["tiingo"].retry_at
    assert len(calls) == 4
    assert await tiingo.fetch_historical_candles("TWO", START, END)
    assert calls[-1] >= deadline


@pytest.mark.parametrize("value", ["garbage", "NaN", "inf"])
def test_invalid_retry_hint_does_not_create_unbounded_sleep(value):
    assert tiingo._retry_after(value) is None


def test_retry_after_supports_http_date():
    assert tiingo._retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0


@pytest.mark.asyncio
async def test_budget_refusal_reaches_existing_fallback_paths(monkeypatch):
    reject = AsyncMock(side_effect=g.ProviderUnavailable("tiingo symbol budget exhausted"))
    monkeypatch.setattr(tiingo, "fetch_historical_candles", reject)
    monkeypatch.setattr(hs, "fetch_historical_candles", reject)
    monkeypatch.setattr("app.data.alpaca.get_alpaca_client", AsyncMock(return_value=None))
    monkeypatch.setattr(hs, "_yfinance_fetch", lambda *args: [dict(ROW, time="2020-01-02",
        adj_factor=0.5, source="yfinance")])
    bars = await history._fetch_fallback("TEST", START, END)
    assert bars[0]["source"] == "yfinance"
    assert (await hs._fetch_chain("TEST", START, END))[0]["source"] == "yfinance"
    assert reject.await_count == 2


@pytest.mark.asyncio
async def test_shared_cooldown_protects_another_concurrent_caller():
    gov = g.Governor.for_testing("tiingo", rate=100000, capacity=100000)
    rejected = asyncio.Event()
    async def first():
        rejected.set()
        raise g.RateLimited("429", retry_after=0.04)
    async def other():
        await rejected.wait()
        async def request():
            assert g.time.monotonic() >= gov._providers["tiingo"].retry_at
            return "ok"
        return await gov.call("tiingo", request)
    results = await asyncio.gather(gov.call("tiingo", first, retries=0), other(), return_exceptions=True)
    assert isinstance(results[0], g.RateLimited) and results[1] == "ok"
