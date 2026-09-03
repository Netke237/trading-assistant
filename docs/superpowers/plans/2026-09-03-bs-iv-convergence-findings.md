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

---

# Amendment A — adversarial audit, 2026-09-03

An independent adversarial review re-derived every load-bearing number in this document from
scratch, against the real `bs_iv`, without reusing the scripts above. Appended rather than
rewritten, following the Barrier Race spec's precedent: the original reasoning stays readable,
including where it was wrong.

## A.1 What survived

- **The load-bearing claim holds.** 230C and 240C return `None` via the low-vega exit — reproduced
  on an independently constructed flat-34.5% chain as well as on the original surface.
- Headline numbers reproduce exactly: 4613 well-posed, 825 Newton failures (17.88%), brentq 0.
- **The "well-posed" filter is honest and self-penalising.** Unfiltered Newton failure is
  **20.76%** — *higher* than the filtered 17.88%. The filter made the result look better for the
  code, not worse.
- The fixture-contract trap is real: 215C inverts in 3 iterations, so a test written against it
  alone passes and hides everything.

## A.2 What was wrong

**The verdict stands, but partly for the wrong reason, and the recommendation does not stand.**

1. **"The hazard is silence, not a wrong number" is false**, and it was the most reassuring
   sentence here. It is an artifact of round-tripping European prices. Real **American ITM puts**
   trade at or above `K − S`, which on this underlying exceeds the European price: a K=250 put at
   mid 38.19/48.19 inverts to **0.3739 / 0.4413** against a true 0.345 — silently, no `None`, in
   both solvers. The guard proposed below does not catch it, because those mids sit *above* the
   European floor. A confidently wrong IV is worse than a refusal, and this document said the
   opposite.

2. **The root cause is incomplete.** "Vega trips the guard before iterating" explains roughly
   two-thirds. For the rest — **including K=230** — the seed's vega (1.2e-4) *passes* the 1e-10
   guard, and Newton then overshoots to sigma ≈ 1.7e4 where `d1` is **+2286.7**, hugely positive.
   The document's own "307 failures at iteration 1" row contradicts its "aborts at iteration 0"
   sentence.

3. **The hybrid recommendation is unjustified.** It traded correctness risk for a speed cost that
   does not exist: `brentq` over a `math.erf` normal runs at **24.3 µs/contract against today's
   Newton at 494 µs** — 20× *faster* than the status quo, because the real cost is `scipy.stats.norm`,
   not the solver. Plain brentq wins outright. There is no case for Newton-first.

4. **A seed change alone fixes most of it.** Corrado-Miller in place of Brenner-Subrahmanyam takes
   17.88% → **2.58%** with no new solver. This document never evaluated the fix its own root-cause
   analysis implies.

5. **`bs_iv` may not be on Phase A's critical path at all.** `backend/app/data/market.py:598`
   already reads Tradier's **per-contract `implied_volatility`** — and line 615 discards it into
   `"ivRank": int(round(iv * 100))`, a field named for a percentile. Sourcing Phase A's `iv` from
   the provider sidesteps the solver entirely for the gate.
   **Nuance the audit missed:** that field is *conditionally overwritten* at `market.py:629`/`:643`
   with a genuine IV rank from IBKR or Tastytrade when those are available, so `ivRank` currently
   means raw IV×100 on some rows and a true percentile on others. Phase A must capture `iv` into
   its own field *before* that overwrite — it cannot just read `ivRank`. The conflation is a
   pre-existing data-integrity bug in its own right and should be fixed alongside, not inherited.

6. **Blast radius understated.** `bs_iv` has four live production call sites — `reward_risk.py:33`,
   `first_passage.py:374`, `heston_cache.py:87,102`, `heston.py:134,137` — and committed tests pin
   exact outputs (e.g. `bs_iv(2.50, 185, 190, 30/365, 0.05, True) = 0.200202`). "Replace the Newton
   loop" is **not a drop-in**. It also reframes the severity: 230C/240C already fall back to
   `sigma_fallback = 0.25` against a true 0.345 **in production today**, so this is a current
   defect, not only a future blocker.

7. **The surviving caveat is unimplementable as written** — it does not say which floor (European
   or American, and for puts it must be American), "a tick" versus the half-cent actually
   validated, or whether the guard belongs inside `bs_iv` or at the four call sites.

8. **`scipy` was already available**, which was this document's own best argument and it missed it:
   `scipy==1.17.1` is pinned in `backend/requirements.txt` and `from scipy.stats import norm` is
   already imported at `black_scholes.py:6`. The "no venv, no scipy" note in Environment above
   describes the session, not the project.

9. **The gate's constant-IV assumption is unexamined and asymmetric.** Holding IV fixed at the stop
   reads 215C at 71.2% versus 53.0% at +6 vol points (conservative, safe), but 190P at 67.1% versus
   **84.0%** at −6 points (optimistic, unsafe). Those gaps are wider than the spacing between the
   0.80 / 0.70 / 0.60 thresholds, which means vol regime can move a contract across a threshold
   more easily than moneyness can.

## A.3 Revised recommendation

1. **Source the contract IV from the provider** where one is available — it is already fetched and
   thrown away. Capture it before the `ivRank` overwrite, and fix the conflated field.
2. **Where the IV must be solved, use plain `brentq`** over a `math.erf` normal. Not a hybrid: it
   is both more correct and 20× faster than what ships today.
3. **Replace the seed too** (Corrado-Miller), so any remaining Newton path is not left in its
   current state.
4. **Guard the ill-posed region explicitly** — refuse to invert a mid below the **American**
   intrinsic floor plus a tick for puts, and say where the guard lives.
5. **Treat the four existing call sites as in scope.** Changing `bs_iv` changes `reward_risk` and
   `first_passage` behaviour today and will move pinned test expectations. That is a fix, not a
   regression — but it must be deliberate, measured, and its own commit.
6. **Do not rely on the constant-IV assumption** without at least disclosing it on the card, given
   §A.2.9.

## A.4 Still unverified

No live market data (both the original and the audit ran on synthetic surfaces). Whether Tradier's
per-contract IV is good enough in production to displace a solver. Whether the Q7 thresholds
(0.80 / 0.70 / 0.60) hold on a real universe — round 5 records them as "taken as proposed", never
measured. American-exercise bias remains invisible to any round-trip test by construction.
