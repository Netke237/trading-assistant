"""Unit tests for app.scoring.reward_risk.estimate_rr()."""

import logging

import pytest

from app.scoring.reward_risk import estimate_rr, estimate_targets
from app.models.heston import HestonParams, HestonPrice


def _as_detail(fake_price):
    """Adapt a float-returning Heston price fake to heston_price_detail, the
    entry point reward_risk calls since DECISION-23 H-1: the same price with
    fell_back=False, and any exception raised unchanged."""
    def _detail(*args, **kwargs):
        return HestonPrice(price=fake_price(*args, **kwargs), fell_back=False)
    return _detail


# ── BS-fallback pricing (Heston unavailable) — call ───────────────────────────
# Formerly a flat delta*move guess; now a real Black-Scholes reprice using IV
# derived from the contract's own current quote (via bs_iv), at half the DTE
# (dte_at_target). The label was renamed from "Delta approximation" to
# "BS repriced (IV-derived)" to match — these tests were renamed from
# test_delta_approx_* because they test the fallback FORMULA itself, which
# is no longer a delta approximation.

def test_bs_fallback_call_above_strike():
    """Call, target(200) > strike(190). sigma derived from bs_iv(2.50, 185,
    190, 30/365, 0.05, True) = 0.200202 (converges). Repriced via bs_price at
    dte_at_target=15/365: exit=10.7388546688 -> 10.74. reward=8.238855,
    risk=2.50*0.60=1.50, rr=5.49. Verified directly against the real
    bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.model_used == "BS repriced (IV-derived)"
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == 3.30   # 8.238855 / 2.50 (was / 1.50 = 5.49)
    assert rr.estimated_exit_premium == 10.74


def test_bs_fallback_call_below_strike():
    """Call, target(188) < strike(190). sigma derived from bs_iv(1.00, 185,
    190, 30/365, 0.05, True) = 0.120547 (converges). exit=1.1465734530 ->
    1.15. reward=0.146573, risk=1.00*0.60=0.60, rr=0.24. Verified directly
    against the real bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=188, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=1.00, is_call=True,
    )
    assert rr.model_used == "BS repriced (IV-derived)"
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == 0.15   # 0.146573 / 1.00 (was / 0.60 = 0.24)
    assert rr.estimated_exit_premium == 1.15


# ── BS-fallback pricing (Heston unavailable) — put ────────────────────────────

def test_bs_fallback_put_below_strike():
    """Put, target(170) < strike(180). sigma derived from bs_iv(2.00, 185,
    180, 30/365, 0.05, False) = 0.205017 (converges). exit=9.9433742445 ->
    9.94. reward=7.943374, risk=2.00*0.60=1.20, rr=6.62. Verified directly
    against the real bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=170, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=2.00, is_call=False,
    )
    assert rr.model_used == "BS repriced (IV-derived)"
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == 3.97   # 7.943374 / 2.00 (was / 1.20 = 6.62)
    assert rr.estimated_exit_premium == 9.94


def test_bs_fallback_put_above_strike():
    """Put, target(185) == stock(185), strike(180) below both (OTM put).
    Unlike the old formula (which returned current_premium unchanged for
    zero price movement), the BS reprice happens at dte_at_target (half of
    expiry_years) -- a shorter time-to-expiry than the current quote's -- so
    even zero movement shows time decay: exit=0.4565739681, which is BELOW
    current_premium(1.00) -> reward=-0.543426. risk=1.00*0.60=0.60 ->
    rr=-0.543426/0.60=-0.91 (M2: negative reward's sign/magnitude is
    preserved, not flattened to 0.0). Verified directly against the real
    bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=1.00, is_call=False,
    )
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == -0.54   # -0.543426 / 1.00 (was / 0.60 = -0.91)
    assert rr.estimated_exit_premium == 0.46


# ── sigma_fallback constant (was dead code pre-fix) and the inner crude-guess
# safety net — both are edge-of-the-formula paths with no coverage above,
# since every test so far uses inputs where bs_iv converges and bs_price
# succeeds. Test the two private helpers directly rather than trying to
# reverse-engineer estimate_rr/estimate_targets inputs that happen to trigger
# them, since both are meant to be rare/defensive paths. ───────────────────────

def test_derive_fallback_sigma_uses_constant_when_bs_iv_cannot_converge():
    """stock=100/strike=90/premium=2.567 (call) is economically impossible —
    premium below intrinsic value (10) at those inputs — so bs_iv cannot
    converge to ANY volatility that reproduces it and returns None (verified
    directly: bs_iv(2.567, 100, 90, 30/365, 0.05, True) is None). This is the
    one case in this file that reaches the sigma_fallback branch, making the
    previously-dead sigma_fallback parameter actually load-bearing."""
    from app.scoring.reward_risk import _derive_fallback_sigma

    sigma = _derive_fallback_sigma(
        current_premium=2.567, stock_price=100, strike=90,
        expiry_years=30 / 365, r=0.05, is_call=True, sigma_fallback=0.25,
    )
    assert sigma == 0.25


