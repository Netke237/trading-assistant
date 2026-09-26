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


def _ttl_for(interval: str, rows: list[dict]) -> float:
    return _TTL_BY_INTERVAL.get(interval, 30 * 60) if rows else 60


def _fetched_at_wall(interval: str, rows: list[dict], expiry: float) -> float:
    """Wall-clock instant the cached `rows` were fetched, derived from the entry's
    monotonic expiry (expiry = fetch + _ttl_for). Derived rather than stored so
    the cache entry keeps its (rows, expiry) shape."""
    fetched_mono = expiry - _ttl_for(interval, rows)
    return time.time() - (time.monotonic() - fetched_mono)


async def get_intraday(symbol: str, interval: str = "15min", days: int | None = None) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh."""
    rows, _ = await get_intraday_with_fetched_at(symbol, interval, days)
    return rows


def _needs_refresh(interval: str, rows: list[dict], fetched_at: float,
                   now_wall: float, max_age: float | None) -> bool:
    """P4a (decision Q14): should a still-TTL-valid entry be refetched?

    The TTL alone (30 min for a 15min bar) let the chart-alert scheduler's
    `candles[-2]` jump two bars, so a closed candle was never evaluated. Two
    rules, either suffices:

    - DUE INSTANTS (R1-1): the newest bar `rows[-1]` has become due since the
      fetch -- `fetched_at < due <= now` for `due = time + span` (the real-time
      yfinance bar that normally ends the merged series) OR
      `due = time + span + lag` (a delayed Tradier-sandbox bar; `lag` as in
      `market.completed_bars_for_interval`). A fetch after both is quiet, so
      this is silent overnight.
    - AGE (R2-1): `max_age` given and the entry is at least that old. The
      due-instant rule stalls when a refetch returns no newer bar (no trade
      printed yet, a live token where both instants coincide, an illiquid
      symbol); the caller (the scheduler) passes `max_age=span` only while
      the session is open or the newest bar is recent.

    Daily/weekly, an unknown interval, or a newest bar without an int `time`:
    no due-instant rule (TTL and `max_age` only).
    """
    from app.data.market import (
        _INTERVAL_COMPLETION_SECONDS, _TRADIER_INTRADAY_INTERVALS, intraday_feed_lag_seconds,
    )
    if max_age is not None and now_wall >= fetched_at + max_age:
        return True
    span = _INTERVAL_COMPLETION_SECONDS.get(interval)
    if span is None or not rows:
        return False
    t = rows[-1].get("time")
    if not isinstance(t, int) or isinstance(t, bool):
        return False
    lag = intraday_feed_lag_seconds() if interval in _TRADIER_INTRADAY_INTERVALS else 0
    return any(fetched_at < due <= now_wall for due in (t + span, t + span + lag))


async def get_intraday_with_fetched_at(
    symbol: str, interval: str = "15min", days: int | None = None,
    refresh_on_close: bool = False, max_age: float | None = None,
) -> tuple[list[dict], float]:
    """`get_intraday`, plus the wall-clock time (epoch seconds) the rows were
    fetched. A4c: a cached bar that was still forming at fetch time keeps its
    partial content after its interval elapses on the wall clock, so a regime
    model's "completed bars" must be judged at THIS instant, not time.time().

    `days=None` (the default) applies the per-interval default window — the
    historical behavior of the daily/weekly/1h/4h widening. An explicit
    `days` is honored as the caller's real request, smaller or larger, since
    this layer only sets the default and never re-caps an explicit value
    (market.py's _YF_MAX_DAYS is the actual fetch-time ceiling).

    P4a (Q14): `refresh_on_close=True` (the chart-alert scheduler) refetches a
    still-valid entry when `_needs_refresh` says a new bar is due or the entry
    is older than `max_age`. The chart WebSocket and /chart/history pass
    neither; they simply read the fresher entry.
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

    def _fresh(entry, mono_now: float):
        if entry is None or mono_now >= entry[1]:
            return None
        fetched = _fetched_at_wall(interval, entry[0], entry[1])
        if refresh_on_close and _needs_refresh(interval, entry[0], fetched, time.time(), max_age):
            return None
        return fetched

    cached = _INTRADAY_CACHE.get(key)
    fetched = _fresh(cached, now)
    if fetched is not None:
        _INTRADAY_CACHE.move_to_end(key)
        return cached[0], fetched

    async with _CHART_SEM:
        # Same check again under the lock (plan G): another caller may have
        # refreshed the entry while this one waited.
        cached = _INTRADAY_CACHE.get(key)
        fetched = _fresh(cached, time.monotonic())
        if fetched is not None:
            _INTRADAY_CACHE.move_to_end(key)
            return cached[0], fetched

        # The fetch STARTS here; a bar complete at this instant is complete in
        # the rows returned. Taken before the fetch, so it can only understate.
        fetched_at = time.time()
        rows = await asyncio.to_thread(fetch_intraday_candles, symbol, interval, days)
        ttl = _ttl_for(interval, rows)
        _INTRADAY_CACHE[key] = (rows, now + ttl)
        _INTRADAY_CACHE.move_to_end(key)
        _evict(now)
        return rows, fetched_at


def _evict(now: float) -> None:
    """Drop expired entries, then evict oldest-first until under the cap.

    Without this the cache only ever grew: a stale entry was overwritten
    solely if that exact symbol:interval:days key was requested again, so
    anything the user browsed once was pinned for the process lifetime."""
    for k in [k for k, (_, exp) in _INTRADAY_CACHE.items() if exp <= now]:
        del _INTRADAY_CACHE[k]
    while len(_INTRADAY_CACHE) > _MAX_CACHE_ENTRIES:
        _INTRADAY_CACHE.popitem(last=False)
