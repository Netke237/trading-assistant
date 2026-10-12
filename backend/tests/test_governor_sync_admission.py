"""TRADIER-GOVERNOR T1: overdraft, blocking sync admission, one FIFO ticket
queue shared by sync and async waiters, and one 429 cooldown shared by sync
and async callers (plan docs/superpowers/plans/2026-10-10-tradier-governor-plan.md
§2 D1/D2, §3 T1).

Timing assertions use deterministic lower bounds (a token-bucket refill can
never admit before the arithmetic allows it) and generous upper bounds
(several times the expected wait), so a loaded host cannot flip them.
"""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import Mock

import pytest

from app.data.governor import (
    Governor,
    ProviderUnavailable,
    RateLimited,
    TokenBucket,
    backoff_delay,
    build_default_governor,
)

EPS = 1e-3


def _wait_until(pred, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.001)


def _drain(bucket: TokenBucket) -> None:
    while bucket.try_acquire():
        pass


def _queue_empty(bucket: TokenBucket) -> bool:
    with bucket._lock:
        return bucket._serving == bucket._next_ticket and not bucket._abandoned


def _thread(fn, *args, **kwargs):
    out: dict = {}

    def run():
        out["result"] = fn(*args, **kwargs)
        out["at"] = time.monotonic()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, out


# ---------------------------------------------------------------- acquire_blocking

def test_acquire_blocking_burst_then_paced():
    bucket = TokenBucket(rate=20, per=1.0, capacity=3)
    start = time.monotonic()
    for _ in range(3):
        assert bucket.acquire_blocking(admit_timeout=None) is True
    assert time.monotonic() - start < 0.2          # the burst does not wait
    t0 = time.monotonic()
    assert bucket.acquire_blocking(admit_timeout=None) is True
    waited = time.monotonic() - t0
    assert 0.02 < waited < 1.0                     # about 1/rate = 0.05 s
    assert _queue_empty(bucket)


def test_acquire_blocking_finite_timeout_returns_false():
    bucket = TokenBucket(rate=0.5, per=1.0, capacity=1)   # one token every 2 s
    assert bucket.acquire_blocking(admit_timeout=None) is True
    t0 = time.monotonic()
    assert bucket.acquire_blocking(admit_timeout=0.1) is False
    waited = time.monotonic() - t0
    assert 0.1 - EPS <= waited < 1.0
    t0 = time.monotonic()
    assert bucket.acquire_blocking(admit_timeout=0.0) is False
    assert time.monotonic() - t0 < 0.1             # zero budget: no wait
    assert _queue_empty(bucket)                    # timed-out tickets cleaned up


def test_acquire_blocking_none_admits_all_contending_threads():
    bucket = TokenBucket(rate=50, per=1.0, capacity=1)
    _drain(bucket)
    workers = [_thread(bucket.acquire_blocking, admit_timeout=None) for _ in range(8)]
    for t, _ in workers:
        t.join(timeout=5.0)
        assert not t.is_alive()
    assert [out["result"] for _, out in workers] == [True] * 8
    assert _queue_empty(bucket)


# ---------------------------------------------------------------- overdraft

def test_overdraft_floors_at_minus_capacity_and_never_blocks():
    bucket = TokenBucket(rate=0.001, per=1.0, capacity=5)
    bucket.overdraft()
    assert bucket._tokens == pytest.approx(4.0, abs=0.01)
    t0 = time.monotonic()
    for _ in range(20):
        assert bucket.overdraft() is None
    assert time.monotonic() - t0 < 0.1
    assert bucket._tokens >= -5.0
    assert bucket._tokens == pytest.approx(-5.0, abs=0.01)


def test_negative_balance_makes_sync_acquirers_wait_until_repaid():
    bucket = TokenBucket(rate=10, per=1.0, capacity=2)
    t0 = time.monotonic()
    for _ in range(4):
        bucket.overdraft()                          # 2 -> -2
    assert bucket.try_acquire() is False
    assert bucket.acquire_blocking(admit_timeout=0.1) is False
    assert bucket.acquire_blocking(admit_timeout=None) is True
    # -2 + 10/s * t >= 1  =>  t >= 0.3 s after the overdraft.
    elapsed = time.monotonic() - t0
    assert 0.3 - EPS <= elapsed < 2.0


def test_negative_balance_makes_async_acquire_wait_until_repaid():
    bucket = TokenBucket(rate=10, per=1.0, capacity=2)
    t0 = time.monotonic()
    for _ in range(4):
        bucket.overdraft()
    asyncio.run(bucket.acquire())
    elapsed = time.monotonic() - t0
    assert 0.3 - EPS <= elapsed < 2.0


