# Phase F — Heston: the pricer first, then the calibration (Q8)

**Date:** 2026-09-12 · **Status:** **F1 BUILT** (see §0a). F2 still spec-only.
**Decision it implements:** Q8, recorded as a paragraph in
`2026-09-03-remaining-stop-model-implementation-plan.md` §Phase F and never written up.
**Build order:** F1 before F2. F2 alone is a no-op — measured below, not asserted.

---

## 0a. Addendum, 2026-09-12 — what building F1 changed about this document

F1 shipped. Its core derivation (§2) held up exactly: against an independently written
reference (the two-CF form reaching P1 via `b₁ = κ − ρσ`, `u₁ = +½` rather than the
Bakshi–Madan shift), the corrected pricer agrees to **0.000000%** over 112 points. But an
adversarial audit round falsified two of this document's own claims and sharpened three more:

1. **§2.2's "the quadrature limits (`500`, `limit=100`) … are measured sufficient" is FALSE.**
   The integrands decay as `exp(−½·v·T·φ²)`, so the frequency beyond which they are negligible
   scales as `1/√(v·T)`. A fixed cutoff of 500 is ample at ordinary variance and expiry and
   **0.769% wrong at `v0=0.01, θ=0.02`, 1 DTE, at the money** (0.432088 vs a true 0.435434).
   That regime is reachable: `v0=0.01` is in the grid under `HESTON_FULL_CALIBRATION`,
   `scan.py`'s `heston_chain` passes every expiry including weeklies, and **F2's chain seeding
   will reach it by default on any low-IV underlying.** F1 as built therefore makes the cutoff
   adaptive — `min(max(500, √(50/(v·T))), 20000)` at `v = min(v0, θ)`, `limit=200`. Worst error
   over 324 cases falls from 0.769% to **0.00218%** at **1.00x latency** (at the production
   default `v0=θ=0.04` the formula returns < 500 for every expiry, so nothing changes there).
   This also cut the worst out-of-band below-forward-intrinsic shortfall from 0.127316 to
   0.002235 — the two were the same defect.

2. **§4's "worth shipping alone … corrects every number on every card" is MISLEADING, and this
   is the most important line in this addendum.** F1 corrects the *pricer*. It does not correct
   the *card*, because `v0_grid = [0.04]` is untouched until F2. Running the shipped reduced
   grid through the **post-F1** pricer on this document's own reference chain:

   | | post-F1 Heston rel-RMSE | flat-BS baseline | verdict |
   |---|---|---|---|
   | 45 DTE (10 in-band strikes) | 0.645 | 0.197 | **3.27x worse than one flat vol** |
   | 180 DTE (35 in-band strikes) | 0.754 | 0.563 | **1.34x worse than one flat vol** |

   Per-strike, post-F1 Heston sits **27% to 100% BELOW** the market mid across the whole band
   (45 DTE: −40.7% at K=205 to −85.1% at K=180; 180 DTE: −27.2% at K=205 to −100.0% at K≥370),
   and `scan.py` still accepts `method == "heston_grid"` and labels it "Heston repriced". So the
   defect's *direction* flipped — the card was wrong HIGH (+1.13 R/R on a losing trade), it is
   now wrong LOW — and F1 remains a large net improvement, because the pricer error it removes
   (451%–2782%) dwarfs the calibration error it leaves. **But no "Heston repriced" number should
   be trusted until F2 lands.** §3.3's baseline gate is precisely what makes shipping a fit
   seven times worse than a flat vol impossible. F2 is not optional polish; it is the other half
   of one defect.

3. **§5.3's table listed four pinned tests; SIX pinned pricer output.** The two it missed:
   `test_estimate_rr_put_heston_path_uses_correct_model_label` (exit premium 14.19 → 9.84, R/R
   10.16 → 6.53) and, in another file,
   `test_trade_plan.py::test_heston_params_floors_non_monotonic_target_instead_of_falling_back`
   (12.47 / 12.47 / 15.34 → 4.57 / 9.10 / 15.48). Like §5.3's row 1, the latter lost its premise
   entirely and is renamed. Reverting the integrand now fails exactly those six and nothing
   else, so the set is closed.

