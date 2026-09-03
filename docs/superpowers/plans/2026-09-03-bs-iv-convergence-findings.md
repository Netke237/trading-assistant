# `bs_iv` convergence investigation — findings

Target: `/home/user/trading-assistant/backend/app/models/black_scholes.py`, `bs_iv` (lines 107-151).
Repo source **not modified**. All scripts and outputs live in this scratchpad directory
(`sweep.py`, `analyse.py`, `refchain.py`, `driver.py`, `verify.py`, `sweep_raw.json`).

---

## Verdict

**No — `bs_iv` as it stands is not a safe basis for the new stop-cost gate.** It returns `None`
on **17.9%** of well-posed contracts overall and on **60–69% of the quotable OTM call wing**,
which is exactly the half of the chain the gate exists to discriminate; the reference chain
loses **2 of its 8 call strikes (230 and 240)**. The failure is a fixable solver-initialisation
defect, not a data problem: a bracketed `brentq` recovers every one of those cases to ~1e-7,
so the gate rewrite should land on a bracketed solver rather than on the current Newton loop.

---

## Environment

There is no `backend/.venv` in the repo, and the system `python3` (3.11, `/usr/local/bin/python3`)
has neither numpy nor scipy. I created a throwaway venv in the scratchpad
(`scratchpad/.venv`, CPython 3.11.15) with **numpy 2.4.6 + scipy 1.17.1** and ran everything there.
The repo's own `bs_price`/`_d1`/`_d2`/`bs_iv` were copied verbatim into `sweep.py`; the `bs_iv`
copy is instrumented to report which exit path fired. The repo file was never touched.

## Method

Round-trip isolation, as specified: choose a true sigma → `bs_price` → feed that price back to
`bs_iv` → check the sigma recovered and record the exit path (`low_vega` / `sigma_le_zero` /
`max_iter`). Grid: S=100, r=0.045, K/S ∈ 0.70…1.60 (17 points), DTE ∈ 1…400 (17 points),
true IV ∈ 0.10…1.20 (12 points), calls and puts = **6913 cases**. Separately, the project's
reference contract and its chain neighbours at S=201.86, DTE=45.

### One methodological guard, without which the numbers lie

Not every grid point is invertible *in principle*. A case is counted only if it is **well-posed**:
quotable (price ≥ $0.05) **and** its time value over the European no-arbitrage floor exceeds half
a cent. Below that the price carries no volatility information at all — a 1-DTE K/S=0.70 call
prices to 30.0086 for *every* sigma from 10% to 80%, identical to double precision, so no solver
can invert it. 4613 of 6913 cases are well-posed; the other 2300 are reported separately and
excluded from the failure rate. Failures counted below are genuine solver failures.

---

## Headline result (well-posed cases, n = 4613)

| solver | returns `None` | converged-but-wrong (>0.1% rel. err.) |
|---|---|---|
| repo Newton-Raphson | **825 (17.88%)** | **0** |
| `scipy.optimize.brentq` on sigma ∈ [1e-4, 5.0] | **0 (0.00%)** | **0** |

Exit paths on the 825 failures: `low_vega` **734**, `sigma_le_zero` **91**, `max_iter` **0**.

## The failure region

Failure is driven by the **Brenner-Subrahmanyam initial guess**, `sigma0 = sqrt(2π/T)·price/S`,
which is only valid at the money. Away from ATM the option is cheap relative to S, so `sigma0`
comes in far **too low**; `_d1` is then hugely negative, `norm.pdf(d1)` underflows, vega trips the
`< 1e-10` guard, and the function bails before it has taken a real step.

| | converged (n=3788) | failed (n=825) |
|---|---|---|
| `sigma0 / true IV` median | 1.228 | **0.117** |
| `sigma0 / true IV` p10 – p90 | 0.519 – 4.487 | 0.024 – 0.266 |
| cases with `sigma0 < 0.5 × trueIV` | — | **825 / 825 (100%)** |
| cases with `sigma0 > 2 × trueIV` | — | 0 |

