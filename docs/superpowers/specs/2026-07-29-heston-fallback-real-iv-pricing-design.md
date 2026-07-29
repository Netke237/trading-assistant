# Design: Real IV-Driven Fallback Pricing for Reward/Risk

**Date:** 2026-07-29
**Status:** Approved, pending implementation plan

## Problem

`backend/app/scoring/reward_risk.py`'s `estimate_rr()` and `estimate_targets()` reprice an
option at a hypothetical future stock price. The primary path uses Heston (when
`heston_params` is supplied and produces a usable price). When Heston is unavailable or
fails, both functions fall back to a crude linear guess:

```python
delta = 0.5 if is_call and target_price > strike else 0.3   # (direction-adjusted)
price_move = abs(target_price - stock_price)
exit_premium = current_premium + delta * price_move
```

This ignores the contract's actual volatility, moneyness curvature, and time decay. It also
means the `sigma_fallback: float = 0.25` parameter on both functions is dead code — declared,
documented, defaulted, but never read anywhere in either function body.

## Goal

Replace the crude fallback with a real Black-Scholes reprice, using the contract's own
market-implied volatility (derived from its current quote) rather than a hardcoded constant —
while keeping the change backend-only, with no plumbing changes to callers.

## Approach

The codebase already has what's needed in `backend/app/models/black_scholes.py`:
- `bs_iv(market_price, S, K, T, r, is_call)` — Newton-Raphson implied-vol solver, returns
  `None` on non-convergence or invalid inputs (never raises).
- `bs_price(S, K, T, r, sigma, is_call)` — standard Black-Scholes price, returns `0.0` on
  invalid inputs (never raises).

Both `estimate_rr` and `estimate_targets` already receive `current_premium`, `stock_price`,
`strike`, `expiry_years`, `is_call`, and `r` — enough to derive the contract's own
implied vol without any new parameters or caller changes.

### New fallback cascade (replaces the single crude-guess branch)

1. **Derive sigma from the contract's own quote:**
   `sigma = bs_iv(current_premium, stock_price, strike, expiry_years, r, is_call)`.
   This inverts the option's *current* market price at its *actual* remaining time
   (`expiry_years`, the full DTE) — the same time basis the quote was made at.

2. **Reprice at the target using that sigma:**
   `bs_price(target_price, strike, dte_at_target, r, sigma, is_call)`, where
   `dte_at_target = max(expiry_years * 0.5, 7/365)` — identical time basis already used by
   the Heston branch, so the two pricing paths stay consistent with each other.

3. **If `bs_iv` fails to converge** (returns `None` — e.g. degenerate or extreme-moneyness
   quotes): use `sigma_fallback` (default `0.25`) as the sigma for the same `bs_price()` call
   instead. This is what makes `sigma_fallback` a real, live default rather than dead code.

4. **If `bs_price` is still unusable** (non-finite or ≤ 0 — expected to be effectively
   unreachable given `T` is always ≥ `7/365` and `S`/`K` are already validated `> 0` by
   callers, but kept as a safety net rather than assumed impossible): fall back to the
   original crude delta-guess formula, exactly as today. This preserves the file's existing
   defense-in-depth philosophy (Heston → real-IV BS → constant-IV BS → delta guess), and the
   function never raises regardless of which tier ultimately produces the number.

### Structure

