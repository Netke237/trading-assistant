from __future__ import annotations

import asyncio
import time
import threading


class TokenBucket:
    """Token-bucket rate limiter shared by async and sync callers.

    Refills `rate` tokens every `per` seconds, up to `capacity`. Waiting
    callers (async `acquire`, sync `acquire_blocking`) are admitted strictly
    first-come-first-served through one ticket queue guarded by the internal
    lock: a caller takes tokens only when its ticket is at the head of the
    queue and enough tokens are available, so neither kind of waiter can
    starve the other. `try_acquire` never waits and succeeds only when nobody
    is queued. `overdraft` never waits either: it books a token even on an
    empty bucket, flooring the balance at `-capacity`, and the queue then
    repays the debt from the normal refill (the head needs `_tokens >= n`).
    """

    # Floor on a waiter's poll interval, so a waiter behind a head that is
    # about to be admitted re-checks without spinning.
    _MIN_POLL = 0.002

    def __init__(self, rate: float, per: float = 1.0, capacity: float | None = None) -> None:
        self.rate = float(rate)
        self.per = float(per)
        self.capacity = float(capacity) if capacity is not None else float(rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()
        # FIFO ticket queue (all fields guarded by _lock).
        self._next_ticket = 0
        self._serving = 0
        self._abandoned: set[int] = set()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * (self.rate / self.per))
        self._updated = now

    # -- queue helpers (caller holds _lock) ------------------------------
    def _skip_abandoned(self) -> None:
        while self._serving in self._abandoned:
            self._abandoned.discard(self._serving)
            self._serving += 1

    def _take_ticket(self) -> int:
        with self._lock:
            ticket = self._next_ticket
            self._next_ticket += 1
            return ticket

    def _try_admit(self, ticket: int, tokens: float) -> tuple[bool, float]:
        """Admit `ticket` if it is the head and enough tokens are free.
        Otherwise return how long to sleep before re-checking."""
        with self._lock:
            self._refill()
            self._skip_abandoned()
            if ticket == self._serving and self._tokens >= tokens:
                self._tokens -= tokens
                self._serving += 1
                self._skip_abandoned()
                return True, 0.0
            ahead = ticket - self._serving - sum(
                1 for t in self._abandoned if self._serving < t < ticket
            )
            delay = (ahead + tokens - self._tokens) * (self.per / self.rate)
            return False, max(delay, self._MIN_POLL)

    def _abandon(self, ticket: int) -> None:
        with self._lock:
            if ticket == self._serving:
                self._serving += 1
                self._skip_abandoned()
            elif ticket > self._serving:
                self._abandoned.add(ticket)

    # -- admission -------------------------------------------------------
    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking admission sharing the waiting callers' token budget.
        Refuses while anyone is queued, so it never jumps the queue."""
        with self._lock:
            self._refill()
            self._skip_abandoned()
            if self._serving != self._next_ticket or self._tokens < tokens:
                return False
            self._tokens -= tokens
            return True

    def overdraft(self, tokens: float = 1.0) -> None:
        """Book `tokens` without waiting, even on an empty bucket. The balance
        never goes below `-capacity`. Bypasses the queue by design."""
        with self._lock:
            self._refill()
            self._tokens = max(self._tokens - tokens, -self.capacity)

    async def acquire(self, tokens: float = 1.0) -> None:
        ticket = self._take_ticket()
        admitted = False
        try:
            while True:
                admitted, delay = self._try_admit(ticket, tokens)
                if admitted:
                    return
                await asyncio.sleep(delay)
        finally:
            if not admitted:
                self._abandon(ticket)

    def acquire_blocking(self, tokens: float = 1.0, *, admit_timeout: float | None) -> bool:
        """Sync counterpart of `acquire`: sleeps the thread in the same FIFO
        queue until admitted (True) or until `admit_timeout` seconds elapse
        (False). `admit_timeout=None` waits without limit."""
        deadline = None if admit_timeout is None else time.monotonic() + admit_timeout
        ticket = self._take_ticket()
        admitted = False
        try:
            while True:
                admitted, delay = self._try_admit(ticket, tokens)
                if admitted:
                    return True
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    delay = min(delay, remaining)
                time.sleep(delay)
        finally:
            if not admitted:
                self._abandon(ticket)


class CircuitBreaker:
    """Opens after `fail_threshold` consecutive failures, blocking calls for
    `cooldown` seconds. After cooldown it reports closed (half-open trial); a
    success resets the counter, a failure re-opens it."""

    def __init__(self, fail_threshold: int = 5, cooldown: float = 60.0) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.RLock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._opened_at is not None and time.monotonic() - self._opened_at < self.cooldown

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.fail_threshold:
                self._opened_at = time.monotonic()


class SymbolBudget:
    """Tracks distinct symbols fetched within a rolling time window. Used for
    Tiingo's free-tier unique-symbol/hour cap: re-fetching a symbol already
    counted this window is free; a new symbol beyond `max_symbols` is refused."""

    def __init__(self, max_symbols: int, window: float = 3600.0) -> None:
        self.max_symbols = max_symbols
        self.window = window
        self._seen: dict[str, float] = {}  # symbol -> first-seen monotonic ts

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        self._seen = {s: t for s, t in self._seen.items() if t >= cutoff}

    def try_consume(self, symbol: str) -> bool:
        now = time.monotonic()
        self._evict(now)
        if symbol in self._seen:
            return True
        if len(self._seen) >= self.max_symbols:
            return False
        self._seen[symbol] = now
        return True

    def remaining(self) -> int:
        self._evict(time.monotonic())
        return max(0, self.max_symbols - len(self._seen))


class RateLimited(Exception):
    """Raised by a provider adapter when the API returns HTTP 429. Carries the
    server's Retry-After hint (seconds) when present."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Exponential backoff: base * 2**attempt, capped at `cap` seconds."""
    return min(cap, base * (2 ** attempt))


