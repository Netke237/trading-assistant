# Saved scan report layout — code round 1

Target: `SAVED-SCAN-REPORT-LAYOUT`.
Base: `6d5b6ec289dd47eae8c66ac4dfe6f564fb3ff821`.
Branch: `fix/saved-scan-report-layout`.
Status: built, independently audited, unmerged.
Code audit rounds: 1 of maximum 3. `audit_clean: true`.

## Change

Replace inline candidate JSON with a compact saved-results table. Options use
the recorded `stockScore` and `stockConfidence`; Stocks and Pullback use
`stock_score` and `stock_status`. Pre-Breakout and Fib show their recorded
confidence. Missing or explicitly unavailable fields remain unavailable;
measured zero remains zero. Each complete record remains in a collapsed
disclosure. Exclusions and the complete raw report also start collapsed, and
expanded JSON has bounded scrolling. No persistence or broker payload changes.

## Independent review

Reviewer: `/root/saved_report_audit_r1`, a fresh independent subagent applying
`.claude/skills/bmad-review-adversarial-general/SKILL.md` and the numeric /
persistence gate in `PROJECT_STATE.json.audit_rule`.

Exact reviewed diff: the six component files below against the base above.
SHA-256 of `git diff -- frontend/components`:
`9e86d8b75a7800175c0a753685160515bf5cd67d59e07fb7163c82537c84f973`.

- `frontend/components/molecules/SavedScanResultsTable/index.tsx`
- `frontend/components/molecules/SavedScanResultsTable/SavedScanResultsTable.module.css`
- `frontend/components/molecules/SavedScanResultsTable/__tests__/SavedScanResultsTable.test.tsx`
- `frontend/components/organisms/SavedScanReportInspector/index.tsx`
- `frontend/components/organisms/SavedScanReportInspector/SavedScanReportInspector.module.css`
- `frontend/components/organisms/SavedScanReportInspector/__tests__/SavedScanReportInspector.test.tsx`

Result: zero gate findings after a second examination of the full scope.
The reviewer verified the diff hash, traced the durable projection and all five
category producers, and checked saved score/status authority, units,
unavailable fields, measured zero, frozen evidence and report-switch behavior.
No fixes or outstanding findings. Independent checks: project state passed;
two focused component suites / 24 tests passed. The implementing agent checked
that the scope and hash match the final component diff.

## Validation

- Frontend typecheck passed.
- Focused saved-results, saved-report and terminal-outcome suites: 33 tests
  passed across 3 suites.
- Production build passed (existing lint warnings).
- Chromium checked the production Step 3 page at viewport widths 1440 and
  1920, both light and dark, using isolated API fixtures with five candidates
  and large explanation records. No page overflow or browser runtime errors.
  The compact table was approximately 253 px tall. No raw JSON was initially
  visible; opened candidate and complete-report records were capped at 320 px
  with scrolling, and their parsed JSON matched the fixtures exactly.
- This browser check used fixtures, not a live scan or the user's local server.

The audit record itself is bookkeeping added after the frozen application diff.
