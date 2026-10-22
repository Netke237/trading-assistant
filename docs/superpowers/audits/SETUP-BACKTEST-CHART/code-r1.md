# Code Audit Round 1: SETUP-BACKTEST-CHART (#391)

**Reviewer:** Independent Subagent `b4ebb850-0aeb-49aa-a4da-83654365f30e`  
**Date:** 2026-10-22  
**Commit Diff:** `origin/main` (`f61399ad`) .. `HEAD` (`db257049`)  
**Target:** SETUP-BACKTEST-CHART (#391)  
**Artifact Audited:** Implementation diff against `docs/superpowers/plans/2026-10-22-setup-backtest-chart-plan.md`  

## Verdict
**GATE FINDINGS: 0**  
Clean at Round 1.

## Scope Checked
1. **Numerical & Ranking Invariance:**
   - Pre-Breakout and Fib Pullback scans compute all candidate metrics (`confidence`, `metrics`, `fib_swing`, `fib_dist_pct`, `at_level`) prior to backtest execution.
   - Sorting by `confidence` (Pre-Breakout) and `at_level`/`fib_dist_pct` (Fib Pullback) remains completely independent of backtests.
   - Pinned numerical invariance test `test_setup_backtest_chart` asserts exact equality across `n_trades`, `win_rate`, `total_return_pct`, `max_drawdown_pct`, `expectancy`, `sharpe`, `confidence`, and `passes_gate` with and without `detail_collector`.
2. **Engine Chart Evidence Handover:**
   - `_run_backtest` in `backend/app/services/strategy_backtest.py` cleanly hooks `collect_setup_details` into `detail_collector` when `strategy in ("breakout_setup", "fibonacci_pullback")`.
   - `collect_setup_details` in `backend/app/services/strategy_backtest_details.py` builds `input_candles`, `candles`, `equity` (`EquitySample`), `trades` (`DetailedTrade`), `open_positions` (`()`), `initial_equity` (100,000.0), `configuration`, and `effective_params` from `setup_params(strategy, params)`.
   - Equity reconciliation is strictly verified (`math.isclose(ending_return, summary.total_return_pct, abs_tol=1e-7)`).
   - Zero trades case produces `status="success"` with `trades=()` and flat equity at 100.0.
   - Insufficient history (<100 bars) produces `status="insufficient_history"`.
3. **Scan Execution & Artifact Persistence:**
   - In `backend/app/routers/stock_scan.py`, both scan cores execute setup backtests in `_BACKTEST_POOL`, call `_original_artifact`, and attach `backtest_artifact_id` and `backtest_artifact_status`.
   - Server-side persistence via `save_artifact` enforces `allow_nan=False`, writes schema version 1 and provenance `'original'` with 30-day retention.
   - Retrieval via `GET /api/backtest-artifacts/{id}?symbol={sym}` strictly validates `id` and `symbol` matching before returning data.
4. **Frontend Candidate Chart Routing & Plain Words:**
   - Hardcoded `unsupported` guards for `prebreakout` and `fib` sources were removed from `frontend/lib/candidateChart.ts` and `frontend/lib/useOriginalBacktest.ts`.
   - `formatUnavailableReason` in `CandidateChartWorkspace/index.tsx` covers all 11 unavailable reasons, displaying human-readable explanations while retaining the raw status token.
   - Candidate row `↗` buttons in Step 4 Pre-Breakout / Fib Pullback route correctly to `/chart?...` with candidate context.
