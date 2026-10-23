# APP-AUDIT-STOCKS Reconciliation Report

**Programme:** APP-AUDIT (#348)  
**Phase ID:** `APP-AUDIT-STOCKS` (#352)  
**Branch:** `board/app-audit-stocks-6564657f`  
**Target Surfaces:** Stocks scan pipeline (`/api/stock-scan`), Stock scorer (`stock_scorer.py`), 4-tier status caps (Pullback veto, Confidence gate, Regime gate, Fundamentals gate), 7 primary strategies (`strategy_engine.py`), Vectorized backtest runner (`strategy_backtest.py`), Signal confidence (`signal_confidence.py`), Backtest artifacts (`/api/backtest-artifacts`), Position card & sizing (`StockPositionCard`, `_position_size`), Client stores & hydration (`scanStore.ts`, `scanParamsStore.ts`, `StoreHydration`).  
**Baseline Commit:** Frozen at `origin/main` (`bf0b3b54`)  
**Status:** Audit Complete — Zero Gate Findings on verified code and formulas; 2 Informational findings cataloged.

---

## 1. Executive Summary

This reconciliation report delivers the comprehensive Lane D audit of the Stocks scan, strategy signals, backtest engine, confidence evaluation, and position card trade plan across Bamendjou:
1. **Stock Scan Pipeline & Request Resolution:** Verified `resolveStockScanRequest.ts`, `stockScan.ts`, and `routers/stock_scan.py`, confirming accurate universe resolution across predefined indices (`SP500`, `NDX100`, `DOW30`) and `Custom` delimiters, price/cap filtering with unit multipliers (`M` = $10^6$, `B` = $10^9$) and explicit zero preservation (`0` vs `undefined`), horizon hold day sanitization, risk and capital mapping, and strict whitelist isolation stripping options-only keys and IV ceilings.
2. **5-Rule Stock Scorer & 4-Tier Demotion Hierarchy:** Verified `stock_scorer.py`, `fundamentals_scorer.py`, and `fundamentals_gate.py`. Confirmed that under `scoring_mode == "stock"`, event proximity weight is unconditionally zeroed ($w_{\text{event}} = 0.0$) and non-event weights are renormalized proportionally ($\sum_{i \neq \text{event}} w_i' = 1.0$), ensuring earnings/dividend proximity never contributes points to `final_score`. Verified the 4 demotion caps: Pullback timing veto (REJECT $\to$ CAUTION), Confidence gate (evaluating integer forward-replay score 0–100), Regime gate (direction-aligned conviction and stability), and Fundamentals gate (Swing/Position only, Bullish 45/30, Bearish 70/80, negative equity and extreme leverage safety triggers; Intraday strictly exempt).
3. **Strategy Engine & 7 Primary Strategies:** Verified `strategy_engine.py`, `strategy_params.yaml`, and `schemas/stock_scan.py`. Confirmed that all 7 exposed primary strategies (`pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_vwap`, `mean_reversion_multi`) execute symmetrically across Bullish and Bearish directions, enforce strict parameter boundaries (`breakout_volume_mult > 1.0`, `pullback_tolerance_pct > 0`), and cleanly handle multi-variant voting.
4. **Backtest Engine, Confidence Evaluation & Frozen Artifacts:** Verified `strategy_backtest.py`, `signal_confidence.py`, and `backtest_artifacts.py`. Confirmed vectorized calculations for `win_rate`, `expectancy`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, zero-trade safety (`passes_gate=False`), time exits on final bar close (`n_time_exits`), sample size sufficiency evaluation, and immutable frozen artifact storage (`schema_version=1`, `provenance='original'`) requiring matching symbol query (`GET /api/backtest-artifacts/{id}?symbol={symbol}`).
5. **Position Sizing & Trade Plan:** Verified `StockPositionCard` and `stock_scan.py:_position_size`. Confirmed the production share sizing formula:
   $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})}{|\text{Entry Price} - \text{Stop Price}|} + 10^{-9} \right\rfloor\right)$$
   Confirmed that single-position concentration ($> \text{Max Capital}$) sets `concentrationFlag` in UI (decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09`), but **never clamps** `recommendedShares`.
6. **State Lifecycle, Hydration & Isolation:** Verified `StoreHydration` and `scanStore.ts`. Confirmed clean rehydration of persisted stock scan results, timestamp alignment via `toLocalWallClock`, matching context validation, and clean invalidation (`clearScanResults`).

All calculations, schemas, and state transitions strictly satisfy the project's numerical and persistence gate: zero formulas put a wrong number in front of the user, no live broker order is miscalculated, and all persisted data structures adhere to exact storage conventions.

---

## 2. Surface Inventory & Architecture Matrix

| Component / Layer | Source Location | Underlying Store / Schema | External API / Route | Disposition |
|---|---|---|---|---|
| Stock Scan Router | `backend/app/routers/stock_scan.py` | `StockScanRequest`, `StockScanResult` | `POST /api/stock-scan` | Verified |
| Stock Persistence API | `backend/app/routers/stock_scan.py` | `StockScanResult` cache | `GET /api/stock-scan/last` | Verified |
| Stock Run Meta API | `backend/app/routers/stock_scan.py` | `ScheduledScanRun` | `GET /api/stock-scan/last-run` | Verified |
| Backtest Artifact Router | `backend/app/routers/backtest_artifacts.py` | `BacktestArtifact` table | `GET /api/backtest-artifacts/{id}?symbol={s}` | Verified |
| Stock Scorer | `backend/app/scoring/stock_scorer.py` | `scoring_rules.yaml` | `score_stock` | Verified |
| Fundamentals Scorer | `backend/app/scoring/fundamentals_scorer.py` | `scoring_rules.yaml` | `score_fundamentals` | Verified |
| Fundamentals Gate | `backend/app/services/fundamentals_gate.py` | `scoring_rules.yaml` | `resolve_fundamentals_gate` | Verified |
| Strategy Engine | `backend/app/services/strategy_engine.py` | `strategy_params.yaml` | 7 primary signal functions | Verified |
| Strategy Backtest | `backend/app/services/strategy_backtest.py` | `BacktestOut`, `BacktestResult` | `run_strategy_backtest` | Verified |
| Signal Confidence | `backend/app/scoring/signal_confidence.py` | `scoring_rules.yaml` | `status_cap`, `interpret` | Verified |
| Position Sizing | `backend/app/routers/stock_scan.py` | N/A | `_position_size` | Verified |
| StockPositionCard | `frontend/components/organisms/StockPositionCard/` | `riskStore`, `portfolioStore` | In-page UI preview | Verified |
| Request Resolver | `frontend/lib/resolveStockScanRequest.ts` | `scanParamsStore`, `settingsStore` | `buildStockScanRequestBody` | Verified |
| Store Hydration | `frontend/components/StoreHydration/` | `scanStore`, `universeStore` | Client rehydration lifecycle | Verified |
| Step 4 Stocks Page | `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | `scanStore`, `scanParamsStore` | Primary stocks results view | Verified |
| Step 5 Strategy Redirect | `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | N/A | Pass-through redirect | Verified (DEFECT-STOCKS-1) |
| Step 6 Backtest Inspector | `frontend/app/(frame)/screener/step-6-backtest/page.tsx` | `scanStore` | Backtest metrics & inspector | Verified |
| Step 7 Position Card Page | `frontend/app/(frame)/screener/step-7-position-card/page.tsx` | `scanStore`, `riskStore` | Order submission stage | Verified |

---

## 3. Data & Arithmetic Parity Audit (The Gate)

### 3.1 Request Resolution & Whitelist Isolation (Task 1)

#### Universe & Filter Resolution
- `resolveStockScanRequest.ts` builds canonical `StockScanRequestBody` payload matching Pydantic `StockScanRequest`:
  - **Predefined Universes:** Correctly resolves `SP500`, `NDX100`, `DOW30` tickers.
  - **Custom Delimiters:** Normalizes custom symbol lists across commas, newlines, semicolons, whitespace, deduplicating symbols and converting to uppercase.
  - **Price & Cap Filters:** Propagates `min_price`, `max_price`, `min_cap_usd`, and `max_cap_usd` with unit multipliers (`M` = $10^6$, `B` = $10^9$). Explicit zero entries (`'0'`) are preserved as numerical `0` rather than coerced to `undefined`.
- **Horizon & Hold Days:**
  - Sanitizes `hold_min_days` and `hold_max_days` via `sanitizeHoldDays`.
  - Maps `params_horizon` via `tunedParamsHorizon(preset, holdMax)` (Intraday sends none; Swing/Position map to tuned horizon).
- **Capital & Risk Inputs:**
  - Account size maps from `riskStore.limits.portfolioValue` (default 50,000.0) with positive validation.
  - Risk percentage maps from `riskStore.limits.maxLossPerTradePct` (default 0.01 / 1%) bounded in $(0, 1.0]$.
- **Whitelist Isolation:**
  - `STOCKS_SCORER_KEYS` filter prevents options-only keys (`max_delta`, `min_dte`, `target_dte`, etc.) and IV ceilings (`iv_abs_pass_max`, `iv_rank_pass_max`) from leaking into stock scan requests.
  - `normalizeWeightOverride` converts UI percent inputs (0–100) to decimal fractions (0.0–1.0) for `SCORE_WEIGHT_KEYS`.
  - `assertStrategyScanOverrides` validates parameter boundaries before request dispatch (`breakoutVolumeMult > 1.0`, `pullbackTolerancePct > 0`).

### 3.2 5-Rule Stock Scorer & 4-Tier Demotions (Task 2)

#### Composite 5-Rule Scorer in Stock Mode
- In stock mode (`scoring_mode == "stock"` at `backend/app/scoring/stock_scorer.py:1223-1241`):
  $$w_{\text{event}} = 0.0$$
  $$w_i' = \frac{w_i}{\sum_{j \neq \text{event}} w_j} \quad \text{for } i \in \{\text{trend}, \text{pullback}, \text{trigger}, \text{vol}\}$$
  $$S = \text{round}\left(\sum_{i \neq \text{event}} w_i' S_i\right)$$
- Event proximity (earnings/dividends) is displayed in UI and evaluated for the pipeline earnings veto gate, but **never contributes points** to `final_score`.
- Score status classification against `scoring_rules.yaml`:
  - `PASS`: score $\ge 55$
  - `CAUTION`: $35 \le \text{score} < 55$
  - `REJECT`: $\text{score} < 35$

#### 4-Tier Demotion Hierarchy
The demotion caps operate monotonically via `_worse(current, cap)` — a status can only be demoted, never promoted:
1. **Pullback Timing Veto:** If `pullback_status == 'REJECT'`, caps status at `CAUTION` (setup timing is wrong; candidate cannot PASS).
2. **Confidence Gate:** When enabled, evaluates integer forward-replay excursion `confidence` score (0–100):
   - `confidence < cautionBelow` (default 50) $\implies$ `CAUTION`
   - `confidence < rejectBelow` (default 35) $\implies$ `REJECT`
   - `confidence is None` (unvalidated / sample size $< \text{min\_samples}$) $\implies$ `CAUTION`
   - `confidence >= cautionBelow` $\implies$ `PASS` (no demotion)
3. **Regime Gate:** Evaluates market regime conviction and stability aligned with direction:
   - Severe headwind ($\le -40\%$) with `Stable` regime $\implies$ `REJECT`
   - Mild headwind ($\le -15\%$) $\implies$ `CAUTION`
   - Tailwind ($> 0\%$) $\implies$ `PASS`
4. **Fundamentals Gate:** Evaluated for Swing and Position horizons (`is_intraday` scans are strictly exempt):
   - Bullish: health $< 30 \implies \text{REJECT}$, health $< 45 \implies \text{CAUTION}$
   - Bearish: health $> 80 \implies \text{REJECT}$, health $> 70 \implies \text{CAUTION}$
   - Safety flags: `negative_equity` (`stockholders_eq < 0`) and `extreme_leverage` (`debt_to_equity >= 3.0`) trigger unconditional `REJECT` across both directions.

### 3.3 Strategy Engine & 7 Primary Strategies (Task 3)

The 7 primary strategies defined in `Strategy` schema (`backend/app/schemas/stock_scan.py:10`) execute symmetrically across Bullish and Bearish directions:
1. `pullback_ema`: Price pullback to EMA20/EMA50; `require_reversal` enforces green bounce candle.
2. `breakout_base`: Breakout above multi-bar consolidation base; `breakout_volume_mult > 1.0` validates volume expansion.
3. `ma_crossover`: Fast MA crossing Slow MA within `ma_crossover_lookback` bars.
4. `mean_reversion_rsi`: RSI oversold (Bullish) or overbought (Bearish) crossing with SMA trend confirmation.
5. `mean_reversion_bb`: Bollinger Band lower/upper band piercing with mean reversion target at middle band.
6. `mean_reversion_vwap`: Completed intraday VWAP deviation.
7. `mean_reversion_multi`: Multi-variant voting combining RSI, Bollinger Bands, and rolling daily VWAP (`mean_reversion_vwap_daily_signal`) requiring $\ge \text{min\_confirmations}$.

### 3.4 Backtest Engine, Confidence Evaluation & Frozen Artifacts (Task 4)

#### Vectorized Backtest Runner (`strategy_backtest.py`)
- Simulates trades over OHLCV bars: next-bar open entry, stop loss, profit target, and time exits.
- **Time Exits:** Positions held past `hold_max_days` exit at market on the close of the final bar, incrementing `n_time_exits`.
- **Metrics Calculation:**
  $$\text{Win Rate} = \frac{N_{\text{wins}}}{N_{\text{trades}}}$$
  $$\text{Expectancy} = (W \times \overline{\text{Win}}) - ((1 - W) \times \overline{\text{Loss}})$$
  $$\text{Sharpe Ratio} = \frac{\overline{R}}{\sigma_R} \times \sqrt{252}$$
- **Zero-Trade Safety:** When zero trades occur, returns `passes_gate=False`, 0 trades, 0 win rate, 0 expectancy, 0 Sharpe without division by zero.

#### Frozen Candidate Backtest Artifacts (`backtest_artifacts.py`)
- Candidate backtests generate immutable artifacts stored in SQLite/PostgreSQL with `schema_version=1` and `provenance: 'original'`.
- Endpoint `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` requires both artifact UUID and matching symbol query parameter.
- Artifacts are fully detached from mutable user settings: inspecting a candidate on Step 6 displays the exact evidence generated during the scan, preventing recalculation drift.

### 3.5 Position Sizing Arithmetic & Concentration (Task 5)

#### Share Sizing Formula
- Implemented in `backend/app/routers/stock_scan.py:_position_size`:
  $$\text{Risk per Share} = |\text{Entry Price} - \text{Stop Price}|$$
  $$\text{Dollar Risk} = \text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})$$
  $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Dollar Risk}}{\text{Risk per Share}} + 10^{-9} \right\rfloor\right)$$
- Boundary guards: if $\text{Risk per Share} \le 0$, returns `(0, 0.0)`.

#### Concentration Flag Logic (UI Non-Clamping)
- Per decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09` in `StockPositionCard`:
  - If $\text{Shares} \times \text{Entry Price} > \text{Portfolio Value} \times \text{Max Capital Cap}$, the UI displays a `concentrationFlag` warning with `positionDollar`, `capDollar`, `positionPct`, and `capShares`.
  - **Non-Clamping Invariant:** `recommendedShares` remains exactly the risk-budget derived quantity and is **never clamped**. The trader retains full agency with transparent risk visibility.

### 3.6 State Lifecycle, Hydration & Isolation (Task 6)

- `StoreHydration` rehydrates persisted `stockScanResult` and request context from localStorage (`bamendjou-scan-store`).
- `toLocalWallClock` normalizes backend UTC timestamps to local browser wall-clock strings.
- Invalidation: `clearScanResults()` cleanly purges `stockScanResult`, `stockScanRequest`, and `stockScanAt` upon universe changes or explicit reset.

---

## 4. Defect Catalog & Observations

| Finding ID | Severity | Category | Description | Status |
|---|---|---|---|---|
| `DEFECT-STOCKS-1` | Info | routing-architecture | `step-5-strategy/page.tsx` is an unconditional pass-through redirect to `step-4-stocks`. Strategy picker is co-located on Step 4. | Retained for URL compatibility |
| `DEFECT-STOCKS-2` | Info | strategy-guard | `mean_reversion_vwap` raises `ValueError` if included in `mean_reversion_multi` on daily bars; rolling daily VWAP is used instead. | Verified & guarded in UI |

---

## 5. Verification & Test Evidence Summary

### Automated Test Execution Evidence

1. **Backend Verification Suite:** `backend/tests/test_audit_stocks_lane_d.py`
   - **Environment:** Python 3.11.15 (`backend/.venv/Scripts/python.exe`), pytest 8.1.1
   - **Results:** 16 tests executed, **16 PASSED, 0 FAILED** in 6.18s
   - **Covered:**
     - `test_stock_mode_event_weight_zeroed_and_renormalized` (PASS)
     - `test_threshold_status_verdicts` (PASS)
     - `test_pullback_timing_veto_demotes_pass_to_caution` (PASS)
     - `test_confidence_gate_caps_evaluates_integer_confidence` (PASS)
     - `test_regime_gate_demotion_alignment` (PASS)
     - `test_fundamentals_gate_bullish_and_bearish_thresholds` (PASS)
     - `test_worse_monotonicity` (PASS)
     - `test_all_seven_primary_strategies_exist_in_schema` (PASS)
     - `test_seven_strategies_signal_execution` (PASS)
     - `test_strategy_parameter_boundaries_enforced` (PASS)
     - `test_backtest_metric_calculations_and_schema` (PASS)
     - `test_zero_trades_empty_result_safe` (PASS)
     - `test_backtest_artifact_lifecycle_and_symbol_query` (PASS)
     - `test_position_sizing_formula_with_conviction` (PASS)
     - `test_position_sizing_boundary_conditions` (PASS)
     - `test_concentration_flag_math_never_clamps_shares` (PASS)

2. **Frontend Verification Suite:** `frontend/app/(frame)/screener/step-4-stocks/__tests__/auditStocksLaneD.test.tsx`
   - **Environment:** Jest 29, Node v24.14.0, TypeScript 5.7
   - **Results:** 6 tests executed, **6 PASSED, 0 FAILED** in 5.80s
   - **Covered:**
     - `builds valid StockScanRequestBody with numeric conversions and whitelist filtering` (PASS)
     - `preserves explicit zero in price and cap filters (0 vs undefined)` (PASS)
     - `omits price and cap filters when raw strings are empty or whitespace` (PASS)
     - `enforces strategy scan overrides assertions` (PASS)
     - `normalizes weight overrides correctly` (PASS)
     - `clears scan results on clearScanResults()` (PASS)

3. **TypeScript Typecheck:** `npm run typecheck` (`tsc --noEmit`)
   - **Result:** Clean exit code 0; zero type errors across the entire codebase.

---

## 6. Conclusion & Recommendations

The Lane D audit confirms that Bamendjou's Stocks scan, strategies, backtest engine, confidence gating, and position sizing implementations are numerically accurate, robustly guarded against boundary conditions, and completely isolated from cross-domain state leakage.

Zero gate-level defects were discovered. The lane is verified and ready for independent adversarial code review.