def test_try_acquire_refused_while_negative_then_allowed_after_repayment():
    bucket = TokenBucket(rate=20, per=1.0, capacity=1)
    bucket.overdraft()
    bucket.overdraft()                              # 1 -> -1
    assert bucket.try_acquire() is False
    time.sleep(0.15)                                # -1 + 20 * 0.15 = 2 -> capped 1
    assert bucket.try_acquire() is True


def test_mixed_run_burst_bound():
    rate, capacity = 40.0, 5
    start = time.monotonic()
    bucket = TokenBucket(rate=rate, per=1.0, capacity=capacity)
    stop = threading.Event()
    counts = {"bulk": 0, "overdraft": 0}
    lock = threading.Lock()

    def bulk():
        while not stop.is_set():
            if bucket.acquire_blocking(admit_timeout=0.05):
                with lock:
                    counts["bulk"] += 1

    def fire():
        while not stop.is_set():
            bucket.overdraft()
            with lock:
                counts["overdraft"] += 1
            time.sleep(0.05)

    threads = [threading.Thread(target=bulk, daemon=True) for _ in range(4)]
    threads.append(threading.Thread(target=fire, daemon=True))
    for t in threads:
        t.start()
    time.sleep(0.5)
    stop.set()
    for t in threads:
        t.join(timeout=3.0)
        assert not t.is_alive()
    elapsed = time.monotonic() - start
    total = counts["bulk"] + counts["overdraft"]
    assert counts["overdraft"] >= 3 and counts["bulk"] >= capacity
    assert total <= capacity + capacity + rate * elapsed


# ---------------------------------------------------------------- FIFO queue

def test_try_acquire_refuses_while_anyone_is_queued():
    gov = Governor.for_testing("p", rate=1, capacity=3)
    bucket = gov._providers["p"].bucket
    assert bucket.try_acquire() and bucket.try_acquire()     # ~1 token left
    waiter, out = _thread(bucket.acquire_blocking, 2.0, admit_timeout=0.3)
    _wait_until(lambda: bucket._next_ticket == 1)
    assert bucket._tokens >= 1.0 - EPS              # a token is free ...
    assert bucket.try_acquire() is False            # ... but someone is queued
    assert gov.try_acquire("p") is False
    waiter.join(timeout=3.0)
    assert out["result"] is False                   # 1 + 0.3 s * 1/s < 2
    assert _queue_empty(bucket)
    assert bucket.try_acquire() is True


def test_fifo_across_sync_and_async_with_bounded_wait():
    rate = 20.0
    bucket = TokenBucket(rate=rate, per=1.0, capacity=1)
    _drain(bucket)
    order: list[str] = []
    order_lock = threading.Lock()
    admitted_at: dict[str, float] = {}

    def sync_caller(label):
        assert bucket.acquire_blocking(admit_timeout=None) is True
        with order_lock:
            order.append(label)
            admitted_at[label] = time.monotonic()

    def async_caller():
        async def go():
            await bucket.acquire()
            with order_lock:
                order.append("async")
                admitted_at["async"] = time.monotonic()
        asyncio.run(go())

    threads: list[threading.Thread] = []
    entered: list[str] = []
    async_entered_at = 0.0

    def enter(label, target, *args):
        nonlocal async_entered_at
        before = bucket._next_ticket
        if label == "async":
            async_entered_at = time.monotonic()
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
        _wait_until(lambda: bucket._next_ticket == before + 1)
        threads.append(t)
        entered.append(label)

    for i in range(5):
        enter(f"sync{i}", sync_caller, f"sync{i}")
    enter("async", async_caller)
    for i in range(5, 7):
        enter(f"sync{i}", sync_caller, f"sync{i}")
    for t in threads:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert order == entered                         # admission order == ticket order
    # The async waiter had at most 5 tickets ahead: (5 + 1) / rate = 0.3 s.
    assert admitted_at["async"] - async_entered_at < 3 * (5 + 1) / rate
    assert _queue_empty(bucket)


def test_sync_pollers_do_not_starve_async_waiter():
    rate = 20.0
    bucket = TokenBucket(rate=rate, per=1.0, capacity=1)
    _drain(bucket)
    stop = threading.Event()

    def poller():
        while not stop.is_set():
            bucket.acquire_blocking(admit_timeout=None)

    pollers = [threading.Thread(target=poller, daemon=True) for _ in range(5)]
    for t in pollers:
        t.start()
    _wait_until(lambda: bucket._next_ticket >= 5)

    async def go():
        t0 = time.monotonic()
        await asyncio.wait_for(bucket.acquire(), timeout=3.0)
        return time.monotonic() - t0

    try:
        waited = asyncio.run(go())
    finally:
        stop.set()
        for t in pollers:
            t.join(timeout=3.0)
    assert waited < 3 * (5 + 1) / rate


# ---------------------------------------------------------------- abandoned tickets

