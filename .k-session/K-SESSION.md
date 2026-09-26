# K-Session: P4a — chart alert rules

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Build work package P4a (`docs/superpowers/plans/2026-09-25-work-packages.md`): Q1 syncRules sends local-only composites intact and marks refusals; toggle + last_triggered_at via PATCH; Q14 no skipped closed candle in the background check; crosses None fix; A4g round-2 test/docstring items. Plan: `docs/superpowers/plans/2026-09-26-p4a-chart-alert-rules-plan.md`.

## Status
Plan written; plan round 1 pending. Claim P4A-CHART-ALERT-RULES held (renew every ~2h: `python3 scripts/claim.py renew`).

## Done
- Branch restarted from main 9288592 (P2 merged). Claim taken. Plan + PROJECT_STATE phase P4A-CHART-ALERT-RULES.

## Next steps
- [ ] Plan round 1 (fresh subagent, bmad-review-adversarial-general, gate-level only). Cap 3 plan rounds, then ask Kenneth.
- [ ] Build A1-A4 (frontend) and B1-B4 (backend) with tests + a mutation per item.
- [ ] Full suites, then code rounds (cap 3), state closure, ask Kenneth to merge, release claim, `k_session.py finish`.

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
