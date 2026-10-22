# APP-AUDIT-OPTIONS audit execution plan

Tracking: #351, programme #348, lane C. Audit/report only; defects become separate linked fix phases.
Application baseline: `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`.
Branch: `board/app-audit-options-baa5a15a`.

## Evidence contract

Keep all new executable probes, fixtures, transcripts, reports and manifests under
`docs/superpowers/audits/app-audit/APP-AUDIT-OPTIONS/`. Never modify application code,
production configuration, shared fixtures or lane A's inventory. Coordinator alone
updates phase state and GitHub. Each execution ticket uses a fresh implementer.
Python must be 3.11; record Python, Node, dependency/build/browser versions, source
SHA, config/input hashes and fixture origins. Use synthetic deterministic data in
isolated temporary storage; block provider/broker/notification calls. A stubbed
browser/API run is labeled synthetic, never live-data evidence. No orders, real
notifications, shared-data jobs, calibration changes or storage-key renames.

Every claimed pass needs a command, captured output, exact inputs, independently
derived expectations and observed results. Existing test passes are corroboration,
not independent numeric truth. Calculate expected scores from frozen YAML formulas,
prices using explicit bid/ask/mid/full-premium units, sizing using independently
derived risk budgets/floor/caps, and report counts from fixture membership. Never
copy an implementation result into an expected value or regenerate golden pins.

Record normal, expanded/nested, empty, loading, failed/cancelled, previous, unsaved,
legacy/unsupported, zero/false/null/absent, stale async and reload/restart results.
For each relevant family, distinguish PASS, FAIL, BLOCKED, NOT RUN and N/A with
reason. No unavailable local check is a pass. Separate arithmetic/persistence from
presentation/usability. Source reachability or a screenshot alone is not proof.

## Task 1 — Backend numbers and request-to-contract trace

Read scan request schemas, routers/scan.py and contracts.py, scan service, scoring
modules, trade_plan and related existing tests. Build a lane-local Python probe
and report `backend-evidence.md`; save sanitized structured observations.
Trace captured universe/filter/direction/horizon request through actual scan
orchestration with fake providers to accepted/excluded candidates, shortlist,
ranked contracts, selected contract and trade card. Freeze configuration and bars.
Independently assert representative weighted totals, score/status thresholds,
IV/event gates, minimum/maximum boundaries, missing/nonfinite measurements,
contract liquidity/DTE/caps, alternatives and decimal strikes in both directions.
Compute full-premium R/R, stop/target costs, shares/contracts and rounding against
explicit independent formula fixtures. Exercise disabled gates and zero values.
Run focused existing suites; record their scope and failures without changing pins.
Investigate related #162/#179/#335 on this SHA; fixes remain separate. Never invoke
real providers or broker adapters. Gaps in complete orchestration remain explicit.

## Task 2 — Frontend numbers, state and broker preview

Read Options Steps 4–7, context rails, contract grading/explanation, trade-card
override/snapshot, scan store and broker dialogs. Write lane-local Jest probes
using the existing Jest config (explicit paths) and `frontend-evidence.md`.
Render representative components with frozen API/store fixtures and independently
assert scores/statuses, percent/currency units, sorting/ranking, exclusions,
contract selection/alternatives, decimal strike, bid/ask/mid, full-premium R/R,
edited card arithmetic, basket totals and broker preview/request capture.
Fake all sending endpoints; assert capture only, never real placement.
Exercise absent vs zero, legacy/missing fields, failed saves, stale responses,
mode/category changes and rehydration using isolated localStorage. Existing
unit tests corroborate; actual browser behavior is separately labeled below.
Coordinate shared control findings with B, broker execution with F, UI with J.

## Task 3 — Durable reports and browser journeys

Read backend report model/service/lifecycle/router and frontend report API,
store/inspector/migration and current-controls comparison. Add lane-local probes
and `report-browser-evidence.md`. Use an isolated SQLite file and synthetic runs
for options/stocks/prebreakout. Exercise running/completed/failed/cancelled,
previous/unsaved/legacy records, category retention, exact frozen request/config
identity, counts/drop-offs/exclusions and reload. Restart the isolated backend
process against the same DB and assert read-back; distinguish component storage
simulation from browser reload and actual browser process restart.
Run a production browser build where feasible with stubbed provider endpoints:
Steps 4–7 and saved inspector categories, expand nested disclosures, change current
settings and verify historical numbers/labels remain frozen. Capture request,
response, read-back and screenshots/DOM assertions with browser/build versions.
Use minimum supported 1200px and a larger viewport for relevant numeric labels.
If production build/browser/restart cannot run, mark those exact checks blocked;
do not substitute dev rendering or a unit test as an equivalent pass.

## Task 4 — Reconciliation, defects and independent evidence review

Coordinator integrates the three disjoint reports into `report.md` and a coverage
matrix. Read lane A's latest published inventory and record its exact commit/hash;
map all applicable C surface/state rows to evidence or an explicit pending gap.
Compare baseline/source deltas; final inventory reconciliation is required before
closure. An incomplete A increment cannot certify final complete coverage.
For each defect publish a separate linked issue with reproduction, expected vs
actual, baseline SHA, owner lane, related existing issue, regression evidence and
retest status. Reuse existing defects rather than duplicate them. Presentation
defects are logged even below the numeric gate. Do not implement remedies here.
Retest relevant final merged fixes or retain blockers; a proposal is not a fix.

## Review and closure gates

Before execution: fresh independent BMad review of this entire plan against source;
numeric/persistence gate from PROJECT_STATE.audit_rule, maximum three plan rounds.
Only after a clean plan review create sub-issues for Tasks 1–3 and delegate them.
Before each spawn/write/push renew and verify the shared claim.
After execution, fetch/merge main, record whether application baseline changed and
retest affected coverage. Fresh independent BMad code/evidence review covers the
whole integrated branch diff, executable probes, reported expectations and scope
claims against the pinned application source. Maximum three code rounds; subsequent
rounds cover only prior fixes and interactions. Independent review must not silently
turn missing evidence into a pass. Record exact reviewer, hashes, findings, fixes,
remaining blockers and stage counters. Report-only evidence still receives review
because new executable probes and numeric assertions can be wrong.

Run typecheck before each commit, relevant focused tests/probes and state check.
Keep raw outputs bounded and sanitized. No source code change is authorized by this
plan. Open a PR only with accurate partial/complete status; keep #351 open whenever
acceptance, final inventory, local checks or blocking retests remain unresolved.
Never claim whole-app correctness or elimination of all defects. Self-merge only
under every board.md condition; otherwise preserve a reviewable branch/PR and name
the outstanding requirement.
