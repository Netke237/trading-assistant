from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from app.data.market import fetch_intraday_candles, normalize_interval

# LRU-bounded: a 1h entry is ~1 MiB (730d of bars) and the key is
# symbol:interval:days, so browsing a large watchlist across intervals would
# otherwise leak hundreds of MiB over the process lifetime. Entries are swept
# on expiry and evicted oldest-first past the cap.
_INTRADAY_CACHE: "OrderedDict[str, tuple[list[dict], float]]" = OrderedDict()
_MAX_CACHE_ENTRIES = 200

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


async def get_intraday(symbol: str, interval: str = "15min", days: int | None = None) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh.

    `days=None` (the default) applies the per-interval default window — the
    historical behavior of the daily/weekly/1h/4h widening. An explicit
    `days` is honored as the caller's real request, smaller or larger, since
    this layer only sets the default and never re-caps an explicit value
    (market.py's _YF_MAX_DAYS is the actual fetch-time ceiling).
    """
    interval = normalize_interval(interval)
    if days is None:
        if interval == "daily":
            days = _CHART_DAILY_DAYS
        elif interval == "weekly":
            days = _CHART_WEEKLY_DAYS
        elif interval in ("1h", "4h"):
            days = _CHART_HOURLY_DAYS
        else:
            days = 55
    key = _key(symbol, interval, days)
    now = time.monotonic()

    cached = _INTRADAY_CACHE.get(key)
    if cached is not None and now < cached[1]:
        _INTRADAY_CACHE.move_to_end(key)
        return cached[0]

    async with _CHART_SEM:
        cached = _INTRADAY_CACHE.get(key)
        if cached is not None and time.monotonic() < cached[1]:
            _INTRADAY_CACHE.move_to_end(key)
            return cached[0]

        rows = await asyncio.to_thread(fetch_intraday_candles, symbol, interval, days)
        ttl = _TTL_BY_INTERVAL.get(interval, 30 * 60) if rows else 60
        _INTRADAY_CACHE[key] = (rows, now + ttl)
        _INTRADAY_CACHE.move_to_end(key)
        _evict(now)
        return rows


def _evict(now: float) -> None:
    """Drop expired entries, then evict oldest-first until under the cap.

    Without this the cache only ever grew: a stale entry was overwritten
    solely if that exact symbol:interval:days key was requested again, so
    anything the user browsed once was pinned for the process lifetime."""
    for k in [k for k, (_, exp) in _INTRADAY_CACHE.items() if exp <= now]:
        del _INTRADAY_CACHE[k]
    while len(_INTRADAY_CACHE) > _MAX_CACHE_ENTRIES:
        _INTRADAY_CACHE.popitem(last=False)
