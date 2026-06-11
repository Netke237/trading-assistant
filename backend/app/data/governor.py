from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Async token-bucket rate limiter.

    Refills `rate` tokens every `per` seconds, up to `capacity`. `acquire()`
    blocks until a token is available, so callers are admitted at most as fast
    as the configured rate. Admission is serialized by an internal lock, which
    is what makes strict per-provider pacing possible.
    """

    def __init__(self, rate: float, per: float = 1.0, capacity: float | None = None) -> None:
        self.rate = float(rate)
        self.per = float(per)
        self.capacity = float(capacity) if capacity is not None else float(rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated
                self._tokens = min(
                    self.capacity,
                    self._tokens + elapsed * (self.rate / self.per),
                )
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                await asyncio.sleep(deficit * (self.per / self.rate))


class CircuitBreaker:
    """Opens after `fail_threshold` consecutive failures, blocking calls for
    `cooldown` seconds. After cooldown it reports closed (half-open trial); a
    success resets the counter, a failure re-opens it."""

    def __init__(self, fail_threshold: int = 5, cooldown: float = 60.0) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown:
            return False  # half-open: allow a trial call through
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
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

    async def call(
        self,
        provider: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        retries: int = 3,
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
            try:
                result = await coro_factory()
                ps.breaker.record_success()
                ps.status = "connected"
                return result
            except RateLimited as exc:
                ps.status = "degraded"
                ps.breaker.record_failure()
                if attempt >= retries:
                    logger.warning("%s rate-limited, retries exhausted", provider)
                    raise
                delay = exc.retry_after if exc.retry_after is not None else backoff_delay(attempt)
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
        "tradier":  _state("tradier",  rate=120 / 60, capacity=15),
        "tiingo":   _state("tiingo",   rate=1 / 72,  capacity=2,
                           budget=SymbolBudget(max_symbols=50, window=3600.0)),
        "yfinance": _state("yfinance", rate=2,        capacity=2),
        "ibkr":     _state("ibkr",     rate=40,       capacity=40),
    }
    return Governor(providers)


_GOVERNOR: Governor | None = None


def get_governor() -> Governor:
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = build_default_governor()
    return _GOVERNOR