def test_bs_reprice_or_delta_approx_falls_back_to_crude_guess_when_bs_price_unusable(monkeypatch):
    """If bs_price itself returns something unusable (non-finite or <=0 —
    documented as expected-unreachable in practice, but still a real code
    path this module ships), _bs_reprice_or_delta_approx must fall back to
    the crude flat-delta guess rather than propagate a bad price. Call,
    target(200) > strike(190) -> delta=0.5; price_move=|200-185|=15;
    current_premium=2.50 -> 2.50 + 0.5*15 = 10.0 (matches the pre-fix crude
    formula's own historical expected value for this exact fixture)."""
    import app.scoring.reward_risk as rr_module

    monkeypatch.setattr(rr_module, "bs_price", lambda *a, **k: 0.0)
    price, used_bs_reprice = rr_module._bs_reprice_or_delta_approx(
        t_price=200, stock_price=185, strike=190, dte_at_target=15 / 365,
        r=0.05, sigma=0.20, is_call=True, current_premium=2.50,
    )
    assert price == 10.0
    assert used_bs_reprice is False


def test_zero_price_movement_returns_zero_ratio():
    """target == stock_price (185). The BS-fallback reprice at
    dte_at_target (half of expiry_years) is time-decayed below
    current_premium (exit=1.2685575930 < 2.50) -> reward=-1.231442.
    risk=2.50*0.60=1.50 -> rr=-1.231442/1.50=-0.82 (M2: negative reward's
    sign/magnitude is preserved, not flattened to 0.0). Verified directly
    against the real bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == -0.49   # -1.231442 / 2.50 (was / 1.50 = -0.82)
    assert rr.estimated_exit_premium == 1.27


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
    assert rr.model_used == "BS repriced (IV-derived)"


def test_estimate_rr_uses_premium_stop_pct():
    """risk = current_premium * premium_stop_pct, so halving premium_stop_pct doubles rr_ratio.
    premium_stop_pct only affects risk, not exit_premium, so the doubling
    relationship holds regardless of which pricing formula produces
    exit_premium."""
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

    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: premium_stop_pct sets risk only with a protective stop order.
    result_60 = estimate_rr(**base_kwargs, premium_stop_pct=0.60, protective_stop_order=True)
    result_30 = estimate_rr(**base_kwargs, premium_stop_pct=0.30, protective_stop_order=True)

    # 0.30 stop_pct = half the risk basis → rr_ratio should be double
    assert result_60.rr_ratio > 0
    assert result_30.rr_ratio > 0
    # Allow floating-point tolerance
    assert abs(result_30.rr_ratio - result_60.rr_ratio * 2) < 0.05

    # Also verify the 0.60 case matches expected math: sigma derived from
    # bs_iv(2.00, 100, 100, 0.25, 0.05, True) = 0.064799 (converges).
    # exit_premium = bs_price(108, 100, 0.125, 0.05, 0.064799, True) =
    # 8.6231323590 -> 8.62; reward=6.623132; risk=1.20; rr=5.52. Verified
    # directly against the real bs_iv/bs_price.
    assert abs(result_60.rr_ratio - 5.52) < 0.01


def test_estimate_exit_premium_rounded_on_zero_reward():
    """estimated_exit_premium must round to 2 decimals even when reward is
    negative (M2: the reward<=0 early-return was removed, so this now flows
    through the normal division path -- but both paths always round
    estimated_exit_premium, so this still exercises that rounding).

    NOTE: this can no longer use a deep-ITM fixture (the old
    stock=100/strike=90/premium=2.567 combo) to force a negative reward.
    That premium is below the option's intrinsic value at those inputs (an
    economically impossible/arbitrage quote), so bs_iv cannot converge to
    ANY volatility that reproduces it -- it correctly falls back to
    sigma_fallback(0.25), which reprices well ABOVE the premium
    (exit=10.21), giving a POSITIVE reward -- defeating the point of this
    test. Using an OTM, zero-movement fixture instead (target==stock, strike
    above both) reliably produces a real, convergent, time-decayed reprice
    below current_premium, still exercising a negative-reward result -- and
    the resulting decayed exit_premium already has enough decimal digits
    (1.3112629983) to exercise the 2-decimal rounding on its own, without
    needing an artificially over-precise current_premium input.

    sigma derived from bs_iv(2.567, 185, 190, 30/365, 0.05, True) = 0.203581
    (converges). exit = bs_price(185, 190, 15/365, 0.05, 0.203581, True) =
    1.3112629983 -> 1.31, below current_premium(2.567) -> reward=-1.255737,
    risk=2.567*0.60=1.5402 -> rr=-1.255737/1.5402=-0.82. Verified directly
    against the real bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185.0, target_price=185.0, invalidation_price=175.0,
        strike=190.0, expiry_years=30 / 365, current_premium=2.567, is_call=True,
    )
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == -0.49   # -1.255737 / 2.567 (was / 1.5402 = -0.82)
    assert rr.estimated_exit_premium == 1.31


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
    assert rr.model_used == "BS repriced (IV-derived)"
    # Matches test_bs_fallback_call_above_strike's expected math exactly.
    assert rr.estimated_exit_premium == 10.74
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == 3.30


