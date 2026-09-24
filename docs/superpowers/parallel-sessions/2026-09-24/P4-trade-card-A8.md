# P4 — A8: trade card / Step-7 questions

**Paste this whole file as the first message of a new session.**
Lane id: `A8-TRADE-CARD-FOLLOWUPS`. Base: `origin/main` (≥ 22c49425). Mostly frontend.
Split into small audit batches, one layer each. **Item 1 first**: it's gate-level and needs no decision.

## Item 1: build it, no decision (oq 64)
The Step-7 context rail (`frontend/app/(frame)/@contextRail/screener/step-7-trade-card/**`, `components/organisms/ContextRail`) builds its IV and spread gates from the **raw scan candidate**, not the overridden card. After a Step-6 pick it describes the *auto-picked* contract, so the picked contract's score sits over another contract's figures. The card itself was fixed for this class in `a62c3447`; mirror that fix. It's a small change on its own; don't fold it into anything.

## DECISIONS: ask Kenneth (one AskUserQuestion, up to 4 per call), then batch the builds
- **oq 59 (+58)**: the card prints "Time stop 18d" (`data.exit.timeStopDays`), but the TIME_STOP alert fires on a hardcoded `dteRemaining <= 3` (`frontend/lib/alertEngine.ts` ~:311), so a trader reads an 18-day exit and gets a 3-DTE one. *Recommended now:* relabel the card so it can't be misread, e.g. "Time stop 18d (alert fires at 3 DTE)". Threading timeStopDays onto PortfolioPosition (oq 58) is a later, bigger change.
- **oq 60**: the stop-cost headline uses the stale scan-snapshot mid and can print "$0 left" three rows above a different live mid. *Recommended:* compute the headline from the live mid when there is one, else label it "at scan mid".
- **oq 61**: Step 7's `[active]` effect clears saveNotes, so Prev/Next destroys the basket's "premium stop could not be applied" notices. *Recommended:* keep the notices until the basket changes.
- **oq 56**: should Current price accept 0? A long option that expired worthless *is* 0. *Recommended:* accept 0 as a value and give "clear" its own control.
- **oq 57**: the global premium stop is selectable at 100% (`backend/app/routers/risk_settings.py` `le=1.0`, Settings step 0.05). At 100%, PREMIUM_STOP can never fire. *Recommended:* cap it at 0.95 in both the backend and Settings.
- **oq 62**: the editors' 10–99% band isn't an invariant on stored values (the backend derives the ratio against the fill). *Recommended:* clamp server-side and log it. This is backend, and the smallest touch possible; check it doesn't collide with lane P7's `schemas/__init__.py` edit.

## Files this lane owns
`frontend/app/(frame)/screener/step-7-trade-card/**`, `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/**`, `frontend/components/organisms/{TradeCard,ContextRail}/**`, `frontend/lib/alertEngine.ts`, Settings risk section, `backend/app/routers/risk_settings.py`. Backend portfolio write paths only for oq 62.
Don't touch `components/organisms/AutoTradeArm` (lane P3).

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
