# P5 — The bearish backtest crashes on a negative target price (maybe split-unadjusted data)

**Paste this whole file as the first message of a new session.**
Lane id: `BACKTEST-NEGATIVE-PRICE-SPLITS`. Base: `origin/main` (≥ 22c49425).
**Investigation first**: no plan until the cause is proven.

## Symptom (oq 77, found by the 2026-09-18 market-hours bearish scans)
- The bearish `pullback_ema` backtest fails with `Make sure 0 < price < inf! price: -241.56` (WMT), CPRT -256.81, TSCO -480.05, SRE -192.17, LYB (Position).
- The assert is `backtesting.py:715`. The order is `services/strategy_backtest.py` (~:133) `self.sell(..., tp=sig.target_price)`.
- `services/strategy_engine.py` (~:482-485) builds bearish extensions as `current - risk * rr_target_mult (*1.5)`, which goes negative once risk > current/(2..3).
- Effect today: these names are dropped as `failed_backtest`.

## The hypothesis to prove or kill
WMT (3:1 2024), CPRT (2:1 2023), TSCO (5:1 2024) and SRE (2:1 2023) all split inside the lookback. If the history fed to `run_backtest` is **split-unadjusted**, the split bar carries a huge ATR/risk.
- If that's the cause, **bullish backtests are also wrong, silently**: the inflated target is positive, so nothing asserts. That would put a wrong number under every backtest-gated confidence badge, which makes it gate-level.
- Check: do the bars for WMT show the 2024 split as a ~66% one-day drop? Trace which source/store served them (`backend/app/data/` historical store, Tiingo/yfinance adapters, ingestion).

## Then
- **If the data is unadjusted**: plan the fix at the data layer (adjust on ingest or on read; decide which source's adjusted series to trust). That's a decision to bring to Kenneth with numbers: how many SP500 names are affected and which cached bars need re-ingesting. Separately, guard the bearish target so it can never be ≤ 0 (clamp the target or refuse the signal), with a test.
- **If the data is fine**: the defect is the bearish target arithmetic alone. Fix it at `strategy_engine.py` ~:482 with a test per affected shape.
- **The second item in the same entry** (wording, below-gate unless it misleads): the stock-scan direction banner (`routers/stock_scan.py` ~:1199, `not candidates and _dir_filtered > 0`) says "market structure does not support short-side entries" even when the gate removed 9/303 and `failed_signal` removed 276. Make it fire only when the direction gate is the dominant reason.

## Files this lane owns
`backend/app/services/strategy_backtest.py`, `services/strategy_engine.py` (the bearish target build only; lane P2 owns the `require_choppy_regime` paths), the `backend/app/data/` historical/ingestion code the fix needs, and `routers/stock_scan.py` ~:1190-1210 (the banner only).

## Protocol (shared by every parallel lane — other sessions are running at the same time)

1. Run `python3 scripts/state.py` (expect exit 0). Read the lane map `docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md` (if it isn't on main yet: `git fetch origin claude/q2-hardening-merged-a2wx5g && git show FETCH_HEAD:docs/superpowers/parallel-sessions/2026-09-24/00-INDEX.md`), then `audit_rule` in `docs/superpowers/PROJECT_STATE.json`.
2. Cut your branch from `origin/main`. **Stay inside your lane's files** (listed below). If you need a file owned by another lane, stop and tell Kenneth.
3. In `PROJECT_STATE.json`, add ONE new `phases` entry with this lane's id and point `active_phase` at it on your branch. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
4. Write a small plan (`docs/superpowers/plans/2026-09-2X-<lane>-plan.md`), then run an adversarial round on the plan (skill `K-adversarial-audit-loop` / `bmad-review-adversarial-general`, fresh subagent, told the gate: only a wrong number to a user or broker, or corrupt persisted data, counts). Then build, then run an adversarial round on the code. Only gate-level findings are fixed; the rest is logged in `open_questions`. HARD CAP: 3 rounds, then stop and tell Kenneth.
5. Merge only when clean, one lane at a time. First `git fetch origin main && git merge origin/main`. Resolve `PROJECT_STATE.json` as a UNION: keep every lane's entries, set `active_phase` to yours, and prepend your record to `main` and `active_phase_note`. Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `state.py`. Then `git merge --no-ff` into main and push. If main moved, repeat.
6. Baselines at 22c49425: backend 2959 passed / 1 skipped, frontend 1811 / 136 suites. Report your delta as exactly your new tests.
