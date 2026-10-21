# APP-AUDIT-B-CAP-UNITS — independent plan audit, round 1 of 3

GATE FINDINGS: **1**. Plan stage is not clean.

Reviewer: fresh independent agent `/root/fix368_plan_r1`, applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` and the repository numeric/persistence gate. This review concerns only issue #368 / APP-AUDIT-B-CAP-UNITS. No implementation, repository edit, commit, push, external write, or audit of another phase was performed.

Exact artifact: `docs/superpowers/plans/2026-10-17-app-audit-b-cap-units-plan.md`.
SHA256, verified before and after review: `ed593c1cd3ad67d7a6d0d8ba34da1fae58b9af429356fccf18ecd6fef6d41a63`.
Source HEAD: `93d5c484a38588b7f0dee13b361dc997b7e8a618` in `/workspace/fix-368`, branch `board/app-audit-b-cap-units-96e70c96`.

## Gate finding

- **location:** Plan Task 1 ownership restriction and steps 1–2 (`docs/superpowers/plans/2026-10-17-app-audit-b-cap-units-plan.md:19–32`), interacting with `backend/app/services/scan_schedule_scheduler.py:162–178`, `frontend/lib/searchProfilesStore.ts:35–49,210–247`, and `backend/app/schemas/scan_schedule.py:23–26`.
  **trigger_condition:** An enabled Options schedule was created before deployment from a profile with `minCapRaw: '25', capUnit: 'M'` (or an M maximum). It already persists `resolved_request.min_cap_usd: 25`. The planned one-line builder change repairs subsequent resolution, but no planned step refreshes that existing persisted request. The backend scheduler validates and executes `entry['resolved_request']` directly; it never invokes the frontend builder or reads the original raw profile. Reopening the application or changing only a schedule's time/enabled setting does not re-resolve it. Existing profile resync runs on an explicit profile save/update, which this plan never requires for rollout.
  **guard_snippet:** Include a concrete, safe remediation/rollout step and regression for pre-fix saved Options schedules, using the originating raw M profile/provenance when available and an explicit re-save/recreation path when it is not. Demonstrate that an already-stored 25-dollar request originating from 25M cannot silently continue as the allegedly repaired schedule. Do not blindly multiply every stored USD filter: persisted schedule requests do not contain `capUnit`, and correctly resolved B/API requests must retain their literal USD values. This can be bounded to the affected schedule path; it does not require changing the shared conversion in a second place.
  **potential_consequence:** After the proposed fix, an existing scheduled 25M minimum continues admitting a $10M company, while the same profile run manually or freshly resolved excludes it. An existing M maximum likewise continues rejecting nearly every real company. Scheduled candidate counts/results remain numerically wrong indefinitely, despite the plan's fresh-resolver regressions passing. The isolated actual-router probe below observed the $10M fixture pass the persisted 25-dollar request and fail the correct 25,000,000-dollar request.

## Scope and adversarial recheck

Read AGENTS.md, the exact `audit_rule`, ticket-orchestration.md, the adversarial review skill, and K-adversarial-audit-loop instructions. Read the issue/comments snapshot `/tmp/350-fix-368-issue.json`. Consulted original controls source-probe/source-output and relevant backend fixture harness as immutable evidence; did not execute their output-writing scripts.

Cross-checked these mechanisms against actual source:

1. Step 2's M/B input labels and shared cap-unit state.
2. Both min and max request fields and their one shared multiplier.
3. M=1,000,000 and B=1,000,000,000 arithmetic, including fractions.
4. Explicit zero surviving conversion; empty strings omitted.
5. Existing finite raw-value checks and unchanged price parsing.
6. Manual RunScanButton context/guard/request wiring to `api.postScanBody`.
7. Saved Options profile resolution delegating to the same builder.
8. Raw profile capture/apply storage retaining raw strings plus capUnit, without double conversion.
9. Persisted schedule creation/update and the actual execution replay path.
10. Backend ScanRequest's literal USD fields and `_execute_scan_core` forwarding them to `_process_symbol`.
11. Actual candidate filtering below/at/above both minimum and maximum, inclusive equality, and zero/None guards.
12. Other request fields, confidence/fundamentals/regime gates, and the separate report-input builder consumer: the one-line change does not require altering them.

A second pass specifically followed the adjacent persisted-schedule execution path rather than assuming resolver coverage proves execution coverage. That pass produced the finding above. No other qualifying findings were established within the phase scope. No style, test-hygiene, calibration, Stocks, or speculative findings are reported.

## Commands and isolated evidence

Read-only commands included `rg --files`, targeted `rg -n`, `cat`, `nl -ba` / `sed` source reads, `git status --short`, `git rev-parse HEAD`, `git log -1 --oneline`, `git diff --stat -- frontend backend`, and `sha256sum` of the exact plan. `python3 scripts/state.py` was run as required at session start and exited 1; its project-wide state diagnostics are not a finding in this phase review. The backend prepared interpreter reported Python **3.11.16**. Cloud runtime status was inspected; no network operation was required.

1. `node` heredoc from the worktree root: installed an in-memory TypeScript transpile/alias require hook, loaded the real Options builder, captured its pre-fix request, then reloaded only that module with the proposed `1` → `1e6` replacement in memory. No source file was written. Compared min/max 25M, 2B, fractional M/B, and zero plus blank omission. All eight unit/boundary cases passed for the proposed conversion. Output:

   ```text
   {"inMemoryPlannedMultiplierProbe":"8 boundary/unit cases passed","persistedBeforeFix":25,"freshAfterFix":25000000,"persistedAfterFix":25}
   ```

2. `PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python` heredoc: imported actual `ScanRequest`, `RejectedCandidate`, and `app.routers.scan._process_symbol`. Mocked all preceding market-data fetches and the market-cap fetch. A custom sentinel on the calendar fallback stopped each accepted fixture immediately after the cap filter, so no scorer/provider/DB/lifespan/broker/order/notification was reached. Verified 12 below/at/above fixtures covering min/max $25M and $2B. Output:

   ```text
   {"persistedRequestMinimumUSD": 25.0, "10M_usingPersisted25MRequest": "passed-cap-filter", "10M_usingCorrect25MRequest": "rejected"}
   actual _process_symbol cap-filter: 12 below/at/above boundary fixtures passed; stopped immediately after cap filter; no lifespan/DB/provider/scorer/order/notification
   ```

These are plan-falsification probes, not a claim that application implementation or the required full suites are complete. The manual rendered path was source-reviewed here; the plan correctly requires its actual rendered regression during implementation.

Final repository application diff remained empty. Existing coordinator state modification, untracked plan, and dependency symlinks were left untouched.
