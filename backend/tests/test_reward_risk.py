"""Unit tests for app.scoring.reward_risk.estimate_rr()."""

from app.scoring.reward_risk import estimate_rr
from app.models.heston import HestonParams


# ── Delta approximation — call ────────────────────────────────────────────────

def test_delta_approx_call_above_strike():
    """Call, target(200) > strike(190) → delta=0.5.
    exit=10.0, reward=7.5, risk=2.50*0.60=1.50, rr=5.0."""
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 5.0
    assert rr.estimated_exit_premium == 10.0


def test_delta_approx_call_below_strike():
    """Call, target(188) < strike(190) → delta=0.3.
    exit=1.90, reward=0.90, risk=1.00*0.60=0.60, rr=1.5."""
    rr = estimate_rr(
        stock_price=185, target_price=188, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=1.00, is_call=True,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 1.5


# ── Delta approximation — put ─────────────────────────────────────────────────

def test_delta_approx_put_below_strike():
    """Put, target(170) < strike(180) → delta=0.5.
    exit=9.50, reward=7.50, risk=2.00*0.60=1.20, rr=6.25."""
    rr = estimate_rr(
        stock_price=185, target_price=170, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=2.00, is_call=False,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 6.25
    assert rr.estimated_exit_premium == 9.50


def test_delta_approx_put_above_strike():
    """Put, target(185) > strike(180) → delta=0.3."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=1.00, is_call=False,
    )
    # price_move = 0 → exit = 1.00 → reward = 0 → rr_ratio = 0.0
    assert rr.rr_ratio == 0.0


# ── Zero / degenerate cases ───────────────────────────────────────────────────

def test_zero_price_movement_returns_zero_ratio():
    """target == stock_price → price_move=0 → reward=0 → rr_ratio=0.0."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.rr_ratio == 0.0


def test_zero_premium_returns_zero_ratio():
    """current_premium=0 → risk=0 → rr_ratio=0.0."""
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=0.0, is_call=True,
    )
    assert rr.rr_ratio == 0.0


def test_exit_premium_floored_at_0_01():
    """When computed exit_premium would be <= 0, floor kicks in."""
    # Very short expiry, deep OTM Heston → may return near-zero
    # Use delta path with negative movement to force floor
    rr = estimate_rr(
        stock_price=185, target_price=100, invalidation_price=175,
        strike=300, expiry_years=1/365, current_premium=0.01, is_call=True,
    )
    assert rr.estimated_exit_premium >= 0.01


# ── Heston path ───────────────────────────────────────────────────────────────

def test_heston_path_uses_correct_model_label():
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "Heston repriced"


def test_heston_path_returns_valid_ratio():
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert isinstance(rr.rr_ratio, float)
    assert rr.estimated_exit_premium > 0


def test_heston_path_not_used_when_params_none():
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
        heston_params=None,
    )
    assert rr.model_used == "Delta approximation"


def test_estimate_rr_uses_premium_stop_pct():
    """risk = current_premium * premium_stop_pct, so halving premium_stop_pct doubles rr_ratio."""
    from app.scoring.reward_risk import estimate_rr

    base_kwargs = dict(
        stock_price=100.0,
        target_price=108.0,
        invalidation_price=97.0,
        strike=100.0,
        expiry_years=0.25,
        current_premium=2.00,
        is_call=True,
    )

    result_60 = estimate_rr(**base_kwargs, premium_stop_pct=0.60)
    result_30 = estimate_rr(**base_kwargs, premium_stop_pct=0.30)

    # 0.30 stop_pct = half the risk basis → rr_ratio should be double
    assert result_60.rr_ratio > 0
    assert result_30.rr_ratio > 0
    # Allow floating-point tolerance
    assert abs(result_30.rr_ratio - result_60.rr_ratio * 2) < 0.05

    # Also verify the 0.60 case matches expected math:
    # exit_premium = 2.00 + 0.5*(108-100) = 6.00; reward=4.00; risk=1.20; rr=3.33
    assert abs(result_60.rr_ratio - 3.33) < 0.01


def test_estimate_exit_premium_rounded_on_zero_reward():
    """The early-return (zero-reward) path must round estimated_exit_premium to
    2 decimals, matching the success path."""
    rr = estimate_rr(
        stock_price=100.0, target_price=100.0, invalidation_price=90.0,
        strike=90.0, expiry_years=30 / 365, current_premium=2.567, is_call=True,
    )
    # target == stock → price_move 0 → reward 0 → early return.
    assert rr.rr_ratio == 0.0
    assert rr.estimated_exit_premium == 2.57


def test_estimate_rr_zero_stop_pct_returns_zero():
    """premium_stop_pct=0 means risk=0, guard should return rr_ratio=0.0."""
    from app.scoring.reward_risk import estimate_rr

    result = estimate_rr(
        stock_price=100.0,
        target_price=108.0,
        invalidation_price=97.0,
        strike=100.0,
        expiry_years=0.25,
        current_premium=2.00,
        is_call=True,
        premium_stop_pct=0.0,
    )
    assert result.rr_ratio == 0.0
