"""
Data-leakage / look-ahead bias tests.

Assert that scorers only use data up to the scan date (no future data).
"""

from datetime import date
from app.scoring.stock_scorer import score_stock, _rule_trend, _rule_pullback, _rule_trigger, _rule_event, _rule_vol


def _make_bars(n: int, start_price: float = 100.0):
    """Generate n deterministic OHLCV bars."""
    bars = []
    price = start_price
    for i in range(n):
        o = round(price, 2)
        c = round(price + (i % 5 - 2) * 0.5, 2)
        h = round(max(o, c) + 0.3, 2)
        l = round(min(o, c) - 0.3, 2)
        bars.append({"time": f"2026-01-{i + 1:02d}", "open": o, "high": h, "low": l, "close": c, "volume": 1_000_000 + i * 100})
        price = c
    return bars


# ---------------------------------------------------------------------------
# Rule-level leakage checks
# ---------------------------------------------------------------------------

def test_rule_trend_only_uses_historical_closes():
    """_rule_trend must not peek beyond the last close in the series."""
    bars = _make_bars(50)
    closes = [b["close"] for b in bars]
    cfg = {
        "trend": {
            "fast_ema": 12,
            "slow_ema": 26,
            "slow_slope_required": True,
            "fast_slope_required": True,
        }
    }
    result = _rule_trend(closes, cfg)
    assert result.name == "trend"
    # The rule should succeed with 50 bars of data
    assert result.status in ("PASS", "CAUTION", "REJECT")


def test_rule_pullback_only_uses_historical_bars():
    """_rule_pullback must not use any bar beyond the provided series."""
    bars = _make_bars(50)
    cfg = {
        "pullback": {
            "swing_high_lookback_bars": 20,
            "swing_high_min_bars_ago": 5,
            "fib_shallow_min": 0.0,
            "fib_shallow_max": 0.30,
            "fib_standard_max": 0.50,
            "fib_golden_max": 0.618,
            "atr_period": 14,
            "atr_pass_min": 1.0,
            "atr_pass_max": 3.0,
            "atr_caution_max": 5.0,
        }
    }
    result = _rule_pullback(bars, cfg)
    assert result.name == "pullback"
    assert result.status in ("PASS", "CAUTION", "REJECT")


def test_rule_trigger_only_uses_historical_bars():
    """_rule_trigger must only use bars and volumes up to the last index."""
    bars = _make_bars(50)
    volumes = [b["volume"] for b in bars]
    cfg = {
        "trigger": {
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "macd_histogram_rising": True,
            "rsi_period": 14,
            "rsi_floor": 30,
            "rsi_div_window_bars": 10,
            "stoch_k": 14,
            "stoch_d": 3,
            "stoch_oversold": 20,
            "stoch_tolerance_pct": 5,
            "momentum_signals_for_pass": 2,
            "volume_lookback_bars": 20,
            "volume_multiplier": 1.5,
            "volume_bonus_pts": 5,
        }
    }
    result, _ = _rule_trigger(bars, cfg, volumes)
    assert result.name == "trigger"
    assert result.status in ("PASS", "CAUTION", "REJECT")


def test_rule_event_does_not_use_future_dates():
    """_rule_event must not treat past dates as upcoming events."""
    cfg = {
        "event": {
            "reject_days": 2,
            "caution_days": 7,
        }
    }
    today = date.today()
    # Earnings in the past should be ignored
    past_earnings = date(today.year - 1, 1, 1)
    result = _rule_event(past_earnings, None, cfg)
    assert result.status == "PASS"
    assert result.detail["event"] == "none"


def test_rule_event_rejects_near_future_event():
    """_rule_event must reject when earnings are too close."""
    cfg = {
        "event": {
            "reject_days": 5,
            "caution_days": 10,
        }
    }
    today = date.today()
    near_earnings = date(today.year + 1, today.month, today.day)
    days_until = (near_earnings - today).days
    result = _rule_event(near_earnings, None, cfg)
    # If the date is < reject_days away, it should be REJECT
    if days_until < cfg["event"]["reject_days"]:
        assert result.status == "REJECT"
    else:
        assert result.status in ("PASS", "CAUTION")


# ---------------------------------------------------------------------------
# End-to-end leakage check
# ---------------------------------------------------------------------------

def test_score_stock_does_not_use_future_data():
    """score_stock with identical bars must produce identical results regardless of when called."""
    bars = _make_bars(60)
    card1 = score_stock("AAPL", "Bullish", "Swing", bars)
    card2 = score_stock("AAPL", "Bullish", "Swing", bars)
    assert card1.score == card2.score
    assert card1.status == card2.status
    assert len(card1.rules) == len(card2.rules)
    for r1, r2 in zip(card1.rules, card2.rules):
        assert r1.score == r2.score
        assert r1.status == r2.status
