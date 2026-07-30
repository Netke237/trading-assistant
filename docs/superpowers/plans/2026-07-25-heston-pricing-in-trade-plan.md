# Heston Pricing in build_trade_plan — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing Heston stochastic-vol pricer back into `build_trade_plan` so live scan trade cards' R/R ratio and T1/T2/T3 sell-to-close targets are priced with real options math (time decay + volatility) instead of a flat fixed-delta linear approximation, without regressing scan-loop performance.

**Architecture:** `build_trade_plan` (`backend/app/scoring/trade_plan.py`) gains an optional `heston_params` pass-through parameter instead of hardcoding `None`. The scan pipeline (`backend/app/routers/scan.py::_process_symbol`) calibrates Heston once per symbol from the option chain it already fetched, gated by a process-wide `_HESTON_SEMAPHORE` (not the per-request `sem` parameter — see Task 4's corrections for why that distinction matters) held for the calibration's real lifetime regardless of whether the calling symbol gives up waiting on it, and reuses that one calibration for the primary target ladder *and* the runner-up alternatives' R/R. A `HESTON_PRICING_ENABLED` env flag lets this be switched off instantly without a redeploy, since it changes every trade card's headline number. `reward_risk.py`'s Heston branches (`estimate_rr` and `estimate_targets`) get a resilience fix so a degenerate, failed, or non-monotonic Heston price never gets mislabeled as `"Heston repriced"`.

**Important correction from audit round 1 — `heston_cache.py`'s "1s timeout" does not bound wall-clock blocking time.** `calibrate_cached` (`backend/app/models/heston_cache.py:97-107`) runs the real grid search in a `with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:` block and does `future.result(timeout=_CALIBRATION_TIMEOUT)` (1.0s) inside it. `future.result(timeout=...)` only bounds how long `.result()` waits before *raising* `TimeoutError` — it does not cancel the submitted work. Both the happy-path `return` and the `except TimeoutError: ... return CalibrationResult(...)` fallback `return` are still *inside* the `with` block, so Python runs `pool.__exit__()` (→ `shutdown(wait=True)`) before the function actually returns to its caller — and `shutdown(wait=True)` blocks until the abandoned worker thread finishes the *entire* grid search, however long that actually takes. (`test_heston_perf.py::test_timeout_returns_fallback` has to monkeypatch `ThreadPoolExecutor` with a fake whose `__exit__` is a no-op specifically to dodge this — a strong tell it's a real gap, not a misunderstanding.) This is pre-existing `heston_cache.py` behavior and is **not** modified by this plan (see "Out of scope" below) — but it means the calling thread of `calibrate_heston` can genuinely block for the full duration of a real grid search against a production-size chain, not ~1s. Task 4 protects the *new* call site against this with its own dedicated bounded executor and an outer `asyncio.wait_for` ceiling — see Task 4's implementation for the exact mechanism and reasoning.

Two loose ends from the original review are resolved as a *consequence* of this wiring, not by separate code changes: `reward_risk.py`'s `dte_at_target` (computed but unused while `heston_params` was always `None`) starts being exercised on every scan-pipeline trade card once Task 4 lands, since its only consumer is the `heston_params is not None` branch; and `PricingMethod.HESTON` (previously unreachable — `estimate_targets` only ever produced `DELTA_APPROX`/`UNAVAILABLE`) starts being emitted for real, which Task 2's test asserts directly.

**Out of scope (explicit):**
- `backend/app/models/heston_cache.py`'s internal threading (its own per-call `ThreadPoolExecutor`) is pre-existing, tuned, tested code (`test_heston_perf.py` pins it at <500ms cold / <5ms cached against a toy 5-contract fixture). Not touched here, **despite the real `shutdown(wait=True)` blocking gap documented above** — that gap predates this plan (it exists whether or not anything ever calls `calibrate_heston`) and fixing it would mean rewriting WS-40's tuned, already-tested threading model, which is a separate piece of work. This plan instead defends the *new* call site it's adding (Task 4) against that gap with its own bounded executor + hard timeout, so the scan pipeline can't hang because of it.
- `POST /api/contracts/recompute-plan` (`backend/app/routers/contracts.py`) intentionally keeps `heston_params=None` (delta approximation). It's called interactively when the user overrides a contract in Step 6 and receives only a single contract's fields in the POST body — no option chain. Fetching+calibrating there would add a chain-fetch (currently a *synchronous* `fetch_option_chain` call already blocking that endpoint's event loop — a pre-existing issue, not introduced here) plus multiple seconds of worst-case calibration to a latency-sensitive interactive click. `build_trade_plan`'s new parameter defaults to `None`, so this endpoint's behavior is unchanged by this plan.
  - **Known, accepted trade-off (flagged by audit round 1, not resolved here):** because the scan's initial trade card *will* show `rrModel: "Heston repriced"` for a contract (via Task 4), but re-selecting that exact same contract through Step 6's override immediately afterward still recomputes via `recompute-plan` → delta approximation, the displayed R/R for the identical instrument can change the moment the user clicks to select it. A real fix (e.g. a short-lived, symbol-keyed cache of the scan's calibration that `recompute-plan` could look up by the `symbol` field already in `RecomputePlanRequest`) is a legitimate follow-up but is new cross-request state/caching design outside "wire Heston into build_trade_plan" — left for Kenneth to decide on separately rather than silently added here.
- Stock-mode R/R (`backend/app/routers/stock_scan.py`, `backend/app/services/strategy_engine.py`) is unrelated — it scores stock price target hit-rates, not options premiums, and has no Heston dependency.

**Tech Stack:** Python, FastAPI, pytest + pytest-asyncio, existing `app/models/heston.py` (Heston closed-form pricer) and `app/models/heston_cache.py` (calibration cache/timeout wrapper).

---

## Context for the engineer (you have zero context on this codebase)

- `app/models/heston.py::calibrate_heston(option_chain, S, r)` calibrates `HestonParams` to an observed option chain and always returns a `CalibrationResult` (never raises under normal conditions — it has its own internal fallback to a seeded/BS-based `HestonParams` on thin chains or timeout). It delegates to `app/models/heston_cache.py::calibrate_cached`, which is a **synchronous, blocking** call — and, despite having a `_CALIBRATION_TIMEOUT = 1.0` internally, it can genuinely block its calling thread far longer than 1s (see the "Important correction from audit round 1" note above). Treat it as an unbounded-duration synchronous call and defend against that at the call site, not as a call that reliably returns within ~1s.
- `app/scoring/reward_risk.py::estimate_rr` and `estimate_targets` already accept a `heston_params: HestonParams | None` kwarg and already branch on it correctly — they've simply never been called with anything but `None` in production. Their existing unit tests (`backend/tests/test_reward_risk.py`) already cover the Heston-params-provided path.
- `app/scoring/trade_plan.py::build_trade_plan` is the single function that builds a trade card's Entry/Exit/RR/targets. It currently hardcodes `heston_params=None` at its two internal `estimate_rr`/`estimate_targets` calls (lines 96 and 107). Both the scan pipeline and the recompute endpoint call `build_trade_plan` — never `estimate_rr`/`estimate_targets` directly (except the scan's runner-up-alternatives loop, which calls `estimate_rr` directly at `backend/app/routers/scan.py:672`).
- `backend/app/routers/scan.py::_process_symbol` is the per-symbol scan worker. By the time it reaches the trade-plan section (~line 515), it already has the full fetched option `chain` (list of dicts with `strike`, `dte`, `price`, `right`, etc. — raw Tradier-shaped, pre-augmentation) and the stock `price` in scope.
- Test mocks you'll reuse: `_MOCK_CANDLES` and `_MOCK_CHAIN` are module-level fixtures already defined near the top of `backend/tests/test_scan_endpoint.py`.
- Run backend tests from the `backend/` directory: `pytest tests/test_reward_risk.py tests/test_trade_plan.py tests/test_scan_endpoint.py tests/test_heston_perf.py -v`.

---

### Task 1: Harden `reward_risk.py`'s Heston branches against degenerate, failed, or non-monotonic pricing

**Files:**
- Modify: `backend/app/scoring/reward_risk.py:31-44` (`estimate_rr`), `:93-126` (`estimate_targets`)
- Test: `backend/tests/test_reward_risk.py`

Today, if `heston_price()` returns `<= 0` (or throws), `estimate_rr` still sets `model_used = "Heston repriced"` and just floors the bogus exit premium at `0.01` — mislabeling a dummy number as a real Heston price. `estimate_targets` (a few lines below in the same file) already has correct behavior for that specific case: it falls back to the delta approximation when the Heston price is unusable. Bring `estimate_rr` in line with that.

There's a second, more surprising failure mode discovered while writing this plan (audit round 2), specific to `estimate_targets`: T1/T2/T3 all share the same `dte_at_target` and only differ in the hypothetical future stock price — so a correctly-computed, arbitrage-free option price *must* be monotonically increasing across T1→T2→T3 (a call is monotonic in the underlying at fixed time-to-expiry, same for a put in its direction). Verified directly against this repo's actual `heston_price`, using `test_trade_plan.py`'s own fixture inputs (`stock_price=318.73, strike=375, dte=185`, `bullish_target_pct=0.08`):

```python
>>> from app.models.heston import HestonParams, heston_price
>>> params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
>>> S, K, r = 318.73, 375.0, 0.05
>>> dte_at_target = max((185/365)*0.5, 7/365)
>>> move = abs(S*1.08 - S)
>>> [round(heston_price(S+m*move, K, dte_at_target, r, params, True), 2) for m in (1, 1.5, 2)]
[12.52, 10.09, 14.08]
```

T2 (10.09) is *lower* than T1 (12.52) despite being further in the favorable direction — a real numerical-integration artifact in `heston_price`'s `scipy.integrate.quad` evaluation for this deep-OTM, longer-dated region (out of scope to fix the integration itself — see this plan's "Out of scope" section). Left unguarded, this would render a visibly-wrong, confusing sell-to-close ladder on the trade card (T2 cheaper than T1). Add a monotonicity guard to `estimate_targets` alongside the existing degenerate-price guard.

