import sys
from unittest.mock import patch

from app.data.market import _fetch_news_yf, fetch_earnings_events


def test_fetch_news_yf_returns_list():
    """Calling _fetch_news_yf must return a list, never raise."""
    result = _fetch_news_yf(["SPY"])
    assert isinstance(result, list)


def test_fetch_news_yf_handles_yf_import_failure():
    """If yfinance is unavailable, _fetch_news_yf must return [] not propagate."""
    # Setting sys.modules entry to None causes 'import yfinance' to raise ImportError.
    with patch.dict(sys.modules, {"yfinance": None}):
        result = _fetch_news_yf(["SPY"])
    assert result == []


def test_fetch_earnings_events_handles_yf_import_failure():
    """If yfinance is unavailable, fetch_earnings_events must return [] not propagate."""
    with patch.dict(sys.modules, {"yfinance": None}):
        result = fetch_earnings_events(["AAPL"])
    assert result == []
