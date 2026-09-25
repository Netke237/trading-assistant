# K-Session: A4f follow-ups — migrate stored HMM_intraday composite rules on 1D/1W to 5m, then the remaining open A4f items

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Build the owner's decision `A4F-MIGRATE-LEGACY-RULES-TOO-2026-09-25` (see
`docs/superpowers/PROJECT_STATE.json` `decisions[0]`): stored HMM_intraday composite
chart-alert RULES on '1D'/'1W' are moved to '5m' once at backend startup, each change
logged, and the rule's name gets an "(interval was 1D)" note. Then pick up the other
open A4f items, but only when the owner chooses them.

## Status
A4f-rules is CLEAN (plan: 2 rounds; code: 2 rounds) and recorded in PROJECT_STATE (`20304b2`). The merge to main is waiting on the owner's go-ahead.

## Done
- A4f (the watch path) is already on main, from a parallel branch (merge `f49446e`).
- `claude/dazzling-ride-0unofk` is superseded; its unique content was recorded in `42347af`.
- The A4f-rules plan, `docs/superpowers/plans/2026-09-25-a4f-rules-hmm-intraday-interval-plan.md`:
  round 1 NOT CLEAN (4 gate-level, all taken); round 2 CLEAN (12 sub-gate items taken into the build, §7).
- The A4f-rules build (checkpoint after `9215c3b`):
  - `hmm_intraday_interval_error` in `composite_trigger_evaluator.py`.
  - `POST /alerts/rules` returns 422 for this pair; `PUT` does too, but allows a stored legacy pair it leaves unchanged.
  - `migrate_hmm_intraday_rule_intervals` in `chart_alerts.py`, run at the top of `run_chart_alert_scheduler()` and retried until it succeeds once.
  - The Alerts page calls `syncRules()` on mount.
  - Tests: `backend/tests/test_a4f_rules_hmm_intraday_interval.py` (8) and 1 frontend case.
  - 17 backend mutants and 1 frontend mutant were all killed.
  - Backend 3176 passed / 1 skipped; frontend 1986; tsc clean.

## Next steps
- [x] Code round 1 (1 gate-level, fixed) and round 2 (clean; nits folded). 20 backend mutants and 1 frontend mutant killed. Backend 3177/1 skipped, frontend 1986, tsc clean.
- [x] PROJECT_STATE updated: phase `A4F-RULES-HMM-INTRADAY-INTERVAL`, decisions[0] marked built, open questions added.
- [ ] Once the owner approves: run `python3 .k-session/k_session.py finish` (removes `.k-session/`), then `git merge --no-ff` this branch into main and push main. First record the merge in PROJECT_STATE's `main` field, following the precedent "written on the branch BEFORE the merge".

## Blockers / open questions
- (Resolved: the owner chose (a).) The earlier options were:
  (a) A4f-rules, the decision above;
  (b) `open_questions[0]`, the recommended next item (about one line): `strategy_watch_evaluator.evaluate_all`
      reads `w['strategy_key']` for every enabled watch. Composite watches have no
      such key, so one enabled composite watch raises KeyError and that tick checks
      no watches at all;
  (c) `open_questions[1]`: an HMM_intraday watch on '4h' never fires (about 110
      completed bars, below the model's 200 minimum);
  (d) `open_questions[2]`(b): the VWAP confirmation on a '1D' watch runs on daily bars.

## Decisions
- Migrate legacy '1D'/'1W' HMM_intraday rules to '5m', because they never fire:
  `chart_alerts.py` (~:894-906) passes no intraday bars on 1D/1W. The owner decided this on 2026-09-25.
- Run the rule migration at startup rather than on import, because `load()`-style
  migration runs on every module import, including in tests.
- `claude/dazzling-ride-0unofk` is not merged. It is superseded, and deleting it is the owner's call.

## Conventions
- Start of session: `python3 scripts/state.py` (must exit 0). `docs/superpowers/PROJECT_STATE.json` is the single source of truth for phase, audit and decision status; update it before ending.
- Process: plan → adversarial round (fresh subagent, bmad-review-adversarial-general) → build with tests and mutation checks → code round. Nothing is done until a round comes back clean. The cap is 3 rounds per stage.
- Commit messages: repo style `Area: summary -- detail` (e.g. `A4f: ...`, `State: ...`), not Conventional Commits. Checkpoints may use `wip(k-session): ...`.
- Branch: `claude/hopeful-volta-ujru28` (base: `main`). Integrate base with `git merge`; never rebase or force-push.
- Before pushing: `cd backend && .venv/bin/python -m pytest -q` (main baseline 3144 passed / 1 skipped); `cd frontend && npx tsc --noEmit && npx jest` (baseline 1985 passed).
- Tests must never write the tracked `backend/config/strategy_watches.yaml` or run the real app lifespan, because it can send real Gmail/Telegram alerts and rewrite `settings.yaml`.

## Notes for the next agent
- Do not trust a designated branch to hold the work. Check ancestry against `origin/main` first, because parallel sessions have shipped the same item before.
