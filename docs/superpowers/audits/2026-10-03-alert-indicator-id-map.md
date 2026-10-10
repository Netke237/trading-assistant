# ALERT-INDICATOR-ID-MAP review evidence

Review gate: wrong user-visible readings or corrupt persisted data, including mechanism comments that would cause a wrong change. The original reviews were performed by the implementing agent; they did NOT satisfy K-adversarial-audit-loop and are not counted as audit rounds. The previous audit-clean declaration was incorrect and has been withdrawn. Qualifying independent audit records follow below.

Non-qualifying self-review pass 1 examined selector serialization, browser evaluation, backend dispatch, persistence and compatibility. Corrections: parameter ordering is explicit rather than object insertion order; opaque chart IDs are never guessed; browser computations use saved rule parameters without active chart state; empty and unsupported references cannot be saved. Numeric-period bounds prevent enormous integer conversion failures. MACD requires fast < slow so the browser's missing-fast-EMA fallback cannot diverge from backend warm-up. Bollinger standard deviations use the same finite, positive decimal syntax in both parsers.

Non-qualifying self-review pass 2 examined those corrections and their interactions: timestamp-based chart IDs, default/legacy labels, custom periods, indicator removal, API create/update/read round trips, invalid-input rejection and the EMA seed bar. No remaining gate findings were identified in that self-review.

Validation observations:

- TypeScript typecheck passed.
- Full frontend run: 173 suites, 4,273 tests passed. Subsequent added boundary/empty-selection tests were exercised in the focused rerun: 138 passed (six suites).
- Full backend run before the final regression-pin correction: 4,546 passed, one skipped, one golden-pin failure. Running the exact pre-change indicator module from main b036a368 proved that its output already failed that stale historical checksum. The test now pins the verified pre-change baseline, normalizing only the intentionally added EMA seed reading. Every later EMA reading and every other standard indicator remains pinned to the baseline. Final affected backend rerun: 195 passed. The full backend suite was not repeated after that test-only correction.
- Direct browser/backend comparison: 14 references, 1,171 timestamped readings agreed within 0.000051 (backend rounding).
- Real API with a disabled rule: create, read, update, reject invalid update without altering the stored rule, delete passed. No notification or broker action was invoked.
- Frontend `/alerts` returned HTTP 200 using development fallback fonts. Production build was blocked by denied Google Fonts networking; required domains were saved in the environment draft, not applied to the current runtime.

Compatibility observations: existing recognized names remain readable. Opaque stored chart IDs contain no recoverable parameter snapshot and must be reselected when editing; no stored data is silently rewritten. EMA now includes its seed at period-1, matching the chart; earlier warm-up readings remain absent. Composite momentum calculations are unchanged. Parameterized `BB_MID` explicitly denotes the middle band; unsupported chart-only indicators are excluded from new rule choices.


## Independent code audit round 1

Fresh reviewer: `indicator_map_audit_1`; applied `bmad-review-adversarial-general` under the project gate. Reviewed actual `12b64ea6^..12b64ea6`, traced selector, both parsers, browser/live evaluation, persistence and cooldown synchronization. Two gate findings:

1. Browser full-precision readings diverged from backend four-decimal rounding, causing false alerts and cooldown writes. Seven closes of 100, one of 100.01, sixteen of 100 yield EMA(7)=100.00002505648939 in browser vs 100.0 on server, so `>100` disagrees. Fixed by applying existing `pythonRound4` to browser EMA/SMA/RSI/ATR/BB/VWAP readings. MACD, volume and close remain unrounded, matching backend.
2. Saved `BB_UPPER(2,1e308)` computes infinity from ordinary prices and can persist invalid JSON history. Fixed by bounding the multiplier to 10000 in both parsers and rejecting nonfinite current/previous indicator readings in both evaluators. Invalid readings never enter trigger history, even when another OR condition matches.

Regression evidence: affected backend checks 199 passed. Fresh independent round 2 reviews only these fixes and their interactions. No clean audit declaration yet.


## Independent code audit round 2

Fresh reviewer: `indicator_map_audit_2`; reviewed only round-1 fixes against `295fc279` and their interactions. One gate finding: EMA(7) closes `[100.05,99.87,100.46,100.38,100.08,99.69,99.61,99.4,99.96]` compute `99.88875` in chart arithmetic versus `99.88874999999999` in backend arithmetic. Rounding gives 99.8888 versus 99.8887, causing false `>99.8887` and `crosses_above99.8887` triggers. Fixed by using the exact backend EMA recurrence for alert EMA and MACD line/signal rather than the algebraically equivalent chart recurrence. Explicit threshold and crossing tests cover the reproducer.

Fresh independent round 3 reviews only this correction and its interactions. This is the code-stage hard cap. No clean declaration yet.


## Independent code audit round 3 — cap reached, not clean

Fresh reviewer: `indicator_map_audit_3`; reviewed the actual delta against `d51238a4`, including EMA arithmetic and MACD fast/slow/signal seed interactions. One unresolved gate finding:

- `frontend/lib/alertIndicators.ts`, alertEMA seed summation: Python 3.12.14 compensated `sum` differs from JavaScript `reduce`. EMA(8) closes `[99.57,99,99.57,100.89,100.37,100.57,99.64,100.58]` produce browser 100.0238 and backend 100.0237. The actual browser evaluator falsely triggers `>100.0237` and persists the wrong reading. Seed arithmetic must be aligned for EMA and MACD, with the supported runtime resolved first (Docker uses Python 3.11 while this environment uses 3.12.14).

Code-stage three-round cap reached without a clean round. Audit loop stopped; no fourth round and no unreviewed correction. Task is not done or mergeable. A split/runtime-alignment decision is required before continuing. Latest focused validation: frontend 179 passed, backend 199 passed, typecheck clean; these passing checks do not validate the known failing seed boundary.

Independent tally: round 1 two findings fixed; round 2 one finding fixed; round 3 one finding outstanding.


## Subsequent user-authorized resolution

The user authorized a narrower `ALERT-INDICATOR-SEED-PARITY` split and merge after completion. Docker/CI's intended Python3.11 runtime resolves the observed seed difference; the onboarding environment had incorrectly used Python3.12. The original checksum was valid under3.11 and is restored. See `2026-10-03-alert-indicator-seed-parity.md` for two fresh qualifying clean reviews and exact parity evidence. This original code-stage history remains capped at three non-clean rounds and is archived intact in PROJECT_STATE.json; it is not reset or reclassified as clean.
