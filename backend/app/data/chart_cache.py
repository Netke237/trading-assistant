from __future__ import annotations

import asyncio
import time

from app.data.market import fetch_intraday_candles, normalize_interval

_INTRADAY_CACHE: dict[str, tuple[list[dict], float]] = {}

_TTL_BY_INTERVAL: dict[str, float] = {
    "1min":  15 * 60,
    "5min":  15 * 60,
    "15min": 30 * 60,
    "1h":    30 * 60,
    "4h":     4 * 3600,
    "daily":  4 * 3600,
}

_CHART_SEM = asyncio.Semaphore(2)


def _key(symbol: str, interval: str, days: int) -> str:
    return f"{symbol}:{interval}:{days}"


async def get_intraday(symbol: str, interval: str = "15min", days: int = 55) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh."""
    interval = normalize_interval(interval)
    key = _key(symbol, interval, days)
    now = time.monotonic()

    cached = _INTRADAY_CACHE.get(key)
    if cached is not None and now < cached[1]:
        return cached[0]

    async with _CHART_SEM:
        cached = _INTRADAY_CACHE.get(key)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]

        rows = await asyncio.to_thread(fetch_intraday_candles, symbol, interval, days)
        ttl = _TTL_BY_INTERVAL.get(interval, 30 * 60) if rows else 60
        _INTRADAY_CACHE[key] = (rows, now + ttl)
        return rows
