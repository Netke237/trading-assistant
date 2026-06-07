# backend/tests/test_stock_scorer_stock_mode.py
import pytest
from app.scoring.stock_scorer import score_stock


def _bars(n=120, trend="up"):
    """Synthetic OHLCV bars. trend='up' rises, 'down' falls, else flat."""
    bars = []
    price = 100.0
    for i in range(n):
        if trend == "up":
            price += 0.4
        elif trend == "down":
            price -= 0.4
        vol = 1_000_000
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_score_stock_accepts_scoring_mode_options():
    """scoring_mode='options' (default) must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_score_stock_accepts_scoring_mode_stock():
    """scoring_mode='stock' must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="stock")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_options_mode_is_default():
    """Calling without scoring_mode must behave like options mode."""
    card_default = score_stock("AAPL", "Bullish", "Swing", _bars())
    card_options = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card_default.score == card_options.score