def test_heston_exception_falls_back_to_delta_approx(monkeypatch):
    """If heston_price() raises for any reason, estimate_rr must still return a
    usable delta-approximation result instead of propagating the exception."""
    import app.scoring.reward_risk as rr_module

    def _boom(*args, **kwargs):
        raise ValueError("integration failed")

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(_boom))
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "BS repriced (IV-derived)"
    assert rr.estimated_exit_premium == 10.74


def test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models(monkeypatch):
    """T1/T2/T3 share dte_at_target and only differ in the hypothetical stock
    price, so a correctly-priced option must be monotonically increasing
    across the ladder. A Heston price that comes out lower than the previous
    level's TRUE Heston price cannot be a real option value — it must be
    floored up to that true Heston reference and stay labelled 'Heston
    repriced', NOT be switched entirely
    to the cruder delta-approximation model. Switching models was the old
    behavior and is exactly what let a LATER level's legitimate Heston price
    get wrongly discarded too (see the next test): switching models replaces
    prev_opt_price with an inflated fallback value, so a subsequent level's
    genuinely correct Heston price can get judged 'non-monotonic' against
    that inflated reference instead of the true Heston chain."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    real_heston_price = rr_module.heston_price_detail
    call_count = {"n": 0}

    def _flaky(S, K, T, r, p, is_call):
        call_count["n"] += 1
        detail = real_heston_price(S, K, T, r, p, is_call)
        if call_count["n"] == 2:
            # simulate T2 coming back numerically too low
            return HestonPrice(price=detail.price * 0.1, fell_back=detail.fell_back)
        return detail

    monkeypatch.setattr(rr_module, "heston_price_detail", _flaky)
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    # The dip is FORCED by the monkeypatch above, deliberately: this fixture's
    # real ladder is monotonic. It used to dip on its own, but that was a
    # defect in heston_price's Fourier inversion (a doubled frequency,
    # 2i*phi*ln(S/K)) and not a property of the integration -- fixed in Phase
    # F1, see docs/superpowers/plans/2026-09-12-heston-calibration-spec.md.
    # Forcing it is now the only way to reach the floor, and is the right way
    # to test a floor regardless.
    # Raw ladder from the post-F1 pricer: 10.824772314194291 /
    # 17.96351814222973 / 25.399857193045563 (naturally monotonic; the
    # monkeypatch above is what forces T2's dip).
    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 10.82

    # T2's forced price (1.7963...) is the artifact — floored UP to T1's
    # price, and still labelled Heston repriced, not switched to delta
    # approximation.
    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 10.82

    # T3 raw = 25.399857193045563 — well above T1's price, so it is its own
    # legitimate, unfloored, unclamped Heston price.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 25.4


def test_ladder_floor_says_so_when_it_fires(monkeypatch, caplog):
    """Decision LADDER-FLOOR-LOG-2026-09-13. The floor only ever RAISES a
    level, so it cannot produce a too-low target and it stays. But F1 removed
    the one mechanism it was built to catch — the Fourier-inversion defect —
    so a dip reaching it now most likely means the pricer has REGRESSED, and a
    silent floor would quietly raise the number instead of surfacing it. That
    is a mask, not a guard.

    Spec section 6.3 says remove the floor only once F1 has run against live
    chains long enough to say the artifact never appears. This log line is the
    mechanism by which that evidence accumulates; without it there is nothing
    to read back off.

    WARNING rather than INFO is measured, not stylistic: under uvicorn's
    default logging config the root logger has no handler and sits at WARNING,
    so an `app.*` INFO record is dropped outright — see
    test_heston_calibration.py::
    test_boundary_log_is_warning_because_info_is_dropped_under_uvicorn.
    """
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    real_heston_price = rr_module.heston_price_detail
    call_count = {"n": 0}

    def _flaky(S, K, T, r, p, is_call):
        call_count["n"] += 1
        detail = real_heston_price(S, K, T, r, p, is_call)
        if call_count["n"] == 2:
            return HestonPrice(price=detail.price * 0.1, fell_back=detail.fell_back)
        return detail

    monkeypatch.setattr(rr_module, "heston_price_detail", _flaky)
    with caplog.at_level(logging.WARNING, logger="app.scoring.reward_risk"):
        targets = estimate_targets(
            stock_price=185, base_target_price=200, strike=190,
            expiry_years=30 / 365, current_premium=2.50, is_call=True,
            heston_params=params,
        )

    assert targets[1].estimatedOptionPrice == 10.82, (
        "fixture guard: the floor must actually have fired for this test to "
        "be testing anything"
    )
    floor_logs = [rec.getMessage() for rec in caplog.records
                  if "ladder dipped and was floored" in rec.getMessage()]
    assert len(floor_logs) == 1, (
        f"expected exactly one floor warning, got {len(floor_logs)}: {floor_logs}"
    )
    assert all(rec.levelno >= logging.WARNING for rec in caplog.records
               if "ladder dipped" in rec.getMessage())
    # The line has to identify WHICH contract and level dipped, or it cannot
    # be acted on when it turns up in a log a week later.
    assert "190.00 C" in floor_logs[0]
    assert "10.8247" in floor_logs[0] or "10.82" in floor_logs[0]


def test_clean_ladder_logs_nothing(monkeypatch, caplog):
    """The other half: on the real fixture the post-F1 ladder is naturally
    monotonic, so the floor must stay quiet. A line per clean ladder would
    bury the one that matters."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    with caplog.at_level(logging.WARNING, logger="app.scoring.reward_risk"):
        targets = estimate_targets(
            stock_price=185, base_target_price=200, strike=190,
            expiry_years=30 / 365, current_premium=2.50, is_call=True,
            heston_params=params,
        )

    assert [t.pricingMethod for t in targets] == ["Heston repriced"] * 3
    assert not [rec for rec in caplog.records
                if "ladder dipped" in rec.getMessage()]


