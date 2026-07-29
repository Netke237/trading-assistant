# Real IV-Driven Fallback Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crude linear delta-guess fallback in `estimate_rr`/`estimate_targets` (used when Heston pricing is unavailable) with a real Black-Scholes reprice, driven by the contract's own market-implied volatility, making the currently-dead `sigma_fallback` parameter a live emergency default.

**Architecture:** Two new private helpers in `backend/app/scoring/reward_risk.py` — `_derive_fallback_sigma` (backs out IV from the contract's current quote via `bs_iv`, falling back to the `sigma_fallback` constant if that fails to converge) and `_bs_reprice_or_delta_approx` (reprices via `bs_price` using that sigma, falling back to the original crude delta guess only if `bs_price` itself is unusable). Both `estimate_rr` and `estimate_targets` call these instead of computing the crude guess inline. `estimate_targets` derives the fallback sigma lazily — once per ladder, on whichever level first needs it — and reuses it for any later level that also needs the fallback, since the underlying contract's quote doesn't change across T1/T2/T3.

**Tech Stack:** Python, pytest. Uses `app.models.black_scholes.bs_iv` / `bs_price` (already exist, unmodified).

**Full design reference:** `docs/superpowers/specs/2026-07-29-heston-fallback-real-iv-pricing-design.md`

**Important context for whoever implements this:** every new numeric expected value below was computed by actually running the exact formula this plan implements against `backend/app/models/black_scholes.py`'s real `bs_iv`/`bs_price` (not estimated by hand) — the same "verified directly against the real pricer" convention this test file already uses for its Heston fixtures. If your implementation produces a different number than what's written here, that's a signal your code doesn't match the design, not that the expected value is wrong — re-check against the design in `docs/superpowers/specs/2026-07-29-heston-fallback-real-iv-pricing-design.md` before changing an assertion.

---

### Task 1: Add BS-fallback helpers, wire into `estimate_rr`, update its tests

**Files:**
- Modify: `backend/app/scoring/reward_risk.py:1-68` (imports, new helpers, `estimate_rr` body)
- Test: `backend/tests/test_reward_risk.py:1-192` (existing `estimate_rr`-only tests)

- [ ] **Step 1: Update the failing/changed tests in `test_reward_risk.py`**

Replace lines 1–53 (imports through the end of the "Delta approximation — put" section) with:

```python
"""Unit tests for app.scoring.reward_risk.estimate_rr()."""

from app.scoring.reward_risk import estimate_rr, estimate_targets
from app.models.heston import HestonParams


# ── BS-fallback pricing (Heston unavailable) — call ───────────────────────────
# Formerly a flat delta*move guess; now a real Black-Scholes reprice using IV
# derived from the contract's own current quote (via bs_iv), at half the DTE
# (dte_at_target). The "Delta approximation" label is unchanged — it still
# means "the non-Heston tier" from the API's perspective — but these tests
# were renamed from test_delta_approx_* because they test the fallback
# FORMULA itself, which is no longer a delta approximation.

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
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 5.49
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
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 0.24


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
    assert rr.model_used == "Delta approximation"
    assert rr.rr_ratio == 6.62
    assert rr.estimated_exit_premium == 9.94


def test_bs_fallback_put_above_strike():
    """Put, target(185) == stock(185), strike(180) below both (OTM put).
    Unlike the old formula (which returned current_premium unchanged for
    zero price movement), the BS reprice happens at dte_at_target (half of
    expiry_years) -- a shorter time-to-expiry than the current quote's -- so
    even zero movement shows time decay: exit=0.4565739681, which is BELOW
    current_premium(1.00) -> reward=-0.543426 <= 0 -> rr_ratio=0.0 via the
    early-return guard (same final ratio as before this fix, reached for a
    different, more honest reason). Verified directly against the real
    bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=195,
        strike=180, expiry_years=30/365, current_premium=1.00, is_call=False,
    )
    assert rr.rr_ratio == 0.0
```

Now update `test_zero_price_movement_returns_zero_ratio` (originally at old line 58-64). Find:

```python
def test_zero_price_movement_returns_zero_ratio():
    """target == stock_price → price_move=0 → reward=0 → rr_ratio=0.0."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.rr_ratio == 0.0
```

Replace with:

```python
def test_zero_price_movement_returns_zero_ratio():
    """target == stock_price (185). The BS-fallback reprice at
    dte_at_target (half of expiry_years) is time-decayed below
    current_premium (exit=1.2685575930 < 2.50) -> reward=-1.231442 <= 0 ->
    rr_ratio=0.0 via the early-return guard. Verified directly against the
    real bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185, target_price=185, invalidation_price=175,
        strike=190, expiry_years=30/365, current_premium=2.50, is_call=True,
    )
    assert rr.rr_ratio == 0.0
```

`test_zero_premium_returns_zero_ratio` and `test_exit_premium_floored_at_0_01` (old lines 67-84) are unchanged — leave them exactly as they are. They only assert `rr_ratio == 0.0` / `estimated_exit_premium >= 0.01`, both of which still hold under the new formula (verified directly: `risk <= 0` still forces `rr_ratio == 0.0` regardless of `exit_premium`'s value when `current_premium == 0`; the deep-OTM/short-dated floored case still floors to `0.01`).

Now update `test_estimate_rr_uses_premium_stop_pct` (old lines 119-144). Find:

```python
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
```

Replace with:

```python
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

    result_60 = estimate_rr(**base_kwargs, premium_stop_pct=0.60)
    result_30 = estimate_rr(**base_kwargs, premium_stop_pct=0.30)

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
```

Now update `test_estimate_exit_premium_rounded_on_zero_reward` (old lines 147-156). Find:

```python
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
```

Replace with:

```python
def test_estimate_exit_premium_rounded_on_zero_reward():
    """The early-return (zero-reward) path must round estimated_exit_premium
    to 2 decimals, matching the success path.

    NOTE: this can no longer use a deep-ITM fixture (the old
    stock=100/strike=90/premium=2.567 combo) to force the early-return path.
    That premium is below the option's intrinsic value at those inputs (an
    economically impossible/arbitrage quote), so bs_iv cannot converge to
    ANY volatility that reproduces it -- it correctly falls back to
    sigma_fallback(0.25), which reprices well ABOVE the premium
    (exit=10.21), giving a POSITIVE reward and skipping the early-return
    path entirely -- defeating the point of this test. Using an OTM,
    zero-movement fixture instead (target==stock, strike above both)
    reliably produces a real, convergent, time-decayed reprice below
    current_premium, still exercising the early-return path -- and the
    resulting decayed exit_premium already has enough decimal digits
    (1.3112629983) to exercise the 2-decimal rounding on its own, without
    needing an artificially over-precise current_premium input.

    sigma derived from bs_iv(2.567, 185, 190, 30/365, 0.05, True) = 0.203581
    (converges). exit = bs_price(185, 190, 15/365, 0.05, 0.203581, True) =
    1.3112629983 -> 1.31, below current_premium(2.567) -> reward=-1.255737
    <= 0 -> early return. Verified directly against the real
    bs_iv/bs_price."""
    rr = estimate_rr(
        stock_price=185.0, target_price=185.0, invalidation_price=175.0,
        strike=190.0, expiry_years=30 / 365, current_premium=2.567, is_call=True,
    )
    assert rr.rr_ratio == 0.0
    assert rr.estimated_exit_premium == 1.31
```

Now update `test_heston_degenerate_price_falls_back_to_delta_approx` (old lines 159-173). Find:

```python
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
```

Replace with:

```python
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
    # Matches test_bs_fallback_call_above_strike's expected math exactly.
    assert rr.estimated_exit_premium == 10.74
    assert rr.rr_ratio == 5.49
```

Now update `test_heston_exception_falls_back_to_delta_approx` (old lines 176-192). Find:

```python
    assert rr.model_used == "Delta approximation"
    assert rr.estimated_exit_premium == 10.0


def test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models(monkeypatch):
```

Replace with:

```python
    assert rr.model_used == "Delta approximation"
    assert rr.estimated_exit_premium == 10.74


def test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models(monkeypatch):
```

- [ ] **Step 2: Run the updated tests to confirm they fail against the OLD implementation**

Run: `cd backend && venv\Scripts\python.exe -m pytest tests/test_reward_risk.py -k "bs_fallback or zero_price_movement or premium_stop_pct or rounded_on_zero_reward or heston_degenerate or heston_exception" -v`

Expected: Several FAIL (new expected values don't match the old crude-delta-guess implementation; `test_bs_fallback_put_above_strike` and `test_zero_price_movement_returns_zero_ratio` may coincidentally PASS since `rr_ratio == 0.0` is unchanged — that's fine, they're still correctly written for the new behavior).

- [ ] **Step 3: Implement the helpers and rewire `estimate_rr` in `reward_risk.py`**

Replace lines 1-68 of `backend/app/scoring/reward_risk.py` (from the top of the file through the end of `estimate_rr`) with:

```python
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

from app.models.heston import HestonParams, heston_price
from app.models.black_scholes import bs_iv, bs_price

RrModel = Literal["Heston repriced", "Delta approximation"]


@dataclass
class RrResult:
    rr_ratio: float
    model_used: RrModel
    estimated_exit_premium: float


def _derive_fallback_sigma(
    current_premium: float,
    stock_price: float,
    strike: float,
    expiry_years: float,
    r: float,
    is_call: bool,
    sigma_fallback: float,
) -> float:
    """Back out the contract's own market-implied vol from its current quote
    (at the full time-to-expiry the quote was made at, expiry_years). Falls
    back to sigma_fallback when bs_iv can't converge (e.g. degenerate or
    extreme-moneyness quotes)."""
    sigma = bs_iv(current_premium, stock_price, strike, expiry_years, r, is_call)
    return sigma if sigma is not None else sigma_fallback


def _bs_reprice_or_delta_approx(
    t_price: float,
    stock_price: float,
    strike: float,
    dte_at_target: float,
    r: float,
    sigma: float,
    is_call: bool,
    current_premium: float,
) -> float:
    """Reprice at t_price via Black-Scholes using the given sigma. Falls back
    to the crude flat-delta guess (the pre-fix behavior) only if bs_price
    itself is unusable — kept as a last-resort safety net, though expected
    to be effectively unreachable given callers already validate T > 0 and
    S, K > 0."""
    price = bs_price(t_price, strike, dte_at_target, r, sigma, is_call)
    if math.isfinite(price) and price > 0:
        return price
    delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
    price_move = abs(t_price - stock_price)
    return current_premium + delta * price_move


def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,   # reserved: kept for call-site symmetry; risk is now premium * premium_stop_pct, not invalidation-based
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,   # fraction of premium at risk (stop-loss basis)
) -> RrResult:
    model_used: RrModel
    heston_ok = False
    dte_at_target = max(expiry_years * 0.5, 7 / 365)

    if heston_params is not None:
        try:
            heston_exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)
        except Exception:
            heston_exit_premium = 0.0
        heston_ok = math.isfinite(heston_exit_premium) and heston_exit_premium > 0

    if heston_ok:
        exit_premium = heston_exit_premium
        model_used = "Heston repriced"
    else:
        sigma = _derive_fallback_sigma(current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback)
        exit_premium = _bs_reprice_or_delta_approx(
            target_price, stock_price, strike, dte_at_target, r, sigma, is_call, current_premium,
        )
        model_used = "Delta approximation"

    exit_premium = max(exit_premium, 0.01)

    risk = current_premium * premium_stop_pct   # only risk the stop-loss fraction
    reward = exit_premium - current_premium

    if reward <= 0 or risk <= 0:
        return RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=round(exit_premium, 2))

    rr_ratio = round(reward / risk, 2)
    return RrResult(
        rr_ratio=rr_ratio,
        model_used=model_used,
        estimated_exit_premium=round(exit_premium, 2),
    )
```

(This changes one structural detail beyond the fallback branch itself: `dte_at_target` is now computed unconditionally at the top of the function, since the fallback branch needs it too — previously it was only computed inside `if heston_params is not None:`. Same formula, same value, no behavior change for the Heston branch.)

- [ ] **Step 4: Run the full test file to confirm Task 1's tests pass and nothing else in the file broke**

Run: `cd backend && venv\Scripts\python.exe -m pytest tests/test_reward_risk.py -v`

Expected: ALL tests in the file PASS. The tests touched in Step 1 now pass against the new `estimate_rr`. The four `estimate_targets` fallback-tier tests (`test_estimate_targets_clamps_delta_approx_fallback_to_prev_level`, `test_estimate_targets_relabels_heston_price_still_below_inflated_prior_display`, `test_estimate_targets_falls_back_when_both_floor_and_display_checks_fail`, `test_estimate_targets_seeds_heston_reference_from_first_successful_level`) are UNCHANGED in this task (still old test code, old values) and `estimate_targets` itself is also unchanged (still the old crude-delta-guess code) — old test code paired with old implementation, so they still pass consistently. They get updated together in Task 2.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/reward_risk.py backend/tests/test_reward_risk.py
git commit -m "feat(reward-risk): derive real IV for estimate_rr's fallback pricing

Replaces the crude flat delta*move guess with a Black-Scholes reprice
using the contract's own market-implied vol (backed out via bs_iv from
its current quote), falling back to the sigma_fallback constant (now
actually used) and then the original crude guess if BS pricing is
unusable. estimate_targets is updated in the next commit."
```

---

### Task 2: Wire the same helpers into `estimate_targets`, update its tests

**Files:**
- Modify: `backend/app/scoring/reward_risk.py` (the `estimate_targets` loop body — helpers from Task 1 are reused, not redefined)
- Test: `backend/tests/test_reward_risk.py` (the four `estimate_targets` fallback-tier tests)

- [ ] **Step 1: Update the four affected tests**

Find `test_estimate_targets_clamps_delta_approx_fallback_to_prev_level` and replace its whole body with:

```python
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
    assert targets[0].estimatedOptionPrice == 20.0

    # T2: Heston raised, so BS-fallback reprice is used. sigma derived from
    # bs_iv(2.50, 185, 190, 30/365, 0.05, True) = 0.200202 (converges).
    # exit = bs_price(207.5, 190, 15/365, 0.05, 0.200202, True) =
    # 17.9269986203 -> 17.93, which undershoots T1's 20.0 -> clamped to
    # 20.0. Verified directly against the real bs_iv/bs_price.
    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 20.0

    # T3: Heston succeeds with its own value (25.0), checked against T1's
    # true Heston price (20.0) — NOT T2's fallback. 25.0 >= 20.0, so it is
    # kept as-is, not floored.
    assert targets[2].pricingMethod == "Heston repriced"
    assert targets[2].estimatedOptionPrice == 25.0
```

Find `test_estimate_targets_relabels_heston_price_still_below_inflated_prior_display` and replace its whole body with:

```python
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

    # T2: Heston raised -> BS-fallback reprice. sigma derived from
    # bs_iv(2.50, 185, 190, 30/365, 0.05, True) = 0.200202 (converges,
    # cached for reuse on any later level that also needs the fallback).
    # exit = bs_price(207.5, 190, 15/365, 0.05, 0.200202, True) =
    # 17.9269986203 -> 17.93.
    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 17.93

    # T3: raw Heston 12.0 clears the floor check against T1's 10.0, but is
    # still below T2's displayed 17.9269986203 (unrounded) -> must fall
    # back too, using the SAME cached sigma (0.200202) as T2: exit =
    # bs_price(215, 190, 15/365, 0.05, 0.200202, True) = 25.3922282437 ->
    # 25.39. Verified directly against the real bs_iv/bs_price.
    assert targets[2].pricingMethod == "Delta approximation"
    assert targets[2].estimatedOptionPrice == 25.39
```

Find `test_estimate_targets_falls_back_when_both_floor_and_display_checks_fail` and replace its whole body with:

```python
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

    # T2: same BS-fallback reprice as the previous test's T2: 17.93.
    assert targets[1].pricingMethod == "Delta approximation"
    assert targets[1].estimatedOptionPrice == 17.93

    # T3: raw 3.0 < prev_heston_price (10.0) -> floored to 10.0 by check 1.
    # 10.0 is still < prev_display_price (17.9269986203, unrounded) -> check
    # 2 also fails -> falls back to the BS-fallback reprice using the same
    # cached sigma: exit = bs_price(215, 190, 15/365, 0.05, 0.200202, True)
    # = 25.3922282437 -> 25.39.
    assert targets[2].pricingMethod == "Delta approximation"
    assert targets[2].estimatedOptionPrice == 25.39
```

Find `test_estimate_targets_seeds_heston_reference_from_first_successful_level` and replace its whole body with:

```python
def test_estimate_targets_seeds_heston_reference_from_first_successful_level(monkeypatch):
    """prev_heston_price must be seeded from whichever level FIRST succeeds,
    not implicitly assumed to be T1. T1 itself fails here (raises), leaving
    prev_heston_price unset — T2 becomes the first real Heston reference.

    T3's raw price (12.0) is deliberately chosen strictly between T1's
    BS-fallback reprice (10.7388546688, real -- see below) and T2's true
    Heston price (15.9), rather than below both, so this test can actually
    tell "anchored to T2" apart from "still anchored to T1's stale
    fallback": if prev_heston_price were incorrectly seeded from T1's
    fallback value and never properly overwritten when T2 succeeds, T3's
    12.0 would clear that stale ~10.74 floor unchecked, then fail the
    display-consistency check against the ladder's actual displayed price
    (15.9, from T2) and surface as 'Delta approximation' at a recomputed
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
            return 15.9  # T2: first level to succeed
        # T3: artifact relative to T2's true price, chosen strictly between
        # T1's fallback (~10.74) and T2's true price (15.9) so this test can
        # actually distinguish the two
        return 12.0

    monkeypatch.setattr(rr_module, "heston_price", _fake)
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
    assert targets[0].pricingMethod == "Delta approximation"
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
```

- [ ] **Step 2: Run the four updated tests to confirm they fail against the OLD `estimate_targets`**

Run: `cd backend && venv\Scripts\python.exe -m pytest tests/test_reward_risk.py -k "clamps_delta_approx_fallback or relabels_heston_price_still_below or falls_back_when_both_floor_and_display or seeds_heston_reference" -v`

Expected: All 4 FAIL (old `estimate_targets` still computes the crude delta guess, doesn't match the new BS-derived values).

- [ ] **Step 3: Rewire `estimate_targets`'s fallback branch in `reward_risk.py`**

In `backend/app/scoring/reward_risk.py`, find the `estimate_targets` function. Add a `fallback_sigma` cache variable next to the existing `prev_display_price`/`prev_heston_price` initialization. Find:

```python
    results = []
    prev_display_price = None  # the displayed/chosen price of the previous level — used
                                # only for the final non-decreasing-display invariant below.
    prev_heston_price = None   # the previous level's TRUE Heston-derived price (raw, or
                                # floored against this same reference) — used only to decide
                                # whether the current level's raw Heston price is a numerical
                                # artifact. Deliberately never set from a delta-approximation
                                # fallback value, so a fallback at one level can never distort
                                # the artifact check for a later, independently-legitimate
                                # Heston price.
```

Replace with:

```python
    results = []
    prev_display_price = None  # the displayed/chosen price of the previous level — used
                                # only for the final non-decreasing-display invariant below.
    prev_heston_price = None   # the previous level's TRUE Heston-derived price (raw, or
                                # floored against this same reference) — used only to decide
                                # whether the current level's raw Heston price is a numerical
                                # artifact. Deliberately never set from a delta-approximation
                                # fallback value, so a fallback at one level can never distort
                                # the artifact check for a later, independently-legitimate
                                # Heston price.
    fallback_sigma = None       # the fallback sigma, derived at most once per ladder (lazily,
                                 # on whichever level first needs it) and reused for every
                                 # later level that also needs it — current_premium,
                                 # stock_price, strike, expiry_years and is_call are identical
                                 # across T1/T2/T3, only t_price changes per level.
```

Now find the fallback branch inside the loop:

```python
        if not use_heston_price:
            # Heston is unusable for this level — either genuinely (no
            # params, raised, or returned a non-finite/non-positive price;
            # heston_ok is False) or because its own artifact-floored price
            # still can't clear the display check above (heston_ok was True
            # but use_heston_price was rejected). Either way, fall back to
            # the delta approximation. This level does NOT update
            # prev_heston_price: a later level's Heston price is still
            # judged against the last real Heston reference, not this
            # fallback.
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX
```

Replace with:

```python
        if not use_heston_price:
            # Heston is unusable for this level — either genuinely (no
            # params, raised, or returned a non-finite/non-positive price;
            # heston_ok is False) or because its own artifact-floored price
            # still can't clear the display check above (heston_ok was True
            # but use_heston_price was rejected). Either way, fall back to a
            # Black-Scholes reprice using the contract's own market-implied
            # vol. This level does NOT update prev_heston_price: a later
            # level's Heston price is still judged against the last real
            # Heston reference, not this fallback.
            if fallback_sigma is None:
                fallback_sigma = _derive_fallback_sigma(
                    current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback,
                )
            opt_price = max(0.01, _bs_reprice_or_delta_approx(
                t_price, stock_price, strike, dte_at_target, r, fallback_sigma, is_call, current_premium,
            ))
            method = PricingMethod.DELTA_APPROX
```

- [ ] **Step 4: Run the full test file to confirm everything passes**

Run: `cd backend && venv\Scripts\python.exe -m pytest tests/test_reward_risk.py -v`

Expected: All tests in the file PASS (Task 1's tests still pass, Task 2's four tests now pass too).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/reward_risk.py backend/tests/test_reward_risk.py
git commit -m "feat(reward-risk): derive real IV for estimate_targets' fallback pricing

Wires the same BS-fallback helpers from estimate_rr into
estimate_targets, deriving the fallback sigma once per ladder (lazily)
and reusing it across any levels that need the fallback, since the
underlying contract's quote doesn't change across T1/T2/T3."
```

---

### Task 3: Full regression check across dependent test files

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && venv\Scripts\python.exe -m pytest -q`

Expected: All tests pass (baseline before this plan: 1180 passed, 9 skipped, 1 xpassed, 0 failed — this plan should not change that count except for the tests explicitly touched above). In particular, confirm these files are unaffected (they were checked during planning and don't hardcode fallback-formula numeric outputs — they only assert on the `"Delta approximation"` label or use directly-mocked `RrResult`/`TargetLevel` objects, neither of which this plan changes):
- `backend/tests/test_trade_plan.py`
- `backend/tests/test_multi_target.py`
- `backend/tests/test_scan_router_spreads.py`
- `backend/tests/test_scan_scheduler.py`
- `backend/tests/test_scan_endpoint.py`

If any of these fail unexpectedly, stop and investigate — it means the design's "no plumbing changes needed" assumption was wrong somewhere, which would be a real finding, not a test to force-fix.

- [ ] **Step 2: No commit for this task** — it's verification-only. If Step 1 reveals a real problem, fix it as part of Task 1 or 2 (whichever function's change caused it) and re-commit there instead of adding a new commit here.
