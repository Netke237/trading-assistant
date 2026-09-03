# Session handoff #7 — #21 merged, then audited twice and largely rewritten

**Date:** 2026-09-03
**Branch:** `claude/barrier-race-reprice-shipped-p0m9p5` (pushed, 2 commits on top of `main`)
**`main`:** `728c59e` — PR #21 squash-merged 2026-09-02 19:44Z, all three CI checks green.
**Code written this session:** two rounds of adversarial-audit fixes over the merged barrier race.
`1,504 insertions / 164 deletions` across 13 files, on top of #21's own `2,183 / 243`.

Read `2026-09-02-stop-model-handoff-round-6.md` first for the build order and the coverage table —
both still current. This file covers what happened after #21 merged: two `K-adversarial-audit-loop`
rounds, 26 findings, and what they say about the state of the feature.

---

## 1. What actually happened to #21

It was **already merged** when this session started — not by this session. `main` fast-forwarded
from `89eeb535` to `728c59e`; local `main` was 9 behind and is now synced. Nothing to push.

Then two adversarial audit rounds ran against the merged code. **Both found blockers.** The feature
as merged did not work on the primary user path, and its headline number was wrong.

| Round | BLOCKER | MAJOR | MINOR | NIT | Fixed | Declined |
|---|---|---|---|---|---|---|
| 1 (`3b4fc90`) | 2 | 7 | 8 | 3 | 19 | 1 |
| 2 (`31ae230`) | 1 | 3 | 11 | 5 | 20 | 0 |
| 3 | — | — | — | — | — | **did not run** (see §6) |

---

## 2. The two things that mattered

### 2.1 The stop was repriced with time-to-expiry set backwards

`resolve_reprice_days` returns days **elapsed** until a barrier. `bs_price`'s third argument is time
to expiry **remaining**. The merged code fed one in as the other, which inverts theta:

| median day the stop is hit | code priced it at | correct |
|---|---|---|
| 2 (of 60 DTE) | $0.00 | $4.58 |
| 45 (of 60 DTE) | $3.52 | $0.82 |

So the **later** the simulation said you would be stopped out, the **more** the contract appeared to
be worth at it. On the reference contract risk was overstated 39% and R:R understated 28%, and
`edge_per_contract` — the dollar figure the Final Recommendation prints — was wrong by that leg.

The tell was in the spec itself: §2.4's worked example (`"$5.20 premium − $1.09 at the stop"`) was
not reproducible by the implementation, which produced `$5.20 − $0.18`. And §2.2's rationale for
`max_fraction_of_dte` ("Annual on a 30-day contract reprices at 80 days — past expiry") is only
coherent under the elapsed reading.

`reprice_horizon.remaining_years_at_barrier()` now owns the conversion and is the only place it
happens. Two tests pin it: one against `bs_price` at the remaining life, one purely directional
(a later median must produce a *lower* stop value), which holds whatever the pricing formula is.

### 2.2 The card never appeared on the normal path

Round 1: the auto structural-stop refresh was fired **un-awaited**, so the first Estimate click of a
mount sent the flat scan stop, snapshotted it as the race's barrier, then watched the structural stop
land and cleared itself — *"Barriers changed — re-run the estimate"*, no bars, on a click just made.

Round 2 found that fixing the un-awaited fetch closed **one of three doors**. Both remaining ones are
ordinary button sequences:

- **"Check structure" → Estimate.** The handler skipped its own refresh (`structuralLoading` was
  already true), sent the flat stop, and the in-flight structural then moved `sharedStop`.
- **"Compute Arithmetic Plan" → Estimate.** The plan landed afterwards and `sharedStop` switched to
  its higher-precedence `exit_plan` branch.

In both, the Monte Carlo probability had also been measured against a different stop from the one on
screen — the D1 discrepancy the card is explicitly not allowed to have. **Estimate is now disabled
while either level is in flight.** Chosen over awaiting a foreign promise: it needs no second copy of
"which level wins" and cannot drift against the `sharedStop` memo the freshness check compares to.

---

## 3. The rest, grouped by what they say about the design

### The card contradicted itself in three places
- Four whole-percent shares, rounded independently, summed to **101% on ~1 row in 6** — printed
  directly under the sentence "Every row sums to 100%", beside a stacked bar that *did* sum to 100
  because it used the raw values. Now allocated by largest remainder, in the visible cells and in the
  spoken `aria-label`.
- `rr_premium_stop` was computed by dividing two cent-rounded dollar legs, which does not reproduce
  `pct / premium_stop_pct`: out by up to 14% on sub-$1 premiums, on the one column whose entire
  purpose is to disclose that it measures nothing. Now taken from the definition; the dollars are
  shown as `legs $X and $Y`, never `$X / $Y`, because a slash reads as a division to the audience
  this card is built for.