def test_estimate_targets_clamps_delta_approx_fallback_to_prev_level(monkeypatch):
    """When Heston is genuinely unusable for a level (raises, here — not just
    numerically low), that level falls back to the BS-fallback reprice,
    which can itself undershoot the previous level's displayed price. The
    final display invariant must still clamp it up so the card never shows
    a decreasing ladder (code review finding on commit 80d8a6b, reproduced
    here) — this is unchanged by this task's fix, which only changes what
    happens when Heston SUCCEEDS but comes back numerically low (see the
    previous test).

    NOTE: T1/T3's mocked Heston values were raised from the pre-fix fixture
    (15.9/20.0) to (20.0/25.0). This is deliberate, not arbitrary: T2's real
    BS-fallback reprice for this fixture (target=207.5, strike=190,
    stock=185, current_premium=2.50, expiry=30/365) is 17.9269986203 --
    HIGHER than the old T1 mock (15.9), so with the old mock values the
    fallback would no longer need clamping at all, and this test would stop
    testing what its name says it tests. Raising T1 to 20.0 (above T2's
    real 17.93) restores the undershoot this test exists to cover, while
    T3's 25.0 preserves the original "own legitimate value, higher than
    both" role.

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
            return 20.0  # T1: legitimate, high
        if call_count["n"] == 2:
            raise ValueError("integration failed")  # T2: genuinely unusable
        return 25.0  # T3: legitimate, its own value

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(_fake))
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 20.0

    # T2: Heston raised, so BS-fallback reprice is used. sigma derived from
    # bs_iv(2.50, 185, 190, 30/365, 0.05, True) = 0.200202 (converges).
    # exit = bs_price(207.5, 190, 15/365, 0.05, 0.200202, True) =
    # 17.9269986203 -> 17.93, which undershoots T1's 20.0 -> clamped to
    # 20.0. Verified directly against the real bs_iv/bs_price.
    assert targets[1].pricingMethod == "BS repriced (IV-derived)"
    assert targets[1].estimatedOptionPrice == 20.0

    # T3: Heston succeeds with its own value (25.0), checked against T1's
    # true Heston price (20.0) — NOT T2's fallback. 25.0 >= 20.0, so it is
    # kept as-is, not floored.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 25.0


def test_estimate_targets_relabels_heston_price_still_below_inflated_prior_display(monkeypatch):
    """T3's raw Heston price (12.0) clears the artifact-floor check against
    T1's true Heston price (10.0) — it is NOT a numerical artifact. But T2
    had a genuine Heston failure and its BS-fallback reprice (17.93, real —
    see below) is itself above both T1's and T3's real Heston prices.
    Showing T3 as 'Heston repriced' would mean displaying a number (after
    the non-decreasing-display clamp) that Heston never actually produced
    for T3 — so T3 must fall back too, exactly as if Heston had failed
    outright for it. This is a regression guard against an implementation
    that only floors a level's price against the true Heston chain without
    also re-checking it against the actual displayed price: such an
    implementation would clear T3's artifact-floor check but then let the
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

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(_fake))
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

    # T2: Heston raised -> BS-fallback reprice. sigma derived from
    # bs_iv(2.50, 185, 190, 30/365, 0.05, True) = 0.200202 (converges,
    # cached for reuse on any later level that also needs the fallback).
    # exit = bs_price(207.5, 190, 15/365, 0.05, 0.200202, True) =
    # 17.9269986203 -> 17.93.
    assert targets[1].pricingMethod == "BS repriced (IV-derived)"
    assert targets[1].estimatedOptionPrice == 17.93

    # T3: raw Heston 12.0 clears the floor check against T1's 10.0, but is
    # still below T2's displayed 17.9269986203 (unrounded) -> must fall
    # back too, using the SAME cached sigma (0.200202) as T2: exit =
    # bs_price(215, 190, 15/365, 0.05, 0.200202, True) = 25.3922282437 ->
    # 25.39. Verified directly against the real bs_iv/bs_price."""
    assert targets[2].pricingMethod == "BS repriced (IV-derived)"
    assert targets[2].estimatedOptionPrice == 25.39


