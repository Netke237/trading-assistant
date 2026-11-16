STATUS: done — implementation and verification only; independent visual/code gates remain coordinator-owned.
COMMITS: e98f4d88 fix(trade-card): match preview entry decisions and expandable details

RED evidence from preserved prior implementation:
- /tmp/610-red-focused.log: 4 valid acceptance tests failed (compact entry panel missing; recorded decision disclosure missing; inline submission disclosure missing; race assumptions disclosure missing), 94 passed, plus the separate submission-review suite import failure.
- /tmp/610-red-actions.log: grouped destination-action acceptance test failed because the direct action had no shared decision-action ancestor; 8 passed.
- /tmp/610-red.log was terminated after a bad Jest CLI argument; it is not qualifying RED evidence.
- BrokerOrderReview RED evidence is in coordinator/prior-agent history; no claim of a local RED run here.

GREEN:
- Required full serial baseline: 345 suites, 330 passed / 15 failed; 6365 tests, 6314 passed / 51 failed (/tmp/610-full-serial.log). It ran under heavy browser load and before several final source/test edits were complete.
- Exact union rerun, serial/silent --runTestsByPath: 27 suites, 24 passed / 3 failed; 623 tests, 620 passed / 3 failed (/tmp/610-finisher-targeted-r1.log and .json).
- Those final 3 failures were presentation/scenario test assumptions only. Test-only fixes retained numerical expectations, guards, goldens and all timeouts. Follow-up: 3 suites / 49 tests passed (/tmp/610-finisher-targeted-r2.log and .json).
- Combined latest results: all 27 suites / 623 tests passed; includes all 21 modified test files, all 15 full-baseline failure suites, and all 3 untouched Stocks/Pre-Breakout suites. Machine-readable exact per-suite union: /tmp/610-finisher-final-verification.json.
- npm run typecheck passed (/tmp/610-finisher-typecheck.log); git diff --check passed.
- No application source edited during this finishing task. No numerical golden regenerated. No timeout changed. No backend/model/API/store/payload file changed. No push or branch switch.

Every full-baseline failure classification (unique failed tests, totaling 51):
| Suite | Failed | Classification and final disposition |
| --- | ---: | --- |
| TradeCard.methodPick | 16 | 14 obsolete disabled-reason/disclosed-metadata assertions; 2 sparse-time render failures from the pre-final source guard. Final run passed. |
| direct-send-save-first | 7 | Wait/timeout failures under prior load; suite rerun unchanged, passed (106.922s). |
| direct-send-stop-gate | 2 | Timeouts in existing earnings/auto-trade flow cases; final run passed with all original guards/timeouts. |
| TradeCard.exitSettings | 1 | Read-only assertion scoped to a parent that now also contains editable Limit; assert the read-only text and reject editable/button ancestors. Passed. |
| integrated-flows | 1 | Barrier Race shortcut flow timeout; final run passed. |
| TradeCard.verification | 1 | Obsolete comparison CSS expectation; updated to accepted wrap layout, passed. |
| TradeCard.methodTargetTables | 5 | Obsolete per-share headline/current-time-provenance placement assertions; exact per-contract headline and retained per-share details verified, passed. |
| contracts-sync | 4 | Three timeouts and one still-placing wait under prior load; action-group/disclosure expectations adapted to accepted layout; final run passed. |
| TradeCard.methodSwitch | 1 | Obsolete shaded-header token expectation; accepted readable primary text verified, passed. |
| submission-payload-golden | 3 | Two direct-send timeouts, then cross-test outgoing payload contamination. Entire suite rerun unchanged, exact goldens passed (8.136s). |
| TradeCard.typography | 1 | Contracts moved to sibling entry column; scope to compact Entry & position size panel while retaining Editable-tag/read-only assertions. Passed. |
| Stocks autoExecute.methodPickExempt | 3 | Existing timing failures; untouched rerun passed. |
| Stocks readableScanError | 1 | Existing timing failure; untouched rerun passed. |
| Pre-Breakout presentationShell | 1 | Existing timing failure; untouched rerun passed. |
| TradeCard.monteCarloEssentials | 4 | Undefined/negative/infinite elapsed cases used pre-final time guard (fixed before freeze); NaN requires explicit existing target selection because NaN cannot establish cross-target equality. Kept unavailable/null expectations and opened existing race disclosure before selection; all 4 passed. |

Final rerun's 3 failed assumptions before test-only correction: typography old region scope; exitSettings read-only parent scope; sparse NaN race's unselected target scope. No new application defect was found.

FILES (33 allowed frontend files):
- frontend/app/(frame)/screener/step-7-trade-card/__tests__/contracts-sync.test.tsx
- frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-expiry.test.tsx
- frontend/app/(frame)/screener/step-7-trade-card/__tests__/direct-send-stop-gate.test.tsx
- frontend/app/(frame)/screener/step-7-trade-card/__tests__/integrated-flows.test.tsx
- frontend/app/(frame)/screener/step-7-trade-card/__tests__/submission-review.test.tsx
- frontend/app/(frame)/screener/step-7-trade-card/page.module.css
- frontend/app/(frame)/screener/step-7-trade-card/page.tsx
- frontend/components/molecules/MethodPickSelector/MethodPickSelector.module.css
- frontend/components/molecules/MethodPickSelector/__tests__/MethodPickSelector.test.tsx
- frontend/components/molecules/MethodPickSelector/index.tsx
- frontend/components/organisms/BarrierRaceCard/BarrierRaceCard.module.css
- frontend/components/organisms/BarrierRaceCard/__tests__/BarrierRaceCard.test.tsx
- frontend/components/organisms/BarrierRaceCard/index.tsx
- frontend/components/organisms/BrokerOrderReview/BrokerOrderReview.module.css
- frontend/components/organisms/BrokerOrderReview/__tests__/BrokerOrderReview.test.tsx
- frontend/components/organisms/BrokerOrderReview/index.tsx
- frontend/components/organisms/SubmissionReview/SubmissionReview.module.css
- frontend/components/organisms/SubmissionReview/__tests__/SubmissionReview.test.tsx
- frontend/components/organisms/SubmissionReview/index.tsx
- frontend/components/organisms/TradeCard/TradeCard.module.css
- frontend/components/organisms/TradeCard/__tests__/TradeCard.decisionGroup.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.exitSettings.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.methodComparison.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.methodPick.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.methodSwitch.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.methodTargetTables.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.monteCarloEssentials.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.orderBudget.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.submissionReview.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.typography.test.tsx
- frontend/components/organisms/TradeCard/__tests__/TradeCard.verification.test.tsx
- frontend/components/organisms/TradeCard/index.tsx

DEVIATIONS: Combined full-baseline plus exact all-modified/all-failure rerun used as approved in the continuation brief; no new full rerun. Documentation, state, visual evidence and formal audits not owned/edited here.
NOTICED (not fixed): Independent visual/code acceptance must still complete before merge; this implementation verification is not an independent audit.
