# Unified Options explanation takeover

Both original implementation branches are integrated on `codex/options-explanation-fixes`, preserving ancestry: Step 5 `9b8a2971`, Contracts `ac39b841`. The other Contracts session reported no application edits, commits, pushes or merges; only its audit report `c5921ef1` was published on `docs/options-contract-explanations-audit`. That report was cherry-picked as `0afc1c25`, without merging other branch changes. Both task claims were explicitly reassigned to root by the user.

## External finding reconciliation

| Report finding | Current correction | Evidence |
| --- | --- | --- |
| 1: `iv` wire key fabricated zero IV weight | `283c2cbb` reads `iv_rank`; `d3d2657a` rejects incomplete snapshots rather than defaulting weights to zero | Literal banner test and missing-weight regression |
| 2: ratio 1.6 displayed as 1.6% | `283c2cbb` uses ratio units; `d3d2657a` preserves exact decimal boundary precision | Formatter, component tests and real scorer-generated wide-spread browser fixture |
| 3: preferred .0555 became 6% | `d3d2657a` preserves 5.55%, exact spread observations, delta bounds and IV basis observations | Literal component boundary regressions |
| 4: blocker .047619… rounded to .0476, making `> .04761` false | `d3d2657a` preserves actual spread/delta operands through typed wire model and rendering | Python comparison/Pydantic tests, literal rendered comparison and generated browser wire |

The earlier root review also fixed fractional card weights independently. Step 5's three observation/interval corrections retain a separate clean independent verdict; Contracts follow-up changes do not touch its source, classifiers, stores or gates.

## Requirements and compatibility

- Version 1, row identity, all five weights/components, nested finite numbers and known shape are checked before showing explanation arithmetic or the global rules banner. Legacy/unavailable data remains unavailable; it does not become a zero weight or fabricated pass.
- Additive hard-bound and raw scorer-input snapshots distinguish missing volume/OI/delta from normalized values and expose nonblocking active hard limits. No broker-source raw-presence claim is made when an upstream adapter already normalized a value.
- Contributions, weighted losses and aggregate retain full precision; rendered contributions offer exact detail. Actual scorer half-tie fixtures exercise 64.5→64 and 65.5→66.
- The independent numeric review found normal put row IDs ended `|P` while the legacy score-card ID defaulted to `|C`. `3db610f5` binds explanation identity to the existing returned row ID, preserving the legacy score-card ID, grading and historical persistence contracts. A put regression covers the actual adapter shape without `is_call`.
- The full 200-panel trace exposed large native layout/style work during sorting. `3db610f5` memoizes unchanged details and applies browser offscreen layout containment, preserving all mounted panels and the ordinary one-open-symbol behavior. Final matched production timings and offscreen focus/scroll checks passed on a12086fa; see the production report. No JavaScript virtualization or persisted expansion state was added.
- New real Python/Pydantic wire fixtures and browser assertions cover exact inequalities, fractional preferred bounds, puts, wide ratios, bear-put/bear-call layouts, long unbroken blocker labels, panel/internal overflow at 1280/1440/1920 and the below-minimum effective viewport gate. This emulates zoom's CSS viewport width; it is not an assertion that a physical browser zoom gesture was automated.

## Independent ledger

Historical counters are retained. The user authorized takeover and completion of both audits after the explicit cap discussion; the additional review scope is recorded in project state.

| Target/code round | Reviewer | Exact diff | Gate findings | Status |
| --- | --- | --- | --- | --- |
| Step 5 / 5 | `/root/vol_events_corrections_audit` | `66561e26..283c2cbb`, Step 5 corrections only + interactions | 0 | CLEAN |
| Contracts / 4 | `/root/contracts_handoff_fix_review` | `0afc1c25..d3d2657a`, external-report corrections + interactions | 0 | Numeric CLEAN; put availability limitation independently reproduced and subsequently corrected |
| Contracts / 5 | `/root/contracts_final_handoff_review` | `d3d2657a..3db610f5`, identity and profile fixes + interactions | 0 | CLEAN |

Round 4 independently checked 1,274 signed/exponent/near-boundary percentage formatting probes against Python Decimal and ran 19 backend / 24 frontend tests. It did not report the availability issue as a numeric gate finding; it is nevertheless fixed to meet the user's implementation requirements.

## Validation so far

- Full frontend after `d3d2657a`: 188 suites / 4,547 tests passed.
- `3db610f5`: typecheck, production build and 110 related frontend tests passed.
- Python 3.11: 147 backend tests passed, including watched grading.
- Deterministic parity: 10,000 exact score cards match `ac39b841` after excluding additive explanation; scores/status/reasons/flags/breakdown/detail/identity unchanged. Repeat with `scripts/verify_options_explanation_parity.py` under Python 3.11; result `TAKEOVER_SCORER_PARITY.json`.
- Final-source production browser/layout and matched production stress results passed. Round 5 is independently clean; the reviewer verified put identity, refresh object replacement, keyed sorting, selection/watch/handoff and mounted accessible contents. Existing dev-mode/ten-panel measurements are historical evidence and do not certify the new full workload.

