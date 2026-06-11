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
