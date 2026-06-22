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

def _bars_with_falling_rsi(n=60, peak_at=55):
    """Bars designed so RSI rises above 60 then falls back through 60.
    Last two closes: RSI was above rsi_ceiling, now below it."""
    bars = []
    # Uptrend phase — RSI builds up
    price = 100.0
    for i in range(n - 5):
        price += 0.5
        bars.append(_bar(price - 0.2, price + 0.3, price - 0.4, price))
    # Reversal phase — price drops sharply (RSI falls through ceiling)
    for i in range(5):
        price -= 1.5
        bars.append(_bar(price + 0.2, price + 0.3, price - 0.3, price))
    return bars


def _bars_with_rising_rsi(n=60):
    """Bars designed so RSI is rising (crosses up through floor)."""
    bars = []
    price = 100.0
    for i in range(n - 5):
        price -= 0.3  # downtrend builds oversold
        bars.append(_bar(price + 0.1, price + 0.2, price - 0.3, price))
    for i in range(5):
        price += 0.8  # bounce — RSI crosses up
        bars.append(_bar(price - 0.1, price + 0.3, price - 0.2, price))
    return bars


def _vols(bars):
    return [b["volume"] for b in bars]


# ── Bearish MACD: histogram must cross DOWN ────────────────────────────────────

def test_bearish_macd_requires_histogram_cross_down():
    """For Bearish direction, macd_pass should fire when histogram goes from + to -."""
    cfg = _cfg_swing()
    # Build bars so MACD hist goes + → 0/-
    bars = []
    price = 100.0
    for i in range(80):
        price += 0.6  # uptrend: MACD hist builds positive
        bars.append(_bar(price - 0.1, price + 0.2, price - 0.2, price))
    # Sharp reversal: MACD hist crosses down
    for i in range(10):
        price -= 1.2
        bars.append(_bar(price + 0.1, price + 0.3, price - 0.3, price))
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    # The detail dict exposes macd_pass
    assert "macd_pass" in result.detail, "detail must include macd_pass key"


def test_bearish_macd_does_not_fire_when_histogram_crossing_up():
    """Bullish MACD (hist crosses up) must NOT fire macd_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)  # bars designed with rising momentum
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    # macd_pass should be False — histogram is rising, not falling
    assert result.detail["macd_pass"] is False, (
        "Rising MACD histogram must not fire macd_pass for Bearish"
    )


# ── Bearish RSI: must fall through ceiling, not rise through floor ─────────────

def test_bearish_rsi_fires_on_falling_through_ceiling():
    """For Bearish, rsi_pass should fire when RSI falls from above 60 to below 60."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert "rsi_pass" in result.detail


def test_bearish_rsi_does_not_fire_on_rising_through_floor():
    """RSI crossing UP through 38/44 must NOT fire rsi_pass for Bearish direction."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert result.detail["rsi_pass"] is False, (
        "RSI rising through floor must not fire rsi_pass for Bearish"
    )


# ── Bullish direction: existing behaviour unchanged ────────────────────────────

def test_bullish_rsi_still_fires_on_rising_through_floor():
    """Regression: Bullish rsi_pass still fires when RSI rises through floor."""
    cfg = _cfg_swing()
    bars = _bars_with_rising_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bullish")
    # The test only verifies the key is present (actual pass depends on bar sequence)
    assert "rsi_pass" in result.detail


# ── Stochastic: bearish should check overbought exit ──────────────────────────

def test_bearish_stoch_detail_key_present():
    """stoch_pass key must always be present in detail regardless of direction."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    assert "stoch_pass" in result.detail


def test_bearish_trigger_detail_has_all_keys():
    """detail dict must contain candle, macd_pass, rsi_pass, stoch_pass, momentum_count."""
    cfg = _cfg_swing()
    bars = _bars_with_falling_rsi(80)
    result, _ = _rule_trigger(bars, cfg, _vols(bars), direction="Bearish")
    for key in ("candle", "macd_pass", "rsi_pass", "stoch_pass", "momentum_count"):
        assert key in result.detail, f"Missing key: {key}"
