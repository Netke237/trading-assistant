# Trade card reference alignment — final build acceptance

TRADE-CARD-REFERENCE-ALIGNMENT-FINAL-VERIFIED

Application commit: `e98f4d88226b8c03004aaa0f58889914dcc8260a`. Build acceptance is complete; the separate phase code audit and merge gate remain authoritative. This marker verifies implementation/local acceptance, not shipment or an independent numeric audit.

[Actual page compared with the saved preview](evidence/610/final/index.html) · [Top of page](evidence/610/final/layout/1366-dark-part1-top.png) · [Methods and entry](evidence/610/final/layout/1366-dark-part2-methods-entry.png) · [Decision and execution](evidence/610/final/layout/1366-dark-part3-decision.png).

## Reference and visual acceptance

The controlling interactive reference is `d8245e6695b301dae35a476f170e6cdf4cc0d7b0:docs/superpowers/specs/2026-11-09-trade-card-reference/preview.html`, the exact file linked by the user. The full reference set and latest Stock Qualification amendment remain controlling. Actual app rails reduce available width; sample figures do not specify model results.

Fresh reviewer `accept_final_rendered_preview` independently inspected the final screenshots and returned **ACCEPT**, with no remaining material D01–D12 gaps. [Full independent verdict and viewed-image list](evidence/610/final/visual-acceptance.md). Earlier V1–V5 findings are preserved in [the before-fix report](evidence/610/visual-review-2-before/review.md); all five are resolved. This is a visual acceptance review, not a formal numeric/persistence audit round.

| Amendment | Final behavior and evidence |
| --- | --- |
| D01 | Monte Carlo alone initially; segmented comparison runs no calculation and retains all-three support. All layout/state reports. |
| D02 | Prominent strike/right/full expiry, contract snapshot details and original badges/colors. Layout identity/top captures. |
| D03 | Market Sentiment → Fundamental Health → identity/details → closed Stock Qualification → Exit Plan → methods → entry → decisions. Initial/top captures. |
| D04 | One compact editable Exit Plan, concise loss/remaining values, fully readable time threshold at1200, detailed basis closed. Exit Plan captures and text-bounds assertion. |
| D05 | Structure evidence and Check structure retained inside associated explanations; no standalone repeated settings block. Expanded source/state evidence. |
| D06 | Essential source/units and material caveats visible; full method basis/provenance closed. Arithmetic long paragraph preserved intact in its disclosure. Comparison/details-open captures. |
| D07 | Consistent target/stock/option/probability/time/outcome tables; equal-height/aligned compared cards; Ladder outcome/rung columns remain reachable through table scroll. All pair/three-method state measurements. |
| D08 | MC barrier inputs and guarded barrier-time option value/loss together; per-contract loss headline retains per-share evidence in details. Arithmetic keeps its separate current-time basis. Fresh/stale/rerun captures and unit/availability regressions. |
| D09 | Graphical Barrier Race nested in MC, default closed; assumptions/risk explanations deeper. Race captures and default-disclosure checks. |
| D10 | Final status in identity and one selected-target review; duplicate latest/all-target recommendation removed with explicit surviving twins. Source inventory. |
| D11 | Grouped method/target/basis choice, prominent selected TP/probability/time/quantity outcome, record metadata closed, execution actions together. Decision captures and exact selection regressions. |
| D12 | Inline submission and technical details closed; actionable/provisional/no-protective-order notices visible; broker fact grids and requested/server review distinctions preserved. Destination and changed-review captures plus payload goldens. |

## Information preservation

[625-item reconciliation](evidence/610/final/information-preservation/reconciliation.json), [independent source review](evidence/610/final/information-preservation/source-review.md) and [portable integrity validator](evidence/610/final/information-preservation/validate.py). All625 original IDs/types (520 integer +67 N +38 H) are accounted; unresolved source IDs0. Nine deliberate duplicate summaries identify their surviving originating-method twins. Method-count399 was restored as hover metadata. All original unique explanations/actions/conditional notices and semantic colors retain locations.

This is exhaustive source accounting with state/flow execution evidence; it does not claim625 separate browser assertions. Conditional edge states use the named component/flow regressions and source guards, with browser samples only where the harness exercises them. The source review's runtime-pending language is preserved as historical scope; completed runtime matrices are linked below. No pending item is falsely relabeled individually browser-covered.

## Runtime and local checks

18 mocked browser runs:1200/1366/1920 × dark/light across layout, comparison/freshness and destination harnesses;960 assertions,0 page errors,0 save/order attempts. Initial, computed, all two-method pairs, three methods, edited/reverted, stale/restored/rerun, expanded race, basket/broker review and changed-review refusal are captured. [Layout checks](evidence/610/final/layout/checks.json), [state checks](evidence/610/final/states/checks.json), [destination checks](evidence/610/final/reviews/checks.json).

Typecheck passed. The full frontend invocation completed345 suites (330 passed/15 failed;6314 passed/51 failed tests) while presentation completion and heavy browser work were active. Every failed and modified suite was then included in an isolated final verification union: **27 suites /623 tests passed**. The initial targeted pass was24/27; three test-only outdated presentation/scenario assumptions were corrected, then those3 suites/49 tests passed. No application change occurred during finishing, no timeout was increased, no payload golden or numerical/safety expectation was weakened. Exact payload, quantity, expiry/fingerprint, changed-review and save-first tests pass. All three unrelated Stocks/Pre-Breakout timeout suites passed unchanged. [Verification summary and full result evidence](evidence/610/final/tests/verification-summary.json).

The full invocation's original failures are retained; it is not described as an all-green invocation. No backend file/model/store/API/transport rule changed. All API traffic in captures was mocked, with no real Portfolio save, broker order, provider or notification action.

## Source binding and remaining gate

[Source binding](evidence/610/final/source-binding.json) ties the captures' base HEAD plus frozen working-tree application to the eventual application commit using source hashes; base39db95a8 alone is not mislabeled as containing the final changes. The frozen application has remained unchanged since the accepted capture matrix and source review.

Plan stage3 closed clean; original phase575 history and current counters are preserved. All seven build tasks now meet local acceptance. The independent integrated phase code audit remains a separate requirement before merge, followed by exact-head CI and board self-merge conditions.
