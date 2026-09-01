# Session handoff #3 — PR #19 is open, backend CI was red, and piece 3 is next

**Date:** 2026-09-01
**Branch:** `claude/executing-vs-auditing-7rnjeo` — everything pushed.
**PR:** [#19](https://github.com/Netke237/trading-assistant/pull/19) → `main`, open, **not merged**.
**For:** the next session picking this up.

**Relationship to the earlier handoffs:** this file replaces **§7 ("Recommended order") of
`2026-09-01-stop-model-handoff-round-2.md`** and nothing else. Round 2 remains the reference for the
piece split, the deferred topics and the new Q-A evidence; the **first** handoff
(`2026-09-01-stop-model-session-handoff.md`) remains the reference for the settled decisions (§3),
the expensive codebase facts (§4) and the traps (§7). Both still stand. Read them.

---

## 0. Read these, in this order

| # | Document | What it is |
|---|---|---|
| 1 | **this file** | PR state, the CI fix, what to build next |
| 2 | `2026-09-01-stop-model-handoff-round-2.md` | Piece split, deferred topics, Q-A evidence |
| 3 | `2026-09-01-stop-model-session-handoff.md` | The facts (§4), the open questions (§5), the traps (§7) |
| 4 | `2026-08-31-stop-model-unification.md` | The plan. **DO NOT BUILD AS ONE PIECE.** §8 is the split. |
| 5 | `2026-08-31-montecarlo-premium-stop-columns.md` | Rejection record + algebraic proof. Read before proposing any R:R column. |

---

## 1. What this session did

### 1.1 Closed the piece-1/2 gap (round 2 §4)

`components/organisms/TradeCard/index.tsx` — the `sharedStop` memo moved above `estimateFirstPassage`
(only its position in the file changed; every input it reads was already in scope there), and the
Monte Carlo request's `invalidation_price` now reads `sharedStop?.price ?? data.exit.invalidation`
instead of `exitPlan?.stop.price ?? …`. All three consumers — the Monte Carlo request, the
stop-vs-premium gate, and `structuralRR` — now resolve through one memo, including on a
cache-restored exit plan with no fresh click this mount.

Two regression tests added in `TradeCard.test.tsx` (describe block *"TradeCard — piece 1/2 gap:
cache-restored exit plan with no fresh click this mount"*) reproducing the CandidateNav
Next-then-Prev scenario. **Verified failing against the pre-fix code** (reverted the one line, got
the expected 185.87-vs-178.50 mismatch) before restoring the fix.

### 1.2 Opened PR #19

Five commits plus the four planning documents, base `main`. Excludes the `backend/.venv-check/`
virtualenv dump — see the trap in round 2 §8.

### 1.3 Found and fixed a red backend CI — the PR was **not** actually green when it was opened

This is the part worth reading. The previous session reported "97 suites / 1001 tests green,
typecheck clean" and opened the PR. That was true **and insufficient**: it was the *frontend* suite.
The backend suite was never run, and it was red.

```
FAILED tests/test_config_score_thresholds.py::test_stop_premium_thresholds_endpoint_mirrors_yaml
FAILED tests/test_config_score_thresholds.py::test_stop_premium_thresholds_are_coherent
  KeyError: 'reject_fraction'
```

**Cause.** The D8 revision (commit `a095e74`) reduced the gate to one threshold —
`pass_max_fraction`, two outcomes PASS | CAUTION, never REJECT. The YAML and the endpoint were
updated. `backend/tests/test_config_score_thresholds.py` was not: it still asserted the old
`reject_fraction` / `caution_fraction` pair.

**Fix (commit `659b788b`).** The tests were corrected, not the code. The one-key shape is the
shipped, intended contract — it matches `HorizonStopPremiumThresholds` in
`frontend/lib/stopPremiumThresholdsStore.ts` and its `FALLBACK` of Intraday 0.85 / Swing 0.80 /
Position 0.70, and it matches the YAML (`swing` 0.8 at :132, `intraday` 0.85 at :221, `position` 0.7
at :311). Re-adding `reject_fraction` to make the test pass would have silently undone D8.

The coherence test now asserts the payload's **key set exactly** (`set(pair) ==
{"pass_max_fraction"}`), so a `reject_fraction` reappearing server-side fails loudly rather than
drifting away from the client interface that declares a single key.

Also dropped a stale sentence from the three `stop_premium` comment blocks in `scoring_rules.yaml`
that still explained what "REJECT" meant, directly contradicting the "never REJECT" paragraph four
lines below it in the same block.

**Verified:** backend `1799 passed, 1 skipped` (was `1797 passed, 2 failed`); `npm run typecheck`
clean.

### 1.4 The `test` (Playwright e2e) check is red — and has been on `main` since 2026-08-28

Separate from §1.3, and **not this PR's**. Three tests fail:

```
e2e/tests/screener-steps-1-3.spec.ts:5  › Step 2 - universe page loads with selectable tiles
e2e/tests/screener-steps-1-3.spec.ts:17 › Step 2 - universe selection sends correct payload to scan API
e2e/tests/screener-steps-1-3.spec.ts:52 › Step 3 - direction toggle works
```

**Evidence it is not this PR's:** the identical three tests fail with the identical signature on
`main` at `1f2d8c22` — this PR's own base commit (run #128,
`actions/runs/33522254305`). The Playwright workflow has failed on `main` for **10 consecutive runs
going back to 2026-08-28** (#118 through #128). It is a long-standing broken check, not a flake and
not a regression from this branch.

**Symptom.** Steps 2 and 3 render without their controls — universe tiles not found, Bullish/Bearish
not found — and `clickNext()` from Step 2 lands on `step-1-regime` instead of `step-3-direction`.

**Two hypotheses already ruled out**, so the next session does not repeat them:

- *The `StopPremiumThresholdsBootstrap` this PR adds to `app/(frame)/layout.tsx` breaks every framed
  page.* No — it is a faithful copy of the existing `IvThresholdsBootstrap` /
  `EventThresholdsBootstrap` pattern, its store's `fetch` is wrapped in try/catch and keeps the
  fallback, and the same tests fail on the base commit that does not contain it.
- *The 1200 px `MinWidthGate` hides the content.* No — `playwright.config.ts` uses
  `devices['Desktop Chrome']`, which is 1280×720, above the gate.

**Not fixed here, deliberately.** The failure is in Steps 1–3 navigation; this PR's diff is Step 7
`TradeCard`, `lib/risk.ts`, the config endpoint and YAML. Fixing it inside this PR would widen it
into unrelated code. No fix PR exists to port. **It needs its own change** — and until it lands,
`test` will be red on every PR, so it cannot be used as a merge signal.

---

## 2. The lesson from §1.3 — carry this forward

**This repository has three CI checks: `frontend`, `backend`, and `test`. "The suite is green" means
all three.** The frontend suite passing is not evidence about the backend, and this PR touches
`backend/app/routers/config.py`, `backend/config/scoring_rules.yaml` and
`backend/tests/test_config_score_thresholds.py`.

Run both before claiming green:

```bash
cd frontend && npm run typecheck && npm run test
cd backend  && pytest
```

The backend suite takes ~4 minutes and needs `pip install -r backend/requirements.txt` in a fresh
container (it is not pre-installed).

A second, subtler lesson: **when a decision removes a field, grep for the field name, not just for
the code path.** `reject_fraction` survived in a test because the revision was reasoned about in
terms of "the gate" rather than in terms of every file naming the key.

---

## 3. Immediate state / what to do first

| # | Item | State |
|---|---|---|
| 1 | `backend` + `frontend` checks green on this PR's head | **Verify.** Were re-running at the end of this session. |
| 2 | `test` (Playwright e2e) check | **Red, and red on `main` too** — 10 consecutive runs since 2026-08-28. Not this PR's. §1.4. |
| 3 | Merge PR #19 | **Kenneth's call.** Seven commits and five documents unmerged. |
| 4 | Piece 3 — scan-time `finalStop` | **Next build.** §4 below. |

**On the `test` check:** it cannot be used as a merge signal for this PR, because it is red on the
base branch for reasons that predate this branch by five days. Either merge on `backend` + `frontend`
green, or fix the e2e suite first **in its own PR** — that is a real, separate piece of work worth
scheduling, because right now the repository has a permanently-red check and no one can tell a new
e2e regression from the standing failure.

**Do not start piece 3 on top of an unmerged PR #19 if it can be avoided** — piece 3 edits
`TradeExit`, `scanStore` and the ranking table, and stacking it would make #19 harder to review than
it already is at 18 files. Merge first, branch fresh.

---

## 4. Why piece 3 is next (unchanged from round 2 §5, restated because it is the whole argument)

`computeExitPlan` is called from exactly one place — the "Compute Arithmetic Plan" button
(`TradeCard/index.tsx:1316`). It is optional and user-triggered. Both shipped pieces *prefer* the
exit plan's stop and **fall back when there isn't one**.

So on any card where Kenneth has not clicked that button, **Monte Carlo still sends the flat −3%.**
The bug the first handoff called "the worst factual wrongness on the card" is, today, fixed only for
people who click an optional button first.

**Piece 3 is what puts the structural+ATR stop on the card before any click** — i.e. it is what makes
pieces 1 and 2 actually take effect by default. That is a stronger argument than "it is next in the
list."

Scope is in round 2 §5 — five parts, and all five matter:

1. Backend at scan time: `compute_final_stop` per **symbol** → `exit.finalStop`, wrapped in
   `asyncio.to_thread`. `structuralSource` and `distanceDollar` are **required**, not optional.
2. `stop.contractPrice` cannot exist at scan time — specify that contract-priced sub-cells and
   `recommendedSize` render `—` until a plan is computed.
3. Survive a Step 6 contract override: `mergePlan` does `exit: plan.exit` wholesale and
   `/contracts/recompute-plan`'s `TradeExit` has no `finalStop`, so it would be wiped for exactly the
   cards the user hand-picked a contract for. Add it to `TradeExit` **and** splice in
   `withCachedEstimate`.
4. `scanStore` v12 → **v13** with an explicit migration branch (CLAUDE.md requires both). Pre-13
   restores render **"not computed — re-run the scan"**, never a blank and never a silent PASS.
5. Ranking-table badge (D8): `stopCostPct` + `stopCostStatus` on `WatchlistRow`, populated in
   `cardToRow`, one grid track added to `COLUMNS` and `TableRow`, verified against the 1200 px
   min-width gate. The badge must say it describes the **auto-picked** contract.

After piece 3: piece 4 (per-position `premium_stop_pct`) is independent and can run in parallel.
Pieces 5 and 6 stay deferred; 6 is blocked on **Q-A**, which is Kenneth's call.

---

## 5. Open questions — still open, still Kenneth's

| # | Question | State |
|---|---|---|
| **Q-A** | Stocks gate basis — the strategy signal's stop (spread 0.2–2.0 ATR, so it works) vs. thresholds relative to `atr_multiplier`. Round 2 added evidence that (a) is viable; it did not decide it. | **Blocks piece 6** |
| **A1** | Gate loss basis: delta-linear (cheap, works from scan data, so the ranking badge can exist) vs. the exit plan's repriced value (accurate, needs a click). If repriced drives the **verdict**, `dte_at_target = expiry_years × 0.5` becomes verdict-bearing. **Piece 3's part 5 forces this question** — the ranking badge cannot wait for a click. | **Open, and piece 3 hits it** |
| Q23–Q27 | Answered by Claude, not Kenneth. Reversible assumptions, plan §1.1. | Open, low risk |

**A1 is no longer safely deferrable.** Piece 3 puts a gate badge in the ranking table, before any
contract has an exit plan — so the badge must use the delta-linear basis by construction. Either
confirm that with Kenneth, or accept that the ranking badge and the card can disagree once he clicks
Compute Arithmetic Plan. Say which, in the UI, rather than letting two numbers differ silently.

---

## 6. Traps (carried forward, plus one new)

- **NEW: "green" means all three CI checks.** See §2. The frontend suite passing says nothing about
  the backend.
- **NEW: when a decision deletes a field, grep the field name repo-wide.** `reject_fraction` outlived
  its own removal in a test file for four commits.
- **Do not merge `claude/tradecard-setstate-render-wo6eru`** — committed virtualenv (~129 KB
  `backend/.venv-check/`). Everything of value is already on this branch. It can be abandoned.
- **Do not propose an R:R column with a premium-proportional denominator.** Two designs died on it;
  `premium` cancels and you get a constant multiple of the user's own input. Compute the closed form
  first.
- **Do not assume a value on the card is "display only".** Caught twice per audit round, both rounds.
  `overlay.premiumStop` is the risk denominator in `computeEditedRR` and `rrContribution`;
  `exitPlan.stop.contractPrice` feeds a **submit-blocking** gate.
- **Do not re-run the adversarial loop against the whole plan.** It diverged: 24 → 32 findings after
  a rewrite that fixed every round-1 item. Audit one small piece at a time.
- **Implement, do not audit.** The plan's own conclusion.
- **CLAUDE.md rules that have bitten:** `Status` labels are canonical (`lib/status.ts`) — which is why
  the two-state gate is PASS/CAUTION and not an invented "NOT PASS"; `npm run typecheck` clean before
  every commit; a new persisted store field needs a version bump **and** a migration branch.
- **Kenneth wants plain English.** Non-coder, high IT affinity. Short, jargon-free, worked numeric
  examples. He asks to be grilled and to have work adversarially audited — take both literally.
- **When something said earlier turns out wrong, say so plainly.** §1.3 of this file is an example:
  the previous session's "all green" was wrong, and saying so directly is the right move.
