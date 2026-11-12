# Stocks reference alignment — first build checkpoint

Tracking #621; build task #623. This is the first of two Stocks build tasks. Setup Scanner is a separate queued phase, #622. The user's request was to create tickets and start implementing; no whole-phase completion or merge readiness is claimed by this checkpoint.

## Implemented scope

Terminal position presentation now shows sentiment, fundamentals, identity and closed Stock Qualification / Backtest Evidence in order. The editable execution stop and risk remain prominent. Full structure, original scanned strategy, latest-calculation chronology and Arithmetic race are named default-closed disclosures. Entry, shares and target-allocation editors follow method evidence. Embedded Backtest presentation and execution controller are preserved.

The method workspace still uses the existing static evidence stack. Task #624 adds the reference's independent viewing controls and harmonized comparison. Until that task and integrated acceptance are complete, this first build must not be represented as a complete match to the reference.

## Source and regression evidence

- Exact plan SHA256 `076be833a14f65825385f5dc5317e048d56602218bec1573797772cba7afc85c`: independent plan round 1 clean, zero gate findings; record in `plan-audit-1.md`. Code audit has not started and phase `audit_clean` remains false.
- `first-build-source-check.json`: entire controller before presentation byte-identical to baseline, all eight named controller functions/variables unchanged, 152 unique baseline JSX text units accounted for (151 exact; one directional reference updated for its moved disclosure). This is source accounting, not an independent code audit or exhaustive browser proof.
- Focused reference/presentation tests: 2 suites / 85 tests passed, after four predicted layout failures established the initial red state. Existing field/number assertions remain; access steps open the moved disclosures. Added edited-save scenario keeps execution entry/stop/targets/allocations separate from Arithmetic intent.
- Browser regression: all 8 existing `stock-position-presentation.spec.ts` scenarios passed in 51.4 seconds: Bullish/Bearish × 1200/1920px × dark/light. Each retains selected-plan numeric assertions, fractional medians and mocked save payload checks; no real saves/orders. Log in `evidence/first-build-browser.log`.
- Two fresh 1366px initial captures, dark/light: zero page errors, no horizontal overflow and zero open disclosures. Capture fixtures intercept all API requests; screenshot capture performs no calculation/save/order actions. `capture-first-build.cjs` reproduces them against a running localhost:3001 frontend. The right context rail and original app shell are retained.
- Frontend typecheck passed. Full frontend Jest suite: **346 suites / 6,371 tests passed**, 497.996 seconds (`npm run test -- --runInBand`). No backend changes or backend tests. Task 1 checks are complete; phase-wide code audit remains pending Task 2 and integrated acceptance.

## Retained visuals

`evidence/baseline-position-1366-dark.png` is the pre-change fixture baseline. `evidence/first-build-initial-1366-dark.png` and `...light.png` show the new initial presentation. Two representative screenshots from the eight browser regressions retain a Bullish 1200px decision and Bearish 1920px stop comparison. Other generated regression screenshots remain temporary; no claim that all were archived.

## Continuation

Task #623 is committed at `414c5621`, pushed, and closed after all required local checks. Draft PR [#625](https://github.com/Netke237/trading-assistant/pull/625) holds this first implementation checkpoint. Parent stays `in_progress`, 20% (clean plan; only one of two build tasks complete), size L / complexity 3. Task #623 itself may reach 70% when all required local tests pass; parent does not inherit that milestone. Then a fresh implementer takes #624 on the same claimed branch. Only after both tasks and full preservation/browser acceptance may the coordinator merge current main and run the phase-wide code audit. Cap remains three rounds per stage with continuous phase numbering. No historical counters are reset.
