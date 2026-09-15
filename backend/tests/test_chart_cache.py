from __future__ import annotations
import asyncio
import time
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_cache_miss_calls_fetch():
    """First call for a symbol fetches from source."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        result = await get_intraday("AAPL", "15min", 55)
    assert result == mock_rows
    mock_fetch.assert_called_once_with("AAPL", "15min", 55)


@pytest.mark.asyncio
async def test_cache_hit_skips_fetch():
    """Second call within TTL returns cached data without fetching."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "15min", 55)
        result = await get_intraday("AAPL", "15min", 55)
    assert result == mock_rows
    assert mock_fetch.call_count == 1  # only fetched once


@pytest.mark.asyncio
async def test_cache_expiry_refetches():
    """Call after TTL expires fetches again."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        import time as t
        _INTRADAY_CACHE["MSFT:15min:55"] = (mock_rows, t.monotonic() - 1)  # already expired
        await get_intraday("MSFT", "15min", 55)
    assert mock_fetch.call_count == 1


@pytest.mark.asyncio
async def test_1D_and_daily_share_one_cache_entry_and_ttl():
    """'1D' (chart-facing spelling) must be treated as equivalent to 'daily' for
    both cache-key purposes and the TTL lookup — not fall back to the default
    30-min TTL meant for un-recognized intervals."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows):
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        before = time.monotonic()
        await get_intraday("AAPL", "1D", 3650)
    matching_keys = [k for k in _INTRADAY_CACHE if k.startswith("AAPL:") and k.endswith(":3650")]
    assert matching_keys, f"Expected a normalized cache entry, got keys: {list(_INTRADAY_CACHE.keys())}"
    assert "daily" in matching_keys[0], f"Expected normalized 'daily' in cache key, got: {matching_keys[0]}"
    # Assert the actual stored expiry reflects the 4-hour "daily" TTL, not the
    # 30-minute default fallback — a substring match on the key alone wouldn't
    # catch a case where normalization happened but the TTL lookup itself broke.
    _, expiry = _INTRADAY_CACHE[matching_keys[0]]
    assert expiry - before > 3600, f"Expected ~4h TTL, got {expiry - before:.0f}s remaining"


@pytest.mark.asyncio
async def test_1W_and_weekly_share_one_cache_entry_and_ttl():
    """Same as above for '1W' → 'weekly' — closes the parallel gap where
    _TTL_BY_INTERVAL previously had a 'daily' entry but no 'weekly' one."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows):
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        before = time.monotonic()
        await get_intraday("AAPL", "1W", 3650)
    matching_keys = [k for k in _INTRADAY_CACHE if k.startswith("AAPL:") and k.endswith(":3650")]
    assert matching_keys, f"Expected a normalized cache entry, got keys: {list(_INTRADAY_CACHE.keys())}"
    assert "weekly" in matching_keys[0], f"Expected normalized 'weekly' in cache key, got: {matching_keys[0]}"
    _, expiry = _INTRADAY_CACHE[matching_keys[0]]
    assert expiry - before > 3600, f"Expected ~4h TTL, got {expiry - before:.0f}s remaining"


@pytest.mark.asyncio
async def test_4h_widened_to_hourly_cap_not_left_at_default_55():
    """'4h' (and '1h') must be widened past the chart WS/route's days=55 default,
    same as daily/weekly — yfinance supports 730 days for these intervals
    (market._YF_MAX_DAYS), so leaving them at 55 silently truncates the chart to
    a few weeks of history instead of ~2 years."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "4h")  # caller passes no days -> route/WS default of 55
    mock_fetch.assert_called_once_with("AAPL", "4h", 730)


@pytest.mark.asyncio
async def test_1h_widened_to_hourly_cap_not_left_at_default_55():
    """Same widening as 4h (see test above) — '1h' shares the same branch in
    get_intraday, but had no dedicated regression test of its own."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "1h")  # caller passes no days -> route/WS default of 55
    mock_fetch.assert_called_once_with("AAPL", "1h", 730)


def test_hourly_widening_still_matches_the_yfinance_ceiling():
    """Tripwire for the 730 literal in the widening tests above:
    _CHART_HOURLY_DAYS is only correct while it equals market._YF_MAX_DAYS for
    1h/4h. If Yahoo's window moves and only one side is updated, the chart
    silently over- or under-fetches."""
    from app.data import market
    from app.data.chart_cache import _CHART_HOURLY_DAYS

    assert market._YF_MAX_DAYS["1h"] == _CHART_HOURLY_DAYS
    assert market._YF_MAX_DAYS["4h"] == _CHART_HOURLY_DAYS


@pytest.mark.asyncio
async def test_60m_normalizes_to_1h_and_widens():
    """'60m' must resolve exactly like '1h' — market.py and ibkr.py both already
    handled that spelling, so the cache layer treating it as unknown (55 days,
    default TTL) was an inconsistency waiting to bite a new interval button."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "60m")
    mock_fetch.assert_called_once_with("AAPL", "1h", 730)
    assert "AAPL:1h:730" in _INTRADAY_CACHE


