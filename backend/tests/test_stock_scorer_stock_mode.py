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


def _bars_rvol(n=120, current_vol_mult=2.5):
    """Bars where the last bar has `current_vol_mult` × avg volume."""
    avg = 1_000_000
    bars = []
    price = 100.0
    for i in range(n):
        price += 0.4
        vol = avg if i < n - 1 else int(avg * current_vol_mult)
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_rvol_high_scores_pass_in_stock_mode():
    """RVol >= 2.0x should produce vol component score 90 in stock mode."""
    bars = _bars_rvol(current_vol_mult=2.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 90
    assert vol_rule.detail.get("rvol") is not None


def test_rvol_low_scores_caution_in_stock_mode():
    """RVol < 0.8x should produce vol component score 20 in stock mode."""
    bars = _bars_rvol(current_vol_mult=0.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 20


def test_options_mode_vol_rule_unchanged():
    """options mode vol rule must still return PASS 90 (iv_rank_pass_max=null path)."""
    bars = _bars_rvol(current_vol_mult=0.1)   # tiny volume — would score 20 in stock mode
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="options")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 90   # unchanged — always PASS 90 in options mode
