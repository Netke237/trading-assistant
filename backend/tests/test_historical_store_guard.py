"""Verify most_recent_trading_day() and the stale-check guard."""
from datetime import date, timedelta
from unittest.mock import patch
import pytest


def test_most_recent_trading_day_weekday():
    from app.services.historical_store import most_recent_trading_day
    # Wednesday → same day
    wed = date(2025, 6, 4)  # known Wednesday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = wed
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == wed


def test_most_recent_trading_day_saturday():
    from app.services.historical_store import most_recent_trading_day
    sat = date(2025, 6, 7)  # known Saturday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = sat
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == date(2025, 6, 6)  # Friday


def test_most_recent_trading_day_sunday():
    from app.services.historical_store import most_recent_trading_day
    sun = date(2025, 6, 8)  # known Sunday
    with patch("app.services.historical_store.date") as mock_date:
        mock_date.today.return_value = sun
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        result = most_recent_trading_day()
    assert result == date(2025, 6, 6)  # Friday