4. **§5.1's test 2 (put-call parity) tests nothing about this bug.** Called "independent of
   check 1"; it is independent of nothing, because `heston_price` derives the put from the call
   by parity, so parity holds by construction — the pre-F1 code passes it to 1.4e-14 while
   being wrong by 83161%. The same is true of the no-arbitrage bounds check added during the
   build. Both are retained as structural guards and both now say so in their own docstrings.
   **Neither carries correctness.**

5. **§5.1 as written was mutation-weak.** Tests 1 and 4 pin the pricer only where it degenerates
   to Black-Scholes (`σ_v = 0.01, ρ = 0`) and test 3 constrains shape, not level — so
   **inverting the sign of `ρ`, which destroys the entire skew and is the only reason Heston is
   in this codebase, passed every test in §5.1.** F1 as built adds reference-pinned values at
   `σ_v = 0.5, ρ = −0.7`, an explicit `ρ`-sensitivity test, and short-expiry/low-variance
   coverage. A four-mutation battery (`ρ` flipped; `K*` dropped; the `S·e^{rT}` normaliser
   dropped; the cutoff reverted to 500) now fails 4 / 13 / 13 / 1 cases; before these additions
   the `ρ` flip failed none.

---

## 0. The plan's premise is wrong, and the correction changes the whole phase

The standing plan says:

> `heston_cache.py:36` has `v0_grid = [0.04]` — one value, 20% vol, hardcoded for every symbol on
> every scan, while the reference contract has 34.5% IV. **The pricer is fine; the calibration is the
> defect.**

The first half is true. The bolded half is false, and it is false by a margin that dwarfs the
calibration defect. `heston_price` (`backend/app/models/heston.py:61`) is wrong everywhere except
at-the-money — by **+451%** at 45 DTE and **+2782%** at 180 DTE on strikes *inside the delta band the
scanner actually ranks*.

Measured on the reference chain (spot 201.86, 34.5% ATM IV with a realistic skew), restricted to
`|delta| ∈ [0.15, 0.90]` — the exact band `scan.py` feeds the calibrator (`contract_rules.yaml`
hard-reject 0.20/0.85, widened by `_HESTON_DELTA_SAFETY_MARGIN = 0.05`), at
`v0=0.1287, κ=2.0, θ=0.09, σ_v=0.5, ρ=−0.7`:

| 45 DTE, K | 180 P | 185 P | 190 P | 195 P | 200 P | 205 C | 210 C | 215 C | 220 C | 225 C |
|---|---|---|---|---|---|---|---|---|---|---|
| \|delta\| | 0.18 | 0.23 | 0.28 | 0.35 | 0.43 | 0.49 | 0.41 | 0.33 | 0.25 | 0.19 |
| shipped | 13.455 | 10.967 | 9.168 | 8.339 | 8.786 | 8.871 | 7.449 | 7.430 | 8.438 | 10.029 |
| correct | 2.439 | 3.447 | 4.749 | 6.386 | 8.391 | 8.905 | 6.727 | 4.937 | 3.513 | 2.418 |
| error | **+451%** | +218% | +93% | +31% | +5% | −0.4% | +11% | +51% | +140% | **+315%** |

At 180 DTE the same band spans 0.69x–1.36x moneyness and the worst in-band error is **+2782%**
(K=140 put: 48.38 shipped vs 1.68 correct).

Two things follow, and they set this phase's shape:

1. **The error is U-shaped in strike and near-zero only at the money.** Every downstream workaround
   built around "a numerical-integration artifact for deep-OTM/long-dated inputs" — the ladder floor
   in `reward_risk.py:236-240`, the tests that pin it — is describing this bug.
2. **Seeding `v0` from the chain's IV does nothing until the pricer is fixed.** On the full reference
   chain, the shipped pricer's best absolute-dollar RMSE is **9.009** with the hardcoded
   `v0_grid=[0.04]` and **9.051** with the IV seed. The prescribed Q8 fix, applied alone, makes the
   fit *marginally worse*. Under the corrected pricer the same two runs are **2.674** and **0.443**.

---

## 1. What reaches the user

`scan.py` discards `method="bs_fallback"` results, so a card labelled "Heston repriced" is always a
real grid fit — priced by the broken integrand. That number is the exit premium in the target ladder
and the numerator of the R/R ratio.