import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderUnavailable(Exception):
    """Raised when a provider's circuit is open, so callers can fall through to
    the next provider in their chain without making a doomed network call."""


@dataclass
class _ProviderState:
    name: str
    bucket: "TokenBucket"
    breaker: "CircuitBreaker"
    budget: "SymbolBudget | None" = None
    status: str = "unknown"  # unknown | connected | degraded | down | unconfigured
    retry_at: float = 0.0


class Governor:
    """Single gate every provider call passes through. Enforces per-provider
    rate limits, retries 429s with backoff, and opens a circuit on repeated
    failures so callers fail fast to their fallback chain."""

    def __init__(self, providers: dict[str, _ProviderState]) -> None:
        self._providers = providers

    @classmethod
    def for_testing(
        cls, provider: str, rate: float, capacity: float,
        fail_threshold: int = 5,
    ) -> "Governor":
        state = _ProviderState(
            name=provider,
            bucket=TokenBucket(rate=rate, per=1.0, capacity=capacity),
            breaker=CircuitBreaker(fail_threshold=fail_threshold, cooldown=60.0),
        )
        return cls({provider: state})

    def health(self, provider: str) -> str:
        ps = self._providers.get(provider)
        if ps is None:
            return "unconfigured"
        if ps.breaker.is_open:
            return "degraded"
        return ps.status

    def set_status(self, provider: str, status: str) -> None:
        ps = self._providers.get(provider)
        if ps is not None:
            ps.status = status

    def symbol_allowed(self, provider: str, symbol: str) -> bool:
        """True if `provider` still has budget for `symbol` this window."""
        ps = self._providers.get(provider)
        if ps is None or ps.budget is None:
            return True
        return ps.budget.try_consume(symbol)

    def try_acquire(self, provider: str) -> bool:
        """Refuse immediately on an open circuit or exhausted shared bucket."""
        ps = self._providers.get(provider)
        if ps is None:
            return False
        with ps.breaker._lock:
            return not ps.breaker.is_open and ps.bucket.try_acquire()

    def record_success(self, provider: str) -> None:
        ps = self._providers[provider]
        ps.breaker.record_success()
        ps.status = "connected"

    def record_failure(self, provider: str) -> None:
        ps = self._providers[provider]
        ps.breaker.record_failure()
        ps.status = "degraded"

    def note_rate_limited(self, provider: str, retry_after: float | None) -> None:
        """Record a 429: every caller (sync or async) honours the cooldown."""
        ps = self._providers.get(provider)
        if ps is None:
            return
        delay = retry_after or backoff_delay(0)
        ps.retry_at = max(ps.retry_at, time.monotonic() + delay)
        ps.status = "degraded"

    def admit_sync(
        self, provider: str, *, admit_timeout: float | None, overdraft: bool = False,
    ) -> bool:
        """Blocking admission for sync callers.

        `admit_timeout` is an admission budget in seconds (or None = no
        limit), never an HTTP timeout. With `overdraft=True` the caller never
        waits: it is refused at once during a 429 cooldown, otherwise it books
        a token (the bucket may go negative) and is admitted."""
        ps = self._providers.get(provider)
        if ps is None or ps.breaker.is_open:
            return False
        if overdraft:
            if ps.retry_at > time.monotonic():
                return False
            ps.bucket.overdraft()
            return True

        deadline = None if admit_timeout is None else time.monotonic() + admit_timeout

        def _wait_out_cooldown() -> bool:
            while True:
                now = time.monotonic()
                wait = ps.retry_at - now
                if wait <= 0:
                    return True
                if deadline is not None and now + wait > deadline:
                    return False
                time.sleep(wait)

        if not _wait_out_cooldown():
            return False
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        if not ps.bucket.acquire_blocking(admit_timeout=remaining):
            return False
        # A 429 may have landed while this caller was queued.
        if not _wait_out_cooldown():
            return False
        return not ps.breaker.is_open

    async def call_overdraft(self, provider: str, coro_factory: Callable[[], Awaitable[T]]) -> T:
        """Async fire-path call: never waits on the bucket. Refused at once
        (RateLimited, nothing sent) during a 429 cooldown; otherwise books an
        overdraft token and makes exactly one attempt, never retrying."""
        ps = self._providers.get(provider)
        if ps is None:
            raise ProviderUnavailable(f"provider '{provider}' not registered")
        if ps.breaker.is_open:
            ps.status = "degraded"
            raise ProviderUnavailable(f"{provider} circuit open")
        remaining = ps.retry_at - time.monotonic()
        if remaining > 0:
            raise RateLimited(f"{provider} rate-limit cooldown active", retry_after=remaining)
        ps.bucket.overdraft()
        try:
            result = await coro_factory()
        except RateLimited as exc:
            self.note_rate_limited(provider, exc.retry_after)
            ps.breaker.record_failure()
            raise
        except Exception:
            ps.breaker.record_failure()
            ps.status = "down"
            raise
        ps.breaker.record_success()
        ps.status = "connected"
        return result

    async def call(
        self,
        provider: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        retries: int = 3,
        symbol: str | None = None,
    ) -> T:
        ps = self._providers.get(provider)
        if ps is None:
            raise ProviderUnavailable(f"provider '{provider}' not registered")
        if ps.breaker.is_open:
            ps.status = "degraded"
            raise ProviderUnavailable(f"{provider} circuit open")

        attempt = 0
        while True:
            await ps.bucket.acquire()
            delay = ps.retry_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
                continue
            if ps.breaker.is_open:
                raise ProviderUnavailable(f"{provider} circuit open")
            if symbol is not None and not self.symbol_allowed(provider, symbol):
                ps.status = "degraded"
                raise ProviderUnavailable(f"{provider} symbol budget exhausted")
            try:
                result = await coro_factory()
                ps.breaker.record_success()
                ps.status = "connected"
                return result
            except RateLimited as exc:
                ps.breaker.record_failure()
                delay = exc.retry_after if exc.retry_after is not None else backoff_delay(attempt)
                self.note_rate_limited(provider, delay)
                if attempt >= retries:
                    logger.warning("%s rate-limited, retries exhausted", provider)
                    raise
                await asyncio.sleep(delay)
                attempt += 1
            except Exception:
                ps.breaker.record_failure()
                ps.status = "down"
                raise


