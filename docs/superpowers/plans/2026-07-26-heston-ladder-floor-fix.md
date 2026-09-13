# Heston Ladder Floor Fix Implementation Plan

> **SUPERSEDED IN PART, 2026-09-12 (Phase F1).** This document's central
> premise -- that `heston_price()`'s non-monotonic ladder and its
> distance-from-at-the-money cost were inherent quirks of `scipy.integrate.quad`
> on deep-OTM/long-dated inputs -- is **false**. The dip and the cost were both
> a defect in `heston_price`'s Fourier inversion: `_integrand` re-applied
> `exp(i*phi*lnS)/exp(i*phi*lnK)` on top of a characteristic function that
> already carried `e^{i*phi*ln(S/K)}`, doubling the Fourier frequency to
> `2i*phi*ln(S/K)`. The error was exactly zero at `K == S` and reached +451% at
> 45 DTE / +2782% at 180 DTE in the delta band the scanner ranks. It is fixed;
> see `docs/superpowers/plans/2026-09-12-heston-calibration-spec.md`.
>
> **Every Heston price quoted below is therefore wrong**, including the
> 12.518866931556794 / 10.086141661385824 / 14.081229812545331 ladder (now
> 3.7974 / 8.0361 / 14.2358, strictly monotonic). The decisions this document
> records were reasonable on the evidence available then; do not reuse its
> numbers or its explanation.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `estimate_targets()` in `backend/app/scoring/reward_risk.py` so that a numerical-integration artifact at one ladder level (T1/T2/T3) no longer discards a later, independently-legitimate Heston price — by flooring the artifact level's raw Heston price against the true prior Heston reference instead of switching that level to the cruder delta-approximation model.

**Architecture:** The current code uses a single `prev_opt_price` variable both to decide whether a level's raw Heston price is a numerical artifact ("is it lower than what I last chose to display?") and to enforce the final non-decreasing-display invariant. Those are two different questions that must use two different references. This plan splits them into `prev_heston_price` (the last *true* Heston-derived price — never contaminated by a delta-approximation fallback, used only to detect and floor an artifact) and `prev_display_price` (the last *displayed* price on the card — used only for the final "never show a decreasing ladder" clamp, unchanged from today). When a level's raw Heston price comes back lower than `prev_heston_price`, it is floored up to `prev_heston_price` and stays labelled `"Heston repriced"` — it is never switched to `"Delta approximation"` for this reason.

There is one more wrinkle, found and verified during this plan's own adversarial-audit round: flooring against `prev_heston_price` alone is not sufficient to guarantee a level's *displayed* number is honestly Heston-derived. If an EARLIER level had a genuine total Heston failure and fell back to an inflated delta-approximation value, that inflated value becomes `prev_display_price` — and a LATER level's own legitimate (post-floor) Heston price can still be lower than that inflated `prev_display_price`, even though it already cleared the artifact-floor check against `prev_heston_price`. Showing that level's raw Heston number labelled `"Heston repriced"` would be dishonest (the final displayed number, after the invariant clamp below, would not actually be what Heston computed), and simply letting the clamp silently overwrite it would reintroduce exactly the kind of silent-mislabeling bug this plan sets out to fix, just one level further down the chain. So after the artifact-floor step, each level's Heston-track price is checked a second time against `prev_display_price`: if it would still need to be clamped upward to satisfy the non-decreasing-display invariant, that level falls back to the delta approximation too (same as if Heston had genuinely failed for it), exactly as the pre-existing code already did for every case before this plan. This second check is scoped narrowly — it only fires when an intervening level had a genuine Heston failure, not an artifact, and it never fires within a chain of purely-successful Heston levels (see Task 1's new third test).

The delta-approximation model is used for two cases: (1) Heston is genuinely unusable for that level (missing params, an exception, or a non-finite/non-positive price), and (2) Heston succeeded and cleared the artifact-floor check, but an earlier level's own fallback already inflated the display beyond what this level's real Heston price can honestly support.

**Tech Stack:** Python 3, pytest. No new dependencies. Touches only `backend/app/scoring/reward_risk.py` and its two test files.

**Context:** This is a targeted fix to a single function on an already-audited, already-implemented feature (Heston stochastic-vol pricing in the trade plan, branch `worktree-heston-pricing-in-trade-plan`). It is the third of three adversarial-audit rounds run over that feature; the first two rounds' fixes are already committed (`7fd3fc1`, `bea47cc`). This plan addresses round 3's finding: the ladder's monotonicity guard compares a later level's legitimate Heston price against an inflated fallback value instead of the original Heston reference.

