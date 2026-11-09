# Step7 comparison with supplied batch3

Source: supplied commit `1f096469`, fetched from `claude/ui-layout-information-design-1n94si` and merged unchanged into the comparison branch at `d3f618af`. Saved reference:d8245e66. No batch3 recreation or additional application edit was made. User requested comparison before further implementation; implementation remains paused.

[Side-by-side preview](evidence/610/batch3-comparison/index.html) · [Part1: top](evidence/610/batch3-comparison/1366-dark-part1-top.png) · [Part2: methods/entry](evidence/610/batch3-comparison/1366-dark-part2-methods-entry.png) · [Part3: decisions](evidence/610/batch3-comparison/1366-dark-part3-decision.png).

1366px dark, device scale1, mocked data. The saved reference has more usable width because it has no app rails. Sample amounts differ; this compares information hierarchy/layout, not numerical equality. Fresh browser capture: zero page errors, zero Portfolio/broker write attempts. Typecheck passed. This is visual inspection, not full-state preservation verification or a clean independent code audit.

| Area | Batch3 compared with reference |
| --- | --- |
| Identity and Exit Plan | Retain the close match from batches1/2: prominent contract/full expiry, visible details, collapsed Stock Qualification, compact3-column Exit Plan and one explanation disclosure. |
| Method controls | Segmented Monte Carlo/Arithmetic/Ladder/Compare controls now present; prior checkbox-fieldset criticism is obsolete. |
| MC inputs and Run | Compact labelled fields with editable indicator and primary Run on the same row in single-method view. In comparison, controls wrap inside their card. Substantially closer. |
| Target tables | Clearer shaded headers and compact price/probability/time values. Both MC and Arithmetic tables fit their357px wrappers with no horizontal scroll in the captured two-card state, and table headers align. Headers still wrap more than in the wider standalone reference; extra outcome column remains. |
| MC stop consequences | Existing source and barrier-time distinctions remain. Front loss is still per share ($1.50/share in fixture), while the reference emphasizes per-contract loss; this is a unit-presentation difference, not a price comparison. Source/risk explanations above the table are still longer. |
| Barrier Race | Large labelled stacked bars now precede the outcomes table, matching the main graphic hierarchy. Long three-barrier assumptions remain visible beneath the table rather than fully folded into the deeper assumptions disclosure. |
| Decision/execution | Still the largest gap. Selected-target review remains crowded with recorded fields, an ISO decision timestamp, duplicated option-value/context fields and pricing metadata. Inline submission review still exposes a long permanent block of destination/settings/record details before actions. Reference keeps the compact selected TP/probability/time/quantity outcome and actions prominent. |

Overall: batch3 substantially resolves the previous controls/input/table/bar findings. The remaining density is concentrated in the decision section and explanatory detail, plus the per-share/per-contract emphasis. No claim that all remaining G10–G16 gaps or the625-item preservation register have been verified is made here.
