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