**Verified against the repo's real pricer while writing this plan** (see Task 2's fixture): with `stock_price=318.73, strike=375, dte=185` (the default fixture in `backend/tests/test_trade_plan.py`'s `_plan()`), `heston_price()` returns T1=12.518866931556794, T2=10.086141661385824, T3=14.081229812545331 — a non-monotonic (T2 dips) but otherwise legitimate ladder. Confirmed by directly running the current (pre-fix) code against this exact fixture: it displays as `12.52 / 18.94 / 22.77` (T2 *and* T3 both wrongly discarded to the delta-approximation model, and both inflated above the true T1/T3 Heston prices). After this fix it displays as `12.52 / 12.52 / 14.08` (T2 floored, T3's real Heston price preserved).

---

### Task 1: Rewrite the two existing artifact-handling unit tests, then implement the fix

**Files:**
- Modify: `backend/app/scoring/reward_risk.py:102-174` (the `estimate_targets` results loop)
- Modify: `backend/tests/test_reward_risk.py:195-277` (the two tests that pin down the old "switch models" behavior)

The two existing tests below assert the *old* buggy behavior (an artifact-level Heston dip fully switches that level to `"Delta approximation"`). They must be rewritten first to assert the *new* behavior, confirmed to fail against the current code, and then the implementation change makes them pass.

- [ ] **Step 1: Replace the two existing tests with their rewritten versions**

In `backend/tests/test_reward_risk.py`, replace the entire `test_estimate_targets_falls_back_when_heston_price_is_non_monotonic` function (lines 195-226) with:

```python
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
```

Replace the entire `test_estimate_targets_clamps_delta_approx_fallback_to_prev_level` function (lines 228-277) with:

```python
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
```

Append a third, new test directly after it (this one is new coverage, not a rewrite of an existing test — it covers the second-order interaction found during this plan's own adversarial-audit round: a level whose Heston price clears the artifact-floor check can still need to fall back if an earlier, unrelated level's genuine-failure fallback already inflated the display):

```python
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
```

Append a fourth test directly after it. This one is a distinct regression guard found during a SECOND round of adversarially auditing this plan: every scenario above exercises exactly one of the two checks in Task 1 Step 3's implementation (the artifact-floor check against `prev_heston_price`, or the display-consistency check against `prev_display_price`) — none exercises a level that needs BOTH checks in the same iteration (first floored by check 1, and the floored result still fails check 2). The displayed output happens to numerically match the previous test, but it is reached through a different internal branch — this guards against a future refactor that reorders or short-circuits the two checks in a way that would silently break this specific combination while every other test in this plan keeps passing:

```python
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
```

