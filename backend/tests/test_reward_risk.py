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


def test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models(monkeypatch):
    """T1/T2/T3 share dte_at_target and only differ in the hypothetical stock
    price, so a correctly-priced option must be monotonically increasing
    across the ladder. A Heston price that comes out lower than the previous
    level's TRUE Heston price is a numerical-integration artifact (a
    reproduced, real artifact of heston_price's numerical integration for
    deep-OTM/long-dated inputs) — it must be floored up to that true Heston
    reference and stay labelled 'Heston repriced', NOT be switched entirely
    to the cruder delta-approximation model. Switching models was the old
    behavior and is exactly what let a LATER level's legitimate Heston price
    get wrongly discarded too (see the next test) — this is round 3's
    adversarial-audit finding, fixed here."""
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
    # T1 raw = 15.899302223959836 (verified against the real pricer).
    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 15.9

    # T2's raw price (2.7679...) is an artifact — floored UP to T1's price,
    # and still labelled Heston repriced, not switched to delta approximation.
    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 15.9

    # T3 raw = 39.784960139409236 — well above T1's price, so it is its own
    # legitimate, unfloored, unclamped Heston price.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 39.78


def test_estimate_targets_clamps_delta_approx_fallback_to_prev_level(monkeypatch):
    """When Heston is genuinely unusable for a level (raises, here — not just
    numerically low), that level falls back to the delta approximation, which
    can itself undershoot the previous level's displayed price. The final
    display invariant must still clamp it up so the card never shows a
    decreasing ladder (code review finding on commit 80d8a6b, reproduced
    here) — this is unchanged by this task's fix, which only changes what
    happens when Heston SUCCEEDS but comes back numerically low (see the
    previous test).

    Also confirms the fix's decoupling: T2's failure (and its clamped-up
    display price) must NOT affect T3's Heston-artifact check — T3's own raw
    Heston price is checked against T1's true Heston price, not T2's
    fallback."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    call_count = {"n": 0}

    def _fake(S, K, T, r, p, is_call):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 15.9  # T1: legitimate, high
        if call_count["n"] == 2:
            raise ValueError("integration failed")  # T2: genuinely unusable
        return 20.0  # T3: legitimate, its own value

    monkeypatch.setattr(rr_module, "heston_price", _fake)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 15.9

    # T2: Heston raised, so delta approximation is used. Target price for T2
    # is 207.5 (> strike 190) -> delta=0.5, price_move=22.5 ->
    # 2.50 + 0.5*22.5 = 13.75, which undershoots T1's 15.9 -> clamped to 15.9.
    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 15.9

    # T3: Heston succeeds with its own value (20.0), checked against T1's
    # true Heston price (15.9) — NOT T2's fallback. 20.0 >= 15.9, so it is
    # kept as-is, not floored.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 20.0


def test_estimate_targets_relabels_heston_price_still_below_inflated_prior_display(monkeypatch):
    """T3's raw Heston price (12.0) clears the artifact-floor check against
    T1's true Heston price (10.0) — it is NOT a numerical artifact. But T2
    had a genuine Heston failure and its delta-approximation fallback
    (13.75) is itself above both T1's and T3's real Heston prices. Showing
    T3 as 'Heston repriced' would mean displaying a number (after the
    non-decreasing-display clamp) that Heston never actually produced for
    T3 — so T3 must fall back to the delta approximation too, exactly as if
    Heston had failed outright for it. This is a regression guard for a
    finding made while adversarially auditing this exact plan: an earlier
    draft of this fix cleared T3's artifact-floor check but then let the
    final display clamp silently overwrite its price while leaving the
    label as 'Heston repriced'."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    call_count = {"n": 0}

    def _fake(S, K, T, r, p, is_call):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 10.0  # T1: legitimate
        if call_count["n"] == 2:
            raise ValueError("integration failed")  # T2: genuinely unusable
        return 12.0  # T3: legitimate on its own, but below T2's fallback display

    monkeypatch.setattr(rr_module, "heston_price", _fake)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 10.0

    # T2: Heston raised -> delta approximation. Target price 207.5 > strike
    # 190 -> delta=0.5, price_move=22.5 -> 2.50 + 0.5*22.5 = 13.75.
    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 13.75

    # T3: raw Heston 12.0 clears the floor check against T1's 10.0, but is
    # still below T2's displayed 13.75 -> must fall back too, recomputed via
    # delta approximation (not merely clamped): target price 215 > strike
    # 190 -> delta=0.5, price_move=30 -> 2.50 + 0.5*30 = 17.5.
    assert targets[2].pricingMethod == "Delta approximation"
    assert targets[2].estimatedOptionPrice == 17.5


