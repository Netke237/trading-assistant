# #610 independent visual acceptance review

**INTERIM VERDICT: CONCRETE GAPS — visual acceptance withheld pending refreshed captures.**

Reviewer: fresh independent visual acceptance reviewer. This review assesses the actual rendered application against frozen reference `d8245e6695b301dae35a476f170e6cdf4cc0d7b0`. It is separate from the numeric/persistence code audit and does not change or qualify audit counters. Passing checks, item inventories and source symbols do not override the rendered findings below.

## Scope and comparison basis

Read the current checkout's AGENTS.md and Task7 in `docs/superpowers/plans/2026-11-09-trade-card-reference-alignment-plan.md`; read frozen README, IMPLEMENTATION-GAPS, preview.html and reference.css and viewed the frozen rendered evidence. Read the original independent review `docs/superpowers/plans/trade-card-reference-alignment/evidence/610/visual-review-1/gaps.md`.

Viewed actual DPR1 mocked application captures at 1200, 1366 and 1920, in both themes. Compared hierarchy, grouping, density, active text readability, default disclosures, target-column layout, race placement and destination-review presentation. The shell leaves substantially less content width than the standalone reference, so responsive wrapping is expected. Sample dollars, dates and probabilities are not design specifications. The app's existing palette and status colors should remain; no reference mint or new global colors are requested.

This is screenshot-based presentation review with supplied harness reports used only to identify state/fixture context. No app files, tests, GH records, state records or commits were changed. No production numeric correctness, persistence completeness, broker requests or real provider/deployed-mini-PC behavior is certified. Expanded 9000px captures are useful for overall flow but were resized by the viewer; small-text judgments below use targeted DPR1 crops/captures, not those reduced full pages.

## Concrete remaining gaps

### V1 — 1200px time threshold clips at the Exit Plan card edge (D04)

Evidence: `/workspace/step7-aligned-final-matrix/1200-dark-exit-plan.png` and `1200-light-exit-plan.png`, corroborated by `1200-dark-part1-top.png`. The actual right column cuts off the end of “3 days to expiry.” This is an essential threshold and the reference requires it readable. A no-horizontal-page-overflow result does not establish that this nowrap child is fully visible.

Narrow remedy: adapt the three-column layout or time-line wrapping at this content width so the complete phrase is visible without making it microtext. Preserve the readonly/alert semantics and value.

### V2 — Essential active labels and qualifications are still too faint in dark theme (D06/D07/D08/D09/D11/D12)

Evidence: `1366-dark-part2-methods-entry.png`, `1366-dark-part3-decision.png`, `1920-dark-comparison.png`, `1920-dark-barrier-race.png` under the final-matrix directory. The target-table headers, stop-context labels, probability/time qualification, and particularly “Entry basis is provisional … Not a fill” / “no protective stop-loss …” are rendered as faint small gray text on the dark surface. The selected values and colored warning messages are much clearer. Light equivalents are readable. The remaining problem concerns reading essential active context, not a preference for the reference palette.

Narrow remedy: use a stronger existing text token for active labels and material caveats in these local components, retaining caution/reject colors and the current application palette. No global token redesign or indiscriminate restyling is needed.

### V3 — Long Arithmetic provenance still dominates the default comparison (D06)

Evidence: final-matrix `1366-light-comparison.png`, `1200-dark-comparison.png`, `1920-dark-comparison.png`. The paragraph beginning “Current-time stop cost: Black–Scholes today…” remains expanded before the target table. At 1366 it spans approximately eight lines, explains Structure & Stops versus Barrier Race pricing, premium basis, and the unchanged Exit Plan, and pushes the aligned target tables down while leaving a corresponding blank area in Monte Carlo. This is the explanatory prose D06 explicitly moves into disclosure.

Narrow remedy: keep a concise visible current-expiry versus barrier-time basis statement and the material no-automatic-alert caution; retain the complete original paragraph in the existing Arithmetic basis disclosure. Do not change calculations or erase the distinction between sources.

### V4 — Broker destination review still uses one long column at every width (D12 / original G16)

Evidence: `/workspace/step7-aligned-final-reviews/1200-dark-broker-review.png`, `1366-light-broker-review.png`, `1920-dark-broker-review.png`. Full-resolution derived crops `/tmp/1920-dark-broker-review-crop.png` and `/tmp/1366-light-broker-review-crop.png` were created directly from those supplied images and viewed. Even at 1920, facts occupy a single left-aligned column in a very wide panel. Account metadata includes a full server/credential explanation as the primary value. The reference groups destination/request, position settings and supporting decision into readable parallel fact grids. This remains a clear presentation mismatch, independent of the existing request/fingerprint correctness.

Narrow remedy: responsive fact grids within the existing authoritative groups; short primary account/value strings with full qualifiers retained as secondary hints or technical disclosure. Keep requested/effective distinctions and visible estimate/fill, re-review and no-protective-order warnings.

The basket's requested/server-resolved table is a useful production addition and is not rejected for differing from the demo's grid. Do not replace its authoritative columns with illustrative arithmetic.

### V5 — Two-method MC + Ladder comparison needlessly becomes separate rows at 1366 (D01/D07 comparison)

