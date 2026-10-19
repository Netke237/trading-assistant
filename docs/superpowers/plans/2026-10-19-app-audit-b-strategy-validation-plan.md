# APP-AUDIT-B-STRATEGY-VALIDATION — #373

Remediation: 10% (concrete plan); size M; complexity 3/5. Several persistence and request consumers share the three Settings strategy overrides. No calibration, backend schema or unrelated setting changes.

## Contract

Settings must retain editable numeric drafts locally and display accessible field errors before persisting invalid edits. Blank/clear writes null (follow the direction/horizon profile). A valid edit commits immediately, retaining fractional precision without rounding the actual value. Existing Settings bounds remain: pullback 0.5–15 percent, crossover 1–30 integer bars, breakout greater than 1 through 3. Breakout's strict lower bound follows StockScanRequest; a step is an editing increment, not a new calibration grid, so valid fractional floats need not be multiples of step.

Backend contract for persisted/programmatic overrides is distinct from Settings' editing range: finite pullback >0 and <=1 (fraction), positive integer crossover, finite breakout >1. Do not reset backend-valid legacy values such as breakout 4 or pullback 0.004. Absent/undefined/null means follow profile. Preserve all unrelated zero fields, including risk_pct, bt_min_win_rate and min_stock_score.

Invalid legacy values must fail closed with an actionable message, never silently turn into a different strategy threshold. Keep historical storage unchanged until the operator explicitly corrects/clears it; no migration/version bump because there is no shape change. Show an initial field error for an invalid hydrated value. Reject new invalid store writes/profile saves/updates atomically, before set/persistence, using a shared narrow validator for these three fields. Validate profile application before other store mutations. Validate the shared stock request builder so direct legacy/manual/scheduled profile consumers cannot bypass the check. Ensure manual error reporting uses the validation message (rather than broad reset guidance); existing schedule resolver callers already catch errors and display messages on explicit save. On automatic schedule resync failure due to invalid params, mark the referencing entry stale instead of silently succeeding.

## One integrated build ticket

Files: frontend/app/(frame)/settings/page.tsx and its StrategyScanForm regression test; frontend/lib/strategyScanValidation.ts (new); scanParamsStore.ts; searchProfilesStore.ts; searchProfileSnapshot.ts; resolveStockScanRequest.ts; stockScan.ts only if needed for actionable error; focused frontend/lib/__tests__ regression files. A small Settings CSS module addition only if needed for field error layout. No backend application edits.

1. Add failing regressions for UI zero/negative/just-below-min/strict breakout boundary, integer crossover, valid fractions, blank/clear, reload/remount. Check actual persisted localStorage, not just input display. Capture last valid value when a draft fails.
2. Add shared finite/type/null-aware validation for the three override fields. Use it at store set/load, profile save/update/application, and the shared request boundary. Reject before mutations. Do not validate unrelated settings or coerce zero to null. Historical invalid state stays visible and blocked until correction, not migrated to a new numeric meaning.
3. Add local draft/error state to OverrideInput, preserve precise committed values and synchronize external loads/reset/clear without erasing in-progress invalid drafts on unrelated renders. UI lower/upper bounds above are for edits; do not retroactively reject a schema-valid legacy value solely for exceeding UI range.
4. Test real manual runStockScan (no API call on invalid state), profile apply/save/update atomicity, scheduled resolver, valid exact wire payloads, null omission, hydration at existing versions, stale schedule marking, and legitimate unrelated zero semantics. Cover zero/negative/below-min/valid fractions on each relevant layer.
5. Verify Python 3.11 and use actual StockScanRequest.model_validate offline against representative valid generated wire payloads and invalid boundaries. Use only synthetic data; no jobs, broker orders or notifications. Record exact commands and results.

## Verification and reviews

Plan stage: fresh independent adversarial reviewer applies .claude/skills/bmad-review-adversarial-general/SKILL.md against this plan plus real code. Gate: only wrong user/broker numbers, corrupted persisted data, or mechanism comments inducing a wrong change. Cap 3 plan rounds. Create one rated child ticket only after clean plan approval; fresh implementer follows docs/agents/agent-briefs.md, tests red before implementation, typecheck and full Jest before commit.

Coordinator merges latest origin/main before code audit and reruns relevant checks. Fresh independent code reviewer audits origin/main..implementation head; later rounds only fixes/interactions, cap 3 code rounds. Record reviewer, exact hash/scope, findings/fixes/outstanding in audit doc and PROJECT_STATE.json. State built until actual merge; no shipping claim from tests alone. Follow board.md exact-head CI and self-merge conditions; preserve all unrelated phase state.

Milestones: 20% exact plan approved; 50% implementation; 70% all acceptance/local checks; 85% independent code clean; 95% exact-head CI/premerge; 100% verified merge and integrated regression retest. Each stage retains separate counters.
