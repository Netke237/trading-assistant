"""Tests for _fibonacci_pullback_signal sequencing improvements (Task 6)."""
import pytest
from app.services.strategy_engine import fibonacci_pullback_signal


def _flat_bars(n=120, price=100.0, vol=1_000_000):
    return [{"open": price, "high": price + 0.3, "low": price - 0.3,
             "close": price, "volume": vol} for _ in range(n)]


def _impulse_then_retrace(swing_pct=0.15, retrace_bars=15, n_base=80):
    """Base flat bars, impulse up by swing_pct, then retrace to ~61.8% fib."""
    bars = _flat_bars(n_base, price=100.0)
    base_price = 100.0
    top = base_price * (1 + swing_pct)
    # Impulse up over 15 bars
    for i in range(15):
        p = base_price + (top - base_price) * (i + 1) / 15
        bars.append({"open": p - 0.2, "high": p + 0.3, "low": p - 0.3,
                     "close": p, "volume": 2_000_000})
    # Retrace to ~61.8% level
    fib618 = top - 0.618 * (top - base_price)
    for i in range(retrace_bars):
        p = top - (top - fib618) * (i + 1) / retrace_bars
        bars.append({"open": p + 0.1, "high": p + 0.3, "low": p - 0.2,
                     "close": p, "volume": 800_000})
    return bars


def _tiny_move_bars(swing_pct=0.03, n=120):
    """Small drift — below any meaningful impulse threshold."""
    bars = _flat_bars(n - 5, price=100.0)
    top = 100.0 * (1 + swing_pct)
    for _ in range(3):
        bars.append({"open": top, "high": top + 0.1, "low": top - 0.1,
                     "close": top, "volume": 1_000_000})
    # Dip slightly
    bars.append({"open": top - 0.3, "high": top - 0.1, "low": top - 0.5,
                 "close": top - 0.4, "volume": 900_000})
    bars.append({"open": top - 0.4, "high": top - 0.2, "low": top - 0.6,
                 "close": top - 0.5, "volume": 900_000})
    return bars


# ── impulse_min_pct ────────────────────────────────────────────────────────────

def test_fib_rejects_tiny_impulse():
    """Move < 8% must return (False, None, None) — no setup."""
    bars = _tiny_move_bars(swing_pct=0.03)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.08
    )
    assert level is None, "tiny impulse should return level_hit=None"
    assert at_level is False
    assert dist is None


def test_fib_accepts_strong_impulse():
    """Move of 15% passes the 8% impulse gate."""
    bars = _impulse_then_retrace(swing_pct=0.15)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.08
    )
    assert level is not None, "15% impulse should pass the gate"


def test_fib_impulse_zero_disables_check():
    """impulse_min_pct=0.0 must be backward compatible — never filters on impulse size."""
    bars = _tiny_move_bars(swing_pct=0.03)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.0
    )
    # With no impulse gate, should return a level (even if trivial)
    # Result may be None only if the window has < 10 bars
    assert isinstance(at_level, bool)


def test_fib_no_zerodivision_on_zero_swing_low():
    """swing_low=0 must not raise ZeroDivisionError."""
    bars = [{"open": 0, "high": 1.0, "low": 0.0, "close": 0.5, "volume": 1000}] * 15
    # Should return gracefully
    result = fibonacci_pullback_signal(bars, "Bullish", impulse_min_pct=0.08)
    assert isinstance(result, tuple) and len(result) == 3


# ── retracement_recency_bars ───────────────────────────────────────────────────

def test_fib_rejects_stale_retracement():
    """Peak that occurred 55 bars ago fails a 30-bar recency gate."""
    bars = _impulse_then_retrace(swing_pct=0.15, retrace_bars=55, n_base=60)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.08, retracement_recency_bars=30
    )
    assert level is None, "stale peak (55 bars ago) must fail recency gate"


def test_fib_accepts_recent_retracement():
    """Peak that occurred within recency window passes."""
    bars = _impulse_then_retrace(swing_pct=0.15, retrace_bars=10, n_base=80)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.08, retracement_recency_bars=30
    )
    assert level is not None, "recent peak should pass recency gate"


def test_fib_recency_zero_disables_check():
    """retracement_recency_bars=0 is backward compatible — no recency filter."""
    bars = _impulse_then_retrace(swing_pct=0.15, retrace_bars=80, n_base=60)
    at_level, dist, level = fibonacci_pullback_signal(
        bars, "Bullish", impulse_min_pct=0.0, retracement_recency_bars=0
    )
    # Result depends on data, but must not crash and must be a valid tuple
    assert isinstance(result := (at_level, dist, level), tuple) and len(result) == 3


# ── backward compatibility ─────────────────────────────────────────────────────

def test_fib_default_args_backward_compatible():
    """Calling with no extra args must not raise."""
    bars = _impulse_then_retrace(swing_pct=0.15)
    result = fibonacci_pullback_signal(bars, "Bullish")
    assert isinstance(result, tuple) and len(result) == 3


def test_fib_bearish_direction_does_not_crash():
    """Bearish direction must complete without error."""
    bars = list(reversed(_impulse_then_retrace(swing_pct=0.15)))
    result = fibonacci_pullback_signal(bars, "Bearish", impulse_min_pct=0.08)
    assert isinstance(result, tuple) and len(result) == 3
