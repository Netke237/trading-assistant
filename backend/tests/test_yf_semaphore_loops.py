"""YF-CALENDAR-SEMAPHORE: the yfinance limiters must not bind to the first event loop.

On Python 3.11 an `asyncio.Semaphore` binds to the first event loop that has
to WAIT on it; a later loop in the same process that contends on it raises
`RuntimeError: ... is bound to a different event loop`. Before the fix the
calendar limiter (`_get_yf_sem`, limit 5) and the candle pre-warm limiter
(`_get_prewarm_sem`, limit 15) were process-wide singletons, so a second
`asyncio.run` lost symbols. These tests are plain sync functions that call
`asyncio.run` themselves, so pytest-asyncio's own loop is not involved.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import date

import pytest

import app.data.market as mkt


@pytest.fixture(autouse=True)
def _reset_calendar_cache(monkeypatch):
    monkeypatch.setattr(mkt, "_yf_cal_cache", {})
    monkeypatch.setattr(mkt, "_yf_cal_cache_date", "")
    monkeypatch.setattr(mkt, "_yf_cal_fail_until", {})
    yield
    mkt._yf_cal_cache = {}
    mkt._yf_cal_cache_date = ""
    mkt._yf_cal_fail_until = {}


class _PeakCounter:
    """Thread-safe current/peak concurrency counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self) -> None:
        with self._lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def exit(self) -> None:
        with self._lock:
            self.current -= 1


def _stub_calendar(monkeypatch, counter: _PeakCounter, delay: float = 0.05):
    earn = date(2030, 1, 15)
    div = date(2030, 2, 1)

    def _strict(symbol: str):
        counter.enter()
        try:
            time.sleep(delay)
        finally:
            counter.exit()
        return earn, div

    monkeypatch.setattr(mkt, "_calendar_dates_yf_strict", _strict)
    return earn, div


async def _calendar_burst(symbols: list[str]):
    return await asyncio.gather(
        *(mkt.fetch_calendar_dates_async(s) for s in symbols), return_exceptions=True,
    )


def test_calendar_lookups_succeed_in_two_consecutive_loops(monkeypatch):
    counter = _PeakCounter()
    expected = _stub_calendar(monkeypatch, counter)

    burst1 = asyncio.run(_calendar_burst([f"L1S{i}" for i in range(10)]))
    burst2 = asyncio.run(_calendar_burst([f"L2S{i}" for i in range(10)]))

    for burst in (burst1, burst2):
        errors = [r for r in burst if isinstance(r, BaseException)]
        assert errors == [], f"calendar lookups raised: {errors!r}"
        assert all(r == expected for r in burst)


def test_calendar_limit_still_enforced_within_one_loop(monkeypatch):
    counter = _PeakCounter()
    _stub_calendar(monkeypatch, counter)

    results = asyncio.run(_calendar_burst([f"PK{i}" for i in range(20)]))

    assert not any(isinstance(r, BaseException) for r in results)
    assert 1 < counter.peak <= 5


def test_prewarm_succeeds_in_two_consecutive_loops(monkeypatch):
    counter = _PeakCounter()

    async def _fake_fetch_candles(client, symbol, bars=252):
        counter.enter()
        try:
            await asyncio.sleep(0.02)
        finally:
            counter.exit()
        return [{"time": "2030-01-01", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]

    monkeypatch.setattr(mkt, "fetch_candles_async", _fake_fetch_candles)

    first = asyncio.run(mkt.prewarm_candles_async([f"PA{i}" for i in range(20)]))
    second = asyncio.run(mkt.prewarm_candles_async([f"PB{i}" for i in range(20)]))

    assert first == 20
    assert second == 20
    assert 1 < counter.peak <= 15


def test_one_semaphore_per_loop():
    async def _pair():
        return mkt._get_yf_sem(), mkt._get_yf_sem(), mkt._get_prewarm_sem(), mkt._get_prewarm_sem()

    yf_a1, yf_a2, pw_a1, pw_a2 = asyncio.run(_pair())
    yf_b1, _, pw_b1, _ = asyncio.run(_pair())

    assert yf_a1 is yf_a2
    assert pw_a1 is pw_a2
    assert yf_a1 is not yf_b1
    assert pw_a1 is not pw_b1
