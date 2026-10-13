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