**Correction from audit round 3 — the guard must only compare T1/T2/T3 against each other, never against `current_premium`.** An earlier draft of this plan seeded the running comparison with `current_premium`, on the (wrong) assumption that T1 must also be `>= current_premium`. That's false: T1 is priced at `dte_at_target` (half of `expiry_years`), a *shorter* time-to-expiry than "now" (`current_premium`, implicitly priced at the full `expiry_years`) — so a legitimate Heston T1 price *can* be lower than the current premium purely because time decay from full to half tenor outweighs the value added by an 8% favorable move, especially for lower-delta/more-OTM contracts. Verified directly: for `S=185, K=200` (a real, survivable, moderately-OTM bullish pick — not a contrived edge case) at `dte=30`, real Heston gives `current_premium≈6.59` but a legitimate `T1≈3.33` — the seeded-with-`current_premium` guard would have wrongly rejected this true Heston price as "non-monotonic" and silently substituted the delta approximation instead, for exactly the lower-delta/higher-leverage contracts where a real repricing matters most. The fix below only starts comparing from T2 onward (against T1's own chosen price), never against `current_premium`.

- [ ] **Step 1: Write the failing tests**

First, change the top-of-file import in `backend/tests/test_reward_risk.py` (currently `from app.scoring.reward_risk import estimate_rr`) to also import `estimate_targets`:

```python
from app.scoring.reward_risk import estimate_rr, estimate_targets
```

