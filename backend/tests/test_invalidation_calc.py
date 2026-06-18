"""The trade card's invalidation price must be derived from the premium stop, not a fixed pct."""
import pytest


def _invalidation_from_delta(price: float, premium: float, stop_pct: float, delta: float, is_call: bool) -> float:
    move = (premium * stop_pct) / max(abs(delta), 0.05)
    return price - move if is_call else price + move


def test_call_invalidation_is_closer_than_3pct_for_cheap_option():
    """$1 option with delta 0.45, 60% stop: move = (1.0 * 0.60) / 0.45 = $1.33.
    For price=100 that's invalidation=98.67, not 97.00 (-3%)."""
    inv = _invalidation_from_delta(price=100, premium=1.0, stop_pct=0.60, delta=0.45, is_call=True)
    assert round(inv, 2) == 98.67
    assert inv > 97.00   # delta-derived stop is closer than the fixed 3% level


def test_put_invalidation_is_above_price():
    """Bearish put: stock moves UP to hit invalidation."""
    inv = _invalidation_from_delta(price=100, premium=2.0, stop_pct=0.60, delta=0.45, is_call=False)
    assert inv > 100


def test_high_delta_option_gives_smaller_stock_move():
    """Deep ITM delta=0.80 → smaller stock move to lose 60% premium than delta=0.30."""
    inv_deep = _invalidation_from_delta(price=100, premium=5.0, stop_pct=0.60, delta=0.80, is_call=True)
    inv_otm  = _invalidation_from_delta(price=100, premium=5.0, stop_pct=0.60, delta=0.30, is_call=True)
    assert inv_deep > inv_otm  # deep ITM → invalidation closer to current price


def test_delta_floor_prevents_division_by_zero():
    """delta=0 is floored to 0.05, producing a finite result."""
    inv = _invalidation_from_delta(price=100, premium=2.0, stop_pct=0.60, delta=0.0, is_call=True)
    assert inv > 0
    assert inv < 100
