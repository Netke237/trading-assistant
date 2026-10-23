# Adversarial Code Audit Report: APP-AUDIT-STOCKS (Lane D)

**Auditor:** Independent Subagent (bmad-review-adversarial-general)  
**Target:** Code diff between `origin/main` (`bf0b3b54`) and `HEAD` (`5574ab3f`) for Issue #352 (Lane D: Verify Stocks scan, strategies, backtests and position numbers)  
**Stage:** Code Stage Round 1  
**Reviewer:** `5f4827bf-25e5-4b75-acf6-a594ec22091f`  
**Scope Inspected:**
- `backend/tests/test_audit_stocks_lane_d.py`
- `frontend/app/(frame)/screener/step-4-stocks/__tests__/auditStocksLaneD.test.tsx`
- `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/provenance.json`
- `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/reconciliation.json`
- `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/defects.json`
- `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/README.md`
- `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/report.md`
- `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md`
- `docs/superpowers/PROJECT_STATE.json`

**Production Code Checked:**
- `frontend/lib/resolveStockScanRequest.ts`
- `frontend/lib/stockScan.ts`
- `frontend/components/organisms/StockPositionCard/index.tsx`
- `frontend/components/StoreHydration/index.tsx`
- `backend/app/routers/stock_scan.py` (including `_position_size` and `_process_stock`)
- `backend/app/scoring/stock_scorer.py` (5-rule composite score, $w_{\text{event}}=0.0$ in stock mode, non-event weight renormalization, 4 demotion caps: pullback veto, confidence gate, regime gate, fundamentals gate)
- `backend/app/scoring/fundamentals_scorer.py` and `backend/app/services/fundamentals_gate.py`
- `backend/app/services/strategy_engine.py` (7 primary strategies matching `Strategy` enum)
- `backend/app/services/strategy_backtest.py` (win rate, expectancy, total return, max drawdown, Sharpe, time exits on final bar close, `passes_gate`, zero-trade safety)
- `backend/app/scoring/signal_confidence.py` (`status_cap`, sample size sufficiency, interpretation)
- `backend/app/routers/backtest_artifacts.py` (`GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`, `schema_version=1`, `provenance='original'`)

---

## Findings

No gate-blocking findings were found.

---

## Checks Executed to Reach Zero Gate Findings

1. **Composite 5-Rule Stock Scorer & Event Exclusion:**
   - Traced `backend/app/scoring/stock_scorer.py:1223-1241`. Verified that when `scoring_mode == "stock"`, `weights["event"]` is set to `0.0`, and non-event weights are renormalized via `weights = {k: v / total_w for k, v in weights.items()}` so their sum is exactly 1.0.
   - Verified that upcoming earnings or dividend proximity never adds or removes points from `final_score` in stock mode, functioning solely for UI display and the pipeline earnings veto gate.
   - Tested in `backend/tests/test_audit_stocks_lane_d.py:test_stock_mode_event_weight_zeroed_and_renormalized` (passed).

2. **4-Tier Demotion Hierarchy Monotonicity:**
   - Traced `backend/app/scoring/stock_scorer.py:1251-1335` and `_worse(a, b)`:
     - **Pullback Timing Veto:** If pullback is `REJECT`, status is capped at `CAUTION`.
     - **Confidence Gate:** Evaluates forward-replay integer `confidence` (0–100); `< 50` caps at `CAUTION`, `< 35` caps at `REJECT`, `None` (unvalidated / sample count $< \text{min\_samples}$) caps at `CAUTION`.
     - **Regime Gate:** Direction-aligned conviction percentage and stability; headwind $\le -40\%$ with `Stable` regime demotes to `REJECT`; $\le -15\%$ demotes to `CAUTION`.
     - **Fundamentals Gate:** Evaluated on Swing and Position horizons (Intraday strictly exempt). Bullish: health $< 45 \implies \text{CAUTION}$, $< 30 \implies \text{REJECT}$. Bearish: health $> 70 \implies \text{CAUTION}$, $> 80 \implies \text{REJECT}$. Safety flags `negative_equity` and `extreme_leverage` ($\text{debt-to-equity} \ge 3.0$) trigger unconditional `REJECT`.
   - Verified `_worse` monotonicity: subsequent gates can only demote, never promote an already demoted status. Tested in `test_audit_stocks_lane_d.py:test_worse_monotonicity` (passed).