Iterations completed before giving up: **0** in 515 cases, **1** in 307, 2 in two, 3 in one.
The `max_iter` cap **never fires**. This is not slow convergence — it is a first-step abort.

Failure rate by axis (well-posed): OTM/ITM wings, short DTE, and **low** IV are worst.

| true IV | 10% | 15% | 20% | 25% | 30% | 34.5% | 40% | 50% | 60% | 80% | 100% | 120% |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fail % | 20.1 | 21.0 | 23.3 | 22.8 | 21.5 | 21.5 | 20.3 | 18.0 | 16.8 | 14.3 | 12.8 | 11.9 |

Calls 433/2293 (18.9%), puts 392/2320 (16.9%). Every failure is `low_vega` or `sigma_le_zero`.

Moneyness × DTE, well-posed failures / well-posed cases (all IVs, calls+puts). ATM is
perfectly safe; both wings fail, and the region widens as DTE shortens:

| K/S \ DTE | 1 | 3 | 7 | 14 | 30 | 45 | 90 | 180 | 365 |
|---|---|---|---|---|---|---|---|---|---|
| 0.70 | – | – | 1/3 | 2/5 | 4/9 | 5/11 | 6/15 | 7/19 | 7/21 |
| 0.85 | 0/1 | 2/5 | 4/9 | 4/12 | 5/17 | 6/19 | 5/21 | 5/23 | 4/24 |
| 0.95 | 4/9 | 4/16 | 4/19 | 3/21 | 2/23 | 3/24 | 2/24 | 1/24 | 1/24 |
| **1.00** | **0/24** | **0/24** | **0/24** | **0/24** | **0/24** | **0/24** | **0/24** | **0/24** | **0/24** |
| 1.05 | 3/10 | 4/16 | 4/20 | 3/23 | 2/24 | 1/24 | 0/24 | 0/24 | 0/24 |
| 1.15 | 0/2 | 3/7 | 5/11 | 5/15 | 5/19 | 5/21 | 4/23 | 3/24 | 1/24 |
| 1.30 | – | 0/2 | 2/5 | 4/9 | 5/13 | 5/15 | 6/19 | 5/21 | 4/24 |
| 1.60 | – | – | 0/1 | 2/5 | 3/7 | 4/9 | 5/14 | 5/17 | 6/21 |

---

## The reference chain — **yes, it is affected**

S = 201.86, DTE = 45, r = 0.045, strikes 195/200/205/210/215/220/230/240, prices rounded to
cents, on a mild downside-skew surface anchored so K=215 sits at ~34.5% (`refchain.py`).

| K | true IV | mid | Newton | exit path | Brent |
|---|---|---|---|---|---|
| 195 | 0.3553 | 14.32 | 0.355454 | ok | 0.355454 |
| 200 | 0.3476 | 11.31 | 0.347768 | ok | 0.347768 |
| 205 | 0.3408 | 8.71 | 0.340847 | ok | 0.340847 |
| 210 | 0.3348 | 6.53 | 0.334626 | ok | 0.334626 |
| 215 | 0.3295 | 4.77 | 0.329445 | ok | 0.329445 |
| 220 | 0.3250 | 3.39 | 0.324927 | ok | 0.324927 |
| **230** | 0.3178 | **1.58** | **None** | **low_vega** | 0.317785 |
| **240** | 0.3130 | **0.67** | **None** | **low_vega** | 0.313200 |

**2 of the 8 call strikes return no IV — and they are the two cheapest OTM calls, the exact
strikes the old `|stop−spot|×|delta|` gate could not tell apart.** The gate would replace a cap
that pins 4 of 8 strikes at 100% with a "not computed" on the 2 strikes that matter most.
The 8 puts all invert (they are ITM at these strikes, hence vega-rich).

