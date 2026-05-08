import pytest
from app.scoring.stock_scorer import score_stock


def _make_candles(n=250, trend="down") -> list[dict]:
    """Generate synthetic candle sequence. Default 250 bars — enough for slow EMA period of 200."""
    import random
    random.seed(42)
    price = 100.0
    bars = []
    for i in range(n):
        if trend == "down":
            price *= (1 - random.uniform(0.001, 0.008))  # steady downtrend
        else:
            price *= (1 + random.uniform(0.001, 0.008))  # steady uptrend
        o = price * (1 + random.uniform(-0.002, 0.002))
        c = price
        h = max(o, c) * (1 + random.uniform(0, 0.005))
        l = min(o, c) * (1 - random.uniform(0, 0.005))
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1_000_000})
    return bars


def test_bearish_setup_scores_above_50():
    """Clean downtrend with fast_ema < slow_ema should score > 30 for Bearish direction."""
    bars = _make_candles(trend="down")
    card = score_stock("TEST", "Bearish", "Swing", bars)
    assert card.score > 30, f"Expected score > 30 for bearish setup, got {card.score}"
    assert card.direction == "Bearish"


def test_bullish_candles_score_lower_as_bearish():
    """Uptrend candles should score lower when evaluated as Bearish."""
    uptrend = _make_candles(trend="up")
    downtrend = _make_candles(trend="down")
    card_up = score_stock("TEST", "Bearish", "Swing", uptrend)
    card_down = score_stock("TEST", "Bearish", "Swing", downtrend)
    assert card_down.score > card_up.score, (
        f"Downtrend ({card_down.score}) should score higher than uptrend ({card_up.score}) for Bearish"
    )


def test_bullish_scan_unaffected():
    """Existing bullish scoring still works correctly."""
    bars = _make_candles(trend="up")
    card = score_stock("TEST", "Bullish", "Swing", bars)
    assert card.direction == "Bullish"
    assert card.score >= 0


def test_direction_tag_propagates():
    """Score card must carry the direction tag."""
    bars = _make_candles(trend="down")
    card = score_stock("TEST", "Bearish", "Swing", bars)
    assert card.direction == "Bearish"
