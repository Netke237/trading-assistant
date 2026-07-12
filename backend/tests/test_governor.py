from __future__ import annotations

import asyncio
import time

import pytest

from app.data.governor import TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity():
    # capacity 3 → first 3 acquisitions are immediate
    bucket = TokenBucket(rate=3, per=1.0, capacity=3)
    start = time.monotonic()
    for _ in range(3):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05  # no meaningful wait


@pytest.mark.asyncio
async def test_token_bucket_throttles_beyond_capacity():
    # rate 10/sec, capacity 1 → the 2nd acquire must wait ~0.1s
    bucket = TokenBucket(rate=10, per=1.0, capacity=1)
    await bucket.acquire()                      # consumes the only token
    start = time.monotonic()
    await bucket.acquire()                      # must wait for a refill
    waited = time.monotonic() - start
    assert 0.05 < waited < 0.3


from app.data.governor import CircuitBreaker


def test_circuit_opens_after_threshold_failures():
    cb = CircuitBreaker(fail_threshold=3, cooldown=60.0)
    assert cb.is_open is False
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open is True


def test_circuit_closes_after_cooldown():
    cb = CircuitBreaker(fail_threshold=1, cooldown=0.05)
    cb.record_failure()
    assert cb.is_open is True
    time.sleep(0.06)
    assert cb.is_open is False  # half-open: allows a trial


def test_success_resets_failures():
    cb = CircuitBreaker(fail_threshold=2, cooldown=60.0)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.is_open is False  # counter was reset, only 1 failure since


from app.data.governor import SymbolBudget


def test_symbol_budget_counts_distinct_symbols():
    budget = SymbolBudget(max_symbols=2, window=3600.0)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("MSFT") is True
    assert budget.try_consume("GOOG") is False   # over the cap
    assert budget.remaining() == 0


def test_symbol_budget_same_symbol_is_free_within_window():
    budget = SymbolBudget(max_symbols=1, window=3600.0)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("AAPL") is True     # already counted, still allowed
    assert budget.remaining() == 0


def test_symbol_budget_evicts_after_window():
    budget = SymbolBudget(max_symbols=1, window=0.05)
    assert budget.try_consume("AAPL") is True
    assert budget.try_consume("MSFT") is False
    time.sleep(0.06)
    assert budget.try_consume("MSFT") is True     # AAPL evicted, slot freed


from app.data.governor import RateLimited, backoff_delay


def test_rate_limited_carries_retry_after():
    err = RateLimited("429", retry_after=12.5)
    assert err.retry_after == 12.5


def test_backoff_delay_grows_and_is_capped():
    d0 = backoff_delay(0, base=0.5, cap=8.0)
    d1 = backoff_delay(1, base=0.5, cap=8.0)
    d5 = backoff_delay(5, base=0.5, cap=8.0)
    assert d0 == pytest.approx(0.5)
    assert d1 == pytest.approx(1.0)
    assert d5 == 8.0  # capped


from app.data.governor import Governor, ProviderUnavailable, build_default_governor


@pytest.mark.asyncio
async def test_governor_call_returns_result_and_marks_connected():
    gov = Governor.for_testing(provider="alpaca", rate=100, capacity=100)

    async def _ok():
        return [1, 2, 3]

    result = await gov.call("alpaca", _ok)
    assert result == [1, 2, 3]
    assert gov.health("alpaca") == "connected"


@pytest.mark.asyncio
async def test_governor_retries_on_rate_limited_then_succeeds():
    gov = Governor.for_testing(provider="tiingo", rate=100, capacity=100)
    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimited("429", retry_after=0.01)
        return "ok"

    result = await gov.call("tiingo", _flaky, retries=2)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_governor_opens_circuit_and_reports_degraded():
    gov = Governor.for_testing(provider="yf", rate=100, capacity=100, fail_threshold=2)

    async def _broken():
        raise RuntimeError("network down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await gov.call("yf", _broken)
    # circuit now open → next call short-circuits with ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        await gov.call("yf", _broken)
    assert gov.health("yf") == "degraded"


def test_build_default_governor_has_all_providers():
    gov = build_default_governor()
    for name in ("alpaca", "tradier", "tiingo", "yfinance", "ibkr"):
        assert gov.health(name) == "unknown"


def test_tastytrade_provider_registered_with_conservative_rate():
    gov = build_default_governor()
    ps = gov._providers.get("tastytrade")
    assert ps is not None
    # No published production rate limit exists for market-metrics; the only
    # documented number anywhere is the Paper API's 5 req/s default, which is
    # NOT confirmed as the production limit. Stay well under it.
    assert ps.bucket.rate <= 2.0
    assert ps.breaker.fail_threshold >= 3
