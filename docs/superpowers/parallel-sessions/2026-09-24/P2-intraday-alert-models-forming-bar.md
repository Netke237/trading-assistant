# P2 — Intraday alert models: drop the forming bar

**Paste this whole file as the first message of a new session.**
Lane id: `INTRADAY-ALERT-MODELS-COMPLETED-BARS`. Base: `origin/main` (≥ 22c49425).

## Background
A4b (decision `A4B-DROP-FORMING-15MIN-BAR-2026-09-24`) made every Intraday-**horizon** regime reader measure on completed 15-minute bars, via `backend/app/data/market.py` `completed_intraday_bars` + `intraday_feed_lag_seconds`.
- A bar is kept only if its int start `time` + 900 + feed_lag <= now.
- feed_lag is 900 on `sandbox.tradier.com`, else 0.
- A bar whose time isn't an int is dropped.

It deliberately left out the **user-built alert models**, which fit a regime on intraday bars at a **user-chosen interval** (oq 108, "RAISED BY A4b PLAN ROUND 1"):
1. Composite watches with model `HMM_intraday`: `routers/composite_watch.py` (snapshot), and `services/strategy_watch_evaluator.py` → `composite_trigger_evaluator.evaluate_scheduled / evaluate_from_context`. **These fire Gmail/Telegram.**
2. Chart-drawn composite alerts: `routers/chart_alerts.py` (~:819).
3. The `/api/regime/intraday-series` chart overlay (`routers/regime.py`).
4. Strategies' `require_choppy_regime` checks: `services/strategy_engine.py` ~:790-910.
5. `services/alert_evaluator.py` `build_regime_snapshot` (~:154-195): regime conditions in price/condition alert rules.

## DECISION: ask Kenneth first (AskUserQuestion)
"Should the user-built intraday alert models drop the still-forming bar too? Which ones?"
- Recommended: **yes, for everything that decides or fires (1, 2, 4, 5)**. Keep the forming bar on the chart overlay (3), because it's a display, and mark it visually if that's cheap. Otherwise include 3 as well for one consistent rule.
- The helper must be generalised to take the **interval length in seconds** (1min/5min/15min/30min/1h…) plus the sandbox lag. Keep the existing 15-min signature working; A4b's six readers must be unchanged, and their tests must pass untouched.

## Files this lane owns
`backend/app/data/market.py` (the helper only), `routers/composite_watch.py`, `services/composite_trigger_evaluator.py`, `services/strategy_watch_evaluator.py`, `routers/chart_alerts.py`, `routers/regime.py` (the intraday-series endpoint only), `services/alert_evaluator.py`, and `services/strategy_engine.py` (`require_choppy_regime` paths only; lane P5 may edit the bearish target build ~:480).

## Watch out
- Open below-gate item oq 109: `isinstance(time, int)` rejects `numpy.int64`. If a model here gets numpy times, it would fail closed. Check the sources feeding each model.
- Plan: `docs/superpowers/plans/2026-09-24-a4b-intraday-completed-bars-plan.md` is the template to copy.

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
