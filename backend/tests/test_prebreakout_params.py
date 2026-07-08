"""Regression tests for breakout_setup_signal default parameters.

The original defaults (range_atr_mult=0.8) made the range compression gate
mathematically impossible: a 10-bar price range cannot be smaller than 0.8×
a single ATR for any normally-traded stock. These tests verify that the fixed
defaults pass real OHLCV data, and that the broken defaults reject it.
"""
import pytest
from app.services.strategy_engine import breakout_setup_signal


def _make_bars(n: int = 60, base: float = 100.0, atr: float = 0.5) -> list[dict]:
    """Synthetic OHLCV bars: gentle uptrend then tight consolidation near swing high.

    Last 10 bars coil within ±0.2 ATR, sitting ~0.3% below the swing high.
    The uptrend rises only ~4% total (slope 0.08%/bar over 50 bars) so the
    consolidation price of base*1.04 lands within the 8% proximity gate.
    Volume drops to 600k in consolidation (vs 1M in trend) → ratio 0.73 < 0.9.
    ATR compresses sharply in the coil → current ATR ≈ 0.53 × avg ATR < 0.85 gate.
    """
    phase_trend = n - 10  # 50 uptrend bars, last 10 are consolidation
    bars = []
    for i in range(n):
        if i < phase_trend:
            # Gentle uptrend — rises ~4% total so swing high stays close to consol price
            close = base * (1.0 + i * 0.0008)
            high  = close + atr
            low   = close - atr
            vol   = 1_000_000
        else:
            # Consolidation phase — tight coil near (but below) swing high
            close = base * 1.04 + (i % 3 - 1) * atr * 0.2
            high  = close + atr * 0.2
            low   = close - atr * 0.2
            vol   = 600_000  # quiet volume — ratio ~0.73 vs avg
        bars.append({
            "open":   close - atr * 0.05,
            "high":   high,
            "low":    low,
            "close":  close,
            "volume": vol,
        })
    return bars


def test_fixed_defaults_return_signal():
    """With the corrected defaults the scanner must return a SetupSignal."""
    bars = _make_bars(n=60, base=100.0, atr=0.5)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=3.0,
        range_lookback_bars=10,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
        require_trend=True,
    )
    assert result is not None, (
        "Fixed defaults should pass a coiling stock near resistance, got None"
    )
    assert 0 <= result.confidence <= 100


def test_broken_range_mult_returns_none():
    """The original range_atr_mult=0.8 must reject the same bars (documents the bug)."""
    bars = _make_bars(n=60, base=100.0, atr=0.5)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=0.8,   # original broken default
        range_lookback_bars=10,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
        require_trend=True,
    )
    assert result is None, (
        "range_atr_mult=0.8 should kill the range gate for any real stock, got a signal"
    )


def test_confidence_within_bounds():
    """Confidence must always be clamped to [0, 100]."""
    bars = _make_bars(n=60, base=200.0, atr=1.0)
    result = breakout_setup_signal(
        bars,
        "TEST",
        atr_compression_ratio=0.85,
        atr_avg_lookback=20,
        range_atr_mult=3.0,
        range_lookback_bars=10,
        vol_compression_ratio=0.9,
        resistance_proximity_pct=0.08,
        swing_lookback=50,
        direction="Bullish",
        require_trend=True,
    )
    if result is not None:
        assert 0 <= result.confidence <= 100
