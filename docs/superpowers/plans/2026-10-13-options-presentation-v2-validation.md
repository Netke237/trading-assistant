# Options presentation V2 — unchanged frontend baseline

13 October 2026. Coordinator ran `npm run test -- --runInBand` in the unchanged source checkout before the new UI code. Application source matches 7fa0ff5d; origin/main 5f98b791 added only the approved documentation package.

Result: 233 suites, 231 passed and 2 failed; 4,994 tests, 4,992 passed and 2 failed. Runtime 525.005 seconds. No snapshots.

Exact failures, observed before this implementation:

- StockSendDialog.session.test.tsx: `uses matching shared edits for totals, saved levels, allocation, snapshot and pick; quantity edits scale shared allocations` expects `4,470`, but this Windows locale renders `4.470`.
- BarrierRaceCard.test.tsx: `the inline disclosure / shows the assumptions strip outside it` expects `2,000 paths · each row sums to 100%`, but the platform renders the grouping with a dot.

No production formatter or unrelated test changed to hide these differences. React act warnings were also observed in existing tests. Changing process LC_ALL/LANG to en_US did not change Windows ICU's en-DE default.

Subsequent focused tests and final integrated validation must distinguish these two baseline failures from new failures. Passing focused tests/typecheck are not independent code audit; exact-head CI still governs the repository's merge gate.