def test_estimate_targets_falls_back_when_both_floor_and_display_checks_fail(monkeypatch):
    """T3's raw Heston price (3.0) is BOTH an artifact relative to T1's true
    Heston price (10.0, so check 1 floors it to 10.0) AND, even after that
    flooring, still below T2's inflated genuine-failure display (17.93, so
    check 2 also fails). This exercises both the artifact-floor check and
    the display-consistency check firing on the same level in the same
    iteration — the previous test only exercises the display check alone
    (its T3 raw price already clears the artifact floor unaided). Regression
    guard against a future change that reorders or short-circuits the two
    checks: every other test in this file exercises at most one of them per
    level and would not catch a regression that silently breaks this
    specific combination."""
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

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(_fake))
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

    # T2: same BS-fallback reprice as the previous test's T2: 17.93.
    assert targets[1].pricingMethod == "BS repriced (IV-derived)"
    assert targets[1].estimatedOptionPrice == 17.93

    # T3: raw 3.0 < prev_heston_price (10.0) -> floored to 10.0 by check 1.
    # 10.0 is still < prev_display_price (17.9269986203, unrounded) -> check
    # 2 also fails -> falls back to the BS-fallback reprice using the same
    # cached sigma: exit = bs_price(215, 190, 15/365, 0.05, 0.200202, True)
    # = 25.3922282437 -> 25.39.
    assert targets[2].pricingMethod == "BS repriced (IV-derived)"
    assert targets[2].estimatedOptionPrice == 25.39


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
        # Re-pinned by TRADING-REVIEW-PHASE-C-RR: premium_stop_pct sets risk only with a protective stop order.
        protective_stop_order=True,
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
    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(lambda *a, **k: math.nan))

    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert all(t.pricingMethod == "BS repriced (IV-derived)" for t in targets)
    assert all(math.isfinite(t.estimatedOptionPrice) for t in targets)


def test_estimate_targets_falls_back_on_inf_heston_price(monkeypatch):
    """An +inf heston_price must also fall back — it passes the plain
    opt_price <= 0 check just like NaN would, but is equally unusable."""
    import math
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(lambda *a, **k: math.inf))

    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert all(t.pricingMethod == "BS repriced (IV-derived)" for t in targets)
    assert all(math.isfinite(t.estimatedOptionPrice) for t in targets)


def test_estimate_rr_falls_back_on_inf_heston_price(monkeypatch):
    """estimate_rr's heston_ok = heston_exit_premium > 0 is NaN-safe (nan > 0
    is False) but not inf-safe (inf > 0 is True) — an +inf Heston price would
    otherwise produce rr_ratio=inf, which round(inf, 2) preserves as inf and
    which is not valid JSON (serializes as the bareword `Infinity`), a real
    API-response risk. Must fall back to delta approximation instead."""
    import math
    import app.scoring.reward_risk as rr_module

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(lambda *a, **k: math.inf))
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=200, invalidation_price=175,
        strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert rr.model_used == "BS repriced (IV-derived)"
    assert math.isfinite(rr.estimated_exit_premium)
    assert math.isfinite(rr.rr_ratio)