The **committed fixture contract itself converges**: `bs_iv(5.20, 201.86, 215, 45/365, 0.045, True)`
→ `0.346096` in 3 iterations, matching Brent to 1e-6 and round-tripping to $5.200008. So a unit
test written only against that single contract **passes and hides the defect entirely**.

The chain breaks the moment you move off it. Same 8 strikes, calls, flat IV, varying the two
free parameters (`ok` = converges, `vega` = `low_vega`, `sig<=0` = `sigma_le_zero`, `unq` = sub-tick):

IV sweep at 45 DTE:

| K \ IV | 10% | 15% | 20% | 25% | 34.5% | 50% | 70% | 100% |
|---|---|---|---|---|---|---|---|---|
| 195–205 | ok | ok | ok | ok | ok | ok | ok | ok |
| 210 | **vega** | ok | ok | ok | ok | ok | ok | ok |
| 215 | **vega** | **vega** | ok | ok | ok | ok | ok | ok |
| 220 | unq | **vega** | **vega** | **vega** | ok | ok | ok | ok |
| 230 | unq | unq | **vega** | **vega** | **vega** | ok | ok | ok |
| 240 | unq | unq | unq | **vega** | **vega** | **vega** | ok | ok |

DTE sweep at IV = 34.5%:

| K \ DTE | 3 | 5 | 7 | 14 | 21 | 30 | 45 | 90 | 180 |
|---|---|---|---|---|---|---|---|---|---|
| 195–205 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| 210 | **vega** | **vega** | ok | ok | ok | ok | ok | ok | ok |
| 215 | **vega** | **vega** | **vega** | **vega** | **sig<=0** | ok | ok | ok | ok |
| 220 | unq | **vega** | **vega** | **vega** | **vega** | **sig<=0** | ok | ok | ok |
| 230 | unq | unq | unq | **vega** | **vega** | **vega** | **vega** | ok | ok |
| 240 | unq | unq | unq | unq | **vega** | **vega** | **vega** | **vega** | ok |

At 21 DTE, K=215 is already the last passing strike — the gate would be blind above roughly
6.5% OTM on weekly-to-monthly expiries.

## Full-chain census (S=201.86, $2.50 strikes, ±20%, skewed surface, cent-rounded)

| DTE | side | quotable | Newton `None` | Brent `None` | failing strike band |
|---|---|---|---|---|---|
| 7 | calls | 25 | 7 (28.0%) | 2* | 163.98 – 221.48 |
| 7 | puts | 29 | 10 (34.5%) | 4* | 181.48 – 251.48 |
| 21 | calls | 33 | 11 (33.3%) | 0 | 216.48 – 241.48 |
| 21 | puts | 37 | 11 (29.7%) | 0 | 161.48 – 186.48 |
| 45 | calls | 37 | 12 (32.4%) | 0 | 223.98 – 251.48 |
| 45 | puts | 37 | 9 (24.3%) | 0 | 161.48 – 181.48 |
| 90 | calls | 37 | 8 (21.6%) | 0 | 233.98 – 251.48 |
| 90 | puts | 37 | 6 (16.2%) | 0 | 161.48 – 173.98 |

\* Verified in `verify.py`: all six Brent `None`s are deep-ITM contracts whose **cent-rounded mid
falls 0.0003–0.0038 below the European no-arbitrage floor**. Those inputs are arbitrage-violating,
`None` is the correct answer, and Newton returns `None` there too. Brent has **zero** genuine
solver failures anywhere in the sweep.

Restricting to the wing the gate is built to rank:

| DTE | quotable OTM calls | Newton `None` | share of the OTM wing that renders "not computed" |
|---|---|---|---|
| 7 | 8 | 5 | **62.5%** |
| 21 | 16 | 11 | **68.8%** |
| 45 | 20 | 12 | **60.0%** |
| 90 | 20 | 8 | **40.0%** |

The suspicion in the brief was correct and, if anything, understated.