def test_estimate_targets_falls_back_when_both_floor_and_display_checks_fail(monkeypatch):
    """T3's raw Heston price (3.0) is BOTH an artifact relative to T1's true
    Heston price (10.0, so check 1 floors it to 10.0) AND, even after that
    flooring, still below T2's inflated genuine-failure display (13.75, so
    check 2 also fails). This exercises both of Task 1 Step 3's checks
    firing on the same level in the same iteration — the previous test only
    exercises the display check alone (its T3 raw price already clears the
    artifact floor unaided). Regression guard for a gap found while
    adversarially auditing this exact plan a second time: without this test,
    a future change that reorders or short-circuits the two checks could
    silently break this specific combination while every other test in this
    plan still passes."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    call_count = {"n": 0}

    def _fake(S, K, T, r, p, is_call):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return 10.0  # T1: legitimate
        if call_count["n"] == 2:
            raise ValueError("integration failed")  # T2: genuinely unusable
        return 3.0  # T3: artifact (below T1) that, even floored to T1, is still below T2's display

    monkeypatch.setattr(rr_module, "heston_price", _fake)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 10.0

    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 13.75

    # T3: raw 3.0 < prev_heston_price (10.0) -> floored to 10.0 by check 1.
    # 10.0 is still < prev_display_price (13.75) -> check 2 also fails ->
    # falls back to delta approximation: target 215 > strike 190 -> delta=0.5,
    # price_move=30 -> 2.50 + 0.5*30 = 17.5.
    assert targets[2].pricingMethod == "Delta approximation"
    assert targets[2].estimatedOptionPrice == 17.5


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


# ── Non-finite Heston output (NaN/inf) — scipy.integrate.quad can return these
# without raising, for the same pathological deep-OTM/long-dated integrands
# that produce the non-monotonic artifact tested above. Regression guard for
# an adversarial-audit finding that estimate_targets' opt_price <= 0 check is
# not NaN-safe (nan <= 0 is False in Python) and estimate_rr's > 0 check,
# while NaN-safe, is not inf-safe. ─────────────────────────────────────────────

def test_estimate_targets_falls_back_on_nan_heston_price(monkeypatch):
    """A NaN heston_price must fall back to delta approximation, not be
    labeled 'Heston repriced' with a null-serializing estimatedOptionPrice."""
    import math
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    monkeypatch.setattr(rr_module, "heston_price", lambda *a, **k: math.nan)

    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert all(t.pricingMethod == "Delta approximation" for t in targets)
    assert all(math.isfinite(t.estimatedOptionPrice) for t in targets)


def test_estimate_targets_falls_back_on_inf_heston_price(monkeypatch):
    """An +inf heston_price must also fall back — it passes the plain
    opt_price <= 0 check just like NaN would, but is equally unusable."""
    import math
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    monkeypatch.setattr(rr_module, "heston_price", lambda *a, **k: math.inf)

    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert all(t.pricingMethod == "Delta approximation" for t in targets)
    assert all(math.isfinite(t.estimatedOptionPrice) for t in targets)


def test_estimate_rr_falls_back_on_inf_heston_price(monkeypatch):
    """estimate_rr's heston_ok = heston_exit_premium > 0 is NaN-safe (nan > 0
    is False) but not inf-safe (inf > 0 is True) — an +inf Heston price would
    otherwise produce rr_ratio=inf, which round(inf, 2) preserves as inf and
    which is not valid JSON (serializes as the bareword `Infinity`), a real
    API-response risk. Must fall back to delta approximation instead."""
    import math
    import app.scoring.reward_risk as rr_module

    monkeypatch.setattr(rr_module, "heston_price", lambda *a, **k: math.inf)
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "Delta approximation"
    assert math.isfinite(rr.estimated_exit_premium)
    assert math.isfinite(rr.rr_ratio)


def test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact():
    """Reproduces round 3's adversarial-audit finding directly against the
    real (unmocked) heston_price(): with stock_price=318.73, strike=375,
    dte=185 (the deep-OTM/long-dated default fixture from
    test_trade_plan.py's _plan()), heston_price() returns a non-monotonic raw
    ladder — T1=12.518866931556794, T2=10.086141661385824 (an artifact dip),
    T3=14.081229812545331 (legitimate, verified directly against this repo's
    real pricer while writing this plan).

    Before this fix (confirmed by running the current code directly against
    this fixture): T2's dip switched it to the delta-approximation model,
    which computed 18.94 (higher than T1) — and T3's legitimate 14.08 was
    then compared against THAT inflated value, judged 'non-monotonic' too,
    and also discarded to delta-approximation (22.77). The displayed ladder
    was 12.52 / 18.94 / 22.77, with two of three levels wrongly switched off
    Heston.

    After this fix: T2 is floored to T1's true Heston price (12.52) and
    stays labelled Heston repriced. T3's raw price (14.08) is checked
    against T1's true Heston price (12.52), not T2's fallback — it clears
    that check and is preserved unmodified."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    targets = estimate_targets(
        stock_price=318.73, base_target_price=318.73 * 1.08, strike=375,
        expiry_years=185 / 365, current_premium=7.47, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    assert [t.pricingMethod for t in targets] == [
        "Heston repriced", "Heston repriced", "Heston repriced",
    ]
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices == [12.52, 12.52, 14.08]
    assert prices[0] <= prices[1] <= prices[2]


# ── Bearish / put Heston coverage — estimate_targets and estimate_rr had zero
# is_call=False coverage for any Heston code path (round 3 adversarial-audit
# finding #4). ──────────────────────────────────────────────────────────────

def test_estimate_targets_put_heston_ladder_happy_path():
    """A bearish/put ladder with no numerical artifact: all three levels
    price cleanly via Heston and the ladder is naturally non-decreasing.
    stock=185, base_target=170.2 (8% down), strike=170 -> target prices
    170.2/162.8/155.4, verified directly against the real pricer while
    writing this plan: 2.520609140512505 / 10.16028626218315 /
    20.778006605067873."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    targets = estimate_targets(
        stock_price=185, base_target_price=185 * 0.92, strike=170,
        expiry_years=30 / 365, current_premium=3.00, is_call=False,
        heston_params=params,
    )
    assert len(targets) == 3
    assert [t.pricingMethod for t in targets] == [
        "Heston repriced", "Heston repriced", "Heston repriced",
    ]
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices == [2.52, 10.16, 20.78]
    assert prices[0] <= prices[1] <= prices[2]


def test_estimate_targets_put_floors_non_monotonic_heston_price(monkeypatch):
    """Put-side mirror of
    test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models
    — confirms the fix is symmetric for puts, not just calls. Forces T2's raw
    Heston price down to an artifact (10.16 * 0.1 = 1.016, below T1's
    2.5206...) and confirms it floors to T1's price and stays 'Heston
    repriced', while T3's real price (20.78) is preserved."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    real_heston_price = rr_module.heston_price
    call_count = {"n": 0}

    def _flaky(S, K, T, r, p, is_call):
        call_count["n"] += 1
        price = real_heston_price(S, K, T, r, p, is_call)
        if call_count["n"] == 2:
            return price * 0.1
        return price

    monkeypatch.setattr(rr_module, "heston_price", _flaky)
    targets = estimate_targets(
        stock_price=185, base_target_price=185 * 0.92, strike=170,
        expiry_years=30 / 365, current_premium=3.00, is_call=False,
        heston_params=params,
    )
    assert len(targets) == 3
    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 2.52

    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 2.52

    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 20.78


def test_estimate_rr_put_heston_path_uses_correct_model_label():
    """Put-side mirror of test_heston_path_uses_correct_model_label /
    test_heston_path_returns_valid_ratio for estimate_rr — this function had
    zero is_call=False + heston_params coverage. Verified directly against
    the real pricer: exit_premium=14.18879567446055 -> reward=12.1888...,
    risk=2.00*0.60=1.20, rr=10.16."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=170, invalidation_price=195,
        strike=180, expiry_years=30 / 365, current_premium=2.00, is_call=False,
        heston_params=params,
    )
    assert rr.model_used == "Heston repriced"
    assert rr.estimated_exit_premium == 14.19
    assert rr.rr_ratio == 10.16


def test_estimate_targets_seeds_heston_reference_from_first_successful_level(monkeypatch):
    """prev_heston_price must be seeded from whichever level FIRST succeeds,
    not implicitly assumed to be T1. T1 itself fails here (raises), leaving
    prev_heston_price unset — T2 becomes the first real Heston reference.
    T3's raw price (5.0) is an artifact relative to T2's true price (15.9,
    not T1's delta-approximation fallback of 10.0, even though both are
    lower than T2) and must floor to T2's price, confirming the artifact
    check is anchored to the correct level."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    call_count = {"n": 0}

    def _fake(S, K, T, r, p, is_call):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("integration failed")  # T1: genuinely unusable
        if call_count["n"] == 2:
            return 15.9  # T2: first level to succeed
        return 5.0  # T3: artifact relative to T2's true price

    monkeypatch.setattr(rr_module, "heston_price", _fake)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    # T1: Heston raised -> delta approximation. Target price 200 > strike 190
    # -> delta=0.5, price_move=15 -> 2.50 + 0.5*15 = 10.0.
    assert targets[0].pricingMethod == "Delta approximation"
    assert targets[0].estimatedOptionPrice == 10.0

    # T2: first level to succeed -> becomes the Heston reference.
    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 15.9

    # T3: raw 5.0 is an artifact relative to T2's TRUE price (15.9), not
    # T1's delta-approximation fallback (10.0) -> floored to 15.9, stays
    # Heston repriced.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 15.9
