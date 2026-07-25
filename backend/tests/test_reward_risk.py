"""Unit tests for app.scoring.reward_risk.estimate_rr()."""

from app.scoring.reward_risk import estimate_rr, estimate_targets
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


def test_heston_degenerate_price_falls_back_to_delta_approx():
    """heston_price() returning <=0 (e.g. v0=0, which heston.py's degenerate-input
    guard turns into a flat 0.0) must NOT be reported as 'Heston repriced' with a
    floored dummy premium — it must fall back to the delta approximation, exactly
    as if heston_params had been None."""
    params = HestonParams(v0=0.0, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "Delta approximation"
    # Matches test_delta_approx_call_above_strike's expected math exactly.
    assert rr.estimated_exit_premium == 10.0
    assert rr.rr_ratio == 5.0


def test_heston_exception_falls_back_to_delta_approx(monkeypatch):
    """If heston_price() raises for any reason, estimate_rr must still return a
    usable delta-approximation result instead of propagating the exception."""
    import app.scoring.reward_risk as rr_module

    def _boom(*args, **kwargs):
        raise ValueError("integration failed")

    monkeypatch.setattr(rr_module, "heston_price", _boom)
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "Delta approximation"
    assert rr.estimated_exit_premium == 10.0


def test_estimate_targets_falls_back_when_heston_price_is_non_monotonic(monkeypatch):
    """T1/T2/T3 share dte_at_target and only differ in the hypothetical stock
    price, so a correctly-priced option must be monotonically increasing
    across the ladder. A Heston price that comes out lower than the previous
    level's chosen price (see this task's intro — a reproduced, real artifact
    of heston_price's numerical integration for deep-OTM/long-dated inputs)
    must fall back to the delta approximation for that level only, instead of
    exposing a confusing non-monotonic sell-to-close ladder."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    real_heston_price = rr_module.heston_price
    call_count = {"n": 0}

    def _flaky(S, K, T, r, p, is_call):
        call_count["n"] += 1
        price = real_heston_price(S, K, T, r, p, is_call)
        if call_count["n"] == 2:
            return price * 0.1  # simulate T2 coming back numerically too low
        return price

    monkeypatch.setattr(rr_module, "heston_price", _flaky)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    assert targets[0].pricingMethod == "Heston repriced"    # T1 unaffected
    assert targets[1].pricingMethod == "Delta approximation"  # T2 — the artifact
    assert targets[2].pricingMethod == "Heston repriced"    # T3 unaffected


def test_estimate_targets_does_not_reject_legitimate_low_t1_price():
    """T1 is priced at dte_at_target (half of expiry_years) — a SHORTER
    time-to-expiry than 'now' (current_premium, priced at the full
    expiry_years) — so a legitimate Heston T1 price CAN be lower than the
    current premium purely from time decay outpacing an 8% favorable move,
    especially for a lower-delta/more-OTM contract. The monotonicity guard
    must never compare T1 against current_premium — regression guard for a
    finding that an earlier draft of this guard did exactly that and would
    have wrongly rejected this legitimate price."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    # Verified directly against this repo's real heston_price while writing
    # this plan: S=185, K=200, dte=30 gives a real T1 price of ~3.33 while the
    # "current premium" for that same contract (at the full 30-day tenor) is
    # ~6.59 — T1 legitimately lower, not a numerical artifact.
    targets = estimate_targets(
        stock_price=185, base_target_price=185 * 1.08, strike=200,
        expiry_years=30 / 365, current_premium=6.59, is_call=True,
        heston_params=params,
    )
    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice < 6.59


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
