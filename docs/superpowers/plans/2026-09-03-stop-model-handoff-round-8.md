# Session handoff #8 — seven adversarial audit rounds over the merged Barrier Race

**Date:** 2026-09-03
**Branch:** `claude/barrier-race-reprice-shipped-p0m9p5` — pushed, 7 commits on top of `main`, HEAD `3c3a17c`
**`main`:** `728c59e` (PR #21, merged 2026-09-02). Untouched this session.
**Session ended:** interrupted mid-verification by Kenneth. Nothing is lost; everything is committed and pushed.

Read `2026-09-02-stop-model-handoff-round-7.md` first — it covers rounds 1–2 and the state at merge.
This file covers rounds 3–7 and is the one to act on.

---

## 0. Read this first — the one thing that matters

**The audit loop is NOT closed.** `K-adversarial-audit-loop` stops when a round returns clean.
Seven rounds have run and **none has**. Round 7's findings are fixed but **unaudited** — no round 8
has ever seen them.

**And the last commit is only partially verified.** See §5.

---

## 1. What happened

PR #21 was already merged when the session began, green on all three CI checks, with 1,051 tests
behind it. Seven adversarial audit rounds then ran against the merged code.

| Round | Commit | BLOCKER | MAJOR | MINOR | NIT | Diff |
|---|---|---|---|---|---|---|
| 1 | `3b4fc90` | **2** | 7 | 8 | 3 | +818 / −113 |
| 2 | `31ae230` | **1** | 3 | 11 | 5 | +736 / −101 |
| 3 | `fdf7295` | **1** | 5 | 9 | 5 | +520 / −229 |
| 4 | `cdece53` | **2** | 3 | 8 | 5 | +470 / −116 |
| 5 | `25346c0` | 0 | 5 | 5 | 5 | +291 / −76 |
| 6 | `da7ef4c` | 0 | 5 | 5 | 3 | +316 / −62 |
| 7 | `3c3a17c` | 0 | 5 | 4 | 3 | +188 / −42 |

**Rounds 1–4 each found a defect inside the previous round's fix.** Rounds 5–7 found no blockers but
five majors each, and in every one of those rounds **at least one major was a previous fix that
turned out to be cosmetic or unpinned**. The severity is falling; the "my own fix was wrong" rate is
not falling as fast.

Whole feature: `git diff ab3fb46..HEAD` — 19 files, **+5,071 / −292**. #21 itself was +2,183 / −243,
so **the audit rounds are larger than the thing they audited.**

---

## 2. The defects that mattered, in trading terms

Ordered by what they would have cost you at the screen, not by severity label.

1. **The stop was repriced with time-to-expiry backwards** (round 1). `resolve_reprice_days` returns
   days ELAPSED to a barrier; `bs_price` wants the life REMAINING. Feeding one in as the other
   inverts theta: on a 60-DTE call a stop hit on day 2 priced at **$0.00** where it should hold
   $4.58, and a stop hit on day 45 priced *higher* than one hit on day 2. Risk overstated 39%, R:R
   understated 28%, and `edge_per_contract` — the dollar figure the Final Recommendation prints —
   wrong by that leg. **The spec's own worked example was not reproducible by the code**, which is
   what gave it away.
2. **The card never appeared on the normal path** (rounds 1–2). Three separate routes where the
   first Estimate click raced against its own stop and cleared itself with "Barriers changed", while
   the Monte Carlo probability had been measured against a different stop from the one displayed.
3. **At 1 DTE the bolded R:R was meaningless** (round 4). The min-days floor overrode the
   half-day-before-expiry cap, so the stop priced at exactly expiry: risk leg = the whole premium and
   `rr_stock_stop` collapsed to **exactly your typed target percentage** — identical to the greyed
   constant beside it, on a card whose premise is that those differ.
4. **Editing your premium stop re-rolled the whole simulation** (round 4). `premium_stop_pct` was in
   the seed key per spec §2.3, but the spec's stated reason is factually wrong — the premium stop is
   a post-hoc barrier over already-simulated paths. Including it moved the Monte Carlo *target*
   probabilities by ~2 points whenever the quote moved a cent. **Removed — a deliberate spec
   deviation that needs Kenneth's sign-off** (§4).
5. **The premium-stop row contradicted itself** (round 5). `$1.25 option` labelled `~55% of premium`
   against a $2.75 premium: 55% of $2.75 is $1.51, and $1.25 is the complement.
6. **Four percentages summing to 101%** (round 2), printed directly under "Every row sums to 100%",
   beside a bar that did sum to 100.
7. **The invalidation probability was deleted rather than moved** (round 7), leaving the three
   per-target probabilities that "can sum past 100%" on screen with nothing left to explain why.

---

## 3. What the audits say about testing — carry this forward

#21 shipped with 1,051 tests and both round-1 blockers walked through them.

- **No test had ever rendered the race through `TradeCard`.** Every first-passage mock in that suite
  returned a response with no `race` key at all.
- **Deleting every `round(x, 2)` in the money block was caught by zero tests.**
- **Reverting the reprice conversion was caught by zero tests.**
- Across rounds 3–7, **fourteen mutants survived the full suite** at the moment they were tested —
  including, twice, the exact gate the commit under audit was *about*, argued at length in a comment
  and pinned by nothing.
- **Three fixtures were incapable of exhibiting the failure they guarded**, and one was labelled
  "genuine backend output" while being hand-written and internally contradictory. Twice.
- **A test's oracle reproduced the bug rather than detecting it** — `Decimal(repr(v))` discards
  exactly the digit that decides a `toFixed` tie.

**Nine comments asserted measured numbers that were wrong on re-measurement.** All mine. A comment
carrying a fabricated statistic is worse than no comment: it reads as evidence.

Rules that came out of this and are worth keeping:
- A test that passes with and without the code it protects is not a test. **Mutate it.**
- Check whether a fixture *can* fail the assertion it carries.
- **Commit before mutation testing.** `git checkout <file>` to revert a mutant also reverted a real
  uncommitted fix; only the full suite caught it.
- Never assert a measured percentage in a comment without re-deriving it.

---

## 4. Decisions needing Kenneth — these are the blocking items

1. **Dropping `premium_stop_pct` from the endpoint seed key** deviates from spec §2.3. Two
   independent auditors judged the argument SOUND and the spec's premise factually wrong. Argued at
   `backend/app/routers/contracts.py` at the `seed_key` construction. **Needs your yes or a revert.**
2. **`reprice_years` is still dead plumbing.** Stage 1 moved to the resolved horizon; the Fixed %
   Ladder did not, so one TradeCard answers "what stock price gets me to T20%" two ways — ~$2.40
   apart at 30 DTE, $10+ on a one-year contract. Round 7 surfaced it on the card. **Wiring it up
   rewrites ~30 tests in `test_reward_risk.py` / `test_multi_target.py` and changes numbers on a card
   outside this feature's remit.** Your call.
3. **No PASS/CAUTION `StatusBadge`** on the race card (spec §3.2, decision D8). Declined in every
   round and judged SOUND by two auditors: no threshold on edge, R:R or any share is defined
   anywhere, and D8 says the race adds no new gate — inventing one would *be* that gate. Recorded in
   `BarrierRaceCard/index.tsx`. **Needs a threshold from you, or leave it out permanently.**
4. **Spec §2.4's rationale for the `risk_stock_stop <= 0` guard no longer holds.** With the
   repricing corrected, a call at its stop has both lower spot AND less time, so it can only be worth
   less than it cost — the state is unreachable for any solvable quote. The guard is still right
   (reachable when IV cannot be solved) but the spec's reason is wrong. **The spec was deliberately
   not edited** — rewriting a decision log from a later session is how it stops being one.

---

## 5. Verification state — READ BEFORE TRUSTING HEAD

`3c3a17c` is **partially verified**. On that tree:

| Check | Status |
|---|---|
| `pytest tests/test_barrier_race.py tests/test_reprice_horizon.py tests/test_first_passage.py` | **74 passed** |
| `npx tsc --noEmit` | **clean** |
| `npx jest barrierRace BarrierRaceCard TradeCard` | **206 passed** |
| `cd backend && pytest` (FULL) | **NOT RUN after the last edits** |
| `npm run test` (FULL) | **NOT RUN after the last edits** |
| `npm run build` | **NOT RUN after the last edits** |
| `npx playwright test --project=chromium --grep @smoke` | **NOT RUN after the last edits** |
| `npx eslint` | **NOT RUN after the last edits** |

At `da7ef4c` (round 6) everything was green: 1,845 backend / 1,072 frontend / typecheck / build /
smoke, eslint at its 2 pre-existing warnings. **Round 7's changes are the unverified delta.**

**First action in the next session:** run the four missing checks. If any fails it is round 7's doing
and the diff is small (`git diff da7ef4c..3c3a17c`, 9 files, +188 / −42).

---

## 6. Pick up here, in order

1. **Run the four missing checks** (§5). Do not build on `3c3a17c` until they are green.
2. **Round 8 of the audit.** Round 7's fixes have never been audited. Point a fresh subagent at
   `git diff ab3fb46..HEAD`, hostile to `git diff da7ef4c..HEAD`. The prompt shape that worked is in
   this session's history; the key elements are: don't show it earlier rounds' findings, tell it
   mutation testing is welcome, tell it to revert every experimental edit including `git checkout`,
   and tell it to say plainly if the thing is clean.
3. **Get Kenneth's four decisions** (§4). Items 1 and 2 change shipped behaviour.
4. **Look at the card with real data.** Still never seen rendering against a live backend on a real
   contract. Needs FastAPI plus one scan through to Step 7 — a remote container has no market-data
   credentials, so this is Kenneth's machine. **Given that seven rounds found this much, this matters
   more than it did, not less.**
5. Then the build order from handoff #6 §5: gate basis → piece 3 → piece 4 → piece 6 → Heston → piece 5.

---

## 7. Still outstanding

- **The four dead branches.** `git push --delete` returns **403** in a remote session and the GitHub
  MCP server exposes no branch-delete tool. Verified safe; restore SHAs:
  `claude/tradecard-setstate-render-wo6eru` `ce05fd7` (10 unique commits, all their source landed on
  main via other PRs; carries a 304,084-line venv dump), `claude/fix-playwright-e2e-suite` `54ce575`,
  `claude/spawn-2-agents-impl-d3i2ml` `09e684b`, `claude/volume-profile-indicator-bug-01w0cn`
  `6ee39fe` — the last three have **0 commits not in main**. One minute in the GitHub UI.
- **No PR opened for this branch.** Deliberate — none was asked for.
- Everything in handoff #7 §7 not listed above.

---

## 8. Traps carried forward

Handoff #7 §8, plus:

- **A merged, green, 1,051-test PR is not a verified PR.** #21 did not work on its primary user path.
- **A fix is not done when it is written; it is done when a mutation of it fails a test.** Three
  rounds shipped a fix whose own mutant survived the suite.
- **"I fixed the formatter" is not "I fixed the claim".** Round 5 deleted a printed division that did
  not reproduce and replaced it with a sentence instructing the reader to perform the same division,
  with both operands still on screen.
- **Suppressing a wrong sentence can delete a right number.** Round 6 stopped printing "unaffected by
  the premium stop" when the stock stop moved — correct — and thereby deleted the invalidation
  probability from the screen entirely, which spec §3.4 explicitly forbids.
- **Do not put a number in a comment you have not just re-derived.** Nine were wrong.
- **This file's tests do not clear mocks between tests** (`jest.config.ts` sets no `clearMocks`), and
  `expandLadder()` is a toggle whose state persists to `localStorage`. New describes must clear both
  or they are order-dependent. Two separate rounds hit this.