- The edge chain's printed terms did not sum to its printed total (out by 1.6¢/share, $1.56 a
  contract). The money was quantized; the probabilities were not. They now are, at the 2dp they are
  printed at — and via a `_as_printed` helper, because Python's `round()` is half-to-even and JS's
  `toFixed()` is not, and at `n_paths=2000` the shares `0.125` and `0.625` are directly reachable.

### The clamp was overriding the measurement
`max_fraction_of_dte` was applied to the simulation's own median, not just to the fallback table. On
the reference contract it replaced an observed **26d with 22.5d**, valuing the contract at the stop as
though 7.5 days of life remained instead of 4 — risk understated ~3.5%, R:R overstated ~3.6%, always
in the flattering direction, while the card printed "median ~26d" a few lines above "repriced at
22.5d". A simulated median is a day index *inside* the simulation and cannot exceed the contract's
life, so there was nothing to protect against. **The ceiling now applies to the fallback only.**

### Two states the card presented as confident answers
- **A quote whose IV cannot be solved.** `bs_iv` returns `None`, sigma silently becomes the generic
  0.25 default, and the simulation is no longer about this contract — on a quote far below intrinsic
  it prices day 1 above the target and reports **100% target-first with a dollar edge**. Every other
  consumer of that fallback shows a probability; the race is the first to turn it into money. An
  `iv_solved` flag now rides with the race and the card caveats every number.
- **A bolded R:R for an outcome that never happens.** On the reference contract every row has
  `p_stock_stop_first == 0` — the premium stop fires first on every losing path — so the bolded
  "THE measurement" describes a branch the simulation never reached and contributes exactly zero to
  the edge. The card now says so when that is true.

### The premium-stop field's provenance was asserted, not checked
The card said "from the editable field above" unconditionally. The field holds a **dollar** amount
fixed at scan time; the request divides it by the premium quoted **now**, so a contract that has since
fallen turns a 60% stop into a 94% one, and one that has fallen far enough makes the fraction ≥ 1 —
nothing is sent, the backend applies its own default, and the card credited a field that was ignored.
The decision is now taken **once, at request time**, against the premium the request used, and
carried to the card rather than re-derived from the cent-rounded one.

---

## 4. What the audits say about the test suite

This is the part worth carrying forward. #21 shipped with **1,051 tests** and both blockers walked
straight through them.

- **No test had ever rendered the race through `TradeCard`.** Every first-passage mock in that suite
  returned a response with no `race` key at all. Spec §4's tests 12 and 13 were satisfied by passing
  `barriersChanged` / `isFresh` to `BarrierRaceCard` as props — which proves the card honours a prop
  and nothing about whether the component that owns it ever computes that prop correctly.
- **Deleting every `round(x, 2)` in the money block was caught by zero tests.** The test that claimed
  to pin it asserted relations that hold identically with and without the rounding.
- **Reverting the reprice conversion was caught by zero tests.** Nothing asserted a *value* for
  `stop_repriced_value`, `risk_stock_stop`, `rr_stock_stop` or `edge_per_contract` — every assertion
  was structural (`is None` / `is not None` / sums to 1.0).
- **Test #7's "identical across the chain" used premiums that all quantize exactly** (9.80, 5.20,
  2.40), so it passed while the invariant was broken. It now sweeps 1.03 / 0.37.
- **The degenerate-risk test used a contract the endpoint cannot produce** — a $5.20 quote on an
  option worth ~$85, which `bs_iv` cannot solve.

Every fix in both rounds that can be mutated **has been**, and each mutation fails at least one test.
Thirteen new tests (5 backend, 8 frontend).

---

## 5. A finding of our own, not from either auditor

With the repricing corrected, **`risk_stock_stop <= 0` is essentially unreachable for a solvable
quote.** A call at its stop has both a lower spot *and* less time remaining, so it can only be worth
less than it cost. The spec calls that state "possible for a deep-ITM contract on a tight stop" —
true only while the stop was being repriced at the wrong time. The guard is still correct defensive
code and *is* reachable via the unsolvable-IV path, which is now what its test fixtures. Both
directions are asserted: `test_a_solvable_quote_never_produces_a_non_positive_stock_stop_risk` will
start failing if the reprice direction is ever inverted again.

**Spec §2.4 should be amended** to say so. Not done here — the spec is a record of what was decided,
and rewriting it silently from a later session is how a decision log stops being one.

---

## 6. Round 3 did not run

