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
async def test_semaphore_limits_concurrent_fetches():
    """Chart semaphore allows at most 2 concurrent fetches."""
    from app.data.chart_cache import _CHART_SEM
    assert _CHART_SEM._value == 2
