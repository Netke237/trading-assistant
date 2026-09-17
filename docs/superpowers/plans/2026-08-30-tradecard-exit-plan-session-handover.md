# Session Handover — TradeCard Exit-Plan Restructure (Planning Complete)
**Date:** 2026-08-30
**Branch:** `claude/journal-startup-exit-audit-q8aw8v` (pushed to `origin`)
**HEAD:** `db3b8c4`
**Plan:** `docs/superpowers/plans/2026-08-30-tradecard-exit-plan-restructure.md`

---

## Why this exists

This session started with two unrelated smaller questions (where the Journal nav item lives; an audit of the shipped "Compute Exit Plan" feature against its original requirements), then moved into a large planning effort: Kenneth wants to restructure `TradeCard`'s exit-plan UI, which has accreted three overlapping, un-ranked profit-target systems over time — a fixed-% ladder (the original design), a Monte Carlo estimate, and a structural/ATR-based "Exit Plan." The session ran a full `/grill-me`-style interview to converge the design, wrote the implementation plan, then ran `K-adversarial-audit-loop` (audit-only mode) on that plan for **11 rounds** until findings stopped surfacing new dropped demands, then closed the loop by getting Kenneth's explicit confirmation on every remaining open decision.

**No code has been written.** This entire session is planning + audit; the plan is ready to hand to implementation next.

---

## What was done, in order

### 1. Journal nav question
Answered directly, no code change: the Journal link already exists in the left `NavRail`, between "Strategy Watch" and "Settings." Kenneth's screenshot only showed the main panel + right context rail, cropping the left rail out of frame — nothing was actually missing.

### 2. Compute Exit Plan requirements audit
Read the original plan (`docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md`) and its two handoff docs, then independently verified the shipped code against it. Found the implementation matches the spec closely, with one real gap (only the *winning* stop candidate — structural or ATR-floor — was ever exposed to the frontend; the loser was computed and discarded) and one stale-but-harmless doc note (a "known gap" the handoff docs still describe as unfixed had actually been fixed the next day, `7e69d49`). This audit is what motivated the redesign that follows.