## Converged-but-inaccurate cases

**On well-posed inputs there are none — zero, for both solvers.** When Newton returns a number
that number is correct to well inside 0.1%. The hazard here is silence, not a silently wrong IV.

One caveat, outside the well-posed set: on the 2300 **ill-posed** cases (sub-tick or pure-intrinsic
prices) Newton returns a confidently wrong sigma **1399 times** — e.g. a 1-DTE K/S=0.70 call at
$30.0086 returns `1.383823` regardless of whether the truth was 10% or 80%. Brent does the same
thing 429 times (it returns its `lo` bound). Such contracts should never reach the gate, but
neither solver detects the condition, so **whichever solver is used, the gate should refuse to
invert a contract whose mid is under the no-arbitrage floor plus a tick** rather than trusting the
returned number. The bracketed prototype already surfaces this as an explicit `below_intrinsic`
outcome, which is the cheapest place to enforce it.

## Bracketed solver: before / after, and recommendation

Prototype (`bs_iv_brent` in `sweep.py`): evaluate `f(sigma) = bs_price(...) − market_price` at
`lo = 1e-4` and `hi = 5.0`; if `f(lo) > 0` the price is below the no-arb floor → `None`; if
`f(hi) < 0` the implied vol exceeds 500% → `None`; otherwise `brentq(f, lo, hi, xtol=1e-8)`.

| metric (well-posed, n=4613) | Newton (current) | brentq (prototype) |
|---|---|---|
| `None` returned | 825 (17.88%) | **0 (0.00%)** |
| reference chain calls failing | 2 / 8 | **0 / 8** |
| OTM call wing at 45 DTE failing | 12 / 20 (60%) | **0 / 20** |
| converged-but-wrong | 0 | 0 |
| accuracy vs true sigma (exact price input) | — | ≤ **5.4e-7** absolute |
| cost | 451 µs/contract | 958 µs/contract |

Accuracy on the reference OTM wing with cent-rounded mids is ~2e-4 absolute in IV — and
`verify.py` attributes essentially all of that to the cent rounding of the input mid, not to the
solver (feeding the unrounded price gives ≤ 5.4e-7). That residual is a property of penny-quoted
cheap options and applies to any solver.

**Recommendation.** Replace the Newton loop with the bracketed solve, or — if the ~2.1x cost
matters — keep Newton as a fast path and fall back to `brentq` on any of its three `None` exits;
that is exact, since Newton is verified never to return a wrong answer on well-posed input, so
the fallback only ever runs where Newton produced nothing. Either way, keep the existing "null IV
renders as not computed" contract: it still fires correctly for genuine no-arb violations and for
true IV above the bracket, which is what it should have been reserved for all along. Also widen
or make configurable the `hi` bound — 5.0 is ample for equities but returns `None` above 500% IV
(verified: trueIV 4.9 recovers, 5.5 does not).

## What I could not establish

- **No live market data.** Everything is synthetic round-trip. The "realistic chain" uses a
  hand-built skewed surface anchored to the project's 34.5% reference, not a fetched Tradier /
  Tastytrade chain. The *shape* of the failure region is a property of the solver and is
  data-independent, but the exact per-chain failure percentages would shift with a real surface,
  real bid/ask widths, and real strike spacing.
- **No downstream gate code exists yet**, so I could not measure how a `None` actually renders or
  how many candidates a real scan would drop. I quantified the input side only.
- **European vs American.** `bs_price` is European with no dividend term. Real US equity options
  are American, so ITM puts especially carry a model bias that a round-trip test cannot see by
  construction — it is invisible here because the same wrong model is used in both directions.
  That is a basis question for the gate rewrite, separate from convergence.
- I did not test `bs_iv`'s other callers, exotic `r` values (only r = 0.045), or negative rates.
- The 451 vs 958 µs timings are dominated by `scipy.stats.norm` overhead in this venv and should
  not be read as a tuned benchmark.
