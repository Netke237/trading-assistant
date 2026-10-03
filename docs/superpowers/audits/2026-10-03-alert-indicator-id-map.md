# ALERT-INDICATOR-ID-MAP review evidence

Review gate: wrong user-visible readings or corrupt persisted data, including mechanism comments that would cause a wrong change. The original reviews were performed by the implementing agent; they did NOT satisfy K-adversarial-audit-loop and are not counted as audit rounds. The previous audit-clean declaration was incorrect and has been withdrawn. Independent code audit round 1 is now running.

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
