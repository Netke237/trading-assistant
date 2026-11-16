# Trade-card qualification placement

Phase: `TRADE-CARD-QUALIFICATION-PLACEMENT`. Size XS, complexity 1: one existing disclosure moves within the same component, preserving its data and persistence.

The user's annotated screenshot supersedes the older G4 placement: immediately beneath Contract Details show Stock Qualification, then Contract Qualification. Both default to collapsed. Preserve previously saved disclosure preferences, all scores, status badges, colours, tooltips and nested captured explanations. Remove the previous bottom instance; Alternative Contracts remains after Decision & execution.

## One build task

1. Amend the existing placement regression in `frontend/components/organisms/TradeCard/__tests__/TradeCard.referenceLayout.test.tsx` to require both qualification panels within the identity section, adjacent in the requested order, exactly one instance each, and default closed; retain the alternatives assertions. Strengthen the existing corresponding ordering assertion in `TradeCard.scoreDisclosure.test.tsx`. Remove obsolete placement comments in that file and `TradeCard.test.tsx`.
2. Run the amended placement regression before implementation; expect failure because Contract Qualification is still outside the identity section.
3. Move the complete existing Contract Qualification `CollapsibleSection` in `frontend/components/organisms/TradeCard/index.tsx` immediately after Stock Qualification, without changing props, content, storage keys or defaults. Update only the comments describing its old position. No numeric, broker, calculation, state-schema or CSS changes.
4. Run frontend typecheck and existing frontend tests, preserving the full qualification/scoring evidence coverage. If resource constraints expose existing failures, record and diagnose them rather than claiming green. Run a mocked browser check in light and dark themes for requested order and collapsed appearance and expand both to inspect content preservation. Save concise screenshots and evidence.
5. Commit only these four application/test files with `fix(trade-card): group qualifications beneath contract details` and the repository attribution trailer. Coordinator owns plan/state/audit records.

## Acceptance and preservation

- Contract Details → Stock Qualification → Contract Qualification → remaining identity content, followed by Exit Plan.
- Both default collapsed on a fresh browser; independent existing saved open/closed preferences remain respected.
- Exactly one panel of each kind; expanded stock and contract scores, evidence, badges, colours and explanations retain their original source and content.
- Alternative Contracts stays below Decision & execution; no duplicate at the former Contract Qualification location.
- Exact original contract disclosure JSX is unchanged apart from indentation; all number-producing and submission code remains unchanged.
- Plan and integrated code each require a fresh independent gate audit (maximum three rounds per stage). Gate: wrong user/broker numbers or persisted-data corruption; mechanism comments only when acting on them would cause a wrong change. No other findings belong to the formal gate.

## Progress milestones

10% plan drafted; 20% independently approved; 50% code exists; 70% checks and browser acceptance pass; 85% code independently clean; 95% exact-head CI green and merge conditions satisfied; 100% merge and post-merge checks verified. Existing shipped #603 audit counters remain untouched.
