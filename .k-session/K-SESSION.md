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
in-progress. Reconciliation is done; waiting for the owner to pick the next item. No code changed yet.

## Done
- A4f (the watch path) is ALREADY ON MAIN. It came from a parallel branch
  (`claude/wizardly-ritchie-ndb5sg`, merge `f49446e`) and is audit-clean at round 2.
  It covers: the dialog defaults HMM_intraday to '5m'; `StrategyWatchStore` rejects
  HMM_intraday with a non-intraday interval (400); `load()` migrates stored watches
  to '5m' and sets `interval_migrated_from`.
- `claude/dazzling-ride-0unofk` (a second A4f session, interrupted) is SUPERSEDED.
  Its plan commits (`db1281e`, `3622046`) were never audited clean. Its fix for plan
  round 2 was never committed. Its only unique content was the rules decision and a
  correction, and both are now recorded on this branch.
- `42347af`: PROJECT_STATE.json records the rules decision (`decisions[0]`, marked
  NOT BUILT) and corrects `open_questions[2]`(a).

## Next steps
- [ ] The owner chooses the next item (see Blockers). Do not start code before that.
- [ ] If A4f-rules is chosen: write a plan in `docs/superpowers/plans/` covering:
  (1) a one-shot migration of stored rules as an explicit `lifespan` step in
  `backend/app/main.py`, before any scheduler starts, not on import;
  (2) `/alerts/rules` (`backend/app/routers/chart_alerts.py`) rejects new
  HMM_intraday rules on a non-intraday interval, and rejects edits that move a rule
  back onto one (reuse `app.data.market.is_intraday_interval`);
  (3) the Alerts page (`frontend/app/(frame)/alerts/`) reads rules from localStorage
  without re-syncing, so it must refresh rules from the backend when it opens,
  otherwise a toggle there after migration sends the stale '1D' back;
  (4) reset the migrated rule's half-finished "must hold for N minutes" timer;
  (5) tests use a temp store and never run the real lifespan.
- [ ] Run adversarial plan round 1 (skill `K-adversarial-audit-loop`), build, run the code round, and merge only when a round comes back clean.

## Blockers / open questions
- Which item comes next is the owner's choice:
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