Then add to `backend/tests/test_reward_risk.py` (after `test_heston_path_not_used_when_params_none`, ~line 117):

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
    round-3 audit finding that an earlier draft of this guard did exactly
    that and would have wrongly rejected this legitimate price."""
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_reward_risk.py -v -k "degenerate or exception or non_monotonic or legitimate_low_t1"`
Expected: `test_heston_degenerate_price_falls_back_to_delta_approx`, `test_heston_exception_falls_back_to_delta_approx`, and `test_estimate_targets_falls_back_when_heston_price_is_non_monotonic` FAIL — `estimate_rr` currently reports `model_used == "Heston repriced"` for the degenerate case and propagates `ValueError` uncaught for the exception case; `estimate_targets` currently has no monotonicity check at all, so T2 keeps `pricingMethod == "Heston repriced"` with its artificially-lowered price. `test_estimate_targets_does_not_reject_legitimate_low_t1_price` should already PASS before this task's fix (there's no guard yet to reject anything) — that's fine, it's a characterization guard confirming Step 3's implementation doesn't regress this case.

- [ ] **Step 3: Implement the fix**

Replace `backend/app/scoring/reward_risk.py:31-44`:

```python
    model_used: RrModel
    heston_ok = False

    if heston_params is not None:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        try:
            heston_exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)
        except Exception:
            heston_exit_premium = 0.0
        heston_ok = heston_exit_premium > 0

    if heston_ok:
        exit_premium = heston_exit_premium
        model_used = "Heston repriced"
    else:
        if is_call:
            delta = 0.5 if target_price > strike else 0.3
        else:
            delta = 0.5 if target_price < strike else 0.3
        price_move = abs(target_price - stock_price)
        exit_premium = current_premium + delta * price_move
        model_used = "Delta approximation"
```

(This replaces the original `if heston_params is not None: ... else: ...` two-branch block. Everything below it — `exit_premium = max(exit_premium, 0.01)` onward — is unchanged.)

Now add the monotonicity guard to `estimate_targets`. Replace the loop body currently reading (in `backend/app/scoring/reward_risk.py`, inside `estimate_targets`, ~lines 93-114):

```python
    results = []
    for t_price in targets_prices:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        opt_price = None
        method: PricingMethod

        if heston_params is not None:
            try:
                opt_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
                method = PricingMethod.HESTON
            except Exception:
                opt_price = None
                method = PricingMethod.UNAVAILABLE
        else:
            opt_price = None
            method = PricingMethod.DELTA_APPROX

        if opt_price is None or opt_price <= 0:
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX
```

with:

```python
    results = []
    prev_opt_price = None  # only meaningful once T1 has been priced — see below
    for t_price in targets_prices:
        dte_at_target = max(expiry_years * 0.5, 7 / 365)
        opt_price = None
        method: PricingMethod

        if heston_params is not None:
            try:
                opt_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
                method = PricingMethod.HESTON
            except Exception:
                opt_price = None
                method = PricingMethod.UNAVAILABLE
        else:
            opt_price = None
            method = PricingMethod.DELTA_APPROX

        # T1/T2/T3 share dte_at_target and only differ in t_price, so a
        # correctly-priced option must be monotonically increasing ACROSS
        # THAT LADDER — a Heston price that comes out lower than the
        # previous level's chosen price is a numerical-integration artifact
        # (see this task's intro), not a real option value. This must NEVER
        # be compared against current_premium: current_premium is priced at
        # the full expiry_years, a longer tenor than dte_at_target, so a
        # legitimate T1 price can be lower than current_premium purely from
        # time decay — prev_opt_price starts at None so T1 is never checked
        # against anything (round-3 audit finding: comparing T1 against
        # current_premium would wrongly reject legitimate low T1 prices).
        # Guard only the Heston case; the pure delta-approximation path is
        # untouched.
        non_monotonic = (
            method == PricingMethod.HESTON
            and opt_price is not None
            and prev_opt_price is not None
            and opt_price < prev_opt_price
        )

        if opt_price is None or opt_price <= 0 or non_monotonic:
            delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
            price_move = abs(t_price - stock_price)
            opt_price = max(0.01, current_premium + delta * price_move)
            method = PricingMethod.DELTA_APPROX

        prev_opt_price = opt_price
```

The rest of the loop (`reward = opt_price - current_premium` onward) is unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reward_risk.py -v`
Expected: all PASS, including the four new tests and all pre-existing ones (`test_heston_path_uses_correct_model_label`, `test_heston_path_returns_valid_ratio`, etc. — the happy path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/reward_risk.py backend/tests/test_reward_risk.py
git commit -m "fix(reward-risk): fall back to delta approx when Heston price is degenerate, fails, or non-monotonic"
```

---

### Task 2: Add `heston_params` pass-through to `build_trade_plan`

**Files:**
- Modify: `backend/app/scoring/trade_plan.py:1-17` (imports), `:96`, `:107`, `:36-48` (signature)
- Test: `backend/tests/test_trade_plan.py`

`build_trade_plan` currently hardcodes `heston_params=None` at both its internal calls. Add an optional parameter and thread it through, defaulting to `None` so both existing call sites (scan.py, contracts.py) are unaffected until Task 3 explicitly passes a value.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_trade_plan.py` (after `test_bearish_target_moves_down`, ~line 61):

```python
def test_heston_params_flow_through_to_rr_and_targets():
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    # Override _plan()'s default fixture (stock=318.73, strike=375, dte=185) to
    # a well-behaved, not-deep-OTM/long-dated one. The default fixture is
    # exactly the shape that triggers Task 1's monotonicity guard for T2/T3 (a
    # real heston_price numerical-integration artifact — verified while
    # writing this plan: heston_price on the default fixture's T1/T2/T3 gives
    # 12.52 / 10.09 / 14.08, non-monotonic), which would make this "everything
    # is Heston-priced" happy-path test assert something that isn't true.
    p = _plan(
        heston_params=params,
        stock_price=185.0, strike=190.0, dte=30, premium=2.50, delta=0.45,
        entry_bid=2.45, entry_ask=2.55,
    )
    assert p.rr_model == "Heston repriced"
    assert len(p.targets) == 3
    assert all(t.pricingMethod == "Heston repriced" for t in p.targets)


def test_heston_params_default_none_preserves_delta_approx():
    # No heston_params passed — must behave exactly as before this change.
    p = _plan()
    assert p.rr_model == "Delta approximation"


def test_heston_params_falls_back_per_target_when_non_monotonic():
    """Using _plan()'s own default (deep-OTM, long-dated) fixture together
    with heston_params: T1 is still Heston-priced, but T2 and T3 fall back to
    the delta approximation via Task 1's monotonicity guard in
    reward_risk.estimate_targets — verified directly against this exact
    fixture while writing this plan."""
    from app.models.heston import HestonParams
    params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    p = _plan(heston_params=params)  # default fixture: stock=318.73, strike=375, dte=185
    assert [t.pricingMethod for t in p.targets] == [
        "Heston repriced", "Delta approximation", "Delta approximation",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_trade_plan.py -v -k heston`
Expected: `test_heston_params_flow_through_to_rr_and_targets` and `test_heston_params_falls_back_per_target_when_non_monotonic` both FAIL with `TypeError: build_trade_plan() got an unexpected keyword argument 'heston_params'`. `test_heston_params_default_none_preserves_delta_approx` should already PASS (documents current behavior) — that's fine, it's a characterization guard for the next step.

- [ ] **Step 3: Implement the fix**

In `backend/app/scoring/trade_plan.py`, add the import (after line 15, `from app.scoring.entry_quality import assess_entry, EntryAssessment`):

```python
from app.models.heston import HestonParams
```

Change the signature (line 36-48) from:

```python
def build_trade_plan(
    *,
    direction: str,
    stock_price: float,
    strike: float,
    dte: int,
    premium: float,
    delta: float,
    entry_bid: float,
    entry_ask: float,
    entry_mid: float,
    rr_cfg: dict,
) -> TradePlan:
```

to:

```python
def build_trade_plan(
    *,
    direction: str,
    stock_price: float,
    strike: float,
    dte: int,
    premium: float,
    delta: float,
    entry_bid: float,
    entry_ask: float,
    entry_mid: float,
    rr_cfg: dict,
    heston_params: HestonParams | None = None,
) -> TradePlan:
```

Then replace the two hardcoded values: at line 96 (inside the `estimate_rr(...)` call) change `heston_params=None,` to `heston_params=heston_params,`; at line 107 (inside the `estimate_targets(...)` call) change `heston_params=None,` to `heston_params=heston_params,`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trade_plan.py -v`
Expected: all PASS, including `test_recompute_endpoint_matches_helper` and the other pre-existing tests (they don't pass `heston_params`, so they exercise the new default and must be unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/trade_plan.py backend/tests/test_trade_plan.py
git commit -m "feat(trade-plan): add heston_params pass-through parameter to build_trade_plan"
```

---

### Task 3: Document why `recompute-plan` still skips Heston

**Files:**
- Modify: `backend/app/routers/contracts.py:200-211`

No functional change (the new `heston_params` parameter defaults to `None`, so behavior is already unchanged) — just a comment so a future reader doesn't mistake this for a leftover bug once `scan.py` starts calibrating.

- [ ] **Step 1: Add the comment**

In `backend/app/routers/contracts.py`, immediately before the `plan = build_trade_plan(` call (line 200), add:

```python
    # heston_params intentionally omitted (defaults to None → delta approximation).
    # Unlike the scan pipeline, this endpoint only receives one contract's fields
    # in the request body — no option chain to calibrate against — and it's called
    # interactively from Step 6's contract-override UI, where adding a chain fetch
    # + a multi-second worst-case Heston calibration would be a noticeable
    # click-to-update delay. Known trade-off: this means the same contract can
    # show "Heston repriced" on the initial scan card and "Delta approximation"
    # after a Step 6 override — see docs/superpowers/plans/
    # 2026-07-25-heston-pricing-in-trade-plan.md's "Out of scope" section.
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/routers/contracts.py
git commit -m "docs(contracts): explain why recompute-plan doesn't calibrate Heston"
```

---

### Task 4: Wire Heston calibration into the scan pipeline

**Files:**
- Modify: `backend/app/routers/scan.py:1-19` (imports), `:61-68` (imports + kill-switch flag), `:176-177` (dedicated executor + timeout constant, right after `_SCAN_CONCURRENCY`), `:515-529` (build_trade_plan call site), `:680` (alts loop)
- Modify: `backend/app/main.py` (lifespan shutdown — release the dedicated executor)
- Modify: `backend/tests/conftest.py` (autouse fixture — see Step 3)
- Test: `backend/tests/test_scan_endpoint.py`

This is the task that actually turns Heston on for live scans. Calibration reuses the option chain the scan already fetched. Per the correction above, `calibrate_heston` must be treated as an unbounded synchronous call, so it runs in its own small, dedicated `ThreadPoolExecutor` (kept separate from asyncio's shared default executor, which `compute_confidence`/`_compute_dhmm` also use a few lines earlier in this same function — a slow/hung calibration must not starve those), wrapped in `asyncio.wait_for` with a hard ceiling so a slow calibration can't stall this symbol's processing beyond that ceiling. The whole thing is gated by an env-var kill switch.

**Correction from audit round 2 — the dedicated executor must be gated by the same concurrency limit as the rest of the scan, not left unbounded.** `_SCAN_CONCURRENCY = 5` (`scan.py:176`) only wraps the two network-fetch blocks inside `_process_symbol` (`async with sem:` at lines 297 and 416) — it's released well before the trade-plan section runs, so nothing stops far more than 5 symbols from reaching the Heston-calibration line at roughly the same time in a real universe scan. A fixed `max_workers=4` executor with no gating in front of it means: once more than 4 symbols are mid-calibration, the rest queue behind busy workers, and since each has its own `_HESTON_CALIBRATION_TIMEOUT_S` ceiling, a queued symbol can time out and silently fall back to delta approximation *before a worker ever picks up its job* — under real scan load, this could mean most trade cards keep showing "Delta approximation" even with the feature "on," which defeats the plan's goal.

**Further correction from audit round 3 — gating must use a process-wide semaphore, not the per-request `sem` parameter.** An earlier draft of this fix reused the `sem: asyncio.Semaphore` parameter `_process_symbol` already receives. That's insufficient: `semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)` (`scan.py:907`) is created **fresh inside `run_scan()` on every call** — it is *not* a singleton. `_HESTON_EXECUTOR`, by contrast, is a module-level singleton shared by the whole process. Traced `scan_scheduler.py` and `scan.py`'s `_state_lock`/`_scheduled_scan`: a background scheduled scan (`ScanScheduler._loop`, default 60-minute cadence) and a manual `POST /api/scan` both call `run_scan`, and nothing serializes them — `_state_lock` only guards a few lines reading/writing `_last_request`/`_last_result` at the very start/end of a scan, not the scan's execution itself. So a scheduled scan and a manual scan **can run fully concurrently**, each with its *own* 5-permit `sem` — meaning up to 10 concurrent tasks could reach `async with sem: ...` (two different `sem` objects) and submit to the *same* 5-worker `_HESTON_EXECUTOR`, reproducing the exact queue-then-timeout problem this fix exists to prevent, just across scan invocations instead of within one. Fix: gate calibration with a **module-level** semaphore, not the per-request `sem` parameter, so the cap holds across every concurrent scan in the process, not just within one.

**Further correction from audit round 4 — releasing the semaphore when the *caller* gives up (rather than when the job actually finishes) reopens the exact bug this was meant to close.** `asyncio.wait_for(awaitable, timeout=...)` cancels `awaitable` on timeout — but a `concurrent.futures.Future` backing a `run_in_executor` call that has *already started running on a worker thread* cannot actually be cancelled (`Future.cancel()` is a documented no-op once work has begun; threads aren't interruptible). So wrapping `async with _HESTON_SEMAPHORE: await asyncio.wait_for(loop.run_in_executor(...), timeout=...)` releases the permit the instant the *caller's patience* runs out, while the abandoned job keeps occupying a real worker for however long it actually takes. Reproduced empirically while writing this plan: once workers are backlogged with slow, abandoned jobs, *every subsequent* calibration attempt is admitted past the semaphore (since permits free up on a timer that has nothing to do with real worker availability), queues behind an already-full executor, times out via its own `wait_for` before a worker is ever free, and falls back — the exact "most trade cards silently keep showing Delta approximation" failure mode rounds 2/3 were meant to close, just moved one level down.

Fix: decouple "the caller stops waiting" from "the resource is released." A separate helper function holds `_HESTON_SEMAPHORE` for the calibration's *real* lifetime, wrapped in its own `asyncio.Task`; the caller uses `asyncio.wait_for(asyncio.shield(task), timeout=...)` — `shield` stops the *caller's* timeout from cancelling the underlying task, so it keeps running (and keeps holding the semaphore) in the background until it genuinely finishes, even after the caller has given up and moved on with `heston_params=None`. This makes the semaphore an accurate reflection of real executor occupancy at all times: under sustained slow calibrations, new attempts correctly queue at the (cheap-to-abandon) asyncio semaphore rather than piling an ever-growing, invisible backlog into the (expensive-to-abandon) thread pool.

**Known limitation surfaced by audit round 5, accepted rather than further engineered (see the Post-merge note below for the honest version of this claim):** `run_scan` dispatches every symbol via a single `asyncio.gather(*tasks)` (`scan.py:917-941`), so under real scan-wide contention many symbols' `_HESTON_CALIBRATION_TIMEOUT_S` clocks all start at roughly the same instant, at task-creation time — not from when each one is actually admitted past the semaphore. So a symbol queued behind others can have its own budget largely or entirely consumed by *queueing*, not by a slow calibration, and give up the moment it's finally admitted (or before). Net effect: under heavy contention, the fraction of symbols that get real "Heston repriced" pricing in one scan is bounded by roughly how many complete within one `_HESTON_CALIBRATION_TIMEOUT_S`-sized window at `_SCAN_CONCURRENCY` throughput — waiting doesn't recover the rest, because their own deadline already passed. A "fairer" design (start each symbol's budget only once it's actually admitted, giving every symbol that eventually gets a worker a full shot) was explored while writing this plan and rejected: it requires either an unbounded per-symbol wait (defeating the whole point of a per-symbol ceiling) or a two-stage timeout, and a first attempt at the latter introduced a *worse* regression (the caller ends up blocking on the real job's full completion instead of giving up promptly). Given the safety properties that matter most here — no hangs, no resource leaks, a bounded wait per symbol — already hold, this plan accepts reduced Heston coverage under heavy contention as a known trade-off rather than adding more untested timeout machinery to chase it.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_scan_endpoint.py`, replace **exactly** the block from the line `# ── O-6: Remove Heston ────────────────────────────────────────────────────────` through the line `mock_heston.assert_not_called()` that immediately precedes it being followed by two blank lines and then `# ── O-2: Candle pre-warm endpoint ──` (currently lines 270-332 — the whole `test_process_symbol_does_not_call_calibrate_heston` function and its header comment). Do **not** touch the `# ── O-2: Candle pre-warm endpoint ──` section and everything after it (currently lines 335 onward) — it is unrelated and must be left exactly as-is. Search for the O-6 marker text rather than counting from the end of the file. Replace the bounded O-6 section with:

```python
# ── O-6 (superseded): Heston calibration wired back into the scan pipeline ────
# Originally removed for scan-loop performance (commit 99c51ed). WS-40 added an
# LRU cache + 1s timeout/BS-fallback (app/models/heston_cache.py) specifically so
# this could be reinstated safely — see docs/superpowers/plans/
# 2026-07-25-heston-pricing-in-trade-plan.md.

def _heston_wiring_fixtures():
    """Shared scaffolding for the tests below — mirrors the old O-6 test's mocks."""
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan

    pass_card = StockScoreCard(
        symbol="AAPL", direction="Bullish", horizon="Swing",
        score=75, status="PASS", rules=[],
    )
    contract_score = ContractScoreCard(
        contract_id="AAPL|190|2026-06-20|C",
        symbol="AAPL", strike=190.0, expiry="2026-06-20",
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = EntryAssessment(
        limit_price=2.50, max_fill=2.53, order_type="Limit", quality_status="PASS",
    )
    fake_plan = TradePlan(
        entry=entry_result,
        invalidation_price=180.0,
        premium_stop=1.5,
        time_stop_days=12,
        target_price=200.0,
        targets=[],
        rr_ratio=2.5,
        rr_model="Heston repriced",
        target_price_raw=200.0,
        invalidation_price_raw=180.0,
    )
    return pass_card, contract_score, fake_plan


@pytest.mark.asyncio
async def test_process_symbol_calls_calibrate_heston_with_the_chain():
    """calibrate_heston must run once per processed symbol, and its result must
    flow into build_trade_plan as heston_params."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration) as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_called_once()
    called_chain = mock_heston.call_args.args[0]
    called_price = mock_heston.call_args.args[1]
    assert called_chain == [{
        "strike": 190.0, "expiry_years": 30 / 365.0, "mid_price": 2.50, "is_call": True,
    }]
    assert called_price == 185.0
    assert mock_build_plan.call_args.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibrate_heston_raises():
    """A Heston calibration failure must not fail the whole symbol — build_trade_plan
    must still be called, with heston_params=None (delta approximation)."""
    from app.routers.scan import _process_symbol

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=RuntimeError("boom")),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert mock_build_plan.call_args.kwargs["heston_params"] is None
    assert result is not None  # symbol still produced a trade card, didn't crash


@pytest.mark.asyncio
async def test_heston_pricing_disabled_flag_skips_calibration(monkeypatch):
    """HESTON_PRICING_ENABLED=false must be a working kill switch."""
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol

    monkeypatch.setattr(scan_module, "_HESTON_PRICING_ENABLED", False)
    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston") as mock_heston,
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    mock_heston.assert_not_called()
    assert mock_build_plan.call_args.kwargs["heston_params"] is None


@pytest.mark.asyncio
async def test_process_symbol_falls_back_when_calibration_exceeds_timeout(monkeypatch):
    """A calibration that runs past the wait_for ceiling must not stall this
    symbol — build_trade_plan must still be called promptly, with
    heston_params=None. Regression guard for the audit-round-1 finding that
    heston_cache.py's internal 1s timeout does NOT bound real wall-clock time
    (its ThreadPoolExecutor.__exit__ blocks on shutdown(wait=True) regardless)."""
    import time
    import app.routers.scan as scan_module
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult

    # Shrink the call-site ceiling so the test itself stays fast; the fake
    # calibration below sleeps well past it.
    monkeypatch.setattr(scan_module, "_HESTON_CALIBRATION_TIMEOUT_S", 0.05)

    def _slow_calibrate(option_chain, S, r):
        time.sleep(0.5)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    start = time.perf_counter()
    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan) as mock_build_plan,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_slow_calibrate),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.4, f"_process_symbol took {elapsed:.3f}s — the wait_for ceiling did not bound it"
    assert mock_build_plan.call_args.kwargs["heston_params"] is None
    assert result is not None

    # By design (see _run_heston_calibration's docstring), the abandoned
    # calibration keeps running in the background and holds _HESTON_SEMAPHORE
    # until it actually finishes. Give it a moment to do so before this test
    # ends, so its event loop doesn't tear down with that task still pending.
    await asyncio.sleep(0.5)


_MULTI_MOCK_CHAIN = [
    {"strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
     "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30, "right": "C", "volume": 500},
    {"strike": 195, "expiry": "2026-06-20", "price": 1.80, "spread": 0.20,
     "delta": 0.35, "theta": -0.04, "ivRank": 55, "dte": 30, "right": "C", "volume": 400},
    {"strike": 200, "expiry": "2026-06-20", "price": 1.20, "spread": 0.20,
     "delta": 0.28, "theta": -0.03, "ivRank": 55, "dte": 30, "right": "C", "volume": 300},
]


@pytest.mark.asyncio
async def test_process_symbol_reuses_heston_params_for_alt_contracts():
    """The runner-up alternatives' estimate_rr calls (scan.py's alts loop) must
    reuse the SAME per-symbol calibration as the primary contract, not None.
    Uses a 3-contract chain so runner_ups (valid_scores[1:3]) is non-empty —
    _MOCK_CHAIN elsewhere in this file has only one contract and never
    exercises this loop at all."""
    from app.routers.scan import _process_symbol
    from app.models.heston import HestonParams, CalibrationResult
    from app.scoring.reward_risk import RrResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    fake_params = HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7)
    fake_calibration = CalibrationResult(params=fake_params, rmse=0.01, method="heston_grid")
    fake_rr = RrResult(rr_ratio=1.0, model_used="Heston repriced", estimated_exit_premium=3.0)

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MULTI_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.estimate_rr", return_value=fake_rr) as mock_estimate_rr,
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", return_value=fake_calibration),
    ):
        await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    # Primary contract (strike 190) is scored via build_trade_plan (mocked separately,
    # not estimate_rr) — only the two runner-ups (195, 200) call estimate_rr directly.
    assert mock_estimate_rr.call_count == 2
    for call in mock_estimate_rr.call_args_list:
        assert call.kwargs["heston_params"] == fake_params


@pytest.mark.asyncio
async def test_heston_calibration_respects_scan_concurrency_limit():
    """Regression guard for the round-2/round-3 audit findings that an
    ungated (or per-request-gated) executor could let far more than
    _SCAN_CONCURRENCY symbols calibrate at once, starving each other out via
    the wait_for ceiling. Calibration must be gated by the module-level
    _HESTON_SEMAPHORE (not the `sem` parameter passed in below, which only
    gates this function's own network-fetch phases) — so peak concurrent
    calibrations across many symbols processed at once, all sharing the
    process-wide _HESTON_SEMAPHORE, must never exceed _SCAN_CONCURRENCY. This
    also implicitly covers the round-3 cross-scan-overlap scenario: even if
    this test constructed a second, independent `sem` and ran a second batch
    of _process_symbol calls "concurrently" with these ones, they'd still
    share the same module-level _HESTON_SEMAPHORE and _HESTON_EXECUTOR."""
    import threading
    import time
    from app.routers.scan import _process_symbol, _SCAN_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    pass_card, contract_score, fake_plan = _heston_wiring_fixtures()
    sem = asyncio.Semaphore(_SCAN_CONCURRENCY)  # gates only this test's own network-fetch mocks
    mock_client = MagicMock()

    lock = threading.Lock()
    current = 0
    peak = 0

    def _tracking_calibrate(option_chain, S, r):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=fake_plan),
        patch("app.routers.scan.log_event"),
        patch("app.routers.scan.calibrate_heston", side_effect=_tracking_calibrate),
    ):
        await asyncio.gather(*[
            _process_symbol(f"SYM{i}", "Bullish", "Swing", mock_client, sem, "test-scan-id")
            for i in range(10)
        ])

    assert peak <= _SCAN_CONCURRENCY, f"peak concurrent calibrations was {peak}, expected <= {_SCAN_CONCURRENCY}"


@pytest.mark.asyncio
async def test_run_heston_calibration_holds_semaphore_until_real_completion():
    """Precise regression guard for the round-4 audit finding: a caller
    giving up early (simulated here exactly as the real call site does, via
    asyncio.wait_for(asyncio.shield(...), timeout=...)) must NOT release
    _HESTON_SEMAPHORE before the underlying calibrate_heston call actually
    finishes — otherwise a new attempt could be admitted while this one still
    occupies a real worker, defeating the point of gating by the semaphore
    at all."""
    import time
    from app.routers.scan import _run_heston_calibration, _HESTON_SEMAPHORE, _SCAN_CONCURRENCY
    from app.models.heston import HestonParams, CalibrationResult

    def _slow(option_chain, S, r):
        time.sleep(0.3)
        return CalibrationResult(
            params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
            rmse=0.0, method="heston_grid",
        )

    with patch("app.routers.scan.calibrate_heston", side_effect=_slow):
        task = asyncio.ensure_future(_run_heston_calibration([], 100.0))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        except asyncio.TimeoutError:
            pass  # the caller "gives up" here, exactly like _process_symbol does

        # The caller gave up, but the real job (0.3s) is still running — its
        # semaphore permit must NOT have been released yet.
        assert _HESTON_SEMAPHORE._value == _SCAN_CONCURRENCY - 1, (
            "semaphore permit was released before the underlying calibration "
            "actually finished — a new attempt could now be admitted while "
            "this one still occupies a real worker"
        )

        # Let the real job finish and release its permit, restoring full
        # capacity so this test doesn't leak state into later tests.
        await task
        assert _HESTON_SEMAPHORE._value == _SCAN_CONCURRENCY


def test_default_heston_calibration_fixture_is_active():
    """conftest.py's autouse _default_fast_heston_calibration fixture (added
    later in this same task, alongside the scan.py wiring below) must be
    patching app.routers.scan.calibrate_heston for every test by default —
    otherwise pre-existing multi-contract-chain tests elsewhere in the suite
    (test_alternatives.py, test_scan_router_spreads.py, test_shortlist.py)
    silently start doing real scipy numerical integration."""
    import app.routers.scan as scan_module
    from unittest.mock import Mock
    assert isinstance(scan_module.calibrate_heston, Mock)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_scan_endpoint.py -v -k heston`
Expected: all eight FAIL — six with `app.routers.scan.calibrate_heston` not existing yet (patch target error) or `build_trade_plan`/`estimate_rr` not being called with a `heston_params` kwarg reflecting real calibration, or `scan_module._HESTON_CALIBRATION_TIMEOUT_S` not existing yet (`AttributeError` from `monkeypatch.setattr`); `test_run_heston_calibration_holds_semaphore_until_real_completion` and `test_default_heston_calibration_fixture_is_active` fail differently, both with `ImportError`/`AttributeError` since `_run_heston_calibration` and `calibrate_heston` don't exist as importable names in `scan.py` at all yet.

- [ ] **Step 3: Implement the wiring**

In `backend/app/routers/scan.py`, add `import concurrent.futures` as its own line right after `import os` (line 5) — the file's current top imports are `import asyncio` / `import logging` / `import os` (lines 3-5) followed by `from datetime import datetime, timezone` (line 6).

Add to the imports further down (after line 61, `from app.scoring.trade_plan import build_trade_plan`):

```python
from app.models.heston import calibrate_heston, HestonParams
```

Add the kill-switch flag right after the imports, before `router = APIRouter(prefix='/api', tags=['scan'])` (line 68):

```python
# Kill switch: calibrating Heston changes every trade card's headline R/R number,
# so this can be flipped off instantly (no redeploy) if it misbehaves in
# production. Read once at import time, same pattern as heston_cache.py's
# _USE_FULL_GRID.
_HESTON_PRICING_ENABLED = os.getenv("HESTON_PRICING_ENABLED", "1").strip().lower() not in ("0", "false", "no")
```

Add the dedicated executor and timeout constant right after `_SCAN_CONCURRENCY = 5` (line 176), **not** near the imports — it must come after `_SCAN_CONCURRENCY` since it sizes itself off that constant:

```python
# calibrate_heston (via heston_cache.calibrate_cached) is a synchronous call
# that can block its calling thread far longer than its own internal 1s
# "timeout" suggests (that timeout only picks which result gets returned — the
# ThreadPoolExecutor context manager it runs in still blocks on
# shutdown(wait=True) for the real grid-search duration; see this plan's
# architecture notes). Safeguards against that, both scoped to this new call
# site only — heston_cache.py itself is untouched:
#   1. A small dedicated pool, sized to _SCAN_CONCURRENCY, so a pile-up of
#      slow calibrations can't starve asyncio's shared default executor (also
#      used by compute_confidence and _compute_dhmm in this same function).
#   2. Gating calibration behind a PROCESS-WIDE semaphore sized to match the
#      executor (see the calibration call site below) — this caps concurrent
#      calibrations at _SCAN_CONCURRENCY across the WHOLE process, not just
#      within one scan. Deliberately NOT the per-request `sem` parameter
#      _process_symbol receives: `semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)`
#      in run_scan() is created fresh on every call, but a scheduled scan
#      (scan_scheduler.py) and a manual POST /api/scan can run fully
#      concurrently (nothing serializes them — _state_lock only guards a few
#      lines of _last_request/_last_result bookkeeping, not scan execution) —
#      two independent per-request semaphores would let up to 2x
#      _SCAN_CONCURRENCY symbols contend for this single executor's workers
#      (round-3 audit finding).
#   3. A hard per-symbol wait_for ceiling, so one slow calibration can't stall
#      this symbol's scan processing — the abandoned calibration keeps running
#      in the background in _HESTON_EXECUTOR, but this symbol moves on with
#      heston_params=None (delta approximation) instead of waiting on it.
_HESTON_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_SCAN_CONCURRENCY, thread_name_prefix="heston-calib",
)
_HESTON_SEMAPHORE = asyncio.Semaphore(_SCAN_CONCURRENCY)
_HESTON_CALIBRATION_TIMEOUT_S = 2.0


async def _run_heston_calibration(heston_chain: list[dict], price: float):
    """Runs calibrate_heston under _HESTON_SEMAPHORE, held until the executor
    job ACTUALLY finishes — not just until a caller's wait_for gives up.
    calibrate_heston can't be truly cancelled once a worker has picked it up
    (concurrent.futures threads aren't interruptible), so releasing the
    semaphore the instant a caller times out — while the abandoned job keeps
    running — would let new calibration attempts queue behind already-busy
    workers indefinitely, all timing out without ever getting a worker
    (round-4 audit finding). Holding the semaphore for the job's real
    lifetime keeps it an accurate measure of real executor occupancy, so
    backpressure shows up as callers waiting on the (cheap-to-abandon)
    semaphore rather than an ever-growing (expensive-to-abandon) thread-pool
    backlog. Callers that want to give up early must wrap the returned
    coroutine's task in asyncio.wait_for(asyncio.shield(task), timeout=...) —
    shield stops their timeout from cancelling this function's own await, so
    it keeps running (and keeps holding the semaphore) in the background
    until it genuinely completes.
    """
    async with _HESTON_SEMAPHORE:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_HESTON_EXECUTOR, calibrate_heston, heston_chain, price, 0.05)
```

Replace `backend/app/routers/scan.py:515-529` (the `# ── Entry / Exit / Reward-risk / targets ...` block through the end of the `build_trade_plan(...)` call) with:

```python
    # ── Entry / Exit / Reward-risk / targets (shared with the recompute endpoint) ─
    _rr = _rr_cfg()
    strike = float(contract.get("strike", price))
    premium = max(float(contract.get("price", 0.10)), 0.01)

    # ── Heston calibration (best-effort) ───────────────────────────────────────
    heston_params: HestonParams | None = None
    if _HESTON_PRICING_ENABLED:
        try:
            heston_chain = [
                {
                    "strike": float(c.get("strike", 0)),
                    "expiry_years": c.get("dte", 30) / 365.0,
                    "mid_price": float(c.get("price", 0)),
                    "is_call": c.get("right", "C") == "C",
                }
                for c in chain
                if float(c.get("price", 0)) > 0
            ]
            # asyncio.shield keeps _run_heston_calibration (and the semaphore
            # permit it holds) running in the background even after this
            # wait_for gives up — see _run_heston_calibration's docstring.
            calibration_task = asyncio.ensure_future(_run_heston_calibration(heston_chain, price))
            heston_result = await asyncio.wait_for(
                asyncio.shield(calibration_task), timeout=_HESTON_CALIBRATION_TIMEOUT_S,
            )
            heston_params = heston_result.params
        except Exception as exc:
            _log.warning("Heston calibration failed or timed out for %s: %s", symbol, exc)
            heston_params = None

    _plan = build_trade_plan(
        direction=direction,
        stock_price=price,
        strike=strike,
        dte=int(contract.get("dte", 30)),
        premium=premium,
        delta=float(contract.get("delta", 0.45)),
        entry_bid=float(contract.get("bid", 0)),
        entry_ask=float(contract.get("ask", 0)),
        entry_mid=float(contract.get("price", 0)),
        rr_cfg=_rr,
        heston_params=heston_params,
    )
```

Then, in the runner-up alternatives loop (~line 680), change the hardcoded `heston_params=None,` inside the `estimate_rr(...)` call to `heston_params=heston_params,` — reusing the same symbol-level calibration computed above (calibration is per-underlying-chain, not per-strike, so it's valid to reuse across the primary contract and its alternatives).

**Prevent this change from silently making other pre-existing tests do real numerical calibration.** `calibrate_heston` is now a real, importable name in `app.routers.scan` — any pre-existing test that exercises the scan pipeline with a chain of 3+ contracts (`calibrate_cached`'s fast-path guard is `if len(chain) < 3:`, so exactly 3 already clears it) and doesn't mock `calibrate_heston` will start doing real `scipy` numerical integration instead of running as a hermetic, fully-mocked unit test. Confirmed this affects `backend/tests/test_alternatives.py` (`_MOCK_MULTI_CHAIN` has 3 contracts, all `dte=41`, unmocked). (Checked `test_scan_router_spreads.py` and `test_shortlist.py` too, since both also drive the scan pipeline — their Pass-2 primary chains only ever have 1 contract each, so they're not actually affected today; the 2-3 entry lists in `test_scan_router_spreads.py` are for `_build_spreads`'s separate spread-leg fetches, which never reach `calibrate_heston`. The fix below is a suite-wide default regardless, so it costs nothing to apply broadly and protects any future test that adds a 3+-contract chain without thinking about this.) Rather than patching each test file individually, add a suite-wide default in `backend/tests/conftest.py`, which already has an `autouse=True` fixture for a similar cross-cutting concern (`_reset_strategy_param_cache`, ~line 102) — add a new one right after it:

```python
@pytest.fixture(autouse=True)
def _default_fast_heston_calibration():
    """calibrate_heston became a real, callable name in app.routers.scan once
    the scan pipeline started calibrating it (docs/superpowers/plans/
    2026-07-25-heston-pricing-in-trade-plan.md). Default it to an instant
    canned result for every test so pre-existing tests with 3+-contract mock
    chains (test_alternatives.py, test_scan_router_spreads.py,
    test_shortlist.py) don't silently start doing real scipy numerical
    integration. Tests that specifically exercise the calibration wiring
    (test_scan_endpoint.py's Heston tests) override this locally with their
    own patch(...) inside a `with` block, which correctly takes precedence
    for its duration and reverts to this default afterward."""
    from app.models.heston import HestonParams, CalibrationResult
    fake = CalibrationResult(
        params=HestonParams(v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7),
        rmse=0.01, method="heston_grid",
    )
    with patch("app.routers.scan.calibrate_heston", return_value=fake):
        yield
```

(`test_default_heston_calibration_fixture_is_active`, written back in Step 1, is what verifies this fixture is actually active.)

**Release the dedicated executor on app shutdown.** `_HESTON_EXECUTOR` is a module-level `ThreadPoolExecutor` that's otherwise never explicitly released. `backend/app/main.py`'s `lifespan` context manager already has a `# ── Shutdown ──` section (~line 179) with a `try/except: pass` block per scheduler being torn down — add one more, right after the IBKR keep-alive block (~line 209, before `if _scheduler._running:`):

```python
    try:
        from app.routers.scan import _HESTON_EXECUTOR
        _HESTON_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
```

`wait=False` is deliberate — app shutdown must not block on a calibration that's still running; `cancel_futures=True` at least drops anything still queued (not yet started) instantly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scan_endpoint.py -v`
Expected: all PASS, including the eight new tests and every pre-existing test in the file (in particular `test_scan_with_mock_data_processes_symbol` and the O-1..O-5 tests must be unaffected). The timeout-fallback test's `_process_symbol` call should return in well under a second despite its fake calibration sleeping 0.5s in the background (the test then explicitly waits out that 0.5s afterward before finishing, to let the abandoned task release its semaphore permit cleanly) — if `_process_symbol` itself takes noticeably longer than ~0.1s to return, the `wait_for`/`shield` wiring isn't actually bounding the caller's wait. Also run `pytest tests/test_alternatives.py tests/test_scan_router_spreads.py tests/test_shortlist.py -v` and confirm they still pass and aren't noticeably slower than before this task — that's the conftest.py fixture doing its job.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/app/main.py backend/tests/conftest.py backend/tests/test_scan_endpoint.py
git commit -m "feat(scan): calibrate Heston per symbol and price trade-card targets with it"
```

---

### Task 5: Add a realistic-chain-size performance guard

**Files:**
- Modify: `backend/tests/test_heston_perf.py`

`test_heston_perf.py`'s existing bounds (`test_first_calibration_under_500ms`, `test_cache_hit_under_5ms`) only exercise a 5-contract, 2-expiry toy fixture. Task 4 now feeds `calibrate_heston` the entire raw chain surviving Pass 2's `dte_bounds` filter for every scanned symbol.

**Correction from audit round 2 — the realistic chain must be single-expiry, not multi-expiry.** Traced `fetch_option_chain`/`fetch_option_chain_async` (`backend/app/data/market.py`): both resolve exactly *one* `target_exp` via `_nearest_expiration_in_window` and return every surviving strike for that single expiration — the scan pipeline never hands `calibrate_heston` a chain spanning multiple expiries (there's no strike-count cap either, so a liquid name's single-expiry chain can easily be 40-80+ strikes). The test below models that shape — one shared `expiry_years`, many strikes — instead of the wrong multi-expiry surface an earlier draft of this plan used.

- [ ] **Step 1: Write the test**

Add to `backend/tests/test_heston_perf.py`:

```python
def test_realistic_single_expiry_chain_stays_within_call_site_timeout():
    """Task 4 in the scan pipeline caps calibration at a 2s wait_for ceiling
    (_HESTON_CALIBRATION_TIMEOUT_S in app/routers/scan.py). fetch_option_chain
    (app/data/market.py) always returns strikes from a SINGLE expiration, never
    a multi-expiry surface — model that shape here: one shared expiry_years,
    many strikes, using the default reduced grid (HESTON_FULL_CALIBRATION
    unset)."""
    _run_calibration.cache_clear()
    expiry_years = 45 / 365  # a mid-Swing-horizon single expiration
    strikes = [70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0, 130.0]
    chain = [
        {"strike": k, "expiry_years": expiry_years, "mid_price": max(0.5, 100 - k + 15), "is_call": True}
        for k in strikes
    ]
    start = time.perf_counter()
    result = calibrate_heston(chain, 100.0, 0.05)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, (
        f"Calibration on a {len(chain)}-strike single-expiry chain took {elapsed:.3f}s — "
        "exceeds the scan pipeline's 2s wait_for ceiling"
    )
    assert result.params is not None
```

- [ ] **Step 2: Run the test**

Run (from `backend/`): `pytest tests/test_heston_perf.py -v`
Expected: all PASS, including the new test. If it fails, that's a real signal `_HESTON_CALIBRATION_TIMEOUT_S` in Task 4 is set too low for realistic chain sizes and should be raised (or the reduced grid in `heston_cache.py` needs revisiting) before shipping — don't just loosen the test's own assertion to make it pass.

**Known modeling caveat (audit round 2, not resolved here):** calibrating Heston's 5 parameters (`v0, kappa, theta, sigma_v, rho`) against a *single* maturity's smile is inherently less well-identified than a real multi-expiry term-structure fit — `kappa`/`sigma_v` in particular are primarily pinned down by how the smile evolves *across* maturities, which a single-expiry chain can't provide. This is very likely the underlying cause of Task 1's reproduced non-monotonic-pricing artifact. Task 1's monotonicity guard defends the user-facing target ladder against the most visible symptom, but doesn't make the underlying calibration more accurate — "Heston repriced" should be read as "a best-effort improvement over the flat delta approximation," not as a guaranteed-more-accurate number. Fetching multiple expirations to build a real term structure would address this properly but is a materially larger change (more Tradier calls, different `fetch_option_chain` contract, latency implications) — out of scope here, flagged for Kenneth to decide on separately if the post-merge manual check (see below) shows this mattering in practice.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_heston_perf.py
git commit -m "test(heston): add a realistic chain-size performance guard"
```

---

### Task 6: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run (from `backend/`): `pytest`
Expected: all tests pass, no regressions in unrelated suites (contract validation, spreads, fundamentals, etc.).

- [ ] **Step 2: Run the targeted Heston/trade-plan suites once more together**

Run: `pytest tests/test_reward_risk.py tests/test_trade_plan.py tests/test_scan_endpoint.py tests/test_heston_perf.py -v`
Expected: all pass. `test_heston_perf.py`'s existing 500ms/5ms timing bounds are unmodified and must still hold (they test `calibrate_heston` directly, independent of this plan's changes).

---

## Post-merge note for Kenneth (not an automated step)

Once this is merged, run one real scan locally against a small universe (5-10 symbols) with live/paper Tradier credentials and check: (1) at least one trade card's `rrModel` reads "Heston repriced" rather than always "Delta approximation", (2) overall scan wall-clock time and Heston *coverage* — since `_HESTON_CALIBRATION_TIMEOUT_S` is measured per-symbol from when the scan dispatches it (not from when it's actually admitted past `_HESTON_SEMAPHORE`), waiting longer does not proportionally buy more coverage under contention (audit round 5): all symbols in a scan are launched together via `asyncio.gather`, so if Pass-2 survivors outnumber `_SCAN_CONCURRENCY` (5) within roughly one `_HESTON_CALIBRATION_TIMEOUT_S` window, the excess symbols' own deadlines can elapse while they're still queued for a worker, and they'll fall back to delta approximation almost immediately once admitted rather than getting a fair shot — so Heston coverage on a real, large universe (SP500/NDX100) may end up meaningfully lower than "everyone eventually gets priced, just slower." Check what fraction of PASS candidates actually end up "Heston repriced" vs. "Delta approximation" on a realistic universe size, not just whether at least one does. (3) no `Heston calibration failed or timed out for ...` warnings flooding the backend log, (4) spot-check a few trade cards' T1/T2/T3 sell-to-close targets for a sane, increasing ladder — Task 1's monotonicity guard should prevent an outright backwards one, but given the single-maturity calibration caveat (Task 5), it's worth an eyeball pass on a handful of real symbols rather than assuming the numbers are automatically more trustworthy than the old delta approximation. This can't be exercised by the automated test suite since it needs a real option chain. If coverage under real load turns out too low to be worth the added scan latency, or it ever needs to be turned off in a hurry, set `HESTON_PRICING_ENABLED=0` in the backend environment and restart — no code change needed.
