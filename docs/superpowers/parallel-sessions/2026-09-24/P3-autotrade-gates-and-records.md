# P3 — Auto-trade gates and records (A6 + A7 + small auto_trader items)

**Paste this whole file as the first message of a new session.**
Lane id: `AUTOTRADE-A6-A7-GATES-AND-RECORDS`. Base: `origin/main` (≥ 22c49425).
**This lane is the only one allowed to edit `backend/app/services/auto_trader.py`.** Keep it that way. Split the work into two audit batches (≤ ~500 lines each), batch A first.

## DECISIONS: ask Kenneth first (one AskUserQuestion, four questions)
1. **A6 (oq 55)**: should the daily-loss gate (`_check_daily_loss`, auto_trader.py ~:2854) size `premium_at_risk` on the **full premium** or on the **declared premium stop**? Today it uses the declared stop, which can come from `ArmRequest.premium_stop_pct`. Nothing enforces that stop, because the auto-trader places no protective order, so a 10% stop lets 6x more trades through than the 0.60 default. *Recommended: full premium* (conservative; the stop is only a declaration). The fired row's `premium_at_risk` (~:2483) uses the same formula; decide both together.
2. **A7a (oq 78)**: should the `not_submitted` history row (~:2428) carry `regime_gate` (and `sizing`)? The gate demonstrably ran upstream. *Recommended: yes*, so a credential-expiry week stays distinguishable from a gate-degraded one. Flip the pinned test `test_which_rows_carry_the_regime_gate_outcome` deliberately and say so.
3. **A7b (oq 25)**: the same broken sizing config gives **500** on POST /stock-scan (stock_scan.py ~:1171/1188, rationale ~:1129-1147) and **400** on POST /auto-trade/fire (routers/auto_trade.py ~:226, because `SizingConfigError` subclasses RuntimeError). *Recommended: map `SizingConfigError` to 500 on /fire too.* First check how the frontend `AutoTradeArm` handles a /fire error so the message still shows. Alternative: document the asymmetry only.
4. **A7c (oq 26)**: `min_mult > 1` is **refused** (decision SIZING-MIN-MULT-REFUSAL-2026-09-17, section 9.9). Confirm the refusal and close it. That's bookkeeping only.

## Also in this lane (no decision needed; verify each is still live first)
- **oq 2**: `_apply_vol_sizing` (~:1400) has no catch-all. An exception outside its four named classes consumes the arm and writes no history row.
- **oq 5**: the `cap_blocked` (~:2347) and `daily_loss_blocked` (~:2391) rows omit the `error` key every other refusal row carries, so `/auto-trade/status`'s last_order shows no reason.
- **oq 4**: a broker returning a REJECTED OrderResult takes fire()'s success path. `services/auto_trade_booking.py` (~:66-113) now refuses to *book* rejected statuses (O4). Check whether the history row/log still reads as "fired". If it does, log it; if booking covers it, close oq 4 with evidence.
- Below-gate items on the same code, only if you're already there and they change what's in the row: oq 83 (comments saying "UNGATED AT FULL ARMED QUANTITY"), oq 84 (no test for `sizing` on order_failed).

## Batches
- **A**: oq 2, oq 5, oq 4 (the correctness of the history record and the arm).
- **B**: A6, A7a, A7b, A7c (Kenneth's answers).

## Files this lane owns
`backend/app/services/auto_trader.py`, `backend/app/routers/auto_trade.py`, `backend/app/services/auto_trade_booking.py` (read; edit only if oq 4 needs it), and for A7b only the two `HTTPException(500)` lines of `stock_scan.py`'s sizing block (lane P1 owns `_analyze_core`, lane P5 owns the ~:1199 banner). Frontend `components/organisms/AutoTradeArm/**` only if A7b needs it.

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