Two small private helpers in `reward_risk.py`, shared by both `estimate_rr` and
`estimate_targets` (avoids writing the same 4-tier cascade twice, and 3× inside
`estimate_targets`'s per-level loop):

- `_derive_fallback_sigma(current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback) -> float`
  — implements tiers 1 and 3 above (tries `bs_iv`, else `sigma_fallback`).
- A per-level reprice helper implementing tiers 2 and 4 — takes the already-derived sigma and
  produces a price, falling back to the crude delta guess only if `bs_price` itself is
  unusable.

**Lazy, once-per-ladder derivation in `estimate_targets`:** `current_premium`, `stock_price`,
`strike`, `expiry_years`, and `is_call` are identical across T1/T2/T3 — only `target_price`
changes per level. So `_derive_fallback_sigma` is called **at most once per `estimate_targets`
call**, on the first level that actually needs the fallback (not eagerly before the loop) —
if Heston succeeds for every level, the Newton-Raphson solve never runs at all. The derived
sigma is cached in a local variable and reused for any subsequent level that also needs the
fallback.

`estimate_rr` has only one target, so it calls `_derive_fallback_sigma` directly inline
when (and only when) the Heston path is unusable — no caching needed.

### Non-goals / explicitly out of scope

- **No label change.** The API/frontend-visible label stays `"Delta approximation"` /
  `PricingMethod.DELTA_APPROX` for this fallback tier — it's still honestly "the non-Heston
  path" from the caller's perspective, even though the formula underneath is now far more
  accurate. Renaming would require touching `backend/app/schemas/__init__.py`'s
  `PricingMethod` enum and `frontend/types/domain.ts`'s parallel string-literal unions
  (`TradeCard`, `ValidationTable`, and their tests) — a larger, cross-stack change
  deliberately deferred.
- **No changes to `trade_plan.py`, `scan.py`, `contracts.py`, or any frontend file.** All
  inputs the new logic needs are already parameters on `estimate_rr`/`estimate_targets`.
- **No changes to the Heston-vs-Heston monotonicity/artifact-floor logic** in
  `estimate_targets` (the `prev_heston_price`/`prev_display_price` chain). That logic only
  compares Heston prices against each other and the final displayed ladder; it is untouched
  by what happens inside the fallback branch.
- **No new IV clamping/sanity bounds** on the derived sigma. `bs_iv` either converges to a
  vol that reproduces the observed quote exactly, or returns `None` (handled by tier 3) — no
  extra bounds are added, consistent with how the rest of the codebase trusts `bs_iv`/vendor
  IV without additional clamping (e.g. `augment.py`'s BS-delta computation).

## Behavior change worth flagging explicitly

Because `dte_at_target` is *half* of `expiry_years`, a "target price == stock price" case no
longer trivially returns `current_premium` unchanged (as the old linear formula did) — it now
shows a genuinely time-decayed reprice. This is more realistic (an option loses time value
even with no stock movement), but it is a real behavior change. It does not break
`rr_ratio` (a decayed reprice still yields `reward <= 0`, which the existing early-return
guard already turns into `rr_ratio == 0.0`), but it does change the exact
`estimated_exit_premium` number in that scenario.

## Test impact

`backend/tests/test_reward_risk.py` has ~15 assertions that hardcode exact numeric outputs of
the *current* crude formula (e.g. `2.50 + 0.5×15 = 10.0`, `rr_ratio == 3.33`,
`estimatedOptionPrice == 13.75`) as part of testing fallback-chain *behavior* (monotonicity,
NaN/inf-safety, artifact-flooring, display clamping) — not because those tests are about the
formula's accuracy per se. Since the formula changes, these numbers must be recomputed against
the new implementation and updated, following this file's existing convention of documenting
values as "verified directly against the real pricer." The *behavioral* assertions themselves
(labels, monotonicity, NaN/inf-safety, which level uses which model) are unaffected and must
continue to pass unchanged.

One test (`test_estimate_exit_premium_rounded_on_zero_reward`) currently asserts
`estimated_exit_premium == 2.57` (== `current_premium` unchanged, from the old zero-move
identity). Per the behavior change above, this will need a new expected value reflecting
time-decayed BS repricing at `dte_at_target`.

No other test file (`test_trade_plan.py`, `test_multi_target.py`, `test_scan_router_spreads.py`,
`test_scan_scheduler.py`, `test_scan_endpoint.py`) hardcodes exact fallback-path numeric
outputs — they only assert on the `"Delta approximation"` label or mock `RrResult` directly,
both of which are unaffected by this change.

## Files touched

- `backend/app/scoring/reward_risk.py` — the fix (two new private helpers, both fallback
  branches rewired to use them).
- `backend/tests/test_reward_risk.py` — recompute and update ~15 exact-value assertions;
  behavioral assertions unchanged.