### 3. Interview → implementation plan
A multi-round interview (grilling-style, though the `grilling` skill itself wasn't formally invoked) converged Kenneth's restructure request into a concrete design. Key settled decisions, all captured in the plan's own D1–D35 demand ledger:

- **Card order** (top to bottom, under Contract Details): persistent Order Entry strip → **Arithmetic Profit Target** (new, full-width, expanded by default — Kenneth's primary method) → **Monte Carlo Profit Target** (renamed, extended) → **Fixed % Ladder Plan** (the original design, collapsed by default into one group) → **Final Recommendation** (documentation-only, no cross-method arbitration).
- **Full transparency**: both the structural stop AND the ATR-floor stop are now exposed (not just the winner), same for target snapping — raw arithmetic price, nearest structural price, $ distance, $ tolerance, and a 4-state label, not a boolean flag.
- **New pre-trade risk override**: increase risk exposure for a specific trade, feeding the sizing recommendation immediately, persisting onto the resulting position.
- **A real, pre-existing bug found along the way**: the Entry Plan's Contracts field and the Send-to-broker dialog's own Contracts field are two independent, unsynced pieces of state — confirmed in scope to fix.
- Full list of all 35 demands and where each is implemented: see the plan's "Demand ledger" table.

### 4. Adversarial audit — 11 rounds, 57 findings, all fixed
Each round spawned an independent subagent (no memory of prior rounds), fed a full standalone reconstruction of what Kenneth actually asked for (since the plan file alone doesn't carry the conversation), and asked it to find anything dropped, contradicted, or under-specified. Findings were fixed in the plan file between each round; every round was committed and pushed separately (`77a1940` through `1fbfbc8`).

**Rounds 1–6** progressively found and closed a genuinely deep implementation-chain gap in two demands (D19: does a pre-trade risk override actually persist onto the opened position; D23: does fixing the Contracts field actually reach every place a trade gets placed). Each round found the *previous* round's fix was still missing a layer — a file that didn't exist, a wrong function-count, an unimplementable fix description, a missing serializer field, an entire missing component-level callback. Round 7 independently re-traced the whole chain from the UI click through the database and back, and confirmed it had finally bottomed out.

**Rounds 7–11** shifted to a different, subtler class: cross-feature semantic gaps, where one part of the plan silently assumed something a *different* part contradicted. Real examples caught: a "Bottom" label that would have shown two different, disagreeing prices on two different cards; a "Projected R/R" row that would have silently reintroduced the exact cross-method comparison Kenneth explicitly ruled out; an override-resolution helper function that already existed in the codebase and the plan was about to duplicate; two sub-bullets inside the same Feature section (added in different rounds) that had started contradicting each other about how a callback should be wired.

Full round-by-round detail (what each round found, what the fix was, file/line citations) lives inline in the plan document itself — every fix bullet is tagged with which round found it.

### 5. Final confirmation
Presented the 5 remaining open decisions to Kenneth via `AskUserQuestion`, plus a clear out-of-scope summary. **All 5 landed on the plan's own already-written recommended default** — nothing needed to change, just mark them confirmed:
- Container name: **"Fixed % Ladder Plan"**
- Collapse state: **persists across visits** (not just collapsed-by-default)
- Final Recommendation's pre-existing content: **keep the PASS/CAUTION/REJECT verdict badge, drop the two confidence rows** (shown elsewhere already)
- The old "Projected R/R" row: **dropped** from the always-on view (covered instead by the labeled empty-state fallback)
- Send-to-broker dialog quantity edits: **one-off**, do not write back to the shared Contracts field

The plan file was updated to mark all five `✅ CONFIRMED by Kenneth` and pushed (`db3b8c4`). **No open questions remain.**

---

## Current state

- Working tree clean, everything committed and pushed to `origin/claude/journal-startup-exit-audit-q8aw8v`.
- The plan (`docs/superpowers/plans/2026-08-30-tradecard-exit-plan-restructure.md`) is ~900 lines: a Demand ledger (D1–D35), 8 Feature sections with file/line-level implementation detail (verified against live code repeatedly across 11 rounds), an out-of-scope list, a Build sequence with checkpoints, and a Verification section.
- No code changes exist yet — this branch currently only carries plan documents (this handover + the restructure plan + the round-by-round audit history baked into it).

### Explicitly out of scope (in the plan, not silently dropped)
- Free-text "Reason" note on the risk override
- Per-trade override on Max fill's slippage formula (the resulting $ figure stays hand-editable, as today)
- Any cross-method reconciliation logic between the three methods
- Any change to the underlying algorithms themselves (only what they *expose* changes)
- Stocks-mode position creation (no equivalent card there)
- Auto-trade position persistence (pre-existing gap — `/auto-trade/fire` never creates a `PortfolioPosition` row today, for any reason)
- Post-trade transparency in the Portfolio `EditDrawer`'s own separate exit-plan card (gets the new fields for free over the wire, but no new UI to show them)
- Making the post-trade alert system track the Arithmetic stop (flagged as a real, separate gap — alerts still key off the Ladder's stop; no stop-side equivalent to the target side's `activeTpMethod` selector exists)

---

## What's next

- [ ] **Build the plan.** Nothing is blocking implementation — every demand is traced, every open decision is confirmed. Suggested order matches the plan's own "Build sequence with checkpoints" section: backend field exposure first (Feature 4), then the Order Entry strip + Contracts fix together (Features 6+7, the largest single piece), then the card revert/rename (Features 1+2), then the new Arithmetic card (Feature 3), then the pre-trade override (Feature 5), then Final Recommendation last (Feature 8).
- [ ] Given the plan's size and the number of individually-audited fix bullets, consider building it feature-by-feature with a typecheck/test checkpoint after each (as the plan itself specifies), rather than as one large diff.
- [ ] Once built, per this repo's own audit-and-implement pattern (`K-adversarial-audit-loop`), a **second** audit-only loop over the resulting diff (not the plan text) would be the natural close — plans and code drift from each other even when the plan was this thoroughly reviewed.

## How to resume

```bash
cd /home/user/trading-assistant && git status --short   # should be clean
git log --oneline -3                                      # confirm HEAD is db3b8c4 or later
```

Read `docs/superpowers/plans/2026-08-30-tradecard-exit-plan-restructure.md` top to bottom — the Demand ledger is the fastest way back into full context, and every Feature section's fix bullets carry enough inline citation (exact file/line, exact function names) to start implementing without re-deriving anything.