def test_estimate_targets_real_fixture_ladder_is_clean_and_all_heston():
    """The real, unmocked end-to-end ladder on the deep-OTM/long-dated fixture
    from test_trade_plan.py's _plan() (stock_price=318.73, strike=375,
    dte=185): every level prices via Heston, nothing is floored, nothing is
    switched to a cruder model.

    RENAMED AND REWRITTEN BY PHASE F1 (2026-09-12). This test used to be
    called ..._preserves_t3_after_t2_artifact and asserted the ladder
    12.52 / 12.52 / 14.08 — a T1 of 12.52 with a T2 raw dip to 10.09 that the
    floor had to lift. Its premise was that the dip was an inherent artifact
    of heston_price()'s numerical integration on deep-OTM/long-dated inputs.
    It was not: it was a defect in heston_price's Fourier inversion (a doubled
    frequency, 2i*phi*ln(S/K)), documented and fixed in
    docs/superpowers/plans/2026-09-12-heston-calibration-spec.md. With the
    pricer corrected THIS FIXTURE NO LONGER PRODUCES AN ARTIFACT AT ALL —
    its raw ladder is 3.7974079293070417 / 8.036117572871689 /
    14.235827351674061, strictly increasing — so there is nothing here for
    the floor to catch and the test's original assertion was unstateable.

    What it covers now is the clean-path invariant: a correct ladder survives
    estimate_targets untouched and fully labelled. The
    artifact-preservation behaviour it used to cover is covered by the two
    monkeypatched _flaky tests above and below, which force the dip
    deliberately — the right way to test a floor, since it does not depend on
    the pricer having a bug.

    Note the magnitude: T1 fell from 12.52 to 3.80. That is the same
    correction that flips this fixture's R/R from +1.13 to -0.82, i.e. from a
    recommendation to a rejection."""
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
    assert prices == [3.8, 8.04, 14.24]
    # Strictly increasing, not merely non-decreasing: no level was floored to
    # equal its predecessor. If this ever loosens to an equality, the floor
    # has started firing on this fixture again and the pricer has regressed.
    assert prices[0] < prices[1] < prices[2]


# ── Bearish / put Heston coverage — estimate_targets and estimate_rr had zero
# is_call=False coverage for any Heston code path before this; the ladder's
# direction/delta logic branches on is_call, so the fix above must hold for
# puts too, not just calls. ──────────────────────────────────────────────────

def test_estimate_targets_put_heston_ladder_happy_path():
    """A bearish/put ladder with no numerical artifact: all three levels
    price cleanly via Heston and the ladder is naturally non-decreasing.
    stock=185, base_target=170.2 (8% down), strike=170 -> target prices
    170.2/162.8/155.4, verified directly against the real (post-F1) pricer:
    2.482195855028408 / 7.3048502293854085 / 14.264581837656351."""
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
    assert prices == [2.48, 7.3, 14.26]
    assert prices[0] <= prices[1] <= prices[2]


