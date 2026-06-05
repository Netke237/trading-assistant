"""Verify strategy signal functions respect caller-supplied tolerance/lookback params."""
import pytest
from app.services.strategy_engine import (
    pullback_ema_signal, ma_crossover_signal, breakout_base_signal,
)


def _uptrend(n: int = 200) -> list[dict]:
    bars, price = [], 100.0
    for _ in range(n):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": 1_000})
    return bars


def test_pullback_ema_respects_tight_tolerance():
    """With tolerance=0.001 (0.1%), the 2% pullback must return None."""
    bars = _uptrend(200)
    ema_approx = bars[-21]["close"]
    target = ema_approx * 1.02
    for i in range(-20, 0):
        bars[i] = {"open": target - 0.1, "high": target + 0.2,
                   "low": target - 0.2, "close": target + 0.1, "volume": 1_000}
    signal = pullback_ema_signal(bars, tolerance=0.001)
    assert signal is None, "With tolerance=0.001, 2% above EMA must be rejected"


def test_pullback_ema_respects_wide_tolerance():
    """With tolerance=0.10 (10%), a 5% pullback must fire."""
    bars = _uptrend(200)
    ema_approx = bars[-21]["close"]
    target = ema_approx * 1.05
    for i in range(-20, 0):
        bars[i] = {"open": target - 0.1, "high": target + 0.2,
                   "low": target - 0.2, "close": target + 0.1, "volume": 1_000}
    signal = pullback_ema_signal(bars, tolerance=0.10)
    assert signal is not None, "With tolerance=0.10, 5% above EMA must fire"


def _crossover_bars(cross_bars_ago: int, n_flat: int = 100) -> list[dict]:
    """100 flat bars at 100, then `cross_bars_ago` bars at 200.

    The fast MA crosses above the slow MA on the first high bar, which is
    exactly `cross_bars_ago` positions from the end of the list.
    """
    bars = []
    for _ in range(n_flat):
        bars.append({"open": 99.9, "high": 100.5, "low": 99.5,
                     "close": 100.0, "volume": 1_000})
    for _ in range(cross_bars_ago):
        bars.append({"open": 199.9, "high": 200.5, "low": 199.5,
                     "close": 200.0, "volume": 1_000})
    return bars


def test_ma_crossover_respects_short_lookback():
    """With lookback=2, a cross 5 bars ago must return None."""
    bars = _crossover_bars(cross_bars_ago=5)
    signal = ma_crossover_signal(bars, lookback=2)
    assert signal is None, "With lookback=2, cross 5 bars ago must be outside window"


def test_ma_crossover_respects_long_lookback():
    """With lookback=20, a cross 5 bars ago must fire."""
    bars = _crossover_bars(cross_bars_ago=5)
    signal = ma_crossover_signal(bars, lookback=20)
    assert signal is not None, "With lookback=20, cross 5 bars ago must fire"