def test_abandoned_sync_ticket_behind_head_does_not_stall():
    bucket = TokenBucket(rate=20, per=1.0, capacity=1)
    _drain(bucket)
    t_head, head = _thread(bucket.acquire_blocking, admit_timeout=None)
    _wait_until(lambda: bucket._next_ticket == 1)
    t_mid, mid = _thread(bucket.acquire_blocking, admit_timeout=0.01)
    _wait_until(lambda: bucket._next_ticket == 2)
    t_mid.join(timeout=3.0)
    assert mid["result"] is False
    t0 = time.monotonic()
    t_tail, tail = _thread(bucket.acquire_blocking, admit_timeout=None)
    for t in (t_head, t_tail):
        t.join(timeout=3.0)
        assert not t.is_alive()
    assert head["result"] is True and tail["result"] is True
    assert tail["at"] - t0 < 1.0                    # about 2 / rate = 0.1 s
    assert _queue_empty(bucket)


def test_abandoned_sync_ticket_at_head_does_not_stall():
    bucket = TokenBucket(rate=10, per=1.0, capacity=1)
    _drain(bucket)
    t_head, head = _thread(bucket.acquire_blocking, admit_timeout=0.02)
    _wait_until(lambda: bucket._next_ticket == 1)
    t_next, nxt = _thread(bucket.acquire_blocking, admit_timeout=None)
    t_head.join(timeout=3.0)
    assert head["result"] is False
    t_next.join(timeout=3.0)
    assert not t_next.is_alive() and nxt["result"] is True
    assert _queue_empty(bucket)


async def test_cancelled_async_waiter_at_head_does_not_stall():
    bucket = TokenBucket(rate=10, per=1.0, capacity=1)
    _drain(bucket)
    head = asyncio.create_task(bucket.acquire())
    await asyncio.sleep(0.01)
    behind = asyncio.create_task(bucket.acquire())
    await asyncio.sleep(0.01)
    assert bucket._next_ticket == 2
    head.cancel()
    with pytest.raises(asyncio.CancelledError):
        await head
    await asyncio.wait_for(behind, timeout=2.0)
    assert _queue_empty(bucket)


async def test_cancelled_async_waiter_behind_head_does_not_stall():
    bucket = TokenBucket(rate=20, per=1.0, capacity=1)
    _drain(bucket)
    first = asyncio.create_task(bucket.acquire())
    await asyncio.sleep(0.005)
    middle = asyncio.create_task(bucket.acquire())
    await asyncio.sleep(0.005)
    last = asyncio.create_task(bucket.acquire())
    await asyncio.sleep(0.005)
    assert bucket._next_ticket == 3
    middle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await middle
    await asyncio.wait_for(asyncio.gather(first, last), timeout=2.0)
    assert _queue_empty(bucket)


# ---------------------------------------------------------------- Governor.admit_sync

def test_admit_sync_overdraft_admits_on_empty_bucket():
    gov = Governor.for_testing("tradier", rate=0.001, capacity=2)
    bucket = gov._providers["tradier"].bucket
    _drain(bucket)
    t0 = time.monotonic()
    assert gov.admit_sync("tradier", admit_timeout=0.0, overdraft=True) is True
    assert time.monotonic() - t0 < 0.1
    assert bucket._tokens == pytest.approx(-1.0, abs=0.01)


def test_admit_sync_overdraft_refuses_at_once_during_retry_at():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    bucket = gov._providers["tradier"].bucket
    gov.note_rate_limited("tradier", 30.0)
    t0 = time.monotonic()
    assert gov.admit_sync("tradier", admit_timeout=0.0, overdraft=True) is False
    assert gov.admit_sync("tradier", admit_timeout=None, overdraft=True) is False
    assert time.monotonic() - t0 < 0.1              # never sleeps
    assert bucket._tokens == pytest.approx(5.0, abs=0.01)   # nothing booked


def test_admit_sync_honours_retry_at_from_note_rate_limited():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    t0 = time.monotonic()
    gov.note_rate_limited("tradier", 0.2)
    assert gov.health("tradier") == "degraded"
    assert gov.admit_sync("tradier", admit_timeout=0.05) is False
    assert gov.admit_sync("tradier", admit_timeout=None) is True
    assert time.monotonic() - t0 >= 0.2 - EPS


def test_note_rate_limited_defaults_and_never_shortens():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    ps = gov._providers["tradier"]
    t0 = time.monotonic()
    gov.note_rate_limited("tradier", None)
    assert ps.retry_at >= t0 + backoff_delay(0) - EPS
    gov.note_rate_limited("tradier", 30.0)
    longer = ps.retry_at
    gov.note_rate_limited("tradier", 0.1)
    assert ps.retry_at == longer


