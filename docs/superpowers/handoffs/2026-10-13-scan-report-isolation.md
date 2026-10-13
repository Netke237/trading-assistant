# Scan report isolation handoff

Tracking issue #236; branch `board/scan-report-isolation-b19c62b6`.

User requested start on Options #233 plus persistent scan log #236. Options
already has a live claim on another branch; do not take or overwrite it.

## Built

- LOG-01 #237: commit `759bd364`, pushed, child issue closed as build completion.
- Additive durable category report/head tables, read-only latest/run/legacy APIs,
  immutable dispatch input and terminal resolved snapshot, server generations,
  separate previous usable evidence and bounded retention. Legacy untouched.
- Migration `a93b8d24f760`; deployment upgrade required.
- Python 3.11.16: 12 focused API/storage/migration tests passed.
- Frontend typecheck passed. Full suites were started by LOG01 implementer;
  last observation backend 30% without failures, 6 skips; frontend many passing
  suites. Final outcomes not obtained; do not claim full-suite success.

## Gates and next

Prior frozen LOG01–03 plan round1 clean. Lifecycle elaboration plan round2 found
G1: secret-bearing free-text values were incorrectly delegated to key-name
validation. Fixed plan requires typed/domain allowlist projections, omitted
unsafe arbitrary reasons, sanitization in duplicated result/diagnostics paths.
Plan commit `f302f0df`, revised SHA256
`973811c4d045b267d607b1961b235bc36b739cc0d6160e378a181cea495390a2`.

Fresh final plan round3 did not run: reviewer hit usage limit before review.
Audit count remains2; this does not consume a qualifying round3. Need fresh
independent reviewer on ONLY G1 fix and interactions. Maximum3 per stage.

After clean plan: fresh implementer #238 LOG02, using lifecycle reconciliation
plan and approved source amendment. Then #239 inspector integration when
presentation prerequisites allow shared frontend edits. Finally integrated
phase code audit; none run yet. Phase audit_clean false, unfinished, no PR or
merge. Reclaim with unique new branch from this pushed branch if abandoned,
preserving counters; do not reset stage or fabricate independent review.
