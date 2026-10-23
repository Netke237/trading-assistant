# APP-AUDIT-STOCKS — Lane D Execution Plan

**Tracking:** Issue [#352](https://github.com/Netke237/trading-assistant/issues/352), Programme [#348](https://github.com/Netke237/trading-assistant/issues/348)  
**Phase ID:** `APP-AUDIT-STOCKS`  
**Branch:** `board/app-audit-stocks-6564657f`  
**Source Baseline:** Frozen at `origin/main` commit `bf0b3b54`  
**Report Destination:** `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/report.md`  

---

## 1. Goal and Deliverables

Execute the comprehensive Lane D audit of the Stocks scan, strategy signals, backtest engine, confidence evaluation, and position card trade plan across both frontend and backend surfaces of Bamendjou:
1. **Stock Scan Pipeline & Request Resolution** (`resolveStockScanRequest.ts`, `stockScan.ts`, `routers/stock_scan.py`)
2. **5-Rule Stock Scorer & Demotion Hierarchy** (`stock_scorer.py`, `fundamentals_scorer.py`, `fundamentals_gate.py`, `scoring_rules.yaml`)
3. **Strategy Engine & 7 Primary Strategies** (`strategy_engine.py`, `strategy_params.yaml`, `schemas/stock_scan.py`)
4. **Backtest Engine & Signal Confidence** (`strategy_backtest.py`, `signal_confidence.py`, `backtest_artifacts.py`)
5. **Position Sizing & Trade Plan** (`StockPositionCard`, `_position_size`, `reward_risk.py`, `stock_scan.py`)
6. **State Lifecycle, Hydration & Isolation** (`scanStore.ts`, `scanParamsStore.ts`, `StoreHydration`, `step-4-stocks/page.tsx`, `step-6-backtest/page.tsx`, `step-7-position-card/page.tsx`)

The audit establishes exact end-to-end parity: verifying that all mathematical calculations (composite stock scoring with event exclusion, strategy indicators, backtest win rate/expectancy, risk-based share sizing with conviction multiplier, rung allocations, and reward/risk ratios) are numerically accurate, that all status caps and gates demote strictly per policy without score distortion, that backtest artifacts remain detached and immutable, and that client persistence correctly rehydrates without stale state corruption.

**Audit Boundaries:**
- **Audit and report scope only:** No production algorithms, scoring thresholds, strategy parameters, or database schemas are modified during this audit phase.
- **Zero live broker orders or external API mutations:** All evaluations run against deterministic test fixtures and mocked providers.
- **Discovered defects** are cataloged into structured findings (`defects.json`); each actionable defect becomes a separate board remediation ticket.
- **Python 3.11 Runtime:** All automated verification harnesses run strictly under Python 3.11 to maintain exact numerical and float summation parity.

**Deliverable Artifacts** (under `docs/superpowers/audits/app-audit/APP-AUDIT-STOCKS/`):
1. `provenance.json`: Frozen environment, Node, Python 3.11, Chromium, commit SHAs, config hashes, and fixture provenance.
2. `reconciliation.json`: Explicit mapping between Lane A inventoried surfaces/states and Lane D audit touchpoints.
3. `defects.json`: Separated numbers/persistence and presentation/usability defect ledger with full reproduction steps.
4. `README.md` & `report.md`: Complete audit findings, verified assertions, reproduction evidence, and open residuals.
5. Automated evidence harnesses and tests: deterministic scripts verifying scoring, strategies, backtests, sizing, and lifecycle in isolated environments.

---

## 2. Surface Inventory & Architecture Matrix

| Surface / Component | Source Path | Stores / Services Attached | Backend Endpoints | Key Responsibilities |
|---|---|---|---|---|
| **Step 4 Stocks Results** | `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | `useScanStore`<br>`useScanParamsStore`<br>`useUniverseStore`<br>`useSettingsStore` | `POST /api/stock-scan`<br>`GET /api/stock-scan/last`<br>`GET /api/stock-scan/last-run` | Strategy picker, ranked candidates table, score card preview, status tints (`PASS`/`CAUTION`/`REJECT`), WatchStar, StockPositionCard preview, StockSendDialog, HistoryPrefetchRow. |
| **Step 5 Strategy Redirect** | `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | N/A | None (compatibility route) | Unconditional compatibility redirect to `step-4-stocks` where strategy selection and params are co-located. |
| **Step 6 Backtest Inspector** | `frontend/app/(frame)/screener/step-6-backtest/page.tsx` | `useScanStore`<br>`useSettingsStore` | `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` | Displays candidate backtest metrics (win rate, expectancy, total return, max drawdown, sharpe), time exits, confidence gate verdict (`passes_gate`), BacktestInspector. |
| **Step 7 Position Card** | `frontend/app/(frame)/screener/step-7-position-card/page.tsx` | `useScanStore`<br>`useRiskStore`<br>`usePortfolioStore`<br>`useSettingsStore` | `POST /broker/stock-order` | PositionCard with ConfidenceBadge, share quantity, entry, stop, target rungs, dollar risk, total capital, concentration flag, time stop projection, broker execution mode selector (IBKR/Tradier/Alpaca paper). |
| **Strategy Params Panel** | `frontend/components/organisms/StrategyParamsPanel/` | `useScanParamsStore` | None (in-page controls) | Exposes strategy-specific parameter overrides (`pullbackTolerancePct`, `maCrossoverLookback`, `breakoutVolumeMult`, etc.) and backtest threshold controls. |
| **Context Rail** | `frontend/app/(frame)/@contextRail/screener/` | `useScanStore`<br>`useWatchlistStore` | None | Screener rail showing active candidate summary, status counts, and watchlist top picks. |

---

## 3. Detailed Audit Scope & Verification Tasks

### Task 1 — Request Resolution & Context Parity
- **Universe & Filter Resolution (`resolveStockScanRequest.ts:60-150`):**
  - Verify universe resolution across predefined universes (`SP500`, `NDX100`, `DOW30`) and `Custom` tickers.
  - Verify delimiter handling in Custom tickers (commas, newlines, semicolons, whitespace, deduplication, uppercase normalization).
  - Verify price and market cap filter propagation (`min_price`, `max_price`, `min_cap_usd`, `max_cap_usd`) with unit multiplier (`M` = 1e6, `B` = 1e9), including explicit zero preservation (`0` vs `undefined`).
- **Horizon & Tuned Horizon Mapping:**
  - Verify scoring horizon (`Intraday`, `Swing`, `Position`) and hold day sanitization (`sanitizeHoldDays`).
  - Verify `params_horizon` mapping via `tunedParamsHorizon(preset, holdMax)` (Intraday sends `None`; Swing/Position map to tuned horizon).
- **Capital & Sizing Inputs:**
  - Verify `account_size` mapped from `riskStore.limits.portfolioValue` (default 50,000.0) with strictly positive validation (`gt=0`).
  - Verify `risk_pct` mapped from `riskStore.limits.maxLossPerTradePct` (default 0.01 / 1%) with `gt=0, le=1` bounds, verifying that legacy stored `0` correctly defaults to 1% without breaking backend validation.
- **Overrides & Whitelist Isolation:**
  - Verify `STOCKS_SCORER_KEYS` whitelist prevents options-only keys (contract rules, delta, DTE) and IV ceilings from leaking into stock scan requests.
  - Verify `normalizeWeightOverride` converts UI percent inputs (0–100) to decimal fractions (0.0–1.0) for `SCORE_WEIGHT_KEYS`.
  - Verify confidence gate overrides (`confidence_caution_below`, `confidence_reject_below`, `confidence_atr_mult_target`, `confidence_atr_mult_stop`) and regime gate overrides are forwarded correctly.
  - Verify strategy parameter validation via `assertStrategyScanOverrides` (e.g. `pullbackTolerancePct > 0`, `maCrossoverLookback > 0`, `breakoutVolumeMult > 1.0`).

### Task 2 — Stock Scorer & 4-Tier Demotion Hierarchy
- **Composite 5-Rule Weighted Scorer in Stock Mode (`stock_scorer.py:1097-1240`):**
  - Verify stock-mode event exclusion and non-event renormalization (`scoring_mode == "stock"` at `stock_scorer.py:1223-1231`):
    $$w_{\text{event}} = 0.0$$
    $$w_i' = \frac{w_i}{\sum_{j \neq \text{event}} w_j} \quad \text{for } i \in \{\text{trend}, \text{pullback}, \text{trigger}, \text{vol}\}$$
    $$S = \text{round}\left(w_{\text{trend}}' S_{\text{trend}} + w_{\text{pullback}}' S_{\text{pullback}} + w_{\text{trigger}}' S_{\text{trigger}} + w_{\text{vol}}' S_{\text{vol}}\right)$$
  - Confirm that upcoming earnings/dividend dates never contribute points to `final_score` in stock mode (event proximity is retained purely for informational display and the earnings veto gate).
  - Verify score status classification against `scoring_rules.yaml`:
    - `PASS`: score $\ge 55$
    - `CAUTION`: $35 \le \text{score} < 55$
    - `REJECT`: $\text{score} < 35$
- **Component Sub-Scorers:**
  - **Trend (`_score_trend`):** Crossover method (EMA fast vs slow distance and slope), Additive method (Price vs MA, MA slope, ADX strength), and Relative Strength vs benchmark (`NDX` or `SPY`).
  - **Pullback (`_score_pullback`):** Distance to EMA20/50, RSI pullback depth, stochastic location.
  - **Trigger (`_score_trigger`):** Reversal candlestick pattern, MACD histogram momentum, volume expansion.
  - **Event (`_score_event`):** Earnings date proximity vs `event_reject_days` / `event_caution_days` (used for earnings veto evaluation).
  - **Volatility (`_score_vol`):** ATR percentile and Bollinger Band bandwidth.
- **4-Tier Demotion Hierarchy (`stock_scorer.py:1240-1320`):**
  1. **Pullback Timing Veto:** If `pullback_status == 'REJECT'`, status caps at `CAUTION` (candidate remains visible but cannot PASS).
  2. **Confidence Gate:** When `confidence_gate` is enabled, verify status cap based on forward-replay `confidence` score (0–100 integer):
     - `confidence < cautionBelow` (default 50) caps at `CAUTION`
     - `confidence < rejectBelow` (default 35) caps at `REJECT`
     - `confidence is None` (unvalidated / sample count $< \text{min\_samples}$) unconditionally caps at `CAUTION`
  3. **Regime Gate:** Verify demotion based on overall market regime (SPX/NDX conviction and stability) aligned with scan direction.
  4. **Fundamentals Gate:** When enabled for Swing/Position horizons, verify status caps against `scoring_rules.yaml` defaults:
     - Bullish: `cautionBelow: 45` caps at `CAUTION`, `rejectBelow: 30` caps at `REJECT`
     - Bearish: `cautionAbove: 70` caps at `CAUTION`, `rejectAbove: 80` caps at `REJECT`
     - Safety flags: `debt_to_equity >= 3.0` (`extreme_leverage`) and `stockholders_eq < 0` (`negative_equity`) trigger `REJECT` across both directions
     - Verify Intraday scans remain strictly exempt from fundamentals gate.
  - Verify `worstStatus` / `_worse` monotonicity: a status can only be demoted, never promoted by subsequent caps.

### Task 3 — Strategy Engine & 7 Primary Strategies
- **7 Exposed Primary Strategies (`backend/app/schemas/stock_scan.py:10`, `strategy_engine.py`):**
  1. `pullback_ema` (`pullback_ema_signal`): Price pullbacks to EMA20/EMA50; verify `require_reversal` enforces green candle bounce.
  2. `breakout_base` (`breakout_base_signal`): Breakout above multi-bar consolidation base; verify `breakout_volume_mult > 1.0` expansion check.
  3. `ma_crossover` (`ma_crossover_signal`): Fast MA crossing Slow MA within `ma_crossover_lookback` bars.
  4. `mean_reversion_rsi` (`mean_reversion_rsi_signal`): RSI crossing below oversold (Bullish) or above overbought (Bearish) with SMA trend confirmation.
  5. `mean_reversion_bb` (`mean_reversion_bb_signal`): Price piercing lower Bollinger Band (Bullish) or upper band (Bearish) with mean reversion target at middle band.
  6. `mean_reversion_vwap` (`mean_reversion_vwap_signal`): Intraday VWAP deviation; verify requirement for intraday completed bars.
  7. `mean_reversion_multi` (`multi_signal` / `resolve_multi_signal`): Combines RSI, Bollinger Bands, and multi-day rolling VWAP (`mean_reversion_vwap_daily_signal`) based on confirmations count (`mean_reversion_min_confirmations`).
- **Directional Symmetry:**
  - Verify Bullish vs Bearish entry conditions, stop loss placement, and target pricing across all 7 strategies.
  - Verify that Bearish signals properly invert logic (e.g. short entries, stop above swing high, target below entry).
- **Unsupported Strategy & Horizon Combinations:**
  - Verify graceful handling when an intraday-only strategy (e.g. `mean_reversion_vwap`) is requested on daily bars or vice versa.

### Task 4 — Backtest Engine, Confidence Evaluation & Artifacts
- **Vectorized Backtest Runner (`strategy_backtest.py:105-350`):**
  - Verify trade simulation: entry on next bar open following signal bar, stop loss trigger, profit target trigger.
  - Verify Time Exits (`hold_max_days` / max bars): trades held past the horizon hold window are exited at market on the close of the final bar, incrementing `n_time_exits`.
  - Verify metric calculations matching `BacktestOut` schema:
    $$\text{Win Rate} = \frac{N_{\text{wins}}}{N_{\text{trades}}}$$
    $$\text{Expectancy} = (W \times \overline{\text{Win}}) - ((1 - W) \times \overline{\text{Loss}})$$
    $$\text{Total Return \%} = \text{Cumulative return from strategy trades}$$
    $$\text{Max Drawdown \%} = \max_{t} \left(\frac{\text{Peak}_t - \text{Trough}_t}{\text{Peak}_t}\right)$$
    $$\text{Sharpe Ratio} = \frac{\overline{R}}{\sigma_R} \times \sqrt{252}$$
  - Verify zero-trade handling: `_empty_result` safely returns 0 trades, 0 win rate, 0 expectancy, `passes_gate=False` without `ZeroDivisionError`.
- **Signal Confidence Scoring (`signal_confidence.py`):**
  - Verify sample size sufficiency (`n_trades >= min_samples`).
  - Verify confidence score derivation (0–100) from win rate hurdle, expectancy, and trade count.
  - Verify interpretation labels ("Validated", "Caution", "Unvalidated").
- **Backtest Artifact Integrity (`backtest_artifacts.py`):**
  - Verify candidate backtests generate frozen artifacts stored with `schema_version=1`, `provenance: 'original'`, and unique UUID `artifact_id`.
  - Verify artifact endpoint: `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` requiring both artifact ID and symbol query parameter.
  - Verify artifact isolation: Step 6 Backtest Inspector loads the frozen candidate artifact rather than re-running the backtest with live mutable settings.
  - Verify explicit separation between original candidate artifacts and fresh on-demand backtests.

### Task 5 — Position Sizing & Trade Plan
- **Position Sizing Formula (`stock_scan.py:_position_size`, `StockPositionCard`):**
  - Verify production share sizing formula:
    $$\text{Risk per Share} = |\text{Entry Price} - \text{Stop Price}|$$
    $$\text{Dollar Risk} = \text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})$$
    $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Dollar Risk}}{\text{Risk per Share}} + 10^{-9} \right\rfloor\right)$$
  - Verify single-position concentration flag:
    - If $\text{Shares} \times \text{Entry Price} > \text{Max Capital}$, the UI flags `concentrationFlag` (decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09`), but **never clamps** `recommendedShares` or `Final Shares`.
  - Verify zero-dollar and boundary protections:
    - If entry == stop: safely fallback/reject without division by zero.
    - If entry <= 0 or stop <= 0: refuse calculation.
    - If risk_pct <= 0: clamp or fallback to 1% default.
- **Reward/Risk Ratio:**
  $$\text{R/R} = \frac{|\text{Target Price} - \text{Entry Price}|}{|\text{Entry Price} - \text{Stop Price}|}$$
  - Verify R/R precision and display parity.
- **Target Ladder & Rungs:**
  - Verify target rung generation (T1, T2, T3) and share allocations (e.g. 50% at T1, 30% at T2, 20% runner at T3).
- **Time Stop Projection:**
  - Verify `hold_max_days` projection to calendar date.
- **Order Payload Alignment:**
  - Verify that clicking "Send to Broker" in `StockSendDialog` formats `StockOrderRequest` with exact `symbol`, `qty` (integer shares), `order_type`, `limit_price`, `time_in_force`, and broker routing.

### Task 6 — State Lifecycle, Hydration & Concurrency
- **Asynchronous Execution & Polling:**
  - Verify `/api/stock-scan` immediate execution vs background polling via `/api/stock-scan/jobs/{id}`.
  - Verify cancellation endpoint `/api/stock-scan/cancel` and client-side `AbortController`.
- **Stale Async Response Prevention:**
  - Verify that out-of-order scan responses cannot overwrite newer results when switching universes or parameters.
- **Persistence & Hydration (`StoreHydration`):**
  - Verify `scanStore.stockScanResult` persistence in localStorage (`bamendjou-scan-store`).
  - Verify `StoreHydration` rehydrates persisted stock scan results and validates against active scan context (`resultMatchesContext`).
  - Verify clean invalidation: changing universe or custom symbols clears obsolete scan results (`clearScanResults`).

---

## 4. Automated Verification Test Suite

Develop and run an exhaustive automated test suite under Python 3.11 (`backend/tests/test_audit_stocks_lane_d.py`) and Jest (`frontend/app/(frame)/screener/step-4-stocks/__tests__/auditStocksLaneD.test.tsx`):
1. **Scorer & Gate Assertions**:
   - Verify stock-mode event weight zeroing and non-event weight proportional renormalization.
   - Verify weight unit normalization (0-100 vs fraction).
   - Verify all 4 demotion caps: Pullback veto, Confidence gate (evaluating integer `confidence`), Regime gate, and Fundamentals gate (with Bullish 45/30, Bearish 70/80 thresholds, and `extreme_leverage`/`negative_equity` flags).
2. **Strategy Signal Assertions**:
   - Verify all 7 exposed primary strategies emit valid signals on known candle patterns (Bullish and Bearish).
   - Verify parameter boundary enforcement (e.g. `pullback_tolerance_pct`, `breakout_volume_mult`).
3. **Backtest & Confidence Assertions**:
   - Verify `BacktestOut` metrics (`win_rate`, `expectancy`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, `n_time_exits`) on deterministic bar sequences.
   - Verify zero-trade handling and confidence gate pass/fail thresholds.
   - Verify backtest artifact save, retrieval via `GET /api/backtest-artifacts/{id}?symbol={symbol}`, expiration, and immutability.
4. **Position Card Sizing Assertions**:
   - Verify share sizing arithmetic using `Dollar Risk / Risk per Share` with conviction multiplier, `max(1, ...)` floor, and UI concentration flag without clamping.
   - Verify target rungs, R/R ratios, and broker order payload formatting.
5. **Frontend Request Resolution & Hydration Assertions**:
   - Verify `resolveStockScanRequest` extracts correct fields from stores.
   - Verify `StoreHydration` preserves persisted stock scan results across simulated page reloads and invalidates on universe edits.

---

## 5. Timeline & Milestones

- **Phase Registration & Plan Audit:**
  - Register `APP-AUDIT-STOCKS` in `docs/superpowers/PROJECT_STATE.json` and verify zero drift.
  - Run independent adversarial plan audit loop using `bmad-review-adversarial-general` with fresh subagents until clean (cap 3).
- **Execution & Test Verification:**
  - Implement automated test suite (`test_audit_stocks_lane_d.py` and `auditStocksLaneD.test.tsx`).
  - Execute full test passes under Python 3.11 and Jest, recording exact execution evidence.
- **Audit Deliverables Generation:**
  - Generate `provenance.json`, `reconciliation.json`, `defects.json`, `README.md`, and `report.md`.
- **Code & Report Audit:**
  - Run independent adversarial code audit loop using `bmad-review-adversarial-general` with fresh subagents until clean (cap 3).
- **PR, CI & Board Self-Merge:**
  - Open PR, ensure all CI checks pass on exact head, execute self-merge, update PROJECT_STATE.json, close #352, notify board.
