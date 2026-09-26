# K-Session: P4a — chart alert rules

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Build work package P4a (`docs/superpowers/plans/2026-09-25-work-packages.md`): Q1 syncRules sends local-only composites intact and marks refusals; toggle + last_triggered_at via PATCH; Q14 no skipped closed candle in the background check; crosses None fix; A4g round-2 test/docstring items. Plan: `docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md`.

## Status
BUILT, not yet code-audited. Plan rounds 1-2 not clean, round 3 CLEAN (plan stage closed). Build A (frontend) + B (backend) done: 7 + 12 mutants killed. Pre-merge suites green (frontend 3766, backend 3426/1 skipped). origin/main (P1a, P1b-i/ii, P4b + follow-ups) merged in at the head commit; full suites on the MERGED tree were started but their result was not seen -- re-run them first. Claim P4A-CHART-ALERT-RULES re-taken (expires ~23:42 UTC 2026-09-26; renew or re-take).

## Done
- Branch restarted from main 9288592 (P2 merged). Plan + PROJECT_STATE phase P4A-CHART-ALERT-RULES.
- Plan rounds 1-3 (r3 clean) in plan sections E/F/G. Build A a34cef2, build B bc1cf60, main merged in afterwards.
- Known test gap (logged, not a finding yet): ChartWorkspace stamp call sites' persist flags are unpinned (no ChartWorkspace test harness).

## Next steps
- [ ] `python3 scripts/claim.py` -- if P4A-CHART-ALERT-RULES lapsed and nobody took it: `python3 scripts/claim.py take P4A-CHART-ALERT-RULES -m "P4a code rounds"`.
- [ ] Re-run suites on the merged tree: `cd frontend && npx tsc --noEmit && npx jest`; `cd backend && .venv/bin/python -m pytest -q`.
- [ ] Code round 1 (= round 4): fresh subagent, bmad-review-adversarial-general over `git diff origin/main HEAD -- frontend backend`, gate-level only (wrong number / corrupt persisted data / alert missed, wrong or duplicated). Cap 3 code rounds, then ask Kenneth. Record each round in PROJECT_STATE (phase P4A-CHART-ALERT-RULES, audit_rounds 3 so far).
- [ ] When clean: status shipped, audit_clean true; ALERTS-SYNC-LOCAL-ONLY-COMPOSITE + ALERTS-RULE-TOGGLE-PATCH shipped; close open questions (A4e crosses None; 'the chart cache can skip a closed candle') with evidence; annotate the A4g round-2 entry (items 3,4,5,9,10 stay open). Then ask Kenneth to merge; write the main-merge record before merging; release the claim; `k_session.py finish`.

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
