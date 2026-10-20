# Lane B audit plan — issue #350

Audit/report only. Source baseline: `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`.
Phase: APP-AUDIT-SETTINGS-PROFILES. No application fixes, calibration, shared
fixtures, storage-key renames, orders, or notification sends. Each defect will
be a separate linked issue with an owning lane, reproduction, expected/actual,
affected SHA, evidence, existing related issue, and retest requirement.

## Method and independent gates

Run a fresh independent plan reviewer before execution; at most three rounds.
Review fixes/interactions only after round one. Apply the numeric/persistence
gate from PROJECT_STATE.json and additionally report requested coverage gaps
separately. Keep application defect findings separate from audit-artifact
findings: discovery of a product defect does not authorize fixing the product.
After execution, merge current main and review the complete evidence diff with
a fresh independent reviewer (three-round cap). Evidence scripts are executable
code, so their code review is required; application-code stage is N/A because
application files are unchanged. Never treat unavailable checks as passes.

Use one fresh implementer per evidence ticket. Only the coordinator writes
lane-level report/state and GitHub records. Keep artifacts under this directory;
no concurrent edits to central state or Lane A inventory. The lane state records
review hashes, counters and limitations; any central-state reconciliation must
be coordinated rather than overwriting another lane's state.

## Task 1 — shared controls and saved profiles

Own `controls/`. Inventory Steps 1–3 controls and trace input → Zustand state →
request → effective backend field → saved/read-back. Exercise Options, Stocks,
Pre-Breakout; presets/custom, direction/horizon/universe, clear/reset and
zero/false/null/absent values. Reuse #343 (stale Stocks universe), #187/#188
(calibration/Stocks pack); do not change thresholds. Test all 18 committed
profiles plus a custom profile: create/update/rename/delete/apply, mode filtering,
restore script merge-by-id, backup, malformed/legacy payloads, stale tab behavior.
Capture sanitized before/after localStorage and scan payloads. Explicitly separate
current controls from frozen result/profile snapshots.

Use isolated browser storage and mocked API boundaries for deterministic UI
coverage, label mocks clearly; perform real local backend checks separately.
Verify same-origin reload, a fresh browser process reopening a persistent profile,
and a second origin staying isolated. Record browser/build versions and hashes.
For every surface state record pass/fail/not-run/N/A with reason, including
nested, empty, loading, cancelled/failed, unsupported, stale response and restart.

## Task 2 — settings and isolated backend persistence

Own `settings/`. Inventory every Settings section and its nested controls;
trace local-only versus backend saves, endpoints and actual effective config.
Use Python 3.11 and a temporary database/config root, never production files.
Capture normal and invalid saves (including 0/false/null/absent), failed-write
rollback/read-back and backend restart. Freeze relevant config hashes and record
what settings are browser-only versus server-persisted. Exercise stale async
responses/loading/errors where supported, and mark unsupported states explicitly.
Do not invoke credentials, broker probes, notification delivery, or shared jobs.

## Task 3 — independent regime calculations and gate propagation

Own `regime/`. Freeze real fixture provenance and deterministic boundary bars,
parameters/hashes. Independently derive representative Markov/OMM and HMM
probabilities rather than using production helpers as the expected result.
Check transition normalization and percent conversion, state age/duration units,
VIX percentile ties/boundaries, insufficient/fallback data, completed intraday
versus daily bars, direction alignment. Frozen supplied-model HMM fixtures may
test inference independently; distinguish that from untested live model fitting.
Trace Step 1 verdict → shared state → navigation/run gates for all modes; capture
contradictions as defects. Record exact tests and observed values, uncertainty
and unavailable real-provider/model checks without inventing certainty.

## Reconciliation and publication

Consume Lane A inventory increment from `board/app-audit-inventory-8842811f`;
map every B-owned surface to these artifacts and presentation owner J. Record
source SHA differences and unresolved final-inventory requirements. Report
numbers/persistence separately from presentation/usability; file UI defects too.
Publish artifacts on the phase branch, link evidence and defect issues on #350
and #348/#349 as appropriate. Final report lists verified checks and residual
coverage; leave acceptance open if final A inventory or required checks are
unavailable. Open a reviewable PR; never assert audit-clean application behavior
while product blockers remain, and apply board merge conditions strictly.
