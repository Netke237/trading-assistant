# Investigation: 100% Heston Fallback Rate on Long-Dated (6-Month) Scans

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

> **Status: INVESTIGATION ONLY — no implementation authorized.** This document identifies
> a root cause and lists remediation options with tradeoffs. It does not select one, and
> no code has been changed as part of this investigation. Implementation requires an
> explicit go-ahead.

## Question investigated

After decoupling Heston-calibration concurrency from Tradier-fetch concurrency
(`_HESTON_CONCURRENCY`, commit `4f3e835`), a live SP500 scan (Bullish, ~6-month
hold window) still showed **100% fallback to delta approximation — zero Heston
repricing** across all 20 candidates that reached the contract stage. This was
true both before and after the concurrency fix (confirmed by restarting the
backend to rule out stale-process contamination), which rules out queueing as
the cause for this scenario. This investigation traces the actual root cause.

## Evidence

### 1. A single calibration takes ~17s against a 1-2s budget

Directly timing `calibrate_heston()` (bypassing the timeout) for a real
candidate from the scan — AMD, strike 700, DTE 325 (a 6-month hold produces
`dte = hold_days * dte_holding_multiplier(2.0)`, landing contracts around
300-420 days out):

```
price=521.95
raw chain length: 128
distinct DTEs in chain: [325]
heston_chain length (price > 0): 128
calibrate_heston took 17.078s
result: method=bs_fallback, rmse=inf, ...
IntegrationWarning: The maximum number of subdivisions (100) has been achieved.
```

17s is ~8.5x the *outer* 2.0s budget (`_HESTON_CALIBRATION_TIMEOUT_S` in
`scan.py`) and ~17x the *inner* 1.0s budget (`_CALIBRATION_TIMEOUT` in
`heston_cache.py`). Both timeouts only decide which result gets *returned* —
per the existing code comments in `scan.py` (lines 234-238 and 279-297) and
`heston_cache.py`, the real computation keeps running to completion regardless
(the `with ThreadPoolExecutor(...) as pool:` block's implicit
`shutdown(wait=True)` blocks for the real duration even after the `except
TimeoutError` branch returns). So this is not a queueing symptom — a single
calibration is inherently 8-17x too slow for this scenario, and no amount of
worker concurrency changes that.

### 2. The slowness is not universal — it's moneyness- and grid-combo-dependent

Timing `heston_price()` directly with default, well-behaved params
(`v0=0.04, kappa=2.0, theta=0.04, sigma_v=0.3, rho=-0.7`) across a clean
0.7x-1.3x moneyness range at maturities from 7 to 420 days showed **no
slowdown and zero warnings at any maturity** (2-6ms/call throughout). So long
maturity alone is not sufficient to reproduce the problem — the effect only
shows up combined with the actual grid-search parameter space and the real
chain's strike range.

### 3. Isolating the grid: every one of the 16 grid combos is slow for the real chain

