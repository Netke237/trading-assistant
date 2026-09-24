# P7 — Backend hygiene: persisted-data safety + config_loader hardening

**Paste this whole file as the first message of a new session.**
Lane id: `BACKEND-HYGIENE-PERSISTENCE-CONFIG`. Base: `origin/main` (≥ 22c49425).
Three file-disjoint batches; audit each separately. Verify each item is still live first.

## Batch A: corrupt persisted data (gate-level if reachable)
- **oq 69**: `PositionCreate.qty` (`backend/app/schemas/__init__.py` ~:860) is `int = Field(default=1)` with **no `ge=1`**, so POST /portfolio can persist qty 0 or negative. Add `ge=1`. Check that every writer (including `services/position_writer.create_position` and the O4 auto-trade booking) sends ≥ 1, and that no existing test posts 0 on purpose.

## Batch B: alert dedup file
- **oq 3**: `alert_notifier._save_dedup` writes `alert_dedup.json` with a bare `open(...,'w')` (no temp file + rename), and `_load_dedup` swallows the parse failure, so a crash mid-write silently clears every dedup hold. That means duplicate Gmail/Telegram pages after a restart. Use an atomic write: copy the pattern `ATOMIC-CONFIG-WRITES` used for the YAML writers.
- **oq 12**: `forget_alerts` swallows `_save_dedup` failures at logger.debug, so the in-memory hold clears while the on-disk hold survives a restart. At least log a warning.

## Batch C: config_loader YAML hardening (pending_kenneth[11], oq 34–37)
Ask Kenneth one question first: "Spend a change plus a round on config_loader hardening?" *Recommended: yes, for the dotted-key one only.*
- **oq 34**: a flat dotted key forges a legal path. Build the path as a tuple and compare tuples instead of joining on '.'. It's a one-liner.
- oq 35 (an `_defaults: &anchor` holder carrying `direction_conviction`), oq 36 (a self-referential anchor gives RecursionError), oq 37 (two untested guards, e.g. dropping `str(k)` at ~:200): add tests; fix only if cheap.

## Files this lane owns
`backend/app/schemas/__init__.py` (`PositionCreate` only), `backend/app/services/alert_notifier.py`, `backend/app/services/config_loader.py`, and their tests. Lane P4 may add a server-side clamp near the portfolio write path (oq 62); coordinate if both touch `schemas/__init__.py`.

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
