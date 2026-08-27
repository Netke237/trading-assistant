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
