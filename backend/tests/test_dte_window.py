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


def test_resolve_dte_bounds_returns_none_when_hold_days_absent():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(None, None, lambda: 2.0) is None
    assert resolve_dte_bounds(15, None, lambda: 2.0) is None
    assert resolve_dte_bounds(None, 45, lambda: 2.0) is None


def test_resolve_dte_bounds_returns_window_for_valid_input():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(15, 45, lambda: 2.0) == (30, 90)


def test_resolve_dte_bounds_falls_back_to_none_on_misconfigured_multiplier():
    from app.scoring.dte_window import resolve_dte_bounds
    assert resolve_dte_bounds(15, 45, lambda: 0.0) is None
    assert resolve_dte_bounds(15, 45, lambda: -1.0) is None


def test_resolve_dte_bounds_falls_back_to_none_when_multiplier_fn_raises():
    """The multiplier source can itself fail to produce a number (e.g. a
    non-numeric value in contract_rules.yaml makes float() raise ValueError) —
    that must degrade the same way a bad-but-numeric multiplier does, not 500."""
    from app.scoring.dte_window import resolve_dte_bounds
    def _broken_multiplier():
        raise ValueError("could not convert string to float: 'oops'")
    assert resolve_dte_bounds(15, 45, _broken_multiplier) is None


def test_resolve_dte_bounds_raises_on_inverted_range():
    """A caller that skips its own ordering check (both current callers already
    reject inverted ranges upstream — see Task 2) must get a loud failure here,
    not a silent None that masks the bad input as 'no override requested'."""
    from app.scoring.dte_window import resolve_dte_bounds
    with pytest.raises(ValueError):
        resolve_dte_bounds(100, 15, lambda: 2.0)


def test_widen_contract_overrides_widens_both_hard_and_preferred_bounds_identically():
    """Position horizon: 90-105 day hold -> dte_window gives lo=180, hi=210.
    Both min_dte/max_dte (hard) and preferred_dte_min/max (soft score) must get
    the identical +/-10 day tolerance -- this is the core of the fix."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    assert overrides["min_dte"] == overrides["preferred_dte_min"] == 170
    assert overrides["max_dte"] == overrides["preferred_dte_max"] == 220


def test_widen_contract_overrides_applies_the_same_narrow_horizon_floor_clamp():
    """Swing-like narrow horizon: lo=10, hold_max_days=15. widened_min_dte's
    floor clamp (hold_max_days+1=16) must apply to preferred_dte_min the exact
    same way it already applies to min_dte -- a contract can't be scored as
    'ideal' at a DTE that would expire before the hold is even over."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({}, lo=10, hi=30, hold_max_days=15)
    assert overrides["min_dte"] == overrides["preferred_dte_min"] == 16
    assert overrides["max_dte"] == overrides["preferred_dte_max"] == 40


def test_widen_contract_overrides_preserves_unrelated_keys():
    """Must merge into (not replace) whatever overrides dict is already in
    progress -- e.g. an unrelated max_price key from a prior step."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte
    overrides = widen_contract_overrides_for_dte({"max_price": 50.0}, lo=180, hi=210, hold_max_days=105)
    assert overrides["max_price"] == 50.0
    assert overrides["min_dte"] == 170


def test_widen_contract_overrides_matches_the_existing_widened_min_dte_helper():
    """Direct equivalence check against the already-tested widened_min_dte() /
    DTE_WINDOW_TOLERANCE_DAYS building blocks, so this test fails if the new
    helper's arithmetic ever drifts from the primitives it's built on."""
    from app.scoring.dte_window import widen_contract_overrides_for_dte, widened_min_dte, DTE_WINDOW_TOLERANCE_DAYS
    overrides = widen_contract_overrides_for_dte({}, lo=180, hi=210, hold_max_days=105)
    assert overrides["min_dte"] == widened_min_dte(180, 105)
    assert overrides["max_dte"] == 210 + DTE_WINDOW_TOLERANCE_DAYS
