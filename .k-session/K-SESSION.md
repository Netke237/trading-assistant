# K-Session: MANUAL-IBKR-CONFIRM-AS-ERROR

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Manual `/broker/option-order` and `/broker/stock-order` (backend/app/routers/broker.py) must answer
IBKR's order-reply "please confirm" message (`OrderResult.awaiting_confirmation` True) as an
ERROR carrying IBKR's question text, instead of today's empty-`order_id` 200 "success".
The frontend send dialogs must show it as a failure. Decision MANUAL-IBKR-CONFIRM-AS-ERROR-2026-09-25
in docs/superpowers/PROJECT_STATE.json (Kenneth: "Yes I want to fix it").
Process: plan -> adversarial round(s) until clean -> build -> code round(s) until clean -> merge to main.

## Status
in-progress — BUILT (uncommitted→committed in this checkpoint); plan clean at round 2; CODE round 1 next.

## Done
- e285f0f merged origin/claude/jolly-thompson-0q7paq (state commit 3efd25f: the decision above + closed open question) into this branch; resolved a PROJECT_STATE.json decisions-list conflict by keeping all three decisions; `scripts/state.py` exits 0.
- Verified against code (this session, read-only):
  - `ibkr_paper.py` place_order sets `awaiting_confirmation` (no `order_id` key, non-empty `id` and `message`; list message joined).
  - `routers/broker.py` place_stock_order (~:165) and place_option_order (~:231) never read it: they log `broker_order_filled` and return `{order_id: "", status, broker, deduped: False}`; that response is also cached by the idempotency claim (`_release_claim(idem_key, response)`), so a retry within the dedup window gets the same fake success.
  - Only `auto_trader.py:2180` reads the flag (via `getattr`, because Tradier's OrderResult lacks the field).
  - Previous session (unverified by this one): all four frontend order call sites already surface a thrown API error; `SendToBrokerDialog` makes no API call itself. Re-check before relying on it.

## Next steps
- [x] Rewrite the plan at docs/superpowers/plans/2026-09-25-manual-ibkr-confirm-as-error-plan.md. Must cover: which HTTP status (e.g. 409/502) + detail = IBKR's question; `broker_order_failed` log event, not `_filled`; response NOT cached as success by the idempotency claim (a retry must re-ask the broker, or deliberately return the same error; state which); `getattr` guard for non-IBKR results; frontend call sites in frontend/lib/api.ts + StockSendDialog / trade-card send path show the text as a failure; tests (backend route tests with a real OrderResult(awaiting_confirmation=True), frontend if touched); a PROJECT_STATE phase entry with a regex presence probe.
- [x] Plan adversarial round (fresh subagent, bmad-review-adversarial-general) -> fix -> re-audit until clean (cap: 3 rounds per stage, decision AUDIT-CAP-PER-STAGE-2026-09-25).
- [x] Build + tests (backend 3196 passed/1 skipped; frontend 1992 passed; typecheck clean; 7 backend + 5 frontend mutants killed).
- [ ] Code adversarial round until clean (fresh subagent); record rounds in plan + PROJECT_STATE phase MANUAL-IBKR-CONFIRM-AS-ERROR (status shipped_unaudited until clean).
- [ ] Record the phase + rounds in PROJECT_STATE.json on the branch BEFORE merging; merge --no-ff to main; `k_session.py finish`.

## Blockers / open questions
- None blocking. Kenneth-only housekeeping (unchanged): deleting merged remote branches; jolly-thompson-0q7paq is now safe to delete once this branch reaches main.
- Deferred by the earlier round 2, not in scope: an IBKR reply with `id` and an empty `message: []` is not flagged.

## Decisions
- Show the confirmation question as an error on the manual routes — Kenneth's call (MANUAL-IBKR-CONFIRM-AS-ERROR-2026-09-25).
- Do NOT implement sending POST /iserver/reply/{id} — out of scope; nothing in the codebase confirms orders.
- The auto-trader path is already done (AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED, merged at cd4a2fa); do not touch it.

## Conventions
- Start every session with `python3 scripts/state.py` (must exit 0). Nothing is done until an adversarial round comes back clean.
- Commit style: plain imperative subject, phase-prefixed (e.g. `MANUAL-IBKR-CONFIRM-AS-ERROR: ...`), merges as `Merge: <phase> -- <summary>`; `wip(k-session):` for checkpoints.
- Branch: `claude/sweet-meitner-9q8hch` (base: `main`); integrate base with `git merge`, never rebase/force-push.
- Backend tests: `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` (no xdist, no `-n`). Focused: `tests/test_autotrade_ibkr_confirm_not_submitted.py tests/test_ibkr_paper.py` plus the broker-router tests.
- Frontend (if touched): `cd frontend && npm run typecheck && npm run test`.

## Notes for the next agent
- The previous session wrote the plan file and started plan round 1, then hit its usage limit. Neither the plan nor the round was committed or pushed, and no remote branch has them. Treat them as lost and rewrite the plan.
- Other live k-session branches are unrelated tasks (A4g on happy-planck-yu5e4b, A4f-rules on hopeful-volta-ujru28). Do not merge them here.