- [ ] **Step 2: Run the four tests against the current implementation**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_reward_risk.py::test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models tests/test_reward_risk.py::test_estimate_targets_clamps_delta_approx_fallback_to_prev_level tests/test_reward_risk.py::test_estimate_targets_relabels_heston_price_still_below_inflated_prior_display tests/test_reward_risk.py::test_estimate_targets_falls_back_when_both_floor_and_display_checks_fail -v` (from the worktree's `backend/` directory)

Expected: the FIRST test FAILS — `targets[1].pricingMethod` is currently `"Delta approximation"`, not `"Heston repriced"` (confirmed by running it directly against the current code before writing this plan). The SECOND, THIRD, and FOURTH tests all currently PASS against the pre-fix code (confirmed by running each directly against the current code before writing this plan) — pre-fix code's simpler single-reference logic happens to produce the same labels/numbers for these specific inputs. They are written against the NEW implementation's two-check structure and serve as regression guards for the gaps found while auditing this plan; they are not expected to fail pre-fix. Do not treat the second, third, or fourth test passing early as a problem — only the first test failing pre-fix is required.

- [ ] **Step 3: Implement the fix in `estimate_targets`**

In `backend/app/scoring/reward_risk.py`, replace lines 102-174 (from `results = []` through the final `return results`) with:

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
                                # Heston price (round 3 adversarial-audit finding, fixed here).
    for t_price in targets_prices:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        opt_price: float
        method: PricingMethod
        raw_price = None
        heston_ok = False

        if heston_params is not None:
            try:
                raw_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
            except Exception:
                raw_price = None
            heston_ok = raw_price is not None and math.isfinite(raw_price) and raw_price > 0

        if heston_ok:
            floored_price = raw_price
            # T1/T2/T3 share dte_at_target and only differ in t_price, so a
            # correctly-priced option must be monotonically increasing ACROSS
            # THAT LADDER — a Heston price that comes out lower than the
            # previous level's TRUE Heston price is a numerical-integration
            # artifact (see this plan's intro), not a real option value or a
            # sign that Heston is unusable for this level. Floor it against
            # the true Heston reference rather than discarding the whole
            # Heston computation for a cruder model — this keeps the level
            # labelled "Heston repriced" and, critically, keeps
            # prev_heston_price anchored to real Heston output so a LATER
            # level's own legitimate Heston price is never compared against
            # an inflated fallback value.
            if prev_heston_price is not None and floored_price < prev_heston_price:
                floored_price = prev_heston_price
            # Even after flooring against the TRUE Heston chain, this level
            # can still be lower than what's already on display, if an
            # earlier, unrelated level had a genuine Heston failure and its
            # fallback was itself inflated. This level cannot honestly stay
            # labelled "Heston repriced" in that case — the number that would
            # end up on screen (after the invariant clamp below) would not be
            # what Heston computed for THIS level, it would be inherited from
            # that earlier, unrelated fallback. Fall back to the delta
            # approximation for this level too, exactly as if Heston had
            # failed outright — this is the pre-existing behavior for every
            # case that isn't a pure numerical artifact, unchanged by this fix.
            if prev_display_price is not None and floored_price < prev_display_price:
                heston_ok = False
            else:
                opt_price = floored_price
                method = PricingMethod.HESTON
                prev_heston_price = opt_price

        if not heston_ok:
            # Heston is unusable for this level — either genuinely (no
            # params, raised, or returned a non-finite/non-positive price)
            # or because its own artifact-floored price still can't clear
            # the display check above. Either way, fall back to the delta
            # approximation. This level does NOT update prev_heston_price:
            # a later level's Heston price is still judged against the last
            # real Heston reference, not this fallback.
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX

        # Hard invariant: the *displayed* ladder must be non-decreasing
        # regardless of which pricing path produced each level. A
        # delta-approximation fallback can itself undershoot the previous
        # level's displayed price — clamp it up to prev_display_price rather
        # than leave a visibly-wrong ladder. This only ever raises a level,
        # never lowers one, and prev_display_price is None for T1 so T1 is
        # never clamped against anything (including current_premium, which
        # is intentionally never part of this chain). Note this clamp also
        # raises rrContribution below for the clamped level (reward =
        # opt_price - current_premium uses the post-clamp price) —
        # intentional: rrContribution must stay consistent with the
        # estimatedOptionPrice actually shown on that same row.
        if prev_display_price is not None:
            opt_price = max(opt_price, prev_display_price)

        prev_display_price = opt_price

        reward = opt_price - current_premium
        risk_basis = current_premium * premium_stop_pct
        rr = round(reward / risk_basis, 2) if risk_basis > 0 and reward > 0 else 0.0

        results.append(TargetLevelSchema(
            targetPrice=round(t_price, 2),
            stockPrice=round(t_price, 2),
            estimatedOptionPrice=round(opt_price, 2),
            pricingMethod=method,
            rrContribution=rr,
        ))

    return results
```

- [ ] **Step 4: Run the full `test_reward_risk.py` file and confirm everything passes**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_reward_risk.py -v` (from the worktree's `backend/` directory)

Expected: all tests PASS, including the two rewritten and one new test from Step 1 and every pre-existing test in the file (`test_estimate_targets_does_not_reject_legitimate_low_t1_price`, `test_estimate_targets_falls_back_on_nan_heston_price`, `test_estimate_targets_falls_back_on_inf_heston_price`, etc. — none of these touch the artifact-floor path, so they must be unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/reward_risk.py backend/tests/test_reward_risk.py
git commit -m "fix(reward-risk): floor artifact Heston ladder prices instead of switching models"
```

---

### Task 2: Add the primary end-to-end regression test using the real production fixture

**Files:**
- Modify: `backend/tests/test_reward_risk.py` (append a new test at the end of the file)

This is the exact scenario from round 3's adversarial-audit finding, reproduced directly against the real (unmocked) `heston_price()` — proof the fix resolves the originally-reported bug, not just the synthetic unit tests above.

- [ ] **Step 1: Write the test**

Append to the end of `backend/tests/test_reward_risk.py`:

```python
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
```

- [ ] **Step 2: Run it**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_reward_risk.py::test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact -v` (from the worktree's `backend/` directory)

Expected: PASS (Task 1's implementation already makes this pass — this step confirms it, and locks the exact numbers in as a regression guard).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_reward_risk.py
git commit -m "test(reward-risk): add real-fixture regression test for the ladder floor fix"
```

---

### Task 3: Update the system-level trade-plan test to match the new behavior

**Files:**
- Modify: `backend/tests/test_trade_plan.py:89-100`

`test_heston_params_falls_back_per_target_when_non_monotonic` currently asserts the OLD buggy behavior end-to-end through `build_trade_plan`. It uses the exact same default fixture as Task 2's new test, so its expectations must change identically.

- [ ] **Step 1: Replace the test**

Replace the entire `test_heston_params_falls_back_per_target_when_non_monotonic` function (lines 89-100) in `backend/tests/test_trade_plan.py` with:

