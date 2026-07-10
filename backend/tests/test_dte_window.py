import pytest

from app.scoring.dte_window import dte_window


def test_position_preset_reproduces_existing_band():
    """15-45 day hold must yield the existing 30-90 DTE band exactly."""
    assert dte_window(15, 45, 2.0) == (30, 90)


def test_intraday_clamps_zero_to_one():
    """0 * 2 = 0 is not a tradeable DTE; the bottom clamp lifts it to 1."""
    assert dte_window(0, 2, 2.0) == (1, 4)


def test_swing_preset():
    assert dte_window(5, 15, 2.0) == (10, 30)


def test_quarterly_preset():
    assert dte_window(45, 60, 2.0) == (90, 120)


def test_semi_annual_preset():
    assert dte_window(90, 105, 2.0) == (180, 210)


def test_annual_preset():
    assert dte_window(165, 200, 2.0) == (330, 400)


def test_custom_range_is_doubled():
    """The originally-reported case: typing 60-185 means expiries 120-370 days out."""
    assert dte_window(60, 185, 2.0) == (120, 370)


def test_max_below_min_is_clamped_up():
    """A degenerate 0-0 hold clamps min to 1, and max must not fall below it."""
    assert dte_window(0, 0, 2.0) == (1, 1)


def test_negative_hold_raises():
    with pytest.raises(ValueError):
        dte_window(-1, 10, 2.0)


def test_non_positive_multiplier_raises():
    with pytest.raises(ValueError):
        dte_window(5, 15, 0.0)


def test_hold_max_below_hold_min_raises():
    with pytest.raises(ValueError):
        dte_window(20, 5, 2.0)
