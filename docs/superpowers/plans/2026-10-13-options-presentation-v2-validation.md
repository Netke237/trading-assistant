# Options presentation V2 — unchanged frontend baseline

13 October 2026. Coordinator ran `npm run test -- --runInBand` in the unchanged source checkout before the new UI code. Application source matches 7fa0ff5d; origin/main 5f98b791 added only the approved documentation package.

Result: 233 suites, 231 passed and 2 failed; 4,994 tests, 4,992 passed and 2 failed. Runtime 525.005 seconds. No snapshots.

Exact failures, observed before this implementation:

- StockSendDialog.session.test.tsx: `uses matching shared edits for totals, saved levels, allocation, snapshot and pick; quantity edits scale shared allocations` expects `4,470`, but this Windows locale renders `4.470`.
- BarrierRaceCard.test.tsx: `the inline disclosure / shows the assumptions strip outside it` expects `2,000 paths · each row sums to 100%`, but the platform renders the grouping with a dot.

No production formatter or unrelated test changed to hide these differences. React act warnings were also observed in existing tests. Changing process LC_ALL/LANG to en_US did not change Windows ICU's en-DE default.

Subsequent focused tests and final integrated validation must distinguish these two baseline failures from new failures. Passing focused tests/typecheck are not independent code audit; exact-head CI still governs the repository's merge gate.

## Implementation checkpoints (code audit pending)

- #240, `1ad8592a`: selected-contract context relocation; typecheck and 207 tests across three suites passed.
- #241, `d4d2ea66`: fresh scores collapsed; saved open/closed preferences and mounted evidence preserved; Alignment label added without changing sentiment semantics. Typecheck and 248 focused tests across ten suites passed. An existing method-pick regex matched its own clock timestamp; unchanged rerun passed.
- #242, `8e4769f9`: order/exit inputs, budget editor and original size Apply control grouped. Eight new placement/behavior tests and 569 existing tests across twenty suites passed; typecheck clean. New amount readouts distinguish scan-mid sizing from today's matched stop-cost and race pricing, with spread/unavailable labels. A mistaken plural Jest filter started a broad sweep, stopped and superseded by the intended passing scoped run.

Account usage interrupted the first #242 implementer before any edits. Saved code resumed on `board/options-presentation-v2-45bd8065`; historical commits and two original plan audit rounds retained. These checkpoints are implementation evidence, not a clean independent code audit.

Pending integration cross-reference: #243 relocates the stop-cost readout into Structure & Stops; #246 must update BarrierRaceCard's existing reference to its former Arithmetic card location. This is a presentation reference update, not a stop-pricing change.

## Browser checkpoint after #243

Two existing mocked desktop regressions passed at 1200px and 1920px against the isolated checkout on port 3002. Covered fresh collapsed scores, keyboard opening, preserved evidence DOM state, readable order/exit values, budget action, alternatives and no page horizontal overflow. Screenshots were inspected at the tested internal scroll position; final whole-page method/results and both-theme inspection remains pending after remaining tickets.

The default Playwright headless-shell executable was absent; the same tests passed using installed Chrome via a temporary external configuration. No production config or application behavior changed, and no broker orders were placed. This checkpoint covers application source through `eec49c3c`; it is not final integration validation or an independent code audit.

## Resumed implementation, 13 October 2026

User explicitly approved transfer from the interrupted saved branch to board/options-presentation-resume-20261013. Recovered source tip b7764d16 matches the screenshot through #245. Originating chat and unpushed remote-machine edits were unavailable. Current main's durable saved reports merged at 6f67921f; only project-state bookkeeping conflicted and both phase records were preserved.

- #246 a481515a: returned race reward × entered quantity × 100, signed/zero/unavailable and formatter basis preserved; Structure & Stops cross-reference corrected. 140 focused tests pass; typecheck clean.
- #247 675b79c2: chooser follows method evidence; explicit decision snapshot and execution fields, stock/premium distinctions, exact-one-matched-row evidence and fractional race median. Sixteen-suite downstream run passed all unaffected suites; three presentation assertions corrected. Corrected TradeCard/method tests: 205 pass; final method suite 41 pass with eight summary regressions. Typecheck clean.

Remaining #248 and integrated #249 gate are pending; these commits are implementation evidence, not a clean code audit.

- #248 60c4b073: single ladder near top, source/edit provenance and separate full-position/rung dollar outcomes. Saved collapse preference retained. Broker labels fit without fragmented wrapping. 404 tests across nine relevant suites pass (eight new cases), typecheck clean. Original page handlers, context, gates, storage keys and request schemas untouched.

#249 final source inventory is in options-presentation-v2-preservation.md; final integrated checks and independent audit are underway.

## Final integration verification

- Typecheck clean; project state check clean after built status matches the presentation marker (pre-existing STATE-PROBE unaudited warnings remain).
- Full frontend suite: 241 suites, 240 pass; 5,090 of 5,091 tests pass. Only failure was TradeCard.p2 C1-1 clicking the freshly expanded ladder closed before checking 0.5x. The test now opens only when collapsed, retaining all original R:R numeric assertions; its complete 13-test suite passes. No production numeric fix was needed.
- Final browser run: all four 1200px/1920px × dark/light scenarios pass. Keyboard disclosure/method/row selection, saved evidence DOM state, field alignment and no page overflow verified. Order/decision screenshots inspected in both themes. Browser responses are mocked; no broker orders.
- Initial light-theme test seed incorrectly used a raw string; corrected to existing Zustand version0/state.theme persistence object, with no production theme change.
- Independent integrated code audit: one code round, zero gate findings, original two plan rounds preserved. Exact source range and reviewer are recorded in options-presentation-v2-code-audit.md. Later local deltas change only conditional test opening and screenshot capture; production source remains the independently reviewed version.

All implementation/verification tickets are complete, pending exact-head GitHub CI and merge. This is built/audited code, not a shipped phase.

## GitHub CI build correction

At PR head439cf801, GitHub frontend passed all241 suites /5,091 tests. Next build then rejected one unescaped apostrophe in a recovered #242 JSX label. Replaced it with &apos;, leaving rendered text and numbers identical. Local production build and typecheck pass. Fresh independent follow-up code round2 reviewed only the post-review deltas and this syntax correction, zero gate findings. Final CI reruns on the corrected source.