Evidence: `/workspace/step7-aligned-final-states/1366-light-mc-ladder.png`, contrasted with final-matrix `1366-light-comparison.png` (MC + Arithmetic). With exactly MC and Ladder selected, both occupy separate full-width rows although MC + Arithmetic share an aligned row at this width. The reference calls for two compared cards on the same row, with the extra third card wrapping. Ladder's wider outcome table can retain horizontal scrolling; it need not force a special stacking rule when the ordinary two-card threshold has been met.

Narrow remedy: remove the special two-method Ladder full-width exception while preserving the shared narrow-content stacking threshold, reachable full-position/rung columns, and the third-card wrap. Verify a real rendered two-method Ladder comparison after the change.

## D01–D12 disposition on the reviewed captures

| ID | Disposition | Rendered evidence and limit |
| --- | --- | --- |
| D01 | Substantially aligned; V5 open | MC alone initially; compact explicit method toggles; all-three state exists. Supplied state checks report opening comparison runs nothing. Two-method Ladder exception remains. |
| D02 | Accept presentation | Prominent strike/right and full long-month expiry/year, two-column identity and secondary metadata. Shell wrapping is reasonable. |
| D03 | Accept presentation | Identity/details → Stock Qualification → Exit Plan → methods → compact entry/size → grouped decision. Stock Qualification directly below Contract Details and initially closed in viewed top/initial captures. |
| D04 | V1 open | One compact editable plan, succinct loss/remaining values and one closed explanation; complete time threshold clips at 1200. |
| D05 | Accept presentation | No standalone Structure & Stops block before methods; associated explanatory content is reachable through expansions. This is not a completeness audit of every conditional source. |
| D06 | V2/V3 open | Main results are much more compact and model disclosures exist, but Arithmetic's long basis paragraph still precedes targets and dark active context remains faint. |
| D07 | Table structure accepted; V2/V5 open | Consistent target/stock/option/probability/time/outcome order; all visible result rows; MC + Arithmetic outer cards and target slots align. Ladder retains full/rung distinction and Not supplied labels. |
| D08 | Main structure accepted; V2 open | Monte Carlo shows stock/option barrier input, value and loss at stop, and barrier-time basis together. Stale screenshots visibly suppress race-derived stop values and show the warning. Numeric agreement is outside this review. |
| D09 | Structure/graphic accepted; V2 open | Race lives inside MC's closed expansion; full-width labeled segments and numeric outcomes shown when opened; deeper assumptions/risk explanations remain disclosed. |
| D10 | Accept presentation | No duplicate Final Recommendation/all-target section; final status in identity and one selected-target review. |
| D11 | Structure accepted; V2 open | Compact grouped method/target/basis choices and prominent selected-target facts; recorded details closed; submission review closed; actions grouped. 1200 stacks the decision columns sensibly. |
| D12 | V2/V4 open | Inline submission review and technical provenance default closed; notices remain visible. Destination tracking/requested/server values distinct. Broker review remains a long single-column presentation. |

## Images actually viewed

Reference directory: `/workspace/trade-card-design-review/docs/superpowers/specs/2026-11-09-trade-card-reference/evidence/`:

- `reference-initial.png`, `reference-comparison.png`, `reference-decision.png`, `reference-broker-review.png`, `reference-basket-review.png`, `reference-race.png`, `reference-light.png`.

Actual directory `/workspace/step7-aligned-final-matrix/`:

- `1200-dark-part1-top.png`, `1366-light-part1-top.png`, `1920-dark-part1-top.png`.
- `1200-light-part2-methods-entry.png`, `1366-dark-part2-methods-entry.png`, `1920-light-part2-methods-entry.png`.
- `1200-light-part3-decision.png`, `1366-dark-part3-decision.png`, `1920-light-part3-decision.png`.
- `1200-dark-exit-plan.png`, `1200-light-exit-plan.png`.
- `1200-dark-comparison.png`, `1366-light-comparison.png`, `1920-dark-comparison.png`.
- `1200-dark-barrier-race.png`, `1366-light-barrier-race.png`, `1920-dark-barrier-race.png`.

Actual directory `/workspace/step7-aligned-final-reviews/`:

- `1200-dark-broker-review.png`, `1366-light-broker-review.png`, `1920-dark-broker-review.png`.
- `1200-light-basket-review.png`, `1366-dark-basket-review.png`, `1920-dark-basket-review.png`.
- Derived full-resolution broker crops listed under V4.

Actual directory `/workspace/step7-aligned-final-states/`:

- `1200-dark-stale.png`, `1200-light-restored.png`.
- `1366-dark-edited.png`, `1366-dark-reverted.png`, `1366-light-mc-ladder.png`, `1366-light-details-open.png`.
- `1920-dark-initial.png`, `1920-light-stale.png`, `1920-dark-restored.png`.

## Next acceptance step

Coordinator has acknowledged these concrete presentation findings and is preparing narrow fixes plus refreshed captures. This interim report describes the supplied pre-fix screenshots. Acceptance requires visually checking the new frozen-source captures; implementation claims alone will not clear V1–V5. No additional polish requests are made.


## Permanent interim evidence

Representative V1–V5 before-fix images are stored beside this report. Absolute scratch paths above identify the original capture run; they do not identify the final candidate. This report withholds visual acceptance and is preserved as the independent review that caused these fixes. The later final verdict is separate.
