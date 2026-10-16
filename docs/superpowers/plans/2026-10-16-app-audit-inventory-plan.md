# APP-AUDIT-INVENTORY — Lane A execution plan

Tracking: #349, programme #348. Source baseline: `27fe5182` (resolve and record full SHA before execution). This is an audit evidence phase, not an application change or a numeric correctness certification. Reports live only in `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/`.

## Deliverable and completion

Build a reproducible inventory of every route and reachable disclosure/state, assign numeric/persistence ownership to B–I and presentation ownership to J, and verify navigation/shared boundaries. A owns discovery and shell/navigation; domain arithmetic remains with its lane. Publish incomplete increments early, but keep #349 open until source/runtime reconciliation is complete. A source count, a passing typecheck, or an independent numeric-gate review alone cannot close missing coverage.

## Task 1 — Source discovery and lane handoff

Enumerate all `frontend/app` page/layout/default/loading/error/not-found entries including routes outside `(frame)`, route groups and parallel slots. Distinguish URL pages, redirects, layouts, rail implementations and fallback slots. Read actual redirect targets and conditions. Traverse transitive local component imports from routes and shell to identify dialogs/drawers, tabs, tables, charts, tooltips, nested disclosures and dynamic repeated instances. Include Settings' nine sections and all three screener modes/submodes. Record source file/line and component/entry action for each surface. Track unresolved dynamic constructs explicitly; token searches are discovery aids, never proof of exhaustiveness.

Use stable path/component-derived IDs, not row numbers. Separate a disclosure definition from each route/mode instance. Each surface has route, source, entry action, numeric/persistence owner B–I, presentation owner J, fixture requirements and a state matrix: normal, expanded/nested, empty, loading, failed/cancelled, legacy/unsupported, zero/false/null/absent, stale async, reload/restart. Applicable states get individual surface+state IDs; N/A requires source-backed reasoning. Untested applicable states remain pending with an owning lane; they are inventory requirements, not lane-A correctness passes. No exclusions without user approval. Mark dev/crash routes explicitly, with exposure conditions.

Create machine-readable inventory plus a readable index and provenance record. Freeze full source SHA, file/config/input hashes, frontend/browser/tool versions, Python version, backend mode and fixture provenance. No secrets or real user data. Preserve distinctions between source-observed, runtime-observed, inferred, pending and not applicable. Do not copy credentials/config values into artifacts.

## Task 2 — Runtime reconciliation

Use an isolated browser profile and a frontend server built from the pinned worktree, with deterministic mocked API data and blocked mutation/external network paths. Do not interact with an existing live backend or reuse its storage. Probe actual navigation links, every URL/redirect, context rail soft-navigation versus hard reload, back/forward and restoration, three screener modes, nine Settings sections and shared loading/error/not-found/min-width boundaries. Read existing tests/fixtures to reuse suitable deterministic data; record input hashes. Probe nested disclosures with fixtures that make them reachable; map runtime observations to inventory IDs. Explicitly identify fixture states and real-environment checks not performed. Do not send orders, notifications, scans, tuning jobs, or writes to shared backend data.

Every runtime-discovered surface must map back to source and lane ownership; every source route/entry must have runtime status and evidence or a named outstanding check. Runtime observations are facts about the recorded fixture/version, not claims that production data is numerically correct. Report blocked/unavailable checks and leave acceptance unfinished if they prevent reconciliation.

Preserve sanitized request metadata, mocked response payloads and before/after browser-storage read-back for restoration/reload probes, linked to surface/state IDs and fixture hashes. Capture both backend-recovery mock inputs and browser persistence, since StoreHydration and InitStores can overlay restored state. Record N/A with reason when a surface has no request or persistence. Never capture live credentials or unrelated browser storage.

## Task 3 — Findings and verification

Record each demonstrated defect with reproduction, expected/actual, affected SHA, owning lane, related issue, regression evidence and retest state. Separate numeric/persistence from UI/usability findings. File below-gate UI defects too. Fixes are separate claims/phases, never opportunistic changes here. Publish lane handoff links on #349/#348 so B–J can consume the incremental inventory. No actual notifications outside the authorized board workflow.

Verify inventory IDs unique, source locations resolve, every discovered route/slot and reached component is covered, all states have an owner/disposition, all runtime results reference valid IDs, and counts distinguish redirects/pages/disclosure definitions/instances/state rows. Run `python scripts/state.py --quiet` and frontend typecheck before commits. Evidence tooling receives focused verification if introduced. No backend dependencies/tests needed for a report-only phase; Python must remain 3.11.

## Independent audit and shipping record

Before executing tasks, fresh independent plan reviewer applies `.claude/skills/bmad-review-adversarial-general/SKILL.md` under `PROJECT_STATE.json.audit_rule`: wrong displayed/broker numbers or persisted-data corruption, including mechanism claims; do not report below-gate findings as audit blockers. Also independently check requested inventory coverage, separately from the numeric gate. Record reviewer, plan hash/exact diff, findings/fixes/outstanding. Maximum three plan rounds; later rounds only prior fixes/interactions. No app correctness/audit-clean claim from plan review.

After reports/tooling are complete, merge current main before a fresh independent final review. Review cumulative evidence/tooling scope against this plan; maximum three code-stage rounds. Report-only code N/A is permissible only with explicit rationale and no executable changes; final evidence coverage still needs independent verification. Record source application audit verdict separately from report/tool review. Follow board ownership checks before every spawn, push and GitHub write, and normal PR/CI/self-merge gates. If a required check cannot run, publish useful evidence but do not close #349 or claim completion.
