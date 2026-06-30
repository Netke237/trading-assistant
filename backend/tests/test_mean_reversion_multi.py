"""Tests for mean_reversion_vwap_daily_signal and mean_reversion_multi scan path."""

import pytest
from app.services.strategy_engine import (
    mean_reversion_vwap_daily_signal,
    StrategySignal,
)


def make_bars(n: int, base_price: float = 100.0, base_volume: float = 1_000_000) -> list[dict]:
    """Build synthetic daily bars with slight noise.

    Args:
        n: number of bars
        base_price: starting price
        base_volume: base volume (bars will have volume ± 10%)

    Returns:
        List of bar dicts with OHLCV + date
    """
    bars = []
    price = base_price
    for i in range(n):
        # Slight random drift (±0.2% per bar)
        drift = 1 + (i % 7 - 3) * 0.002
        price *= drift

        vol = base_volume * (0.9 + (i % 3) * 0.1)
        bars.append({
            "open": price - 0.3,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": vol,
            "date": f"2025-01-{(i % 31) + 1:02d}",
        })
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: vwap_daily fires on snap-back (Bullish)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_snap_back():
    """bar[-2] closes 5% below rolling VWAP, bar[-1] snaps back above VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable by using consistent prices
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below rolling VWAP of ~100)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None, "Expected signal on Bullish snap-back"
    assert signal.direction == "Bullish"
    assert signal.entry_price > 0
    assert signal.strategy == "mean_reversion_vwap"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: vwap_daily does NOT fire when bar[-1] still below VWAP
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_no_snap_back():
    """bar[-2] closes below VWAP, but bar[-1] still below VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below VWAP)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 97 (still below VWAP of ~100)
    bars[-1]["close"] = 97.0
    bars[-1]["low"] = 96.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is None, "Expected None when bar[-1] still below VWAP"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: vwap_daily does NOT fire when deviation is insufficient
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bullish_insufficient_deviation():
    """bar[-2] closes only 0.5% below VWAP (threshold is 2%), bar[-1] above VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 99.5 (0.5% below VWAP of ~100, below threshold)
    bars[-2]["close"] = 99.5
    bars[-2]["low"] = 99.0

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_deviation_pct=0.02  # 2% threshold
    )

    assert signal is None, "Expected None when deviation is below 2% threshold"


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: vwap_daily fires for Bearish direction
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bearish_snap_back():
    """bar[-2] closes 5% above rolling VWAP, bar[-1] snaps back below VWAP."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 105 (5% above rolling VWAP of ~100)
    bars[-2]["close"] = 105.0
    bars[-2]["high"] = 105.5

    # bar[-1]: close = 99 (snaps back below VWAP)
    bars[-1]["close"] = 99.0
    bars[-1]["low"] = 98.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bearish")

    assert signal is not None, "Expected signal on Bearish snap-back"
    assert signal.direction == "Bearish"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: vwap_daily insufficient bars returns None
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_insufficient_bars():
    """Only 10 bars (less than vwap_lookback=20 + 2 required)."""
    bars = make_bars(10, base_price=100.0, base_volume=1_000_000)

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_lookback=20
    )

    assert signal is None, "Expected None with insufficient bars"


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: vwap_daily detail contains rolling_vwap and deviation_pct
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_detail_fields():
    """Verify detail dict contains rolling_vwap and deviation_pct."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 95 (5% below VWAP)
    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5

    # bar[-1]: close = 101 (back above VWAP)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None
    assert "rolling_vwap" in signal.detail
    assert "deviation_pct" in signal.detail
    assert signal.detail["rolling_vwap"] > 0
    assert signal.detail["deviation_pct"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: StrategySignal structure and risk/reward/rr_ratio properties
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_signal_structure():
    """Verify StrategySignal has all required fields and properties."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Setup for successful signal
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None
    assert isinstance(signal, StrategySignal)
    assert signal.strategy == "mean_reversion_vwap"
    assert signal.direction == "Bullish"
    assert signal.entry_price > 0
    assert signal.stop_price > 0
    assert signal.target_price > 0
    assert signal.atr > 0
    # For Bullish: stop < entry < target
    assert signal.stop_price < signal.entry_price < signal.target_price
    assert signal.risk > 0
    assert signal.reward > 0
    assert signal.rr_ratio > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Bearish signal structure
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_bearish_signal_structure():
    """Bearish signal: target < entry < stop."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 105.0
    bars[-2]["high"] = 105.5
    bars[-1]["close"] = 99.0
    bars[-1]["low"] = 98.5

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bearish")

    assert signal is not None
    assert signal.direction == "Bearish"
    # For Bearish: target < entry < stop
    assert signal.target_price < signal.entry_price < signal.stop_price


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Edge case — just above boundary (> 2% deviation)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_just_above_2pct_deviation():
    """bar[-2] at 2.1% below VWAP (just above threshold)."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    # Keep VWAP stable
    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    # bar[-2]: close = 97.9 (2.1% below VWAP of 100)
    bars[-2]["close"] = 97.9
    bars[-2]["low"] = 97.4

    # bar[-1]: close = 101 (back above)
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        vwap_deviation_pct=0.02
    )

    # Just above threshold should fire (< comparison with 0.021)
    assert signal is not None, "Expected signal at 2.1% deviation (> 2% threshold)"


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Customizable stop and target multipliers
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_custom_atr_multipliers():
    """Test with custom stop_atr_mult and rr_target_mult."""
    bars = make_bars(25, base_price=100.0, base_volume=1_000_000)

    for i in range(len(bars)):
        bars[i]["close"] = 100.0
        bars[i]["high"] = 100.5
        bars[i]["low"] = 99.5
        bars[i]["volume"] = 1_000_000

    bars[-2]["close"] = 95.0
    bars[-2]["low"] = 94.5
    bars[-1]["close"] = 101.0
    bars[-1]["high"] = 101.5

    # Custom multipliers
    signal = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        stop_atr_mult=1.0,  # wider stop
        rr_target_mult=3.0,  # higher reward target
    )

    assert signal is not None
    # With higher target multiplier, reward should be larger
    reward_1x = signal.reward

    # Compare to default (0.5, 2.0)
    signal_default = mean_reversion_vwap_daily_signal(
        bars,
        direction="Bullish",
        stop_atr_mult=0.5,
        rr_target_mult=2.0,
    )

    assert reward_1x > signal_default.reward


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: No signal when zero ATR (degenerate case)
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_zero_atr():
    """All bars identical — ATR = 0, should return None."""
    bars = []
    for i in range(25):
        bars.append({
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000_000,
        })

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    # With zero ATR, stop calculation would fail (risk <= 0)
    assert signal is None


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Real-world-like bars with volume variation
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_daily_with_realistic_bars():
    """Use make_bars() helper to generate realistic synthetic data."""
    bars = make_bars(30, base_price=150.0, base_volume=2_500_000)

    # Manually set up snap-back
    # First 28 bars will have slight variation from make_bars
    # Adjust last 2 bars for our test
    for i in range(len(bars) - 2):
        bars[i]["close"] = 150.0
        bars[i]["high"] = 150.5
        bars[i]["low"] = 149.5
        bars[i]["volume"] = 2_500_000

    # bar[-2]: down 3% from 150
    bars[-2]["close"] = 145.5
    bars[-2]["low"] = 145.0
    bars[-2]["high"] = 146.0

    # bar[-1]: back up to 151
    bars[-1]["close"] = 151.0
    bars[-1]["high"] = 151.5
    bars[-1]["low"] = 150.0

    signal = mean_reversion_vwap_daily_signal(bars, direction="Bullish")

    assert signal is not None, "Expected signal with realistic bars"
    assert signal.entry_price == pytest.approx(151.0, abs=0.01)
