# P1 — A5: the Analysis page ignores Step-3 overrides

**Paste this whole file as the first message of a new session.**
Lane id: `A5-ANALYSIS-OVERRIDES`. Base: `origin/main` (≥ 22c49425).

## Problem (verify it's still live before planning)
- `backend/app/routers/stock_scan.py` `_analyze_core` (~:438) builds `_regime_gate = dict(full_cfg.get("regime_gate") or {})` **with no override resolution**. It then caps the card status and appends a `regime_headwind` CAUTION flag from it (~:446).
- `StockAnalysisRequest` inherits `StockScanRequest` (`backend/app/schemas/stock_scan.py` ~:191), so it already *accepts* overrides. `AnalyzeStockRequest` in `frontend/lib/api.ts` (~:323-341) declares `overrides?`. But `frontend/lib/analysisStore.ts` (~:36-52), the sole caller, sends **none**.
- Consequence: with "Headwind reject %" set to -10, the scan REJECTs a symbol while /analysis shows a PASS regime rule and no headwind flag.
- Same page, same function, fold in:
  - **oq 76(a)**: /analysis builds gate_flags for price, score, regime_headwind, signal, backtest and confidence, but **not `direction_conviction`**. The one-line resolver `config_loader.load_direction_conviction_min_trend` exists.
  - **oq 110**: the Analysis page fetches 80 days of 15-min bars (R2/R3), while the scans and the fire path fetch 55.

## DECISION: ask Kenneth first (AskUserQuestion), then plan
"Is the Analysis page a **mirror of the scan** (it applies the same Step-3 overrides) or a **defaults view** (it shows config defaults and says so on screen)?"
- Recommended: **mirror**. The user opens Analysis to understand a scan verdict. analysisStore sends `scanParamsStore`'s overrides, and `_analyze_core` resolves the regime gate the way the stock scan does (copy the stock-scan resolver, don't re-derive it).
- Alternative: a defaults view with a visible "config defaults, not your Step-3 settings" label.

## Files this lane owns
`backend/app/routers/stock_scan.py` (only `_analyze_core` and its helpers, ~:340-560), `backend/app/schemas/stock_scan.py`, `frontend/lib/analysisStore.ts`, `frontend/app/(frame)/analysis/**`, and the `AnalyzeStockRequest` block of `frontend/lib/api.ts`.
Don't touch: the stock-scan sizing block (~:1129-1170, lane P3) or the direction banner (~:1199, lane P5).

## Done when
- A test proves the same symbol + overrides give the same regime-gate verdict on /stock-scan and /analyze-stock.
- /analysis shows a direction_conviction flag.
- The 80-vs-55 window is either aligned or logged with a reason.

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