Timing each of the 16 `_run_calibration` grid combos (from
`heston_cache.py`'s reduced grid: `kappa∈{0.5,3.0}, theta∈{0.02,0.08},
sigma_v∈{0.2,0.6}, rho∈{-0.8,-0.2}`) against AMD's real 128-strike chain
(strikes $25-$1120, moneyness 0.05x-2.15x, at T=325 days):

```
kappa=0.5 theta=0.02 sigma_v=0.2 rho=-0.8:  1.092s, warnings=0
kappa=0.5 theta=0.02 sigma_v=0.2 rho=-0.2:  0.855s, warnings=0
kappa=0.5 theta=0.02 sigma_v=0.6 rho=-0.8:  2.690s, warnings=18  <-- worst
kappa=0.5 theta=0.02 sigma_v=0.6 rho=-0.2:  1.453s, warnings=0
kappa=0.5 theta=0.08 sigma_v=0.2 rho=-0.8:  0.844s, warnings=0
kappa=0.5 theta=0.08 sigma_v=0.2 rho=-0.2:  0.598s, warnings=0
kappa=0.5 theta=0.08 sigma_v=0.6 rho=-0.8:  1.630s, warnings=0
kappa=0.5 theta=0.08 sigma_v=0.6 rho=-0.2:  1.100s, warnings=0
kappa=3.0 theta=0.02 sigma_v=0.2 rho=-0.8:  0.853s, warnings=0
kappa=3.0 theta=0.02 sigma_v=0.2 rho=-0.2:  0.752s, warnings=0
kappa=3.0 theta=0.02 sigma_v=0.6 rho=-0.8:  1.541s, warnings=0
kappa=3.0 theta=0.02 sigma_v=0.6 rho=-0.2:  0.920s, warnings=0
kappa=3.0 theta=0.08 sigma_v=0.2 rho=-0.8:  0.624s, warnings=0
kappa=3.0 theta=0.08 sigma_v=0.2 rho=-0.2:  0.484s, warnings=0  <-- best
kappa=3.0 theta=0.08 sigma_v=0.6 rho=-0.8:  0.787s, warnings=0
kappa=3.0 theta=0.08 sigma_v=0.6 rho=-0.2:  0.613s, warnings=0
```
(all timings for the same 128-strike set)

Every combo took between 0.48s and 2.69s — summing all 16 values above gives
16.836s, close to the ~17.08s measured for the full `calibrate_heston()` call
(the small gap is ordinary run-to-run jitter, not a discrepancy — see finding
#5's note on timing variance). **This is not one pathological combo** — every
one of the 16 takes at least 0.48s for this chain, and the *average* per-call
cost even for the fastest combo (0.484s / 128 strikes ≈ 3.8ms/call) is
roughly in line with finding #2's clean-moneyness baseline (2-6ms/call) — so
the multi-second totals are not caused by a uniform slowdown across every
call. As finding #4 shows, the driver is a small subset of far-from-ATM
strikes each costing far more per call than the baseline; every grid combo
pays that same subset's cost (just weighted differently by each combo's own
parameters), which is why even the *fastest* combo still totals nearly half a
second and the worst totals 2.69s.

### 4. Per-strike breakdown: cost scales with distance from at-the-money

Timing the worst combo (`kappa=0.5, theta=0.02, sigma_v=0.6, rho=-0.8`)
strike-by-strike across the full chain:

| Moneyness (K/S) | Cost per call |
|---|---|
| 0.05 (deep ITM, K=$25) | 65 ms (2 integration warnings) |
| 0.19 (K=$100) | 35 ms |
| 0.50 (K=$260) | 17 ms |
| 1.00 (K=$520, ATM) | **3.6 ms** |
| 1.50 (K=$780) | 9 ms |
| 2.15 (deep OTM, K=$1120) | 17 ms |

Cost rises sharply as strikes move away from at-the-money, but asymmetrically:
the deep-ITM tail is ~18x the ATM baseline (65ms vs 3.6ms), while the deep-OTM
tail is a smaller ~4.7x (17ms vs 3.6ms) — "at the chain's extremes" understates
that these two tails differ by a factor of ~4 from each other, not just from
ATM. Explicit non-convergence warnings occur only at the 9 strikes from $25 to
$65 (in $5 increments — moneyness 0.048x-0.125x), each showing exactly 2
warnings (one per `quad()` call inside `heston_price`); every other strike in
the 128-strike chain showed zero warnings. The chain includes strikes far
outside the delta range ever actually used to select a real contract
(`contract_rules.yaml`: hard-reject delta band is 0.20-0.85, preferred band is
0.30-0.70) — a $25 strike against a $521.95 underlying at 325 DTE has a delta
far above 0.85, and would never itself be a candidate contract, yet it is
still included in the calibration input and costs the most to price.

**Caveat on generality:** this per-strike profile was measured on one symbol
(AMD), whose real chain happens to be unusually strike-rich (128 strikes
spanning 0.05x-2.15x moneyness). A large-cap with a narrower listed strike
ladder at the same DTE could show a smaller absolute slowdown — the
qualitative pattern (cost rises with distance from ATM) is expected to hold
generally, but the specific magnitudes above are demonstrated on this one name,
not surveyed across the universe.

### 5. Filtering to a moneyness band clears the outer budget but not the inner one — and the two timeouts have different, non-obvious consequences

Directly testing removal of the far strikes: filtering AMD's 128-strike chain
to the 0.7x-1.3x moneyness band used as the "clean" baseline in finding #2
keeps only 31 of 128 strikes (**76% removed**, not a smaller fraction) and cuts
the full 16-combo grid-search time from ~16.3s to ~1.6s (~10x, reproduced twice
independently — a second run measured 15.47s→1.55s, ~10x — the ~1-2s spread
across this document's several timings of the "same" unfiltered case is
ordinary run-to-run jitter on a live network+CPU-bound test, not a
discrepancy).

1.6s clears the *outer* 2.0s `_HESTON_CALIBRATION_TIMEOUT_S` budget in
`scan.py`, but is still above the *inner* 1.0s `_CALIBRATION_TIMEOUT` in
`heston_cache.py`. Tracing what that combination actually produces (not just
assuming it): `calibrate_cached()`'s `future.result(timeout=1.0)` raises at
t=1.0s, since real completion is at ~1.6s — this takes the `except
TimeoutError` branch, which computes a crude IV-seeded fallback
(`HestonParams` built from average implied vol only, not the grid search) and
commits to returning it. The real, properly-fitted grid-search result — which,
by simple subtraction of the two independently-measured constants above
(~1.6s total − 1.0s inner timeout ≈ 0.6s later), must finish computing while
the `with` block is already in its `except`-triggered exit — is silently
discarded; the function has already committed to the except branch's return
value. This "≈0.6s" figure is an arithmetic inference from the two measured
numbers, not a directly-instrumented timestamp of the discard moment itself.
The underlying claim — that `calibrate_cached()` returns the crude fallback,
not the real result, once the inner timeout fires first — was separately
confirmed directly: a synthetic reproduction (a slowed-down `heston_price`,
whose total real compute came out to ~2.0s, comfortably past the 1.0s inner
timeout) returned `method="bs_fallback"`, `rmse=inf`, with `.params` matching
the IV-seed formula exactly (`kappa=2.0, sigma_v=0.3, rho=-0.7`, `v0=theta=`
the average implied vol squared) — confirming that once the inner timeout
fires, the crude fallback is what `scan.py:694` receives, regardless of the
exact total elapsed time.

Critically, `scan.py:694` extracts only `.params` from whatever
`CalibrationResult` comes back (`heston_params =
calibration_task.result().params`) — `.method` and `.rmse` are discarded and
never reach `build_trade_plan` or `reward_risk.py`. Both
`estimate_rr`/`estimate_targets` (`reward_risk.py:35,121`) gate purely on
`heston_params is not None`, with no way to distinguish "a real 16-combo grid
fit" from "a crude single-point IV-seed guess" — both produce a non-None
`HestonParams` and both are labelled `"Heston repriced"` downstream.

So for **this specific investigated symptom** — "100% fallback to delta
approximation" — moneyness filtering alone (at the ~1.6s level measured here)
would fully resolve it: `heston_params` stops being `None`, so the
`"Delta approximation"` label stops appearing. But it does **not** deliver
genuine Heston-calibrated pricing at 1.6s — it silently substitutes the crude
IV-seed fallback, mislabelled as `"Heston repriced"` exactly as if it were a
real grid-search fit. Getting an *honestly* Heston-calibrated result (not just
avoiding the "Delta approximation" label) requires clearing the *inner* 1.0s
budget, not merely the outer 2.0s one — a materially stricter target than this
document originally assumed.

This also means the mislabelling mechanism is general, not specific to
moneyness filtering (Option A, below, under "Remediation options"):
**any** calibration whose *internal compute time inside `calibrate_cached()`*
— not the externally-observed total task latency `scan.py`'s `asyncio.wait`
sees, which also includes `_HESTON_SEMAPHORE` queueing wait before
`calibrate_cached()` even starts running — lands between 1.0s and 2.0s will
silently display "Heston repriced" while actually using the crude IV-seed
fallback, with no visible indication that it happened. This distinction
matters: a task queued behind other concurrent symbols could show ~1.5s of
*external* latency while its own actual compute is under 1.0s (correctly
Heston-priced), so external latency alone cannot be used as a proxy for
whether this mislabelling occurred without also accounting for queueing delay.

To be clear about which symptom was actually measured where: this
investigation's SP500 scan (see "Question investigated") found the *loud*
symptom — 100% `"Delta approximation"`, 0% `"Heston repriced"` — because every
candidate's real compute exceeded the *outer* 2.0s budget entirely (finding
#1). That scan could not have exhibited the *quiet* mislabelling mode
described in this paragraph, since the two are mutually exclusive by
definition (quiet mislabelling requires compute to land *under* 2.0s, which
none of this scan's candidates did). Whether the quiet mode occurs elsewhere
in the app — for symbols/horizons whose compute time lands in the 1.0-2.0s
band — was not measured at all in this investigation; see "What this
investigation did not do."

### 6. The existing calibration cache is unlikely to help in practice

`heston_cache.py`'s `_run_calibration` is wrapped in `@lru_cache(maxsize=256)`,
keyed by an MD5 hash (`_iv_surface_key`) computed over *every* strike's exact
`mid_price` in the chain, plus `S` and `r`. In live trading, option quotes
move continuously — a single strike's mid-price shifting by a cent between two
scans changes the hash entirely, invalidating the cache entry. So this cache
is structured to help only within a single scan's repeated lookups for the
same symbol (e.g., primary + alternate contracts reusing one calibration, per
`test_process_symbol_reuses_heston_params_for_alt_contracts`), not across
separate scans run minutes or hours apart, even though the underlying IV
surface likely hasn't meaningfully changed. This is not itself a cause of the
17s/100%-fallback symptom (a cache miss is expected and correct behavior for a
first calibration of a chain), but it means the current cache does not offset
the cost found above across repeated scans, and is a relevant consideration
for remediation option discussions below.

### 7. This is a known, already-partially-addressed symptom, not a new phenomenon

The most recent prior session's own work — `docs/superpowers/plans/2026-07-26-heston-ladder-floor-fix.md`
— independently documents and works around the *same* underlying fragility:
at DTE=185 (already a "long-dated" fixture, `stock_price=318.73, strike=375`),
`heston_price()` was found to return a **non-monotonic** raw ladder across
target prices (T1=12.52, T2=10.09 — a dip below T1 — T3=14.08), explicitly
described in that plan as "a numerical-integration artifact... for
deep-OTM/long-dated inputs." That fix floors the artifact value downstream in
`reward_risk.py` rather than addressing why `heston_price()` produces it. This
investigation's finding — severe slowness and occasional non-convergence
warnings at long DTE combined with far-from-ATM strikes — is a more extreme
manifestation of the same root fragility, now shown to also cause the
*timeout/fallback* symptom (not just the *non-monotonic* symptom), at 6-month+
holding horizons specifically.

## Root cause

`heston_price()`'s numerical integration
(`scipy.integrate.quad(lambda phi: _integrand(phi, j), 0, 500, limit=100)` in
`backend/app/models/heston.py:99-100`) converges reliably and quickly for
near-the-money strikes at any tested maturity, but converges slowly — and
occasionally fails to converge within the fixed 100-subdivision limit — for
strikes far from at-the-money, and this effect compounds with (rather than
being caused solely by) long time-to-expiry. The characteristic-function
formulation used (`backend/app/models/heston.py:45-58`) is the "original"
Heston (1993) form (`g = (kappa - rho*sigma_v*phi*i - d) / (kappa -
rho*sigma_v*phi*i + d)`, log term `cmath.log((1 - g*exp_dT)/(1 - g))`) rather
than the numerically robust reformulation described in Albrecher, Mayer,
Schoutens & Tistaert (2007), "The Little Heston Trap" — the well-documented
fix for exactly this class of symptom (the complex logarithm's argument can
wind around the origin as the integration variable `phi` varies, especially
for longer `T` or more extreme strikes, producing a discontinuous integrand
that adaptive quadrature struggles to resolve by subdivision). This
investigation did not implement or numerically verify the trap
reformulation against reference prices — it is cited as the standard,
literature-documented explanation consistent with every symptom observed
(slow convergence, occasional explicit non-convergence warnings, worse at
long T and extreme moneyness, absent at short T and near-ATM), not confirmed
by directly patching and re-testing. (Update 2026-07-28: this WAS
subsequently implemented and tested — see the Addendum at the end of this
document. Result: it is a no-op for this codebase's actual calibration
grid.)

Separately and compoundingly, `heston_chain` (`scan.py:663-672`) is built from
every chain entry with `price > 0`, with no moneyness or delta filter — so the
calibration grid search evaluates many strikes that would never themselves be
selected as the scored contract (real contract selection uses a 0.20-0.85 hard
delta band, 0.30-0.70 preferred), and those far-from-ATM strikes are
precisely the expensive ones per finding #4.

## Why the concurrency fix (commit 4f3e835) does not help this scenario

That fix reduces *queueing* wait — the time a symbol's calibration spends
waiting for a free worker before it can even start. It cannot make a single
already-running calibration finish faster. For short-horizon scans (per
`frontend/lib/horizonPresets.ts` and `dte_window.py`'s `max(1, round(hold *
multiplier))` floor: Intraday, hold 0-2 days → DTE ~1-4 days [the floor
clamps the hold=0 case up from 0 to 1, per `dte_window.py`'s own docstring];
Swing, hold 5-15 days → DTE ~10-30 days — not the `contract_rules.yaml`
static `hard_reject.min_dte:21`/`max_dte:90` fallback band, which only
applies when no horizon-derived override is supplied) where individual
calibrations are fast (per finding #2, no slowdown observed at any tested
maturity from 7 to 420 days with clean strikes) and many symbols
compete for calibration workers simultaneously, the concurrency fix is still
expected to help, consistent with the original diagnosis. For 6-month+ holds,
every individual calibration is already too slow on its own — concurrency is
irrelevant to that.

## Remediation options (not selected — for discussion)

**A. Filter `heston_chain` to a delta/moneyness-relevant band before calibrating.**
Restrict calibration inputs to strikes near the contract-selection delta band
(e.g., moneyness ~0.7x-1.3x, matching where finding #2's clean baseline showed
no slowdown even at long T) instead of every chain entry with `price > 0`.
Directly removes the most expensive strikes (finding #4) and reduces N in the
grid search's `O(combos × N)` cost — measured in finding #5 at ~10x for this
case (16.3s → 1.6s). That clears the *outer* 2.0s budget, which per finding #5
is enough to eliminate this investigation's literal symptom (the
`"Delta approximation"` label stops appearing, since `heston_params` stops
being `None`). It does **not** clear the *inner* 1.0s budget, so at this
specific filtering level the result would still be a crude IV-seed fallback
silently mislabelled `"Heston repriced"`, not a genuine grid-search fit (finding
#5). A tighter filter and/or fewer grid combos would be needed to also clear
the inner 1.0s budget if genuine calibration (not just avoiding the visible
fallback label) is the goal. Lowest engineering risk of the options here; does
not touch the pricer's math. Does not address whatever residual
slowness/non-convergence exists even near ATM at very long T (not observed in
this investigation's 420-day/clean-moneyness test, but that test used
well-behaved default params only, not the full 16-combo grid).

**B. Reformulate `_heston_char_fn` using the "Little Trap"-safe branch.**
Addresses the literature-documented root cause directly rather than avoiding
its expensive inputs. Higher engineering risk — requires careful validation
against known reference option prices (e.g., published Heston benchmark
values) to confirm the reformulation is both correct and actually faster/more
stable for this codebase's parameter ranges, not just in the general case.
Would also likely reduce or eliminate the non-monotonic "artifact" behavior
the ladder-floor fix currently works around downstream, though confirming
that is separate follow-up work, not part of this investigation.

**C. Replace or tune the numerical integration scheme.** Fixed-point
quadrature (e.g., Gauss-Laguerre) or a transform-based method (Carr-Madan
FFT, COS method) are standard alternatives for Heston pricing specifically
because they sidestep quad's adaptive-subdivision cost on hard integrands.
Largest engineering scope of the options listed; would replace, not patch,
the current pricing core.

**D. Reduce grid size for long-dated calibrations specifically.** Cuts total
time proportionally (fewer combos × same per-call cost) without addressing
why any individual call is slow. A mitigation, not a fix — would reduce but
likely not eliminate fallback at 6-month+ horizons, and does not touch the
already-known non-monotonic-artifact issue.

**E. Accept and document the limitation.** Leave current behavior as-is;
explicitly document that Heston pricing is only reliable/fast enough for
shorter horizons (Swing/Intraday) and that Position/6-month+ scans are
expected to run on delta approximation. Zero engineering cost, but leaves the
original motivation for adding Heston pricing to trade plans unmet for
longer-horizon users.

**F. Widen the calibration cache to survive across scans, not just within one.**
Per finding #6, the current `@lru_cache` key is invalidated by any strike's
mid-price moving by even a cent, so it never helps across separate scans in
practice even though the underlying IV surface changes slowly. A coarser key
(e.g., binned/rounded IVs, or a per-symbol-per-day cache with an explicit
staleness window) would let a slow first calibration be amortized across many
scans instead of re-paying the full cost every time. This does not make a
single calibration faster and does nothing for the very first calibration of
a session, but it changes the practical cost from "every scan" to "roughly
once per IV-surface change," which may matter more than any single-call
speedup for how often the fallback is actually seen in practice. Independent
of, and combinable with, any of Options A-D.

**G. Propagate `CalibrationResult.method` downstream so "Heston repriced" means what it says.**
Per finding #5, `scan.py:694` currently discards `.method`/`.rmse` and keeps
only `.params`, and `reward_risk.py` gates purely on `heston_params is not
None` — so a crude IV-seed fallback (`method="bs_fallback"`, `rmse=inf`) is
indistinguishable from a genuine 16-combo grid fit by the time it reaches the
trade card, and both display as `"Heston repriced"`. This is a distinct
problem from calibration *speed* (Options A-D address why calibration is
slow; this addresses what happens when it's slow enough to hit the *inner*
1.0s timeout but not the *outer* 2.0s one) — it is an honesty/labeling fix,
not a performance fix, and is combinable with any other option. Low
engineering risk in isolation (thread one more field through) — and lower
than it might first appear: `PricingMethod.UNAVAILABLE = "Unavailable"`
already exists in `backend/app/schemas/__init__.py:346` as a third label, but
is currently unused by any production code path (referenced only in
`backend/tests/test_multi_target.py:42`), so a more honest third label
already exists as unused scaffolding — this would be wiring an existing label
through, not designing a new one. Still changes what fraction of "Heston
repriced" labels the UI has shown historically would have actually read
"Delta approximation" or this third label had it been wired through from the
start — worth sizing that before committing to it, not just wiring the field
through.

## What this investigation did not do

- Did not modify `heston.py`, `heston_cache.py`, `scan.py`, or any other
  source file.
- Did not implement or test the "Little Trap" reformulation (Option B) — its
  applicability is asserted from the literature and consistency with observed
  symptoms, not confirmed by direct experiment. (Update 2026-07-28: this WAS
  subsequently tested — see the Addendum at the end of this document.)
- Did not isolate and re-time the remaining near-ATM strikes' cost at
  T=325d+full-grid on their own (finding #5 measured the filtered-vs-unfiltered
  totals, but did not further decompose the filtered set's residual cost by
  strike).
- Did not test whether the concurrency fix (commit 4f3e835) measurably helps
  short-horizon (Swing/Intraday) scans — flagged as a separate, still-open
  follow-up from the prior conversation.
- Did not survey symbols beyond AMD to confirm the magnitude (not just the
  qualitative direction) of the moneyness-cost relationship generalizes across
  the universe (see the caveat after finding #4).
- Did not design or evaluate a specific coarser cache-key scheme for Option F
  beyond naming the idea — no staleness window, binning granularity, or
  invalidation policy was worked out.
- Did not check how often the quieter mislabeling failure mode identified in
  finding #5 (internal compute time landing between the inner 1.0s and outer
  2.0s budgets, silently displaying a crude IV-seed fallback as `"Heston
  repriced"`) occurs elsewhere in the app today, for symbols/horizons outside
  this investigation's specific 6-month/SP500 scan. That scan measured 100%
  for the loud symptom (`"Delta approximation"` — every candidate's compute
  exceeded even the outer 2.0s budget, per finding #1), which is mutually
  exclusive with the quiet mode by definition (finding #5) — so the quiet
  mislabeling symptom was not, and could not have been, observed by that
  scan at all. Whether it occurs elsewhere was not measured, since checking
  it requires inspecting `CalibrationResult.method` — a field this
  investigation confirmed exists but that the current code never surfaces
  past `scan.py:694`.

## Addendum (2026-07-28): Option B tested and ruled out as a no-op (reduced grid only)

During preparation of `docs/superpowers/plans/2026-07-28-heston-moneyness-filter-and-honest-labeling.md`
(which implements Options A and G above), Option B was directly tested
before being scoped into that plan — and found to change nothing for this
codebase's default (reduced) calibration grid. This finding is now backed by
a permanent, committed regression test: `backend/tests/test_heston_char_fn.py`.

**What was tested:** the Little Heston Trap (Albrecher, Mayer, Schoutens &
Tistaert, 2007) causes a problem specifically when `|g|` — a term inside
`_heston_char_fn` (`backend/app/models/heston.py:47`) — exceeds 1, which
flips `cmath.log`'s principal-branch continuity as the integration variable
sweeps through. The literature's fix is to conditionally pick whichever root
of the pricer's `d` term (a `cmath.sqrt(...)` result, which always has two
valid roots) keeps `|g| <= 1`.

`|g|` depends only on `kappa`, `sigma_v`, `rho`, and the integration variable
`phi` — **not** on `theta` or time-to-expiry `T` (confirmed directly from
`_heston_char_fn`'s structure: `theta` enters only via `a = kappa*theta`,
used in the `C` term; `T` enters only via `exp_dT = exp(-d*T)`, used in `C`
and `D` — both computed strictly after `d` and `g`). So the parameter space
actually relevant to this trap condition is just `(kappa, sigma_v, rho)` ×
`phi`, not the full 16-combo `(kappa, theta, sigma_v, rho)` grid.

That conditional branch-selection fix was implemented in a standalone script
(the exploratory version; the verification itself is now reproducible via
`backend/tests/test_heston_char_fn.py`) and run against every
`(kappa, sigma_v, rho)` combination this codebase's **reduced** calibration
grid actually uses (the default when `HESTON_FULL_CALIBRATION` is unset) —
`kappa` ∈ {0.5, 3.0}, `sigma_v` ∈ {0.2, 0.6}, `rho` ∈ {-0.8, -0.2}
(`backend/app/models/heston_cache.py`) — scanning `|g|` across the full
integration domain (`phi` ∈ [0, 500], both the real-`phi` and `phi - 1j`
argument forms `heston_price` actually evaluates). **`HESTON_FULL_CALIBRATION=1`'s
full 3×3×3×3×3 grid (interior values like `kappa=1.5`, `sigma_v=0.4`) was NOT
tested** — that flag is off by default in this codebase.

**Result:** `|g|` peaked at ~0.996 — close to, but never crossing, 1 — so the
branch-selection condition never fires for the reduced grid. Directly
confirmed against the investigation's own pathological fixture (AMD,
deep-ITM K=25, the worst grid combo from finding #3, T=325 days): the
reformulated pricer produced a bit-identical price and the identical 2
integration warnings as the current code, both before and after. The same
held for the DTE=185 ladder-artifact fixture from
`docs/superpowers/plans/2026-07-26-heston-ladder-floor-fix.md` (T1/T2/T3
identical to the last digit). **Scope note:** `backend/tests/test_heston_char_fn.py`
only guards the `|g| < 1` bound stated above — the separate "bit-identical
price / identical warnings" claim in this paragraph is not backed by any
committed test and rests on the same uncommitted standalone script; a future
refactor of `_heston_char_fn` or the integration path would still be caught
by the committed test if it pushed `|g|` past 1, but would not be caught if
it broke the bit-identical-repricing claim specifically (low practical risk
today, since Option B's reformulation was never implemented, so there is no
reformulated code path to regress).

**Conclusion:** the branch-cut discontinuity this reformulation fixes does
not occur anywhere in this codebase's default parameter space, so
implementing it would not change the slowness, the integration warnings, or
the non-monotonic ladder artifact today. The residual slow-convergence
symptom (finding #4: cost rising sharply for strikes far from at-the-money)
is more consistent with a genuinely oscillatory integrand for those inputs —
closer to Option C's territory (a different integration scheme) than Option
B's. Because the observed `|g|` margin below the trap threshold is only
~0.4%, `backend/tests/test_heston_char_fn.py` is a permanent regression
guard, not a one-off check — if a future change widens the calibration grid
(e.g. adding a third `sigma_v` or `rho` value, or turning on
`HESTON_FULL_CALIBRATION` by default) pushes `|g|` past 1, that test fails
and Option B should be revisited then, with the full grid in scope.

Per the user's decision (2026-07-28), Option B is not implemented; the
residual slowness for symptoms not resolved by Options A/G is left as a
documented, known limitation (Option E) for this round. Options C, D, and F
remain unevaluated.