On the fixture already in this repo (`test_trade_plan.py`'s `_plan()`: spot 318.73, K 375, 185 DTE,
premium 7.47, target 344.23, `premium_stop_pct` 0.60), run through the real `estimate_rr`:

| | exit premium | R/R shown |
|---|---|---|
| shipped | 12.52 | **+1.13** |
| pricer corrected, same params | 3.80 | **−0.82** |

The card recommends, at +1.13 R/R, a trade whose first target leaves the position under water. This
is a wrong number in front of a user and on the basis of which an order gets sent: gate-level by
`audit_rule`, without argument.

The same fixture's ladder is the one `test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact`
calls a reproduced numerical artifact:

| target | 344.23 | 356.98 | 369.73 |
|---|---|---|---|
| shipped | 12.519 | 10.086 ← "artifact dip" | 14.081 |
| corrected | 3.797 | 8.036 | 14.236 |

**The corrected ladder is strictly monotonic.** The artifact is the bug; there is no residual quirk
for the floor to catch on this fixture.

---

## 2. The pricer defect, derived

`_heston_char_fn` is **correct and stays untouched**. It returns

```
g(φ) = exp(C + D·v0 + i·φ·x),   x = ln(S/K)
```

i.e. it already folds the strike in: `g(φ) = f₂(φ)·e^{−iφ·lnK}`, where `f₂` is the log-price
characteristic function. It also already uses the Little-Trap-safe branch (`g` paired with
`exp(−dT)`), which is why `test_heston_char_fn.py` passes and stays valid.

The caller re-applies the strike and the spot. `heston_price`'s `_integrand` (lines 87-96) computes

```python
char  = _heston_char_fn(phi - 1j*j, ...)          # = g(φ − i·j)
denom = 1j*phi * cmath.exp(1j*phi*math.log(K))
return (cmath.exp(1j*phi*math.log(S)) * char / denom).real
```

Collecting the moneyness exponents with `φ' = φ − i·j`:

```
  iφ·lnS  +  iφ'·ln(S/K)  −  iφ·lnK
= iφ·lnS − iφ·lnK + iφ·ln(S/K) + j·ln(S/K)
= 2iφ·ln(S/K)  +  j·ln(S/K)
```

Two defects in one line:

- **The oscillation frequency is doubled** — `2φ·ln(S/K)` where the Fourier inversion needs
  `φ·ln(S/K)`. This is why the error is zero at `K = S` (where `ln(S/K) = 0`, so the doubling is
  invisible) and grows monotonically with `|ln(S/K)|` in both directions.
- **A spurious real factor `(S/K)^j`** multiplies `P1`.

A third, independent defect: `P1` under the Bakshi–Madan shift needs dividing by `f₂(−i) = S·e^{rT}`.
The shipped code never does.

