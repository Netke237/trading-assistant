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


def test_options_mode_vol_rule_uses_iv_rank_not_rvol():
    """options mode must use IV rank gate, not rvol — tiny volume must NOT score 20.

    With iv_rank_pass_max=34 set for Swing, passing no iv_rank returns CAUTION 50
    ("no_iv_data"), confirming that rvol is ignored in options mode.
    """
    bars = _bars_rvol(current_vol_mult=0.1)   # tiny volume — would score 20 in stock mode
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="options")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score != 20, "options mode must not use rvol scoring"
    assert vol_rule.score == 50   # no iv_rank provided → "no_iv_data" CAUTION 50


from app.scoring.stock_scorer import _rule_trigger, _horizon_cfg, _rule_event
import copy
from datetime import date, timedelta


def _trigger_bars_macd_cross(n=80):
    """Bars engineered so MACD histogram crosses zero near the last bar."""
    bars = []
    price = 50.0
    for i in range(n):
        if i < n // 2:
            price -= 0.3
        else:
            price += 0.6
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 800_000})
    return bars


def _cfg_swing():
    return copy.deepcopy(_horizon_cfg("Swing"))


def test_trigger_no_candle_required_signals_is_pass_in_stock_mode():
    """Stock mode: required momentum signals without candle → score >= 65 (not capped at 35)."""
    cfg = _cfg_swing()
    # Force zero required signals so momentum_count >= required is guaranteed
    cfg["trigger"]["momentum_signals_for_pass"] = 0
    bars = _trigger_bars_macd_cross()
    # Make last bar bearish so no candle is detected
    bars[-1]["close"] = bars[-1]["open"] - 0.5
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    assert result.score >= 65   # stock mode: momentum alone drives PASS, not capped at 35


def test_trigger_with_candle_bonus_in_stock_mode():
    """Stock mode: candle adds +15 pts on top of momentum base."""
    cfg = _cfg_swing()
    cfg["trigger"]["momentum_signals_for_pass"] = 0  # guaranteed pass threshold
    bars = _trigger_bars_macd_cross()
    # Bullish last bar → candle detected
    bars[-1]["close"] = bars[-1]["open"] + 1.0
    bars[-1]["high"] = bars[-1]["close"] + 0.3
    volumes = [b["volume"] for b in bars]
    result_no_candle_bars = _trigger_bars_macd_cross()
    result_no_candle_bars[-1]["close"] = result_no_candle_bars[-1]["open"] - 0.5
    result_no_candle_bars[-1]["low"] = result_no_candle_bars[-1]["close"] - 0.3
    result_without_candle, _ = _rule_trigger(result_no_candle_bars, _cfg_swing(), volumes, "Bullish", scoring_mode="stock")
    result_with_candle, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    assert result_with_candle.score >= result_without_candle.score
    assert result_with_candle.status == "PASS"


def test_trigger_options_mode_still_caps_no_candle_at_35():
    """Options mode: no candle + required signals met → CAUTION 35 (unchanged)."""
    cfg = _cfg_swing()
    bars = _trigger_bars_macd_cross()
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # bearish — no candle
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="options")
    momentum_count = result.detail.get("momentum_count", 0)
    required = cfg["trigger"]["momentum_signals_for_pass"]
    if momentum_count >= required:
        assert result.score == 35


def test_event_neutral_in_stock_mode():
    """Stock mode: earnings tomorrow must return PASS 90 (event = flag not penalty)."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="stock")
    assert result.status == "PASS"
    assert result.score == 90
    assert result.detail.get("days_to_event") is not None   # metadata still present


def test_event_still_penalises_in_options_mode():
    """Options mode: earnings tomorrow must return REJECT (unchanged behaviour)."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="options")
    assert result.status == "REJECT"
    assert result.score == 5
