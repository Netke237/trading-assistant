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
    "weekly": 4 * 3600,
}

_CHART_SEM = asyncio.Semaphore(2)

# The chart WS stream and /chart/history default to days=55 — the right cap for
# 1min/5min/15min/30min (yfinance's real window for those, per market._YF_MAX_DAYS)
# but far too short for 1h/4h/daily/weekly, which can serve much more. Widen those
# here — at the caching layer, so the cache key reflects the real window and only
# the chart path is affected (scanner / regime / HMM callers hit
# fetch_intraday_candles directly and keep their own days). ~5y matches the
# scanner's daily depth (market._fetch_daily_yf uses 5y); 730d matches
# market._YF_MAX_DAYS["1h"/"4h"], yfinance's real cap for those intervals.
_CHART_DAILY_DAYS = 1825    # ~5 years of daily bars
_CHART_WEEKLY_DAYS = 1825   # ~5 years of weekly bars
_CHART_HOURLY_DAYS = 730    # ~2 years of 1h/4h bars


def _key(symbol: str, interval: str, days: int) -> str:
    return f"{symbol}:{interval}:{days}"


async def get_intraday(symbol: str, interval: str = "15min", days: int = 55) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh."""
    interval = normalize_interval(interval)
    if interval == "daily":
        days = max(days, _CHART_DAILY_DAYS)
    elif interval == "weekly":
        days = max(days, _CHART_WEEKLY_DAYS)
    elif interval in ("1h", "4h"):
        days = max(days, _CHART_HOURLY_DAYS)
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
