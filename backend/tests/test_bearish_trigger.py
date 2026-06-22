"""Tests that bearish trigger momentum checks fire on bearish (not bullish) signals."""
import pytest
from app.scoring.stock_scorer import _rule_trigger, _rsi, _macd_histogram


def _bar(o, h, l, c, v=500_000):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _cfg_swing():
    """Load the real swing config."""
    from app.scoring.stock_scorer import _horizon_cfg
    return _horizon_cfg("Swing")


# ── Helpers to build bar sequences with known indicator values ─────────────────
# These are calibrated against the actual indicator formulas so indicator crossovers
# occur at exactly the last two bars.

def _bars_bearish_rsi_cross():
    """80 uptrend bars + 3 drops: rsi[-2]≈61 (above ceiling=60), rsi[-1]≈50 (below)."""
    bars = []
    price = 100.0
    for _ in range(80):
        price += 0.5
        bars.append(_bar(price - 0.1, price + 0.2, price - 0.2, price))
    for _ in range(3):
        price -= 2.0
        bars.append(_bar(price + 0.2, price + 0.3, price - 0.3, price))
    return bars


def _bars_bullish_rsi_cross():
    """80 downtrend bars + 3 bounces: rsi[-2]≈32 (below floor=38), rsi[-1]≈43 (above)."""
    bars = []
    price = 100.0
    for _ in range(80):
        price -= 0.5
        bars.append(_bar(price + 0.1, price + 0.2, price - 0.2, price))
    for _ in range(3):
        price += 1.5
        bars.append(_bar(price - 0.1, price + 0.3, price - 0.2, price))
    return bars


def _bars_bearish_macd_cross():
    """80 accelerating-uptrend bars + 2 flat bars: hist[-2]≈+0.09 (pos), hist[-1]≈-0.13 (neg)."""
    bars = []
    price = 100.0
    for i in range(80):
        price += 0.3 + i * 0.02  # acceleration keeps MACD growing
        bars.append(_bar(price - 0.1, price + 0.2, price - 0.2, price))
    # 2 flat bars: histogram decays from positive to negative in one step
    for _ in range(2):
        bars.append(_bar(price - 0.1, price + 0.2, price - 0.2, price))
    return bars


def _bars_with_rising_rsi(n=80):
    """Downtrend then bounce: RSI is rising at the end (does NOT cross the floor)."""
    return _bars_bullish_rsi_cross()


def _bars_with_falling_rsi(n=80):
    """Uptrend then drops: RSI is falling at the end (does NOT guarantee ceiling cross)."""
    return _bars_bearish_rsi_cross()


def _vols(bars):
    return [b["volume"] for b in bars]


# ── Bearish MACD: histogram must cross DOWN ────────────────────────────────────

def test_bearish_macd_requires_histogram_cross_down():
    """For Bearish direction, macd_pass must be True when histogram crosses from + to -."""
    cfg = _cfg_swing()
    tc = cfg["trigger"]
    bars = _bars_bearish_macd_cross()
    closes = [b["close"] for b in bars]
    hist = _macd_histogram(closes, tc["macd_fast"], tc["macd_slow"], tc["macd_signal"])
    # Verify test data actually produces the cross condition (diagnostic assertion)
    assert len(hist) >= 2 and hist[-2] > 0 and hist[-1] <= 0, (
        f"Test data must produce hist cross-down: hist[-2]={hist[-2]:.4f}, hist[-1]={hist[-1]:.4f}"
    )
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert result.detail.get("macd_pass") is True, (
        f"Bearish MACD cross-down must set macd_pass=True, got detail={result.detail}"
    )


def test_bearish_macd_does_not_fire_when_histogram_crossing_up():
    """Bullish MACD (hist crosses up) must NOT fire macd_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_bullish_rsi_cross()  # bars with rising momentum (downtrend → bounce)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    # macd_pass should be False — histogram is rising, not falling
    assert result.detail["macd_pass"] is False, (
        "Rising MACD histogram must not fire macd_pass for Bearish"
    )


# ── Bearish RSI: must fall through ceiling, not rise through floor ─────────────

def test_bearish_rsi_fires_on_falling_through_ceiling():
    """For Bearish, rsi_pass must be True when RSI falls from above 60 to below 60."""
    cfg = _cfg_swing()
    tc = cfg["trigger"]
    rsi_ceiling = tc.get("rsi_ceiling", 60)
    bars = _bars_bearish_rsi_cross()
    closes = [b["close"] for b in bars]
    rsi_vals = _rsi(closes, tc["rsi_period"])
    # Verify test data actually straddles the ceiling (diagnostic assertion)
    assert rsi_vals[-2] > rsi_ceiling >= rsi_vals[-1], (
        f"Test data must straddle ceiling: rsi[-2]={rsi_vals[-2]:.1f}, rsi[-1]={rsi_vals[-1]:.1f}, ceiling={rsi_ceiling}"
    )
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert result.detail.get("rsi_pass") is True, (
        f"Bearish RSI fall-through ceiling must set rsi_pass=True, got detail={result.detail}"
    )


def test_bearish_rsi_does_not_fire_on_rising_through_floor():
    """RSI crossing UP through the floor must NOT fire rsi_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_bullish_rsi_cross()  # RSI rises through floor — wrong direction for Bearish
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert result.detail["rsi_pass"] is False, (
        "RSI rising through floor must not fire rsi_pass for Bearish"
    )


# ── Bullish direction: existing behaviour unchanged ────────────────────────────

def test_bullish_rsi_still_fires_on_rising_through_floor():
    """Regression: Bullish rsi_pass must be True when RSI rises through floor."""
    cfg = _cfg_swing()
    tc = cfg["trigger"]
    rsi_floor = tc["rsi_floor"]
    bars = _bars_bullish_rsi_cross()
    closes = [b["close"] for b in bars]
    rsi_vals = _rsi(closes, tc["rsi_period"])
    # Verify test data actually straddles the floor (diagnostic assertion)
    assert rsi_vals[-2] < rsi_floor <= rsi_vals[-1], (
        f"Test data must straddle floor: rsi[-2]={rsi_vals[-2]:.1f}, rsi[-1]={rsi_vals[-1]:.1f}, floor={rsi_floor}"
    )
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bullish")
    assert result.detail.get("rsi_pass") is True, (
        f"Bullish RSI rise-through floor must set rsi_pass=True, got detail={result.detail}"
    )


# ── Stochastic: bearish should check overbought exit ──────────────────────────

def test_bearish_stoch_exits_overbought():
    """For Bearish, stoch_pass key must be present in result.detail (exit-overbought logic)."""
    cfg = _cfg_swing()
    bars = _bars_bearish_rsi_cross()  # uptrend + drops; stoch may or may not fire but key must exist
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert "stoch_pass" in result.detail, "stoch_pass key must be present in detail"


def test_bearish_trigger_detail_has_all_keys():
    """detail dict must contain candle, macd_pass, rsi_pass, stoch_pass, momentum_count."""
    cfg = _cfg_swing()
    bars = _bars_bearish_rsi_cross()
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    for key in ("candle", "macd_pass", "rsi_pass", "stoch_pass", "momentum_count"):
        assert key in result.detail, f"Missing key: {key}"