@pytest.mark.asyncio
async def test_double_checked_lock_hit_still_promotes_recency():
    """A caller that loses the race to a concurrent writer — its outer,
    pre-semaphore cache check misses, then by the time it acquires
    _CHART_SEM another coroutine has already written a fresh entry — must
    still count as a touch of that key for LRU purposes. Without
    move_to_end() on this inner-check branch too, a key only ever reached
    through it stays wherever the *original write* left it, so it can be
    evicted sooner than a real LRU would allow even while still being
    actively requested."""
    from app.data.chart_cache import get_intraday, _INTRADAY_CACHE

    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    _INTRADAY_CACHE.clear()
    fresh_entry = (mock_rows, time.monotonic() + 3600)

    call_n = 0

    def fake_get(k, default=None):
        nonlocal call_n
        call_n += 1
        # Outer check (before acquiring _CHART_SEM): nothing cached yet.
        if call_n == 1:
            return None
        # Inner check (after acquiring _CHART_SEM): a concurrent writer
        # finished in between and the entry is now there.
        return fresh_entry

    with patch.object(_INTRADAY_CACHE, "get", side_effect=fake_get), \
         patch.object(_INTRADAY_CACHE, "move_to_end") as mock_move_to_end, \
         patch("app.data.chart_cache.fetch_intraday_candles") as mock_fetch:
        result = await get_intraday("RACE", "15min", 55)

    assert result == mock_rows
    mock_fetch.assert_not_called()  # served from the inner-check hit, not refetched
    mock_move_to_end.assert_called_once_with("RACE:15min:55")


@pytest.mark.asyncio
async def test_cache_is_bounded_and_evicts_oldest_first():
    """The cache was unbounded and only ever overwritten per-key, so every symbol
    the user browsed stayed resident for the process lifetime — at ~1 MiB per 1h
    entry after the widening, that is hundreds of MiB across a watchlist."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows):
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE, _MAX_CACHE_ENTRIES
        _INTRADAY_CACHE.clear()
        for i in range(_MAX_CACHE_ENTRIES + 25):
            await get_intraday(f"SYM{i}", "15min", 55)
    assert len(_INTRADAY_CACHE) <= _MAX_CACHE_ENTRIES
    assert "SYM0:15min:55" not in _INTRADAY_CACHE          # oldest evicted
    assert f"SYM{_MAX_CACHE_ENTRIES + 24}:15min:55" in _INTRADAY_CACHE  # newest kept


@pytest.mark.asyncio
async def test_explicit_days_for_daily_is_honored_not_floored():
    """A caller explicitly asking for fewer days than the default widening
    (e.g. days=10 for a daily chart) must get exactly that back, not silently
    forced up to the ~5y default. Before this fix, `days = max(days, cap)`
    could only ever push an explicit value *up*, never respect a smaller
    explicit request — this is the case that was previously impossible."""
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "daily", 10)
    mock_fetch.assert_called_once_with("AAPL", "daily", 10)
    assert "AAPL:daily:10" in _INTRADAY_CACHE


@pytest.mark.asyncio
async def test_omitted_days_for_daily_still_widens_to_the_default():
    """Regression guard: omitting `days` entirely (the None sentinel) for a
    widened interval must still resolve to the historical per-interval
    default — the no-args production call path is unchanged by this fix."""
    from app.data import chart_cache
    mock_rows = [{"time": "2024-01-02", "open": 100, "high": 105, "low": 99, "close": 103, "volume": 1000}]
    with patch("app.data.chart_cache.fetch_intraday_candles", return_value=mock_rows) as mock_fetch:
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await get_intraday("AAPL", "daily")
    mock_fetch.assert_called_once_with("AAPL", "daily", chart_cache._CHART_DAILY_DAYS)
    assert f"AAPL:daily:{chart_cache._CHART_DAILY_DAYS}" in _INTRADAY_CACHE


@pytest.mark.asyncio
async def test_at_most_2_concurrent_fetches():
    """At most 2 concurrent chart fetches run simultaneously."""
    import asyncio as _asyncio
    peak = 0
    current = 0

    async def fake_thread(fn, *args):
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await _asyncio.sleep(0.02)
        current -= 1
        return []

    with patch("app.data.chart_cache.asyncio.to_thread", side_effect=fake_thread):
        from app.data.chart_cache import get_intraday, _INTRADAY_CACHE
        _INTRADAY_CACHE.clear()
        await _asyncio.gather(
            get_intraday("S1", "15min", 55),
            get_intraday("S2", "15min", 55),
            get_intraday("S3", "15min", 55),
            get_intraday("S4", "15min", 55),
        )
    assert peak <= 2