def test_admit_sync_refuses_open_circuit_and_unknown_provider():
    gov = Governor.for_testing("tradier", rate=100, capacity=5, fail_threshold=1)
    gov.record_failure("tradier")
    t0 = time.monotonic()
    assert gov.admit_sync("tradier", admit_timeout=None) is False
    assert gov.admit_sync("tradier", admit_timeout=None, overdraft=True) is False
    assert gov.admit_sync("nope", admit_timeout=None) is False
    assert gov.admit_sync("nope", admit_timeout=0.0, overdraft=True) is False
    assert time.monotonic() - t0 < 0.1


def test_admit_sync_normal_waits_for_token():
    gov = Governor.for_testing("tradier", rate=20, capacity=1)
    assert gov.admit_sync("tradier", admit_timeout=None) is True
    t0 = time.monotonic()
    assert gov.admit_sync("tradier", admit_timeout=None) is True
    assert 0.05 - EPS <= time.monotonic() - t0 < 1.0
    assert gov.admit_sync("tradier", admit_timeout=0.0) is False


def test_async_call_rate_limited_sets_cooldown_admit_sync_waits_out():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    spy = Mock(wraps=gov.note_rate_limited)
    gov.note_rate_limited = spy
    calls = {"n": 0}

    async def limited():
        calls["n"] += 1
        raise RateLimited("429", retry_after=0.3)

    t0 = time.monotonic()
    with pytest.raises(RateLimited):
        asyncio.run(gov.call("tradier", limited, retries=0))
    assert calls["n"] == 1
    spy.assert_called_once_with("tradier", 0.3)
    assert gov._providers["tradier"].retry_at >= t0 + 0.3 - EPS
    assert gov.admit_sync("tradier", admit_timeout=0.0, overdraft=True) is False
    assert gov.admit_sync("tradier", admit_timeout=None) is True
    assert time.monotonic() - t0 >= 0.3 - EPS


# ---------------------------------------------------------------- Governor.call_overdraft

async def test_call_overdraft_refuses_during_retry_at_without_calling_factory():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    bucket = gov._providers["tradier"].bucket
    gov.note_rate_limited("tradier", 30.0)
    factory = Mock()
    t0 = time.monotonic()
    with pytest.raises(RateLimited):
        await gov.call_overdraft("tradier", factory)
    assert time.monotonic() - t0 < 0.1
    factory.assert_not_called()
    assert bucket._tokens == pytest.approx(5.0, abs=0.01)


async def test_call_overdraft_one_attempt_on_empty_bucket():
    gov = Governor.for_testing("tradier", rate=0.001, capacity=2)
    bucket = gov._providers["tradier"].bucket
    _drain(bucket)
    calls = {"n": 0}

    async def ok():
        calls["n"] += 1
        return "quote"

    t0 = time.monotonic()
    assert await gov.call_overdraft("tradier", ok) == "quote"
    assert time.monotonic() - t0 < 0.1
    assert calls["n"] == 1
    assert bucket._tokens == pytest.approx(-1.0, abs=0.01)
    assert gov.health("tradier") == "connected"


async def test_call_overdraft_429_notes_cooldown_and_never_retries():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    spy = Mock(wraps=gov.note_rate_limited)
    gov.note_rate_limited = spy
    calls = {"n": 0}

    async def limited():
        calls["n"] += 1
        raise RateLimited("429", retry_after=5.0)

    t0 = time.monotonic()
    with pytest.raises(RateLimited):
        await gov.call_overdraft("tradier", limited)
    assert time.monotonic() - t0 < 0.1
    assert calls["n"] == 1
    spy.assert_called_once_with("tradier", 5.0)
    assert gov._providers["tradier"].retry_at >= t0 + 5.0 - EPS
    assert gov.health("tradier") == "degraded"


async def test_call_overdraft_unknown_provider():
    gov = Governor.for_testing("tradier", rate=100, capacity=5)
    with pytest.raises(ProviderUnavailable):
        await gov.call_overdraft("nope", Mock())


# ---------------------------------------------------------------- default governor

def test_default_tradier_never_trips_and_tradier_paper_registered():
    gov = build_default_governor()
    tradier = gov._providers["tradier"]
    assert tradier.bucket.rate == pytest.approx(2.0)
    assert tradier.bucket.capacity == 15
    assert tradier.breaker.fail_threshold == 10**9
    for _ in range(50):
        gov.record_failure("tradier")
    assert not tradier.breaker.is_open
    paper = gov._providers["tradier_paper"]
    assert paper.bucket.rate == pytest.approx(1.0)
    assert paper.bucket.capacity == 5
    assert paper.breaker.fail_threshold == 10**9
    assert gov.health("tradier_paper") == "unknown"
    # Other providers keep their rates.
    assert gov._providers["alpaca"].bucket.rate == pytest.approx(200 / 60)
    assert gov._providers["alpaca"].breaker.fail_threshold == 5
    assert gov._providers["tastytrade"].breaker.fail_threshold == 3