def build_default_governor() -> Governor:
    """Production Governor sized to Kenneth's tiers (spec §3)."""
    def _state(name, rate, capacity, *, fail=5, budget=None):
        return _ProviderState(
            name=name,
            bucket=TokenBucket(rate=rate, per=1.0, capacity=capacity),
            breaker=CircuitBreaker(fail_threshold=fail, cooldown=60.0),
            budget=budget,
        )

    providers = {
        "alpaca":   _state("alpaca",   rate=200 / 60, capacity=20),
        # fail=10**9: the breaker never trips for Tradier (TRADIER-GOVERNOR
        # D2). A trip would fail every Tradier call fast for 60 s after a few
        # failures, dropping scan symbols for a whole minute; pacing, the
        # overdraft and the shared 429 cooldown are the whole protection.
        "tradier":  _state("tradier",  rate=120 / 60, capacity=15, fail=10**9),
        # The paper sandbox account is rate-limited separately from live.
        # 60/min is a conservative assumption (plan §5); same no-trip breaker.
        "tradier_paper": _state("tradier_paper", rate=60 / 60, capacity=5, fail=10**9),
        "tiingo":   _state("tiingo",   rate=1 / 72,  capacity=2,
                           budget=SymbolBudget(max_symbols=50, window=3600.0)),
        "yfinance": _state("yfinance", rate=2,        capacity=2),
        "ibkr":     _state("ibkr",     rate=40,       capacity=40),
        # No published production rate limit for market-metrics exists anywhere
        # in tastytrade's docs. The only documented number found is the Paper
        # API's default of 5 req/s, which is NOT confirmed to apply to
        # production or to this specific endpoint. Deliberately conservative:
        # 1 req/s, small burst capacity, trips the circuit after 3 failures
        # (not 5) so a real problem is caught faster before the account gets
        # flagged for abuse.
        "tastytrade": _state("tastytrade", rate=1.0, capacity=2, fail=3),
    }
    return Governor(providers)


_GOVERNOR: Governor | None = None


def get_governor() -> Governor:
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = build_default_governor()
    return _GOVERNOR