3. **Strategy Engine & 7 Primary Strategies:**
   - Verified that `Strategy` enum literal in `backend/app/schemas/stock_scan.py:10` matches exactly the 7 primary strategies: `pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_vwap`, and `mean_reversion_multi`.
   - Traced `backend/app/services/strategy_engine.py:1420-1421` confirming that `mean_reversion_vwap` raises `ValueError` if placed into `mean_reversion_multi` on daily bars; verified that frontend UI guards this and uses rolling daily VWAP (`mean_reversion_vwap_daily_signal`) instead.
   - Tested execution of all 7 strategies on synthetic bars in `test_seven_strategies_signal_execution` and parameter boundary validation (`breakout_volume_mult > 1.0`, `pullback_tolerance_pct > 0`) in `test_strategy_parameter_boundaries_enforced` (passed).

4. **Vectorized Backtest Runner & Frozen Candidate Artifacts:**
   - Traced `backend/app/services/strategy_backtest.py:363-432`. Verified calculations for `win_rate`, `expectancy`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, `n_time_exits`, and `passes_gate`.
   - Verified zero-trade safety: when 0 trades occur, `_empty_result` returns 0 win rate, 0 expectancy, 0 Sharpe, and `passes_gate=False` without producing `NaN` or `ZeroDivisionError`. Tested in `test_zero_trades_empty_result_safe` (passed).
   - Traced `backend/app/routers/backtest_artifacts.py:26-38`. Verified endpoint `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` requiring UUID and matching uppercase symbol query parameter. Verified artifact immutability, `schema_version=1`, and `provenance='original'`. Tested in `test_backtest_artifact_lifecycle_and_symbol_query` (passed).

5. **Position Sizing Arithmetic & Concentration Flag:**
   - Traced `backend/app/routers/stock_scan.py:_position_size`:
     $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})}{|\text{Entry Price} - \text{Stop Price}|} + 10^{-9} \right\rfloor\right)$$
   - Verified that if entry == stop, `_position_size` returns `(0, 0.0)`.
   - Traced `frontend/components/organisms/StockPositionCard/index.tsx:69-116` (`concentrationFlag`). Verified that exceeding the single-position capital cap sets `concentrationFlag` in the UI per decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09`, but **never clamps** `recommendedShares`. Tested in `test_position_sizing_formula_with_conviction`, `test_position_sizing_boundary_conditions`, and `test_concentration_flag_math_never_clamps_shares` (passed).

6. **Frontend Request Resolution & Store Hydration:**
   - Traced `frontend/lib/resolveStockScanRequest.ts:buildStockScanRequestBody`. Verified price and market cap filter conversions with unit multipliers (`M` = $10^6$, `B` = $10^9$) and explicit zero preservation (`0` vs `undefined`).
   - Verified `STOCKS_SCORER_KEYS` whitelist isolation, ensuring options-only keys (`max_delta`, `min_dte`, `target_dte`, `iv_rank_pass_max`, `iv_abs_pass_max`) are stripped from stock scan requests.
   - Verified weight conversion from UI percentage (0–100) to decimal fraction (0.0–1.0).
   - Traced `frontend/components/StoreHydration/index.tsx` and `frontend/lib/scanStore.ts`. Verified rehydration of persisted stock scan results, `toLocalWallClock` timestamp conversion, context validation, and clean invalidation (`clearScanResults`). Tested in `frontend/app/(frame)/screener/step-4-stocks/__tests__/auditStocksLaneD.test.tsx` (6 passed).

7. **Project State & Typecheck Parity:**
   - Ran `python scripts/state.py`: clean exit code 0, 0 drift.
   - Ran `npm run typecheck` in `frontend/`: clean exit code 0, 0 errors.

---

GATE FINDINGS: 0
