# P6 — Screener pinning pass (the answer to 7 rounds, none clean)

**Paste this whole file as the first message of a new session.**
Lane id: reuse the existing `already_shipped` entry "Screener layout + the tooltip that caused every horizontal scrollbar" (audit_rounds 7, audit_clean false). **Don't edit its audit_rounds/audit_clean to silence state.py.** Record the pinning pass in the note and a new phase entry `SCREENER-PINNING-PASS`.
Base: `origin/main` (≥ 22c49425). Frontend tests, mostly.

## What was decided (decision AUTOTRADE-ALERT-AND-SCREENER-WORK-ORDER-2026-09-20, locked by Kenneth)
"The screener gets ONE PINNING PASS, NOT A ROUND 8. Pin **every** sentence builder in `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` and `frontend/lib/statusTooltips.ts` against **literal expected strings**, the way `eventWindowSentence` already is, in ONE pass. Then audit that pass. Both round-7 findings fall out of it."

## Steps
1. List every function or inline expression that builds user-visible text in those two files.
2. For each: a Jest test with literal expected strings across the branches (PASS/CAUTION/REJECT, each IV basis `rank|absolute|none`, and each horizon where thresholds differ). No snapshot tests and no re-computed expectations.
3. Where pinning shows a real defect, it's a finding. Two known candidates on the same page:
   - **oq 10**: the banner and the tooltip disagree about "Driven by" for the same row.
   - **oq 6**: a horizon with one IV basis gated and the other not gives `gateDisabled` false with `ivBands` empty.
   Fix gate-level ones only; log the rest.
4. Run one adversarial round on the pass. It should come back clean. That closes the screener piece's cap.

## Files this lane owns
`frontend/app/(frame)/screener/step-5-vol-events/**`, `frontend/lib/statusTooltips.ts`, their `__tests__/`, `frontend/components/atoms/Tooltip/**` (read). Touch nothing outside step 5 (lane P4 owns step 7).

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