def test_estimate_targets_put_floors_non_monotonic_heston_price(monkeypatch):
    """Put-side mirror of
    test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models
    — confirms the fix is symmetric for puts, not just calls. Forces T2's raw
    Heston price down to an artifact (7.3048... * 0.1 = 0.7305, below T1's
    2.4822...) and confirms it floors to T1's price and stays 'Heston
    repriced', while T3's real price (14.26) is preserved."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    real_heston_price = rr_module.heston_price_detail
    call_count = {"n": 0}

    def _flaky(S, K, T, r, p, is_call):
        call_count["n"] += 1
        detail = real_heston_price(S, K, T, r, p, is_call)
        if call_count["n"] == 2:
            return HestonPrice(price=detail.price * 0.1, fell_back=detail.fell_back)
        return detail

    monkeypatch.setattr(rr_module, "heston_price_detail", _flaky)
    targets = estimate_targets(
        stock_price=185, base_target_price=185 * 0.92, strike=170,
        expiry_years=30 / 365, current_premium=3.00, is_call=False,
        heston_params=params,
    )
    assert len(targets) == 3
    assert targets[0].pricingMethod == "Heston repriced"
    assert targets[0].estimatedOptionPrice == 2.48

    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 2.48

    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 14.26


def test_estimate_rr_put_heston_path_uses_correct_model_label():
    """Put-side mirror of test_heston_path_uses_correct_model_label /
    test_heston_path_returns_valid_ratio for estimate_rr — this function had
    zero is_call=False + heston_params coverage. Verified directly against
    the real (post-F1) pricer: exit_premium=9.835517234566083 ->
    reward=7.8355..., risk=2.00*0.60=1.20, rr=6.53.

    NOTE: this test was NOT listed in the F1 spec's section 5.3 table of
    pinned ladder assertions (which named four; this is a fifth). It pins an
    exact heston_price output just as they do and moved for the same
    reason."""
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    rr = estimate_rr(
        stock_price=185, target_price=170, invalidation_price=195,
        strike=180, expiry_years=30 / 365, current_premium=2.00, is_call=False,
        heston_params=params,
    )
    assert rr.model_used == "Heston repriced"
    assert rr.estimated_exit_premium == 9.84
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == 3.92   # 7.835517 / 2.00 (was / 1.20 = 6.53)


def test_estimate_targets_seeds_heston_reference_from_first_successful_level(monkeypatch):
    """prev_heston_price must be seeded from whichever level FIRST succeeds,
    not implicitly assumed to be T1. T1 itself fails here (raises), leaving
    prev_heston_price unset — T2 becomes the first real Heston reference.

    NOTE ON THE NUMBERS: heston_price is fully STUBBED in this test (_fake
    below returns hardcoded values), so 15.9 and 12.0 are stub constants, not
    pricer output -- Phase F1 changed what the real pricer returns here
    (10.82 at this ladder point) and deliberately did NOT touch these, because
    this test is about which value prev_heston_price is anchored to, not about
    any price being right.

    T3's stub price (12.0) is deliberately chosen strictly between T1's
    BS-fallback reprice (10.7388546688, real -- see below) and T2's stubbed
    Heston price (15.9), rather than below both, so this test can actually
    tell "anchored to T2" apart from "still anchored to T1's stale
    fallback": if prev_heston_price were incorrectly seeded from T1's
    fallback value and never properly overwritten when T2 succeeds, T3's
    12.0 would clear that stale ~10.74 floor unchecked, then fail the
    display-consistency check against the ladder's actual displayed price
    (15.9, from T2) and surface as 'BS repriced (IV-derived)' at a recomputed
    fallback value instead of correctly flooring to T2's true price and
    staying 'Heston repriced' at 15.9."""
    import app.scoring.reward_risk as rr_module

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    call_count = {"n": 0}

    def _fake(S, K, T, r, p, is_call):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValueError("integration failed")  # T1: genuinely unusable
        if call_count["n"] == 2:
            return 15.9  # T2: first level to succeed (a stub, not a real price)
        # T3: a dip relative to T2's stubbed price, chosen strictly between
        # T1's fallback (~10.74) and T2's stub (15.9) so this test can
        # actually distinguish the two
        return 12.0

    monkeypatch.setattr(rr_module, "heston_price_detail", _as_detail(_fake))
    targets = estimate_targets(
        stock_price=185, base_target_price=200, strike=190,
        expiry_years=30 / 365, current_premium=2.50, is_call=True,
        heston_params=params,
    )
    assert len(targets) == 3
    prices = [t.estimatedOptionPrice for t in targets]
    assert prices[0] <= prices[1] <= prices[2], f"ladder not non-decreasing: {prices}"

    # T1: Heston raised -> BS-fallback reprice (first fallback in this
    # ladder, so sigma is derived here). sigma from bs_iv(2.50, 185, 190,
    # 30/365, 0.05, True) = 0.200202 (converges). exit = bs_price(200, 190,
    # 15/365, 0.05, 0.200202, True) = 10.7388546688 -> 10.74. Verified
    # directly against the real bs_iv/bs_price (matches
    # test_bs_fallback_call_above_strike's fixture exactly).
    assert targets[0].pricingMethod == "BS repriced (IV-derived)"
    assert targets[0].estimatedOptionPrice == 10.74

    # T2: first level to succeed -> becomes the Heston reference.
    assert targets[1].pricingMethod == "Heston repriced"
    assert targets[1].estimatedOptionPrice == 15.9

    # T3: raw 12.0 sits strictly between T1's BS-fallback reprice (10.74)
    # and T2's TRUE price (15.9) -> only a floor correctly anchored to T2
    # forces this to 15.9; a floor still anchored to T1's stale fallback
    # would let 12.0 clear that floor unchecked, then fail the
    # display-consistency check against the ladder's actual displayed price.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 15.9


# ── M2: negative reward must preserve sign/magnitude, not clamp to 0.0 ───────

def test_negative_reward_preserves_sign_deterministic():
    """Deterministic: monkeypatch heston_price to force reward < 0. A repriced exit
    premium below current premium (e.g. IV crush outweighing the directional move)
    must produce a negative rr_ratio proportional to the loss, not a flattened 0.0."""
    import unittest.mock as mock
    from app.scoring.reward_risk import estimate_rr

    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    with mock.patch("app.scoring.reward_risk.heston_price_detail",
                    return_value=HestonPrice(price=3.00, fell_back=False)):
        rr = estimate_rr(
            stock_price=100.0, target_price=105.0, invalidation_price=95.0,
            strike=100.0, expiry_years=0.25, current_premium=5.00, is_call=True,
            heston_params=params, premium_stop_pct=0.60,
        )
    # exit=3.00, reward=-2.00, risk=5.00 (full premium), rr=-0.40
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    assert rr.rr_ratio == -0.40
    assert rr.estimated_exit_premium == 3.00


def test_risk_zero_still_clamps_to_zero_not_negative():
    """risk<=0 (e.g. premium_stop_pct=0) must still clamp to 0.0 — only the reward<=0
    path changed (removed), not the risk<=0 path."""
    from app.scoring.reward_risk import estimate_rr
    rr = estimate_rr(
        stock_price=100.0, target_price=90.0, invalidation_price=110.0,
        strike=100.0, expiry_years=0.25, current_premium=2.00, is_call=True,
        premium_stop_pct=0.0,
        # Re-pinned by TRADING-REVIEW-PHASE-C-RR: premium_stop_pct sets risk only with a protective stop order.
        protective_stop_order=True,
    )
    assert rr.rr_ratio == 0.0


def test_estimate_targets_preserves_negative_rr_contribution():
    """Sibling fix to M2: estimate_targets' rrContribution must not flatten a
    negative-reward target level to 0.0 — same fix as estimate_rr, same file."""
    import unittest.mock as mock
    from app.scoring.reward_risk import estimate_targets

    with mock.patch("app.scoring.reward_risk.heston_price_detail",
                    return_value=HestonPrice(price=3.00, fell_back=False)):
        results = estimate_targets(
            stock_price=100.0, base_target_price=105.0,
            strike=100.0, expiry_years=0.25, current_premium=5.00, is_call=True,
            heston_params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            premium_stop_pct=0.60,
        )
    # opt_price stubbed to 3.00 for every target level via heston_price mock;
    # reward = 3.00 - 5.00 = -2.00, risk_basis = 5.00 (full premium), rr = -0.40
    # Re-pinned by TRADING-REVIEW-PHASE-C-RR: risk is the full premium (no protective stop order), was premium x 0.60.
    for level in results:
        assert level.rrContribution == -0.40, (
            f"expected -0.40 (real negative ratio), got {level.rrContribution} — "
            "rrContribution must not clamp negative reward to 0.0"
        )


# ── DECISION-23 H-1: a Heston fallback is never labelled "Heston repriced" ────
# heston_price_detail returns Black-Scholes at sqrt(v0) with fell_back=True
# when the integration fails arithmetically. That number is not a Heston
# price, so both call sites must take their existing non-Heston path -- the
# same label and number as heston_params=None -- instead of showing it as
# "Heston repriced" (G2 in the H-1 plan).

_H1_PARAMS = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)

# (estimate_rr kwargs) for a call and a put fixture already used above.
_H1_RR_CASES = [
    dict(stock_price=185, target_price=200, invalidation_price=175,
         strike=190, expiry_years=30 / 365, current_premium=2.50, is_call=True),
    dict(stock_price=185, target_price=170, invalidation_price=195,
         strike=180, expiry_years=30 / 365, current_premium=2.00, is_call=False),
]
_H1_LADDER_CASES = [
    dict(stock_price=185, base_target_price=200, strike=190,
         expiry_years=30 / 365, current_premium=2.50, is_call=True),
    dict(stock_price=185, base_target_price=185 * 0.92, strike=170,
         expiry_years=30 / 365, current_premium=3.00, is_call=False),
]


def _force_integration_error(exc_type):
    """Make the REAL pricer's integration raise `exc_type`. ZeroDivisionError
    is what the integrand can raise (a zero complex denominator), so
    heston_price_detail takes its genuine fallback branch; TypeError is a bug,
    which now propagates out of the pricer and must be caught by the call
    site's own try/except."""
    def _force(monkeypatch):
        import types
        import app.models.heston as heston_module

        def _quad(*args, **kwargs):
            raise exc_type("forced integration failure")

        monkeypatch.setattr(heston_module, "integrate", types.SimpleNamespace(quad=_quad))
    return _force


