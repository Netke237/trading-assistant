# K-Session: P4a — chart alert rules

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Build work package P4a (`docs/superpowers/plans/2026-09-25-work-packages.md`): Q1 syncRules sends local-only composites intact and marks refusals; toggle + last_triggered_at via PATCH; Q14 no skipped closed candle in the background check; crosses None fix; A4g round-2 test/docstring items. Plan: `docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md`.

## Status
CLEAN. Code round 1 (= round 4) not clean: 1 gate-level finding (catch-up markers never pruned -> a re-enabled/new rule caught up on candles from before it existed), fixed in d18abd2 with 2 tests + mutant killed. Code round 2 (= round 5) CLEAN. Suites green on the fixed tree: frontend 3854/3854 (tsc clean), backend 3539 passed / 1 skipped; state.py exit 0. PROJECT_STATE: P4A-CHART-ALERT-RULES, ALERTS-SYNC-LOCAL-ONLY-COMPOSITE, ALERTS-RULE-TOGGLE-PATCH shipped/audit_clean; open questions (chart cache skips a closed candle; A4e crosses None) moved to closed_questions; A4g round-2 entry annotated (items 3,4,5,9,10 open); A4E probe updated for the scheduler's `view` argument.

## Done
- Plan rounds 1-3 (r3 clean), build A a34cef2 + build B bc1cf60, main merged in, code round 1 fix d18abd2, code round 2 clean.

## Next steps
- [ ] Ask Kenneth to approve the merge to main (--no-ff). Before merging: merge origin/main into the branch if it moved, re-run suites, write the main-merge record into PROJECT_STATE (`main` field) on the branch.
- [ ] After the merge: release claim P4A-CHART-ALERT-RULES; `k_session.py finish`.

## Blockers / open questions
- None.

## Decisions
- Refusal mark is a NON-persisted map (no persist version bump), rebuilt by each syncRules.
- Catch-up evaluation capped at 3 candles per pair per tick; older candles get the candle list truncated at them.

## Conventions
- Commit subjects: repo style (`P4a plan ...`, `P4a build: ...`, `State: ...`, `Merge: ...`); name a round number in a subject only for a round that ran.
- Before pushing: `cd frontend && npx tsc --noEmit && npx jest`; `cd backend && .venv/bin/python -m pytest -q`; `python3 scripts/state.py`.
- Rule: nothing is done until an adversarial round comes back clean.

## Notes for the next agent
- chart_alerts.py already has PATCH /alerts/rules/{id} for enabled + last_triggered_at.
