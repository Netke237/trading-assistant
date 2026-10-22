# 30: Reconcile trade-card follow-up release status

**What to build:** Determine whether the separate clean follow-up needs integration.

**Blocked by:** Follow-up 55e08e55 and current main comparison.

**Status:** done 2026-10-09 (verification only; no application code changed). Finding: the follow-up **does need integration**, but it cannot be merged as is. See *Outcome*. A new integration ticket needs Kenneth's approval.

**Owner category:** agent release verification.

- [x] Do not recreate merged UI-CORE, SCORE-EVIDENCE or QUALIFICATION work.
- [x] Compare follow-up ancestry and exact audit scope; report PR/merge need without claiming it shipped.

## Outcome

Checked against main `a2b6935` (the T1 merge, #138).

**Where the follow-up is.** It is on branch `origin/codex/trade-card-ui-followup` (TRADE-CARD-UI-FOLLOWUP, tickets TC-UI-01 to TC-UI-07). It has three commits that are on no other branch: `a1329b25` (plan), `bdf3bed2` (build) and `55e08e55` (audit evidence). It forks from main at `4b06656a` (2026-10-05). Main is now 141 commits ahead of that point. `git cherry` shows none of the three commits on main, so the work has **not shipped** by any route. Main's PROJECT_STATE.json has no TRADE-CARD-UI-FOLLOWUP entry; the only state entry is on the branch itself.

**What the audit covered.** One clean plan round. One clean code round: a fresh independent reviewer, range `4b06656a..bdf3bed2`, zero gate findings (`CODE-AUDIT.md` on the branch). That clean result applies to a base that is now out of date. It does not cover a merge into current main.

**Trial merge into current main.** Done in a throwaway worktree; nothing was committed. It produces 5 conflicts:
- `docs/superpowers/PROJECT_STATE.json`
- `frontend/app/(frame)/screener/step-7-position-card/page.tsx`
- `frontend/app/(frame)/screener/step-7-position-card/__tests__/page.test.tsx`
- `frontend/components/organisms/StockPositionCard/index.tsx`
- `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.pending.test.tsx`

All the code conflicts are on the **Stocks** side. Since the fork, main has restructured Stocks Step 7: STOCKS-STEP-MERGE-S2 added the shared Position card, synchronized navigation and shared basket ownership (`ef674cbf`, `cdefda84`). P0B and T1 added an earnings veto, bearish refusal and TIME_STOP (`31409aea`, `fdaf9052`, `2a6f0210`). TC-UI-06's Stocks score-card move was written against the old page layout.

The **Options** side merges without textual conflicts: TradeCard, Step 7 trade card, AlternativeContractRow, CollapsibleSection, ScoreCardPanel. Those are TC-UI-01 to TC-UI-05 and TC-UI-06 (Options half). TC-UI-07's Step 3 change (hide Run Scan in Stocks mode) also merges cleanly. A clean textual merge has not been typechecked or tested.

**Conflict with an active claim.** STOCK-DESIGN-GRILLING (`claude/stock-presentation-design`) is redesigning the Stocks and Pre-Breakout presentation in the Options style. That covers the same Stocks surfaces as TC-UI-06 (Stocks half) and TC-UI-07. Under the parallel-work rule, the Stocks half must not be integrated while that claim is active.

## Recommended follow-up (needs Kenneth's approval before anyone starts)

Proposed **TICKET-38: Integrate the trade-card UI follow-up into current main.** — Kenneth chose option A (2026-10-09). Built on `claude/relaxed-fermat-sm9xru` (d43931e2 + F1 fix a8c3b4a4); code audit clean at code round 2 of 3; phase TRADE-CARD-UI-FOLLOWUP-OPTIONS in PROJECT_STATE. Not merged — awaiting Kenneth.
- **Option A (recommended): Options-only now.** Bring in TC-UI-01 to TC-UI-05 and the Options half of TC-UI-06 on a new branch from current main. Leave out TC-UI-07 and the Stocks half of TC-UI-06, which go to STOCK-DESIGN-GRILLING. Run typecheck, Jest and the follow-up e2e spec. Then run a fresh independent code audit of the integration diff; the old clean round does not carry over.
- **Option B: everything, later.** Wait until STOCK-DESIGN-GRILLING releases its claim, then integrate all seven tickets and redo the Stocks half against the S2 card.
- Either way, keep the original branch and its audit record as provenance, and do not mark it shipped until an authorized merge.
