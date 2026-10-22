# TRADE-CARD-UI-FOLLOWUP-OPTIONS — integrate the Options half of the trade-card UI follow-up

2026-10-09. Backlog TICKET-38 (`.scratch/project-ticket-reconciliation-20261009/issues/30-trade-card-release.md`). Kenneth chose option A.

## Source

- The feature was built on `origin/codex/trade-card-ui-followup`. Implementation commit `bdf3bed2`, evidence commit `55e08e55`, fork point `4b06656a`.
- The original plan is `docs/superpowers/plans/trade-card-ui-followup/PLAN.md` on that branch. It was independently plan-audited clean (TRADE-CARD-UI-FOLLOWUP round 1). The code was audited clean in code round 1, over range `4b06656a..bdf3bed2`.
- This document is a narrowing of that clean plan and adds no new behaviour. The old code audit does not carry over, because the base has moved 141 commits. The integration diff gets a fresh code audit.

## Scope: what comes in

The changes from `4b06656a..bdf3bed2`, limited to these paths:

| Path | Ticket |
|---|---|
| `frontend/components/organisms/TradeCard/index.tsx`, `TradeCard.module.css`, `__tests__/TradeCard.test.tsx`, `__tests__/TradeCard.methodPick.test.tsx` | TC-UI-01, 02, 03, 06 (Options) |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, `__tests__/contracts-sync.test.tsx` | TC-UI-02 |
| `frontend/components/molecules/AlternativeContractRow/AlternativeContractRow.module.css` | TC-UI-04 |
| `frontend/components/molecules/CollapsibleSection/index.tsx`, `__tests__/keepMounted.test.tsx` | TC-UI-05/06 (shared) |
| `frontend/components/molecules/ScoreCardPanel/index.tsx`, `__tests__/collapsedEvidence.test.tsx` | TC-UI-05 |
| `frontend/e2e/tests/trade-card-ui-followup.spec.ts`, Options test only | validation |

## Excluded (left to the STOCK-DESIGN-GRILLING owner)

- TC-UI-07 (Step 3 Run Scan hidden in Stocks mode): `step-3-direction/page.tsx` and `verdictFollowsRestoredContext.test.tsx`.
- TC-UI-06 Stocks half: `step-7-position-card/page.tsx` and its test; `StockPositionCard/index.tsx` and its test.
- The Stocks e2e test case.
- The original branch's PROJECT_STATE entry and its evidence/screenshots. Those stay on that branch as provenance.

## Method

- Apply the path-limited diff with `git apply -3`. Never merge or cherry-pick the branch: that would mark the Stocks commits as merged, and Git would then drop them silently when the Stocks half is integrated later.
- Where `main` changed the same lines after the fork, keep `main`'s behaviour and fit the follow-up's presentation change around it. The later changes are P0A's Unvalidated ConfidenceBadge, and P0B's earnings veto and bearish refusal before save.

## Constraints

- No backend, numeric calculation, persistence schema, storage key (other than the follow-up's own reviewed `CollapsibleSection` keys) or broker payload changes.

## Acceptance

- `npm run typecheck` is clean.
- The full Jest run passes, with no new failures compared with `main`.
- The Options e2e case passes where Chromium is available. If fonts are mocked, record that as a limitation.
- One fresh independent code audit over `origin/main..HEAD` for the application paths, with zero gate findings, within a cap of 3 code rounds.
- Kenneth decides on the merge.
