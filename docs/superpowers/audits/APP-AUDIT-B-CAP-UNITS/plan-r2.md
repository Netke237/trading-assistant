# APP-AUDIT-B-CAP-UNITS — independent plan audit, round 2 of 3

GATE FINDINGS: **0**. The revised plan is clean within this round's required scope after a second adversarial pass.

Reviewer: fresh independent agent `/root/fix368_plan_r2`, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the repository numeric/persistence gate. Reviewed only the round-1 legacy-schedule remediation and its interactions. Did not reopen the original whole-target review or review any other phase.

Exact artifact: `docs/superpowers/plans/2026-10-17-app-audit-b-cap-units-plan.md`.
SHA256, verified before and after review: `7b87fc503577bcae353abd058518b7783a77f7c157a578bd6a4e424af4fdaebd`.
Git blob SHA: `f60bf3cbde3a90db7a7d456c72f2d0af926c7def`.
Source HEAD: `deb01eb126cded15ccdbae76d0cbe9d1e2ccbe72`, branch `board/app-audit-b-cap-units-96e70c96`.
Comparison: prior immutable snapshot `docs/superpowers/audits/APP-AUDIT-B-CAP-UNITS/plan-r1-reviewed.md` versus the current plan; the diff consists of the new section at lines 46–81. Read the round-1 report `docs/superpowers/audits/APP-AUDIT-B-CAP-UNITS/plan-r1.md`.

No qualifying finding was established, so there are no location/trigger/guard/consequence finding entries to report.

## Scope verified against actual source

Read AGENTS.md, PROJECT_STATE.json's exact audit_rule, ticket-orchestration.md, the adversarial review skill and K-adversarial-audit-loop. Ran the required state checker; it exited 0 with no drift, retaining unrelated historical unaudited-work warnings. No K-session directory exists in this worktree. Coordinator's claim verification was supplied in the brief; this reviewer made no claim mutation.

The source trace covered these potential failure paths and interactions:

1. The scheduler revalidates stored `resolved_request` directly, rather than reconstructing the raw profile. The new refusal therefore acts at the actual authoritative execution boundary.
2. Fixed-time jobs, loop jobs and run-now all converge on `_run_scheduled_entry`; one guard there covers all scheduled dispatch paths. Manual API runs do not traverse it.
3. The optional `ScanRequest` marker does not invalidate a legitimate manual USD request without a marker. Unsupported explicit versions are rejected by the added literal field.
4. `ScanScheduleEntry.resolved_request` remains a generic dict, but its existing post-validator invokes `ScanRequest.model_validate`. Thus a typed marker is validated without replacing/normalizing away the raw dictionary.
5. The router constructs the complete `ScanScheduleEntry` before `upsert`; a failed explicit-version validation cannot partially mutate storage through normal POST/PUT.
6. The generic nested dictionary survives `model_dump`, YAML save and reload. The existing store does not need a new migration or a unit multiplier, preserving compatible raw requests and unrelated fields.
7. Legacy missing-marker requests stay valid for GET/list and PUT. This is necessary for frontend profile resync to discover and replace them; placing the refusal only in scheduled execution preserves that recovery path.
8. The guard's nonzero check covers either minimum or maximum, including negative finite values. Explicit zero remains numerically identical under either old or new conversion; a zero maximum retains its existing zero behavior rather than being treated as a missing filter.
9. A fresh profile resolution reuses the corrected shared Options builder, so it carries both literal USD amounts and marker 1. `updateProfile` invokes the existing resync, which PUTs the newly resolved full request; raw profile capture/storage need not change.
10. Schedule-only edits resend the existing blob and cannot certify old amounts. Failed or unavailable resync leaves the old request without the marker, so the proposed scheduler refusal remains effective rather than silently resuming the wrong scan.
11. The scheduler currently catches exceptions and persists/notifies the fixed string `scan_failed`, not the exception text. The plan explicitly requires an error status and a clear re-save/confirm-units message and explicitly extends scheduler production scope, so implementation must carry the dedicated remediation message through this existing error channel; merely raising a descriptive ValueError would not satisfy this plan. Settings already renders the persisted run error, and the runs endpoint returns it unchanged. This is a cross-checked implementation requirement, not a plan finding.
12. The guard must execute before `run_reported_scan` / `_execute_scan_core` and any provider execution, as explicitly required. Its refusal does not need to delete/disable or rewrite the schedule, dispatch a success count, or alter the stored prior successful result. Stocks dispatch remains outside the new Options check.

## Independent second pass

Re-read only the added plan section against the actual dispatch, schema, POST/PUT ordering, Settings error rendering, profile-save resync and generic-dictionary persistence paths. Specifically challenged: a marker being stripped by validation, legacy rows disappearing from GET and becoming impossible to resync, a schedule-time edit accidentally blessing old values, a missing max-cap guard, an overbroad manual API rejection, a blind migration of valid B/USD data, an exception message being swallowed, and an adjacent scheduled invocation bypassing the shared guard. No additional reachable wrong-number or persisted-corruption defect was established. The clear-message requirement is explicit despite the current generic exception handler, and the implementation regression must prove it.

## Isolated plan-falsification probe

Prepared backend interpreter: Python **3.11.16**. Used `PYTHONDONTWRITEBYTECODE=1` and a temporary directory under `/tmp`. Loaded the actual request and schedule schemas, added only the proposed optional Literal marker in an in-memory ScanRequest subclass, and temporarily supplied that subclass to the actual schedule validator. No application source was changed.

The probe verified:

- Actual schedule JSON validation and YAML store reload retain marker 1 with 25,000,000 minimum and 2,000,000,000 maximum.
- A legacy 25 request without a marker still validates and its raw nested dictionary remains unchanged.
- Five unsupported explicit version values reject before any attempted store update; persisted temporary-file bytes remain unchanged.
- Eight guard truth-table cases cover missing/zero minimum and maximum, both zero, nonzero minimum, nonzero maximum, negative nonzero, and a correctly marked fresh request.

Output:

```text
Proposed optional marker: actual schedule JSON/schema + YAML reload retain marker and USD caps; legacy shape remains unchanged; five unsupported versions reject before store mutation; eight guard truth-table cases pass.
This in-memory schema/guard probe is plan validation, not implementation verification; no scan, database, notification, provider, or broker invoked.
```

This does not claim implementation or full suite completion. The plan retains the original manual/resolver and backend 25M/2B boundary scope and now requires real scheduler/core-call blocking, resync execution, error-message and raw-preservation regressions plus full backend and frontend checks.

No repository source/state/audit edit, commit, push or external write was performed. The only retained written artifact is this requested `/tmp` report. Existing untracked dependency symlinks were left untouched.