```python
def test_heston_params_floors_non_monotonic_target_instead_of_falling_back():
    """Using _plan()'s own default (deep-OTM, long-dated) fixture together
    with heston_params: T1 is Heston-priced, T2's raw Heston price is a
    numerical artifact (verified directly against this exact fixture:
    12.518866931556794 / 10.086141661385824 / 14.081229812545331) and is
    floored up to T1's price rather than switched to the delta
    approximation, and T3's own legitimate Heston price is preserved
    unmodified — see backend/tests/test_reward_risk.py's
    test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact for the
    reward_risk-level version of this same regression."""
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    p = _plan(heston_params=params)  # default fixture: stock=318.73, strike=375, dte=185
    assert [t.pricingMethod for t in p.targets] == [
        "Heston repriced", "Heston repriced", "Heston repriced",
    ]
    prices = [t.estimatedOptionPrice for t in p.targets]
    assert prices == [12.52, 12.52, 14.08]
```

- [ ] **Step 2: Run it**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_trade_plan.py -v` (from the worktree's `backend/` directory)

Expected: all tests in the file PASS, including the rewritten one and the untouched `test_heston_params_flow_through_to_rr_and_targets` (different, well-behaved fixture — unaffected by this change).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_trade_plan.py
git commit -m "test(trade-plan): update system-level test for the ladder floor fix"
```

---

### Task 4: Add bearish/put regression coverage for the Heston ladder and R/R paths

**Files:**
- Modify: `backend/tests/test_reward_risk.py` (append three new tests at the end of the file)

`test_reward_risk.py` currently has zero `is_call=False` coverage for any Heston code path (round 3's finding #4, deferred from the prior audit round). This task closes that gap and confirms the fix in Task 1 is symmetric for puts, since `estimate_targets`'s direction/delta logic branches on `is_call`.

- [ ] **Step 1: Write the tests**

Append to the end of `backend/tests/test_reward_risk.py`:

```python
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
```

- [ ] **Step 2: Run the three new tests**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_reward_risk.py -v -k "put"` (from the worktree's `backend/` directory)

Expected: all three PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_reward_risk.py
git commit -m "test(reward-risk): add bearish/put Heston coverage for estimate_targets and estimate_rr"
```

---

### Task 5: Full backend suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest -q` (from the worktree's `backend/` directory)

Expected: `1132 passed, 9 skipped, 1 xpassed, 0 failed` from before this plan. This plan adds 6 net-new tests: Task 1 rewrites 2 existing tests in place (no net count change from those two) and adds 2 brand-new tests; Task 2 adds 1; Task 3 rewrites 1 existing test in place (no net count change); Task 4 adds 3. Net new = 2 (Task 1) + 1 (Task 2) + 3 (Task 4) = 6 → expect **1138 passed, 9 skipped, 1 xpassed, 0 failed**. If the count differs, investigate before proceeding — do not adjust the expected count to match an unexplained result.

- [ ] **Step 2: No commit** (verification-only task — nothing to stage)

---

## Self-review notes (for the plan author, not the implementer)

- **Spec coverage:** floor-instead-of-switch fix (Task 1) ✓; real-fixture regression proving round 3's exact finding is resolved (Task 2) ✓; system-level test updated to match (Task 3) ✓; bearish/put coverage for both `estimate_targets` and `estimate_rr` Heston paths (Task 4) ✓; full-suite green (Task 5) ✓.
- **Resolved during round 1 of this plan's own adversarial audit:** an earlier draft of the fix used only the artifact-floor check (`prev_heston_price`) and let the pre-existing non-decreasing-display clamp silently overwrite a later level's legitimate Heston price while leaving it labelled `"Heston repriced"` — a new, more subtle version of the same "mislabeled/silently-overwritten price" problem this plan sets out to fix, one level further down the chain (see the Architecture section's second paragraph). Fixed by adding the second check in Task 1's Step 3 implementation (`if prev_display_price is not None and floored_price < prev_display_price: heston_ok = False`) and its dedicated regression test (Task 1's third test). Verified this only fires when an intervening level had a genuine Heston failure — it never fires within a chain of purely-successful Heston levels, confirmed against every other test in this plan (Task 2's real-fixture case, Task 4's put cases) which all still resolve to pure `"Heston repriced"` chains as intended.
- **Resolved during round 2 of this plan's own adversarial audit:** the round-1 fix's two checks (artifact-floor, then display-consistency) were each covered individually, but no test exercised a level that needs BOTH in the same iteration (floored by check 1, and the floored result still fails check 2). Fixed by adding Task 1's fourth test, which is numerically indistinguishable in its final output from the third test but reaches that output via a different internal branch — a regression guard against a future refactor silently breaking this specific combination.
- **Type/naming consistency:** `prev_heston_price` and `prev_display_price` are used identically in Task 1's Step 3 code and referenced by name only in prose elsewhere — no drift.