The doubled frequency is also the *whole* of finding #4 in
`2026-07-27-heston-long-dte-slowness-investigation.md` ("cost scales with distance from
at-the-money"): `quad` subdivides against an integrand oscillating twice as fast as it should.

### 2.1 The fix

Leave `_heston_char_fn` alone. Replace `_integrand` and the two `quad` calls:

```python
def _integrand(phi: float, j: int) -> float:
    if phi == 0.0:
        phi = 1e-12
    g = _heston_char_fn(complex(phi) - complex(0, j), S, K, T, r, params)
    if j == 1:
        # P1 = 1/2 + (1/pi) ∫ Re[ e^{-i φ lnK} f2(φ-i) / (i φ f2(-i)) ] dφ.
        # _heston_char_fn already carries e^{-i φ' lnK}, so
        #   e^{-i φ lnK} f2(φ-i) == K * g(φ-i),  and  f2(-i) == S·e^{rT}.
        return (K * g / (complex(0, phi) * S * math.exp(r * T))).real
    # P2 = 1/2 + (1/pi) ∫ Re[ g(φ) / (i φ) ] dφ — no extra factors at all.
    return (g / complex(0, phi)).real

p1, _ = integrate.quad(lambda phi: _integrand(phi, 1), 1e-10, 500, limit=100)
p2, _ = integrate.quad(lambda phi: _integrand(phi, 0), 1e-10, 500, limit=100)
```

Everything else in `heston_price` — the degenerate-input guard, the `except` → `bs_price` fallback,
the put-call parity tail — is unchanged.

> ~~The quadrature limits (`500`, `limit=100`) are unchanged and are **measured sufficient**
> after the fix; see §2.2.~~ **FALSE — corrected in §0a.1.** A fixed cutoff of 500 is 0.769%
> wrong at `v0=0.01, θ=0.02`, 1 DTE, at the money. F1 as built makes the cutoff adaptive:
> `min(max(500, √(50/(v·T))), 20000)` at `v = min(v0, θ)`, with `limit=200`.

### 2.2 The fix is exact, and it is faster

Verified against an independently written reference (trap-safe Albrecher form, `epsabs=epsrel=1e-12`,
`limit=2000`, written from the literature rather than from this file):

| check | result |
|---|---|
| `σ_v → 0` must collapse to Black-Scholes at `√v0` — 24 points over 7/45/180/365 DTE × 150–275 strikes | worst relative error **0.0132%** |
| vs. the independent reference at `v0=0.1287, κ=2, θ=0.09, σ_v=0.5, ρ=−0.7`, 12 points over 45 and 180 DTE, 140–275 strikes | worst **0.0000%** |
| cost, 29 strikes × one param set | 45 DTE **1.33x faster**, 180 DTE 1.22x, 365 DTE 1.22x |

The shipped code fails the first check by **+11.19** on a **1.998** option (K=180 put, 45 DTE,
`σ_v=0.01`). The correct integrand needs *fewer* `quad` subdivisions, so this is a correctness fix
that pays for itself in latency — no timeout budget needs renegotiating.

---

## 3. The calibration defects

Three, in the order they cost accuracy.

### 3.1 `v0_grid = [0.04]` — one seed, 20% vol, every symbol

`heston_cache.py:36`. The correct seed exists twice in the same file (lines 90 and 105) and is
reachable only on the two fallback paths, which `scan.py` then throws away.

`v0` is the **instantaneous** variance; the chain states it directly. On the 45-DTE reference band
chain the chain's own IV says `v0 = 0.1245` (35.28% vol). The grid offers `0.04` (20.00%) — and
`HESTON_FULL_CALIBRATION=1`, off by default, only widens it to `[0.01, 0.04, 0.09]`, whose top rung
is still 30% vol. No setting of the shipped code can seed this chain correctly.

Measured, absolute-dollar RMSE on the in-band chains — the row that matters is that fixing the seed
*without* fixing the pricer is worthless:

| | 45 DTE (10 strikes) | 180 DTE (28 strikes) |
|---|---|---|
| shipped pricer + `v0=[0.04]` | 4.912 | 15.594 |
| corrected pricer + `v0=[0.04]` | 3.068 | 6.238 |
| corrected pricer + `v0=[chain seed]` | **0.279** | **2.747** |
| flat-BS baseline (best single σ) | 0.701 | 3.904 |

**Seed rule.** Derive `v0` from the chain with the **bracketed** solver `_compute_iv_bs`
(`app/data/market.py:942`), not `bs_iv`. `bs_iv`'s Newton loop returns `None` on most of this chain —
**6/15 solved at 30 DTE, 8/15 at 45 DTE**, always dropping the wings — so the existing fallback seed
is a mean over a survivor subset. `_compute_iv_bs` solves **15/15** at every DTE and recovers the true
chain mean to 0.02 vol points (35.90% vs 35.88% at 30 DTE).

> **Unit trap, to be pinned by a test.** `_compute_iv_bs(mid, S, K, dte, is_call, r)` takes `dte` in
> **days**. The calibration chain dicts carry `expiry_years`. Passing `expiry_years` straight through
> yields a seed of `v0 = 46.94` (685% vol) instead of `0.1288` — confirmed by running it. Multiply by
> 365 at the call site.

### 3.2 The objective is absolute dollars

`rmse = sqrt(sse/valid)` over `(model − mid)²` lets one $20 in-the-money contract outweigh ten $1
wing contracts, while the wings carry the smile the extra four Heston parameters exist to fit. Use
the **relative** residual `(model − mid)/mid`, minimised the same way.

On the reference chains relative and absolute happen to select the same winner, so this is specified
as the correct objective rather than as a measured improvement:

| | rel-RMSE of the abs-RMSE winner | rel-RMSE winner |
|---|---|---|
| 45 DTE | 0.0796 | 0.0796 (same params) |
| 180 DTE | 0.3163 | 0.3163 (same params) |

Vega weighting was the other option named in the plan. **Rejected**: it needs a vega, which needs a
per-contract IV, which is a second solve per strike per grid point inside the hot loop, for a
weighting that relative error already approximates on this chain shape. Revisit only if §6's
measurement says relative error fits the wings badly.

### 3.3 Nothing checks whether Heston is worth using

**The plan's phrase "beats the BS-own-IV baseline on the same chain" cannot be implemented as
written.** Black-Scholes priced at each contract's *own* implied volatility reproduces every mid by
construction: measured RMSE **0.000005**. Nothing can beat it, and the gate would reject Heston
always.

The honest comparator is **one flat vol for the whole chain** — the model Heston has to justify
replacing, fitted the same way and on the same residual:

```
baseline_sigma = argmin_σ  RMSE_rel( bs_price(S, K, T, r, σ, is_call),  mid )   over the chain
```

**Gate:** return `method="heston_grid"` only when `rel_rmse_heston < rel_rmse_flat_bs`. Otherwise
return the flat-BS σ as `HestonParams(v0=σ², κ=2.0, θ=σ², σ_v=0.3, ρ=−0.7)` with a new
`method="bs_flat"`, which `scan.py` discards exactly as it discards `bs_fallback` today (it tests
`== "heston_grid"`, so no call-site change is needed for the discard to work — but see §5, the label
must still be added to the docstring and the `CalibrationResult.method` comment).

Measured, relative RMSE, corrected pricer, chain seed:

| | Heston | flat-BS baseline | verdict |
|---|---|---|---|
| 45 DTE | **0.0796** | 0.2003 | Heston passes, 2.5x better |
| 180 DTE | **0.3163** | 0.4020 | Heston passes, 1.3x better |

Under the *shipped* pricer the 45-DTE fit is 4.912 abs-RMSE against a 0.701 baseline — **seven times
worse than a single flat volatility, and shipped to the card anyway.** The gate is what makes that
impossible to repeat.

---

## 4. Scope, batches, and what is deliberately not in them

`audit_rule` names batch size as the root cause of long audit loops: one layer, ~500 lines. Two
batches, both inside `backend/app/models/`.

**F1 — the pricer.** `heston.py::heston_price::_integrand` and its two `quad` calls. Roughly 15 lines
of source. Plus the golden tests in §5.1 and the rewrite of the ladder tests in §5.3. **Ships alone**:
a large net improvement with no calibration change at all, because the pricer error it removes
(451%–2782%) dwarfs the calibration error it leaves.

> ~~it corrects every number on every card that says "Heston repriced"~~ — **NO. See §0a.2.**
> With `v0_grid = [0.04]` still in place the post-F1 fit is 3.27x (45 DTE) and 1.34x (180 DTE)
> WORSE than a single flat volatility, and prices 27%–100% BELOW the market mid across the band.
> The card's error changes direction, not existence. F2 is the other half of the defect.

**F2 — the calibration.** `heston_cache.py`: the seed, the relative objective, the flat-BS baseline
and the `bs_flat` method. Only after F1 is merged and clean.

**Not in this phase.** Each is a real observation; none of them is the defect this phase exists to
close, and folding them in is exactly the over-fixing `audit_rule` v2 forbids.

- **The ladder floor** (`reward_risk.py:214-260`) and its two "artifact" tests. F1 makes the floor
  a no-op on the one real fixture in the suite, but "no artifact on this fixture" is not "no artifact
  anywhere", and the floor only ever raises a level. Leave it. Re-measure after F1 has run against
  live chains, then propose removing it as its own change.
- **`_CALIBRATION_TIMEOUT` does not bound latency.** `calibrate_cached`'s `with
  ThreadPoolExecutor(...)` block calls `shutdown(wait=True)` on the way out, so the `except
  TimeoutError` branch still blocks for the full grid search. Already known, already worked around at
  the only call site (`scan.py:241-287`), and F1 makes the grid *cheaper*, not more expensive.
- **The `lru_cache` key is redundant and spot-sensitive.** `_run_calibration(iv_key, chain_repr, S,
  r)` — `chain_repr` already determines `iv_key`, and `S` is unrounded, so a one-cent move in spot is
  a cache miss while `_iv_surface_key` was carefully written to round it. Finding #6 of the slowness
  investigation already says the cache rarely helps; this is why.
- **`heston_iv` is dead code.** It computes `h_price`, tests it, and returns `bs_iv(...)` on both
  branches. No caller outside `heston.py`. No wrong number — below the gate.
- **The grid finds the edge of the box, not a minimum.** With the corrected pricer the winner is
  `θ` at its maximum, `σ_v` at its maximum and `ρ` at its minimum in every run measured here,
  including when `θ`'s grid is re-anchored to `[0.5x, 1x, 2x]` the seed (45 DTE rel-RMSE improves
  0.0919 → 0.0700 on the same seed, and `θ` still lands on the top rung). Three of five dimensions pinned at a boundary
  is a box that is too small, not a fit. The winning combo also violates the Feller condition
  (`2κθ = 0.08 < σ_v² = 0.36`), which the closed form tolerates but which says the same thing.
  **Deliberately left alone**: widening the grid or adding a refinement pass is a latency decision
  and a second change, and the §3.3 baseline gate already stops a bad fit from reaching a card. See
  §6.

---

## 5. Tests

### 5.1 F1 — the golden tests that make this un-regressable

1. **`σ_v → 0` collapses to Black-Scholes.** For `v0 = θ`, `σ_v = 0.01`, `ρ = 0`, assert
   `heston_price ≈ bs_price(S, K, T, r, √v0, is_call)` within 0.1% relative (measured worst:
   0.0132%) across at least `DTE ∈ {7, 45, 180, 365}` × `K/S ∈ {0.74, 0.89, 0.99, 1.02, 1.14, 1.36}`
   × both rights. **This is the test the shipped code fails by 560%**, and it needs no external
   reference data to state.
2. **Put-call parity.** `C − P == S − K·e^{−rT}` for the same grid, to 1e-6. Cheap.
   ~~Independent of check 1.~~ **Independent of nothing — see §0a.4.** `heston_price` derives
   the put from the call by parity, so this holds by construction; the pre-F1 code passes it to
   1.4e-14. A structural guard, not a correctness check.
3. **Monotonicity in spot.** For fixed `K, T, params`, a call's price is non-decreasing in `S` and a
   put's non-increasing, over a spot ladder spanning 0.7x–1.4x. This is the invariant the ladder
   floor was written to fake; pin it at the source.
4. **The U-shape is gone.** On the §0 reference chain, assert no in-band strike deviates from the
   `σ_v → 0` Black-Scholes value by more than 1% — the shipped code's deviations run to 451%.

Do **not** pin reference Heston prices copied from a paper: the parameterisation conventions differ
and a mismatched convention produces a test that is wrong in the same direction as the code. Checks
1-3 are self-contained invariants.

### 5.2 F2

5. `v0` seeding: a chain built at a known flat IV calibrates to `v0` within one grid step of `IV²`,
   and **not** to 0.04.
6. The unit trap: feeding `expiry_years` where `_compute_iv_bs` wants days must be impossible —
   assert the seed for a 35% chain lands near 0.1225, not near 47.
7. The baseline gate: a chain generated *from Black-Scholes at one flat vol* (which Heston cannot
   beat, because the baseline reproduces it exactly) returns `method="bs_flat"`, not
   `"heston_grid"`. A chain with a real smile returns `"heston_grid"`.
8. `scan.py` discards `bs_flat`: assert `_calibration_result.method == "heston_grid"` remains the
   only accepted label, so a `bs_flat` result can never be shown as "Heston repriced".

### 5.3 Existing tests that F1 must rewrite, not delete

> **INCOMPLETE: six tests pinned pricer output, not four. See §0a.3.**

These pin exact prices produced by the broken integrand. Each keeps its behavioural assertion; only
the numbers change, and the docstrings that call the dip "a real, reproducible quirk of
`heston_price()`'s integration" must be corrected to name the bug and this spec.

| test | pinned today | under F1 |
|---|---|---|
| `test_estimate_targets_real_fixture_preserves_t3_after_t2_artifact` | 12.52 / 12.52 / 14.08 | 3.80 / 8.04 / 14.24 — **naturally monotonic, no floor fires** |
| `test_estimate_targets_put_heston_ladder_happy_path` | 2.52 / 10.16 / 20.78 | 2.48 / 7.30 / 14.26 |
| `test_estimate_targets_floors_non_monotonic_heston_price_instead_of_switching_models` | T1 15.9 | T1 10.82 (raw ladder 10.82 / 17.96 / 25.40) |
| `test_estimate_targets_put_floors_non_monotonic_heston_price` | T1 2.52 | T1 2.48 |

The two `_flaky` monkeypatch tests keep working unchanged in structure — they force the dip
artificially, which is the right way to test a floor. The **first** row is the one that loses its
premise: its fixture no longer produces a natural artifact, so it must be rewritten as "a clean
ladder stays clean and every level stays labelled Heston repriced", and the artifact-preservation
behaviour it used to cover is already covered by the two `_flaky` tests.

`test_heston_char_fn.py` **stays valid and unchanged**: `_heston_char_fn` is untouched and `P1` still
evaluates it at `φ − i`.

`test_heston_perf.py`'s timing assertions should get *faster*, not slower. If any regresses,
stop — the fix has been mis-transcribed.

---

## 6. Open questions — Kenneth's call, none blocking F1

1. **Which chain IV seeds `v0` — the mean or the ATM strike?** Both beat 0.04 by an order of
   magnitude, and on the two reference chains they disagree about which is better (45 DTE: mean 0.0796
   vs ATM 0.0919; 180 DTE: mean 0.3163 vs ATM 0.3744 — mean wins both, which is the opposite of the
   theory, because the delta band at 180 DTE reaches far enough into the wings to pull the mean up
   toward the smile). One synthetic chain does not settle this. **Proposed: ship the mean (it wins
   both measurements here), and log the ATM alternative as unmeasured**, in the same register as
   Phase A's seeded-but-unmeasured IV thresholds.
2. **Widen or refine the grid?** §4 measures three of five parameters pinned at a boundary. A
   `[0.5x, 1x, 2x]` anchoring of `θ` alone takes the 45-DTE in-band fit from rel-RMSE 0.0919 to
   0.0700 on the same (ATM) seed — 24% better, and the best figure measured anywhere in this
   document — for 50% more combos (16 → 24, 0.24s → 0.36s). A local refinement pass around the coarse winner would buy more
   and cost more. Out of F2 as specified; worth its own measured decision after F2 lands.
3. **Remove the ladder floor?** Only after F1 has run against live chains for long enough to say the
   artifact never appears, not on the strength of one fixture.

---

## 7. Reproducing every number here

All measurements in this document come from one synthetic chain, chosen so anyone can regenerate it:

```python
S, r = 201.86, 0.05                      # the gate-basis spec's reference chain
ATM, SKEW, CURV = 0.345, 0.45, 1.6       # 34.5% ATM IV, realistic equity skew
true_iv(K) = ATM + SKEW * (-ln(K/S)) + CURV * ln(K/S)**2
mid(K)     = round(bs_price(S, K, T, r, true_iv(K), is_call=(K >= S)), 2)
```

Strikes every $5; a strike is *in band* when `|bs_delta| ∈ [0.15, 0.90]`. The correctness reference
is a separately written trap-safe Heston (`d`, `g2 = (b − ρσiφ − d)/(b − ρσiφ + d)`, `exp(−dT)`,
`b = κ − ρσ` for `P1` and `κ` for `P2`), integrated with `epsabs = epsrel = 1e-12, limit = 2000`,
and validated by the same `σ_v → 0` collapse before being trusted.

A synthetic chain is the right instrument for *this* phase and the wrong one for §6: it proves the
pricer is wrong (the `σ_v → 0` invariant needs no market data at all) and it cannot settle which
seed fits real skew best. §6.1 stays open for that reason.
