# K-Session: A4g: 1D/1W chart alerts drop the forming daily/weekly bar

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
A4g (last part of decision `A4C-FOLLOWUPS-LOCKED-2026-09-24`, item 4): on the 1D/1W chart alert path
(`evaluate_and_notify_for_symbol` in `backend/app/routers/chart_alerts.py`), drop today's forming daily
bar / this week's forming weekly bar. Move `auto_trader._todays_bar_is_unclosed` to a shared module
`backend/app/services/market_session.py` (moved, not copied).

## Status
DONE on branch — adversarial round 2 CLEAN at the gate; recorded in PROJECT_STATE.json. Awaiting the owner's go to merge to main.

## Done
- Plan written, pre-round-1: `docs/superpowers/plans/2026-09-25-a4g-forming-daily-weekly-bar-plan.md`
  (commit 153407e on `claude/loving-mayer-sdyltu`; file copied onto this branch).
- Plan amended with round 1 F1 (close-instant comparison, §3 step 2, §6a); market_session.py built
  (helper moved from auto_trader; last_session_close/last_week_close/week_is_unclosed/
  completed_session_bars); chart_alerts wired (D1/D2/D3); auto-trader tests re-pointed at
  market_session (clock + hours seam); A4c 1D test rewritten to A4g semantics; 43 A4g tests pass.

## Next steps
- [x] Amend the plan with round 1's finding F1: decide whether the last bar is still forming by comparing
      its timestamp with the last session close (an instant), not by matching calendar dates. Record round 1
      (not clean, F1 taken) in the plan.
- [x] Build `backend/app/services/market_session.py`: `todays_bar_is_unclosed` (moved verbatim with its
      docstring, `_market_session_open`, `_NYSE_OPEN`, `MARKET_TZ`), `week_is_unclosed`,
      `completed_session_bars(bars, interval, now=None)`.
- [x] `auto_trader.py`: import `todays_bar_is_unclosed as _todays_bar_is_unclosed`; keep the module-global
      name so existing `mocker.patch.object(at, "_todays_bar_is_unclosed", ...)` tests still patch the call site.
- [x] Wire readers D1/D2/D3 (plan §2) in `chart_alerts.py` for 1D/1W: regime snapshot, composite OMM, and
      `bars_daily` (HMM_daily + rsi/bb confirmations + `require_choppy_regime`).
- [x] Adjust existing tests broken by the move; write `backend/tests/test_a4g_forming_daily_weekly_bar.py`
      (43 tests).
- [x] Run the plan's mutations (§6 list + weekday-check), 10/10 killed (edb701a).
- [x] Full suites: backend 3211 passed / 1 skipped; frontend untouched; state.py exit 0.
- [x] Adversarial round 2 (plan amendment + code) via K-adversarial-audit-loop; loop until clean.
- [x] Record A4g in `docs/superpowers/PROJECT_STATE.json` (phase A4G-FORMING-DAILY-WEEKLY-BAR, decision A4G-CHART-COMPLETED-FOR-ALL-2026-09-25, 10 below-gate items + live-feed question in open_questions).
- [ ] On the owner's go: merge origin/main in, re-run backend suite + state.py, merge to main (--no-ff) with a main-merge record, then `k_session.py finish`.

## Blockers / open questions
- Open (logged in plan §1, for Kenneth): Alpaca daily `get_bars` with a date-only `end` — unverified
  whether a mid-session fetch stores today's partial bar. Out of A4g's scope.
- Branch is at main 489202d; main moved 14 commits since the plan was written (A4f merged) — re-check
  the plan's line references at build.
- Project state's recommended next is the composite-watch KeyError fix (open_questions[0]) and A5c planning;
  A4g continues here by the owner's earlier choice.

## Decisions
- Completed bars for ALL inputs on the 1D/1W chart path (HMM_daily and rsi/bb strategy confirmations
  included) — owner, 2026-09-25, so a chart composite and a composite watch with the same trigger see the
  same data.
- Weekly follows the same rule — locked decision; accepted cost: weekly regime lags up to a week.
- Forming-bar test uses timestamp vs last close instant, not calendar-date match — round 1 F1.
- Session helper is moved, not copied — locked decision.

## Conventions
- Start of session: `python3 scripts/state.py` (must exit 0). Nothing is done until an adversarial round
  comes back clean.
- Commit style (repo's own): `A4g: <what>`, `A4g plan: ...`, `State: ...`; checkpoints `wip(k-session): ...`.
- Branch: `claude/happy-planck-yu5e4b` (base: `main`); integrate base with `git merge`, never rebase/force-push.
- Tests: `cd backend && pytest` (single: `pytest tests/test_a4g_forming_daily_weekly_bar.py`);
  frontend `cd frontend && npm run typecheck && npm run test`.

## Notes for the next agent
- A previous session (branch `claude/loving-mayer-sdyltu`) built all of A4g — module, wiring, 34 tests,
  10 mutations killed, round 1 F1 amendment — but never committed it; the container was reclaimed after a
  rate limit. Only the plan survived. Commit and checkpoint after every step.
- Another session holds `.k-session` state on `claude/hopeful-volta-ujru28` (A4f follow-ups, migrating
  stored HMM_intraday rules). Its files (`strategy_watch_store`, `CompositeAlertDialog`, composite_watch's
  HMM_intraday branch) are out of A4g's scope — do not touch.
