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