def _force_flagged_fallback_price(monkeypatch, price=12.34):
    """A positive, finite price that is flagged fell_back=True: only the flag
    says it is not a Heston price."""
    import app.scoring.reward_risk as rr_module

    monkeypatch.setattr(rr_module, "heston_price_detail",
                        lambda *a, **k: HestonPrice(price=price, fell_back=True))


_H1_FORCES = [_force_integration_error(ZeroDivisionError),
              _force_integration_error(TypeError),
              _force_flagged_fallback_price]
_H1_FORCE_IDS = ["zero_division", "type_error", "flagged_fell_back"]


@pytest.mark.parametrize("case", _H1_RR_CASES, ids=["call", "put"])
@pytest.mark.parametrize("force", _H1_FORCES, ids=_H1_FORCE_IDS)
def test_estimate_rr_heston_fallback_is_not_labelled_heston(monkeypatch, case, force):
    baseline = estimate_rr(**case, heston_params=None)
    force(monkeypatch)
    rr = estimate_rr(**case, heston_params=_H1_PARAMS)

    assert rr.model_used != "Heston repriced"
    assert rr == baseline


@pytest.mark.parametrize("case", _H1_LADDER_CASES, ids=["call", "put"])
@pytest.mark.parametrize("force", _H1_FORCES, ids=_H1_FORCE_IDS)
def test_estimate_targets_heston_fallback_is_not_labelled_heston(monkeypatch, case, force):
    baseline = estimate_targets(**case, heston_params=None)
    force(monkeypatch)
    targets = estimate_targets(**case, heston_params=_H1_PARAMS)

    assert all(t.pricingMethod != "Heston repriced" for t in targets)
    assert [t.model_dump() for t in targets] == [t.model_dump() for t in baseline]