No merge into main has occurred. Main6cce7364 was merged into this feature branch as2ef6c900, retaining the new dividend-only note and all upstream task state. Final runtime acceptance is recorded below.

## Final corrections and qualification

| Target/code round | Reviewer | Exact diff/scope | Gate findings | Result |
| --- | --- | --- | --- | --- |
| Contracts / 6 | `/root/contracts_minimum_layout_review` | `3db610f5..9a0ad23f`, minimum-width grid correction and interactions | 0 | CLEAN |
| Contracts / 7 | `/root/contracts_tooltip_retry_review` | `9a0ad23f..a12086fa`, authoritative snapshot hover and interactions | 0 | CLEAN |
| Step5 / 6; Contracts / 8 | `/root/options_upstream_merge_review` | Parents `a12086fa` / `6cce7364`, staged merge resolution and Steps5–7 schema/override/API/persistence interactions | 0 | CLEAN |
| Step5 / 7 | `/root/options_merge_test_scope_review` | Two selector assertions against `2ef6c900`; no product changes | 0 | CLEAN; independent20-test run |

The tooltip reviewer originally aborted due model usage quota with no verdict. That attempt is not counted as a completed round; a new reviewer independently completed the same exact scope. The performance evidence author was also interrupted by quota before final-source capture; root completed that runtime capture. Root-run timings do not substitute for independent code audits.

The new production checks exposed internal table overflow at1280px despite no document-level horizontal scrolling. `9a0ad23f` corrected shrinkable column widths, shared header/row gaps and wrapping while preserving all controls. All viewports now pass internal overflow assertions. `a12086fa` replaces the legacy score hover’s hardcoded preferences with the validated server snapshot summary, exact blockers and authoritative score/status; missing snapshots remain unavailable. Right anchoring and wrapping keep hover text within the table.

Latest-main integration preserves upstream dividend-only rejection explanation using the exact upstream condition. Two inherited tests queried a single global REJECT label; the redesigned page correctly has separate event and gate labels. Their assertions now target the actual rendered row gate through the existing helper, keeping both dividend-note assertions intact. Product conditions and scoring were not altered to make those tests pass.

## Final runtime acceptance

- Merged source2ef6c900: typecheck and optimized production build passed.
- Latest Contracts sourcea12086fa:33 production browser cases passed. Merged source:28 page/layout/contract cases plus5 Step5 boundary cases passed (33 total), including real scorer-generated wire inequalities, bear-put/bear-call, keyboard and network isolation. Original tracked screenshots were restored byte-for-byte; a new1280px bear-call capture is retained separately.
- Merged frontend:14 related suites /249 tests passed, including Step5, Step6, explanation helper/cards and earnings/send interactions. Full frontend previously passed188 suites /4547 tests atd3d2657a; it was not re-run in full after later targeted corrections. Inherited Jest act warnings are separate from browser console assertions.
- Python3.11 merged backend:78 validator/explanation/watched-grading tests passed; earlier broad correction run passed147 tests. Initial misspelled test-path commands ran zero tests and are not validation evidence.
- Merged scorer parity:10,000 exact score cards still match deliveredac39b841 after excluding the additive explanation.
- Accepted matched production stress capture at exacta12086fa:200 rows and0/1/200 valid mounted panels, five runs per state. Worst interaction p95:108.5ms; maximum long task76ms; maximum median interaction regression14.7%, all within200ms/100ms/20% budgets. Zero HTTP requests during explain/sort/pick. Full raw runs, representative traces, portable helpers, cached-render comparison and offscreen/keyboard/star/refresh assertions are retained in `TAKEOVER_PRODUCTION_REPORT.md` and its linked artifacts. Step6 source is unchanged by the upstream merge.
- Latest origin/main6cce7364 is an ancestor of the feature branch; merge-tree against it completes without conflicts. Both original implementation heads are ancestors. The other session’s report-only commit was reconciled without duplicate application changes.

Historical audit counters remain intact: Step5 findings[13,12,6,0,0,0,0], Contracts[0,1,0,0,0,0,0,0]. No gate findings remain outstanding. This is a reviewable feature branch, not a production deployment or merge into main. Existing unrelated STATE-PROBE audit warnings are outside these targets.

## Main merge

On2026-10-04, the user explicitly authorized merging to main. Main fast-forwarded from6cce7364 to the exact audited feature head `e1751e1596215052b6811b5a239fae4e4a8a7c37`; GitHub remote main was verified at that commit. No new application changes or conflict resolutions were needed. Both task statuses are now shipped; audit history and evidence remain intact. Earlier no-merge statements above describe pre-merge checkpoints. No production deployment was performed.