The third audit subagent hit the account's session rate limit before it read the diff. It produced
**no findings**. The loop is therefore **not closed**: `K-adversarial-audit-loop` stops when a round
comes back clean, and no round has. Round 2 found a blocker in round 1's own fix, which is exactly
the reason the loop exists.

**Pick up here:** re-run round 3 against `git diff ab3fb46..HEAD`, hostile to `3b4fc90..HEAD` in
particular (the newest ~1,500 lines).

---

## 7. Still not done

- **Round 3 of the audit** (§6). Highest priority — everything below assumes the race is sound.
- **Look at the card with real data.** Still never seen rendering against a live backend on a real
  contract. Needs FastAPI running plus one scan through to Step 7; a remote container has no market
  data credentials, so this is Kenneth's machine. Given rounds 1 and 2, this matters more than it did.
- **The four dead branches.** `git push --delete` returns **403** in a remote session (the git
  credential is scoped to pushing the designated branch) and the GitHub MCP server exposes no
  branch-delete tool. Verified safe first; restore SHAs recorded here so the check does not need
  repeating: `claude/tradecard-setstate-render-wo6eru` `ce05fd7` (10 unique commits, all of their
  source landed on main via other PRs; strictly behind main otherwise; carries the 304,084-line venv
  dump), `claude/fix-playwright-e2e-suite` `54ce575`, `claude/spawn-2-agents-impl-d3i2ml` `09e684b`,
  `claude/volume-profile-indicator-bug-01w0cn` `6ee39fe` — the last three have **0 commits not in
  main**. Deletable from the GitHub UI in under a minute.
- **`reprice_years` is still dead plumbing.** `estimate_rr` / `estimate_targets` accept it; **no
  caller passes it**, so the Profit-Target ladder a few inches above the race still reprices at the
  hardcoded `0.5 × expiry` half-life while the race uses the resolved horizon — two different answers
  to the same question on one card. Wiring it up means rewriting ~30 tests in `test_reward_risk.py`
  and `test_multi_target.py` that assert half-expiry pricing. The parameter's docstring now states
  which unit it wants (remaining life, not elapsed days), so a future caller cannot pass the wrong
  one silently — but §2.2's "the ONLY place that rule lives" is **not true today**.
- **Spec §2.4's `risk_stock_stop <= 0` rationale** (§5 above).
- **No PASS/CAUTION `StatusBadge`** on the race card. Spec §3.2 lists one and D8 specifies two states.
  Declined in round 1 and re-flagged in round 2 as an undocumented gap; the decision is now recorded
  in `BarrierRaceCard/index.tsx` itself. **No threshold on edge, R:R or any share is defined
  anywhere**, and D8 says the race adds no new gate — inventing a threshold to fill the badge would
  *be* that gate. Needs Kenneth, not a coin flip.
- Everything in round 6 §7, unchanged.

---

## 8. Traps carried forward

Round 6 §7, plus:

- **A merged PR is not a verified PR.** #21 was green on all three CI checks, had 1,051 tests behind
  it, and did not work on the primary user path.
- **Never `git checkout <file>` to revert a mutation test on a branch with uncommitted work.** Doing
  exactly that silently reverted a real fix alongside the mutation. Targeted test runs stayed green;
  only the full backend suite caught it. **Commit before mutation testing.**
- **A test that passes with and without the code it protects is not a test.** Four of them were found
  across two rounds, three of which guarded the exact decisions this feature was built around.
- **Check whether a fixture can fail the assertion it carries.** Test #7's premiums, spec test #10's
  shares, and the degenerate-risk contract were all chosen such that the property under test could
  not be violated.
- **Effects run after commit, so a ref cleared in a `useEffect` is stale for one painted frame** —
  and React Testing Library flushes effects inside `rerender`, so that frame is *not* observable from
  a test. Freshness for the race is now derived from state (`raceBarriers.contract === data.contract`)
  as well as from the ref. The state check is defence in depth and is deliberately not claimed to be
  pinned by a test.

---

## 9. Verification at handoff

| Check | Result |
|---|---|
| `cd backend && pytest` | **1838 passed, 1 skipped** |
| `cd frontend && npm run typecheck` | clean |
| `cd frontend && npm run test` | **1058 passed, 100 suites** |
| `cd frontend && npm run build` | clean |
| `npx playwright test --project=chromium --grep @smoke` | 5 passed, 2 skipped |
| `npx eslint components/organisms/TradeCard/index.tsx` | 2 warnings — the pre-existing baseline (round 1 briefly added a third; removed) |

Note the backend suite is **fully green here** — the `hmmlearn` / Python 3.14 failure recorded in the
round-6-era notes is specific to Kenneth's machine and does not occur on Python 3.11.
