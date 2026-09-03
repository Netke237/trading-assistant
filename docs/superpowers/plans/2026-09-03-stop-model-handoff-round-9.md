# Session handoff #9 — HEAD fully verified, three decisions settled, round 8 never ran

**Date:** 2026-09-03
**Branch:** `claude/audit-loop-verification-nhg96z` — HEAD `79a916a`, fast-forwarded from
`claude/barrier-race-reprice-shipped-p0m9p5` (same commit, both names point at it).
**`main`:** `728c59e` (PR #21, merged 2026-09-02). Untouched.
**Session ended:** hit the account session limit. Nothing lost; working tree clean.

Read `2026-09-03-stop-model-handoff-round-8.md` first — everything in it still applies except
§5 (verification, now done) and §4 items 1–3 (now decided). This file supersedes those.

---

## 0. Read this first

Two things changed and one thing did not.

**Changed:** HEAD is now **fully verified** — all four checks handoff #8 §5 listed as NOT RUN are
green. And **three of the four decisions in §4 are settled** by Kenneth (§2 below).

**Did not change:** **the audit loop is still not closed.** Round 8 produced *zero* findings.
It was not clean — it never ran to completion. The auditor was killed three times by API errors
(two 529s, then the session limit). Round 7's fixes remain unaudited, exactly as they were.

**So the count is still seven rounds, none clean.** Do not record round 8 as having happened.

---

## 1. Verification — §5 of handoff #8 is closed

All on `79a916a`:

| Check | Result |
|---|---|
| `cd backend && .venv/bin/python -m pytest -q` | **1845 passed, 1 skipped** |
| `cd frontend && npm run test` | **1078 passed**, 100 suites |
| `cd frontend && npx tsc --noEmit` | clean |
| `cd frontend && npm run build` | success |
| `npx playwright test --grep @smoke` | **19 passed, 2 skipped** |
| `cd frontend && npm run lint` | **0 errors**, 56 warnings — all pre-existing |

Round 7's delta introduced no regression. Frontend went 1,072 → 1,078 (round 7 added six tests);
backend held at 1,845.

### Two corrections to handoff #8's own numbers

- **"eslint at its 2 pre-existing warnings" is wrong — it is 56.** Zero errors, so nothing is
  failing, but the figure in handoff #8 §5 should not be trusted as a baseline. Only two warnings
  land in a file this branch touches (`TradeCard/index.tsx`: unused `TargetRow`, and
  `react-hooks/exhaustive-deps` on the candidate-reset effect at ~line 555). Both are present at
  `728c59e`, so neither is the audit's doing. Verified by diffing against
  `git show 728c59e:frontend/components/organisms/TradeCard/index.tsx`.
- **`npx eslint .` is not the project's lint.** It reports 23 errors, all in generated files
  (`next-env.d.ts` triple-slash, `.next/` types) that `next lint` excludes. Use `npm run lint`.

### Environment traps for a fresh remote container

- **No venv, no node_modules on clone.** `cd backend && python3 -m venv .venv && .venv/bin/pip
  install -r requirements.txt`, and `cd frontend && npm ci`. ~4 minutes total.
- **Playwright fails all 14 browser specs out of the box** with
  `Executable doesn't exist at .../chromium_headless_shell-1234`. The container ships Chromium
  build **1194**; Playwright 1.62.1 wants 1234. Do **not** run `playwright install` (blocked and
  unnecessary). Write a scratch config with
  `launchOptions: { executablePath: '/opt/pw-browsers/chromium' }` and run
  `npx playwright test -c <that config> --grep @smoke`. It must live inside `frontend/` — a config
  in `/tmp` cannot resolve `@playwright/test`. Delete it afterwards.
  **A bare smoke run in a fresh container reads as 14 failures that are not real.**

---

## 2. DECIDED — do not re-litigate these

Kenneth settled three of handoff #8 §4's four items this session.

1. **Seed key: keep the deviation, and amend the spec.** `premium_stop_pct` stays OUT of the
   `/first-passage` seed key. Spec §2.3's stated premise — that the premium stop shapes the
   simulation — is factually wrong; it is a post-hoc barrier over already-generated paths.
   **Action still owed:** append an amendment to the spec recording this, so the next reader does
   not "fix" it back. NOT YET DONE.
2. **`reprice_years`: wire it through now.** One answer per question on the card. The Fixed %
   Ladder must back-solve at the resolved holding horizon, not `expiry_years * 0.5`. Accepted
   costs: ~30 tests rewritten in `test_reward_risk.py` / `test_multi_target.py`, and Fixed % Ladder
   numbers change. The round-7 caution note comes off once the two agree. NOT YET DONE — §3.
3. **Race card StatusBadge: leave it out permanently.** Spec §3.2 / decision D8's badge is
   dropped. No threshold on edge, R:R or any path share exists anywhere, and D8 itself says the
   race adds no new gate — inventing a cutoff would *be* that gate. **Action still owed:** record
   it as a closed decision in the spec so it stops resurfacing every round. NOT YET DONE.

Still undecided, carried from handoff #8 §4 item 4 — and it is informational, not blocking:

4. **Spec §2.4's rationale for the `risk_stock_stop <= 0` guard no longer holds.** With repricing
   corrected, a call at its stop has both lower spot AND less time, so it can only be worth less
   than it cost. The guard is still correct (reachable when IV cannot be solved) but the reason
   printed in the spec is wrong. Fold this into the same amendment as items 1 and 3.

**On amending the spec:** Kenneth approved editing it, but the right form is an **appended
amendment section**, not an in-place rewrite. Handoff #8 §4 item 4 gives the reason and it still
stands: "rewriting a decision log from a later session is how it stops being one." Append; leave
the original decisions legible.

---

## 3. The `reprice_years` wiring — research done, code not written

This is the one approved change with real design work already banked. Kenneth said wire it.

### It is exact, not approximate — which handoff #8 did not know

`first_passage.py:382-394` resolves Stage 1's horizon with **`sim_median=None`**:

```python
dte_at_target = remaining_years_at_barrier(
    float(dte),
    resolve_reprice_days(horizon_preset, hold_min, hold_max, float(dte), None, reprice_cfg),
)
```

`None` by necessity — Stage 1 runs *before* the simulation exists — so it **always takes the preset
fallback**. That makes the horizon a pure function of `(preset, hold_min, hold_max, dte)`, with no
simulation input. So the ladder can be made to agree **exactly**, not merely more closely. That was
not obvious from handoff #8's framing, which implied the two could only be approximated together.

Note the asymmetry that remains and is correct: the **stop** leg (`first_passage.py:502-508`) does
pass the simulated median. Only Stage 1's display back-solve takes the fallback. Do not "fix" the
stop leg to match.

### The shape of the change

1. `build_trade_plan` (`backend/app/scoring/trade_plan.py:37`) gains `horizon_preset`,
   `hold_min`, `hold_max`.
2. It computes, once:
   `reprice_years = remaining_years_at_barrier(dte, resolve_reprice_days(preset, hold_min, hold_max, dte, None, cfg))`
3. It passes that into both `estimate_rr` and `estimate_targets`. **Both already accept
   `reprice_years` and no caller anywhere passes it** (`git grep -n reprice_years -- backend/`
   returns only definitions). This is finished plumbing waiting for one caller.
4. Call sites: `contracts.py:248` and `scan.py:764`. Both have the inputs — the `/first-passage`
   request model carries `horizon_preset` / `hold_min` / `hold_max` (`contracts.py:342-344`), and
   the scan request carries `req.horizon` plus `hold_min_days` / `hold_max_days`.
5. Remove the caution note at `frontend/components/organisms/TradeCard/index.tsx:1826-1834`
   **only after** demonstrating the two numbers agree — with a test, not by reading the code.

### The trap that will silently defeat it — check this FIRST

`_fallback_days` (`reprice_horizon.py:177-216`) looks the preset up in a **dict keyed by exact
string** (`"Swing"`, `"Position"`, …), and on a miss falls through to
`float(fallback.get("Swing", 7))` — **silently**. So:

- If the frontend sends `"Swing"` to `/first-passage` but the scan sends `"swing"`, or any other
  spelling, the ladder gets Swing's 7 days by accident rather than by agreement — and the two cards
  would still disagree, now with **no caution note** to say so. That is strictly worse than today.
- `_CUSTOM` is handled separately and derives from the typed range, so a "Custom" horizon needs
  `hold_min`/`hold_max` to arrive on **both** paths or they diverge the same way.

**Before writing any of this, verify what the frontend actually sends to `/scan` versus
`/first-passage`, and assert the equality in a test.** A test that pins "ladder horizon ==
Stage 1 horizon" for each preset, including Custom and an unknown/absent preset, is the deliverable
that makes this change safe. Without it this is a fix whose own mutant survives — the exact failure
mode handoff #8 §3 records three times.

---

## 4. Round 8 — what happened, and the one lead it left

The auditor was spawned with a deliberately hostile prompt (primary scope `git diff ab3fb46..HEAD`,
disproportionate hostility to `git diff da7ef4c..HEAD`, mutation testing explicitly invited, told to
say plainly if the code is clean, told not to read any `*handoff*` file so earlier rounds' findings
could not prime it). It was killed three times:

| Attempt | How it died | Work salvaged |
|---|---|---|
| 1 | 529 Overloaded, mid-mutation-testing | one fragment, below |
| 2 | 529 Overloaded, seconds after resume | none |
| 3 | 429 session limit (resets 16:30 UTC) | none |

**The only surviving output is one sentence:** `"Mutants 5 and 7 survived. Let me dig further."`

**Treat that as a lead, not a finding.** Which code those two mutants were against was never
reported, and it is not recoverable from the fragment. Two surviving mutants would be among the most
valuable things an audit round can produce — and inventing plausible candidates for them would be
precisely the fabricated-evidence failure handoff #8 §3 counts nine times. **Do not guess them.**

What IS known: attempt 1 left one mutation in the tree —
`rr_stock_stop = risk_stock_stop / reward_dollar` (inverted) in
`backend/app/scoring/first_passage.py` around line 599. That was reverted and the revert verified
(`pytest tests/test_barrier_race.py tests/test_reprice_horizon.py tests/test_first_passage.py`
→ 74 passed). Whether that inversion was one of the two survivors is unknown. It is worth
re-testing first thing, because if a *reversed reward/risk ratio* passes the suite, that is a
blocker-grade coverage hole in the card's headline number.

### Prompt shape that is worth reusing

It is written out in full in this session's history; the elements that mattered:
don't show it earlier rounds' findings; forbid reading `*handoff*` files; invite mutation testing
and demand the exact edit + file:line + test file + what the non-failure proves; require every
experimental edit reverted and the tree left clean at a named SHA; require it to say plainly if the
thing is clean; forbid padding with style preferences.

**Add one thing next time:** tell the auditor to append each finding to a file
(`<scratchpad>/round8-findings.md`) the moment it confirms it, rather than holding them to report at
the end. All three crashes cost the entire round because everything was in-context. That instruction
was added on attempt 2 and never got a chance to pay off.

---

## 5. Pick up here, in order

1. **Re-run round 8.** Nothing has been audited since round 6. Use the prompt shape in §4 plus the
   write-findings-to-a-file instruction. If the session limit is still biting, run the auditor on
   Sonnet rather than not running it — a completed Sonnet audit beats an Opus audit that never
   finishes. Start it by re-testing the inverted-`rr_stock_stop` mutant.
2. **Wire `reprice_years`** per §3 — but do the frontend-payload check in §3's trap paragraph
   *first*. If the two paths send different horizon spellings, fix that before touching the ladder.
3. **Amend the spec** per §2 (items 1, 3, 4) — appended section, original decisions left intact.
4. **Look at the card with real data.** Still never seen rendering against a live backend on a real
   contract. Needs FastAPI plus one scan through to Step 7; a remote container has no market-data
   credentials, so this is Kenneth's machine. Seven rounds of defects make this more important, not
   less — and note that #2 changes numbers on a card Kenneth looks at, so eyeballing it after that
   change is worth more than before it.
5. Then handoff #6 §5's build order: gate basis → piece 3 → piece 4 → piece 6 → Heston → piece 5.

---

## 6. Still outstanding

- **The four dead branches.** Unchanged from handoff #8 §7 — `git push --delete` returns 403 in a
  remote session and the GitHub MCP server exposes no branch-delete tool. Restore SHAs:
  `claude/tradecard-setstate-render-wo6eru` `ce05fd7` (10 unique commits, all landed on main via
  other PRs; carries a 304,084-line venv dump), `claude/fix-playwright-e2e-suite` `54ce575`,
  `claude/spawn-2-agents-impl-d3i2ml` `09e684b`, `claude/volume-profile-indicator-bug-01w0cn`
  `6ee39fe` — the last three have 0 commits not in main. One minute in the GitHub UI.
- **No PR for this branch.** Deliberate — none asked for.
- Everything in handoff #8 §7 and handoff #7 §7 not listed above.

---

## 7. Traps carried forward

Handoff #8 §8 in full, plus:

- **A round that did not finish is not a round that was clean.** Zero findings because the auditor
  died is the opposite of zero findings because the code is good. The tally stays at seven.
- **Do not reconstruct a dead agent's findings from a fragment.** The fragment names mutant
  *numbers* from a list that no longer exists anywhere.
- **Instruct auditors to persist findings to disk as they go.** Three crashes, three total losses.
- **Verify a fresh container before believing a red suite.** Playwright's 14 failures here were a
  browser-build mismatch, and `npx eslint .`'s 23 errors were generated files. Neither was real.
- **`git checkout <file>` to revert a mutant is only safe with nothing uncommitted of your own.**
  It was safe this session because HEAD was committed and clean first. Commit before auditing.
