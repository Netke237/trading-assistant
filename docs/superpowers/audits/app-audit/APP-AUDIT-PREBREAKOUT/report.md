# APP-AUDIT-PREBREAKOUT reconciliation report

**Programme:** APP-AUDIT (#348)  
**Phase ID:** `APP-AUDIT-PREBREAKOUT` (#353)  
**Worktree:** `.worktrees/app-audit-prebreakout`  
**Branch:** `board/app-audit-prebreakout-b4f0d823`  
**Target Surfaces:** Screener Step 4 Pre-Breakout (`frontend/app/(frame)/screener/step-4-prebreakout/`), Parameter Panels (`PreBreakoutParamsPanel`, `FibPullbackParamsPanel`), backend endpoints (`/api/scan/prebreakout`, `/api/scan/fib-pullback`, `/api/stock-scan`), signal engines (`breakout_setup_signal`, `fibonacci_pullback_detail`, `pullback_ema_signal`), candidate evidence (`SelectedRowEvidence`, `SelectedSetupChart`, `SelectedStockContext`, `SelectedStockNews`), and Candidate Chart handoff contracts (`candidateChart.ts`, `useOriginalBacktest.ts`).  
**Baseline Commit:** Frozen at `origin/main` (`b9a4e087`)  
**Status:** Audit Complete — Zero Gate Findings across mathematical models, parameter truncation, evidence preservation, and candidate chart handoff contracts; 3 non-gate follow-up defects cataloged.

---

## 1. Executive Summary

This reconciliation report delivers the comprehensive Lane E data, arithmetic, presentation parity, state lifecycle, and boundary audit across the screener's Step 4 Pre-Breakout surface:
1. **Pre-Breakout Scan (`scanMode === 'prebreakout'`)** — Volatility compression, range consolidation gate, volume contraction, swing level proximity, and confidence score breakdown (30% ATR, 25% Volume, 45% Proximity; or 24/20/36/20 when Fib enabled).
2. **Fibonacci Pullback Scan (`scanMode === 'fib'`)** — Swing identification, multi-level retracement calculation (23.6%, 38.2%, 50.0%, 61.8%, 78.6%), EMA trend filter gate, piecewise distance tolerance confidence scoring, and sorting by at-level status then proximity.
3. **Pullback Scan (`scanMode === 'pullback'`)** — Vectorised EMA pullback execution, risk sizing integration (`scanSizingFromRisk`), and frozen `BacktestArtifact` generation.
4. **Setup Evidence & Context Isolation** — Raw evidence preservation (PR #224 / #304), snapshot isolation (`rememberScan`, `scanSnapshot`), integer parameter truncation (`truncPreBreakoutInts`, `truncFibInts`), setup-only price overlays (`scanChartLines`), and isolated supplementary analysis (`api.analyzeStock`).
5. **Candidate Chart Workspace Handoff** — Strict parameter and context resolution (`buildCandidateChartHref`, `parseCandidateChartContext`), explicit `unsupported` handling for Pre-Breakout and Fib setups, and verified artifact hydration (`GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`) for Pullback setups.

All numerical and persistence mechanisms were verified against the project's numerical and persistence gate: no formula presents a wrong number to the user, no broker order calculation is corrupted, and persisted configurations adhere strictly to repository standards.

---

## 2. Surface Inventory & Architecture Matrix

| Sub-Mode | UI Component | Parameter Panel | Backend Endpoint | Signal Engine / Service | Chart Handoff Status |
|---|---|---|---|---|---|
| `prebreakout` | `step-4-prebreakout/page.tsx` | `PreBreakoutParamsPanel`<br>(`PREBREAKOUT_DEFAULTS`) | `POST /api/scan/prebreakout` | `breakout_setup_signal`<br>(`strategy_engine.py:1516-1660`) | `unsupported`<br>(live chart fallback) |
| `fib` | `step-4-prebreakout/page.tsx` | `FibPullbackParamsPanel`<br>(`FIB_PULLBACK_DEFAULTS`) | `POST /api/scan/fib-pullback` | `fibonacci_pullback_detail`<br>(`strategy_engine.py:1662-1770`) | `unsupported`<br>(live chart fallback) |
| `pullback` | `step-4-prebreakout/page.tsx` | Implicit (`pullbackEmaParams`: EMA 50, Trend EMA 100) | `POST /api/stock-scan`<br>(category: `pullback`) | `run_strategy_backtest`<br>(`strategy_backtest.py`) | Hydrated artifact<br>(`BacktestArtifact`) |

---

## 3. Data & Arithmetic Parity Audit (The Gate)

### 3.1 Pre-Breakout Scan (`scanMode === 'prebreakout'`)

#### Volatility & Range Calculations
- **Source Module:** `backend/app/services/strategy_engine.py:1516-1660`
- **True Range Derivation:**
  For each bar $t \ge 1$:
  $$TR_t = \max\left(H_t - L_t, \, |H_t - C_{t-1}|, \, |L_t - C_{t-1}|\right)$$
  Calculated across all historical bars via `_atr_series(bars, period=14)` (`backend/app/services/strategy_engine.py:95-104`).
- **ATR Calculation:**
  $$ATR_t = \frac{1}{14} \sum_{i=0}^{13} TR_{t-i}$$
  *Implementation Note:* The breakout setup signal uses a 14-period Simple Moving Average (SMA) of True Range starting from bar index 1 (`len(atrs) == len(bars) - 1`), in contrast to the Wilder exponential smoothing formula used in `stock_scorer.py:_atr`.
- **ATR Compression Condition:**
  $$R_{ATR} = \frac{ATR_{\text{current}}}{\frac{1}{M} \sum_{k=0}^{M-1} ATR_{t-k}} \le \text{atr\_compression\_ratio}$$
  where $M = \text{atr\_avg\_lookback}$ (default **20**).
  Component score:
  $$S_{ATR} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{R_{ATR}}{\text{atr\_compression\_ratio}}\right)\right)\right)$$
- **Range Consolidation Gate:**
  Consolidation high-low range over $K = \text{range\_lookback\_bars}$ (default **10**):
  $$\text{Range}_K = \max_{k \in [0, K-1]} H_{t-k} - \min_{k \in [0, K-1]} L_{t-k}$$
  Qualification condition:
  $$\text{Range}_K \le \text{range\_atr\_mult} \times ATR_{\text{current}}$$
  where $\text{range\_atr\_mult}$ defaults to **3.0**.  
  *Audit Verification:* Range consolidation acts strictly as a boolean qualification gate (`if consolidation_range > range_atr_mult * current_atr: return None`); it does not contribute an independent fractional score to the confidence total.

#### Volume & Proximity Metrics
- **Volume Contraction:**
  $$R_{Vol} = \frac{V_{\text{current}}}{\frac{1}{20} \sum_{k=0}^{19} V_{t-k}} \le \text{vol\_compression\_ratio}$$
  where $\text{vol\_compression\_ratio}$ defaults to **0.90**.
  Component score:
  $$S_{Vol} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{R_{Vol}}{\text{vol\_compression\_ratio}}\right)\right)\right)$$
- **Swing Level & Proximity:**
  Lookback window $L = \text{swing\_lookback}$ (default **50**).
  - **Bullish:** Swing High $S_H = \max_{k \in [1, L]} H_{t-k}$. Distance $D = \frac{S_H - C_{\text{current}}}{C_{\text{current}}}$.
    Gate: $0 < D \le \text{resistance\_proximity\_pct}$ (default **0.08** [8%]).
    Component score:
    $$S_{Prox} = \min\left(100, \, \max\left(0, \, 100 \times \left(1 - \frac{D}{\text{resistance\_proximity\_pct}}\right)\right)\right)$$
  - **Bearish:** Swing Low $S_L = \min_{k \in [1, L]} L_{t-k}$. Distance $D = \frac{C_{\text{current}} - S_L}{C_{\text{current}}}$.
    Gate: $0 < D \le \text{resistance\_proximity\_pct}$.
    Component score calculated analogously.

#### Total Confidence Synthesis
- **Base Mode (`fib_enabled=False`):**
  $$\text{Confidence} = \text{int}\left(0.30 \times S_{ATR} + 0.25 \times S_{Vol} + 0.45 \times S_{Prox}\right)$$
  Sum of weights: $0.30 + 0.25 + 0.45 = 1.00$ (100%). Truncated toward zero via Python `int(...)`, clamped strictly to $[0, 100]$.
- **Fibonacci-Augmented Mode (`fib_enabled=True`):**
  $$\text{Confidence} = \text{int}\left(0.24 \times S_{ATR} + 0.20 \times S_{Vol} + 0.36 \times S_{Prox} + 0.20 \times S_{Fib}\right)$$
  Sum of weights: $0.24 + 0.20 + 0.36 + 0.20 = 1.00$ (100%). Truncated toward zero via Python `int(...)`.

  *Audit Verification & Truncation Mechanism:* In `breakout_setup_signal` (`backend/app/services/strategy_engine.py:1644, 1650`), intermediate component scores ($S_{ATR}, S_{Vol}, S_{Prox}, S_{Fib}$) are maintained as raw unrounded floats, and total confidence is synthesized via Python integer truncation (`confidence = int(unrounded)`), which truncates fractional values toward zero. This is in contrast to Fibonacci pullback (`stock_scan.py:2293, 2295`), which synthesizes confidence using `round(...)`.

---

### 3.2 Fibonacci Pullback Scan (`scanMode === 'fib'`)

#### Swing Identification & Retracement Levels
- **Source Module:** `backend/app/services/strategy_engine.py:1662-1770` (`fibonacci_pullback_detail`) and `backend/app/routers/stock_scan.py:2160-2317` (`_fib_pullback_scan_core`)
- **Swing Window:** Lookback $L = \text{fib\_swing\_lookback}$ (default **100**, minimum backend bound **10**).
  $$H_{\text{swing}} = \max_{k \in [0, L-1]} H_{t-k}, \quad L_{\text{swing}} = \min_{k \in [0, L-1]} L_{t-k}$$
  $$\text{Impulse Range } R = H_{\text{swing}} - L_{\text{swing}}$$
  If $R \le 0$, setup is rejected immediately.
- **Retracement Price Levels:**
  - **Bullish:** $P_{lvl} = H_{\text{swing}} - R \times \frac{lvl}{100}$ for $lvl \in \{23.6, 38.2, 50.0, 61.8, 78.6\}$.
  - **Bearish:** $P_{lvl} = L_{\text{swing}} + R \times \frac{lvl}{100}$.

#### Trend Gate & Distance Tolerance
- **EMA Trend Gate:**
  If $\text{ema\_filter\_period} > 0$ (default **20**):
  - Bullish setup requires $C_{\text{current}} > EMA(\text{ema\_filter\_period})_t$.
  - Bearish setup requires $C_{\text{current}} < EMA(\text{ema\_filter\_period})_t$.
  If the closing price violates the EMA trend condition, the symbol is disqualified.
- **Distance Calculation & Tolerance Gate:**
  For each requested Fibonacci level $lvl \in \text{fib\_levels}$ (default `[38.2, 61.8]`):
  $$\text{dist\_pct}_{lvl} = \frac{|C_{\text{current}} - P_{lvl}|}{P_{lvl}} \times 100$$
  The nearest level is selected:
  $$\text{fib\_dist\_pct} = \min_{lvl \in \text{fib\_levels}} \text{dist\_pct}_{lvl}$$
  Tolerance threshold: $tol = \text{fib\_tolerance\_pct} \times 100$ (default **1.5%**).
  Status flags: $\text{at\_level} = (\text{fib\_dist\_pct} \le tol)$.

#### Piecewise Confidence Derivation
- If distance is undefined (`dist_pct is None`):
  $$\text{Confidence} = 0$$
- If within tolerance band ($\text{fib\_dist\_pct} \le tol$):
  $$\text{Confidence} = \max\left(60, \, \text{round}\left(100 - \frac{\text{fib\_dist\_pct}}{tol} \times 40\right)\right)$$
  *Range:* Yields a score between $60$ (at exact tolerance boundary) and $100$ (at zero distance).
- If outside tolerance band ($\text{fib\_dist\_pct} > tol$):
  $$\text{Confidence} = \max\left(0, \, \text{round}\left(60 - \frac{\text{fib\_dist\_pct} - tol}{tol} \times 30\right)\right)$$
  *Range:* Decays smoothly from $60$ down to $0$ as distance doubles the tolerance.
- **Sorting Hierarchy:**
  Candidates are sorted primarily by `not at_level` (at-level hits sort first), and secondarily by `fib_dist_pct` ascending (closest to retracement line first).

---

### 3.3 Pullback Scan (`scanMode === 'pullback'`)

- **Strategy Parameters:** 50-period EMA pullback, 100-period trend EMA (`pullbackEmaParams`).
- **Risk Sizing Integration:** `scanSizingFromRisk()` pulls account configuration (`portfolioValue`, `maxLossPerTradePct`) from `useRiskStore`.
- **Vectorised Backtest:** Executed via `run_strategy_backtest` (`backend/app/services/strategy_backtest.py`), calculating win rate, total return %, expectancy, and gate pass/fail criteria.
- **Frozen Artifact Generation:** Every qualifying pullback candidate receives a frozen `BacktestArtifact` with unique UUID `artifact_id`, enabling full backtest curve hydration.

---

## 4. State Machine, Snapshot Isolation & Parameter Truncation

### 4.1 Integer Parameter Truncation Parity
- **Backend Behavior:** In `backend/app/routers/stock_scan.py:2201, 2361`, lookback integer parameters are strictly cast via `int(req.params.swing_lookback)` etc.
- **Frontend Alignment:** `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` defines:
  ```ts
  function truncPreBreakoutInts(params: PreBreakoutParams): PreBreakoutParams {
    return {
      ...params,
      atrAvgLookback: Math.trunc(params.atrAvgLookback),
      rangeLookbackBars: Math.trunc(params.rangeLookbackBars),
      swingLookback: Math.trunc(params.swingLookback),
    };
  }
  ```
  ```ts
  function truncFibInts(params: FibPullbackParams): FibPullbackParams {
    return {
      ...params,
      fibSwingLookback: Math.trunc(params.fibSwingLookback),
      emaFilterPeriod: Math.trunc(params.emaFilterPeriod),
    };
  }
  ```
- **Fidelity:** Prevents fractional parameter slider drift from corrupting execution hashes or snapshot metadata.

### 4.2 Snapshot Isolation (`rememberScan` & `scanSnapshot`)
- When a scan completes, active execution parameters, direction, horizon, and universe are committed to `applied` snapshots (`applied.pre` or `applied.fib`).
- Parameter panel adjustments made *after* a scan has completed do not mutate the displayed thresholds or evidence criteria of previously scanned candidates.
- Candidate evidence displays (`SelectedRowEvidence`) read directly from `applied` snapshot values, preserving absolute audit repeatability.

### 4.3 Monotonic Network Request Token
- In-flight network cancellation uses an incremental counter: `requestToken.current += 1`.
- Rapid sub-mode switching (`prebreakout` $\rightarrow$ `fib` $\rightarrow$ `pullback`) immediately increments the token; responses from superseded network requests are safely dropped, preventing out-of-order state overwrites.

### 4.4 Supplementary Analysis Isolation
- `SelectedStockContext` triggers single-ticker deep-dive analysis via `api.analyzeStock`.
- Live fundamental scores and market regime alignment metrics are kept strictly segregated in supplementary state; they never overwrite or pollute the candidate's original setup evidence.

---

## 5. Candidate Chart Workspace Handoff & Provenance

### 5.1 Handoff Contract (`buildCandidateChartHref`)
- **Source Module:** `frontend/lib/candidateChart.ts:1-29`
- **URL Parameter Schema:**
  - `symbol`: Ticker symbol.
  - `source`: `'prebreakout' | 'fib' | 'pullback' | 'stocks' | 'ranking'`.
  - `backtest_artifact_id`: Backtest artifact UUID (only passed when present).
  - `backtest_artifact_status`: Status string (e.g. `'unsupported'`, `'original_unavailable'`, `'ready'`).
- **Sub-Mode Specific Behavior:**
  - For `prebreakout` and `fib`:
    ```ts
    status = 'unsupported';
    // backtest_artifact_id is omitted
    ```
  - For `pullback`:
    ```ts
    status = row.backtest_artifact_status ?? 'original_unavailable';
    backtest_artifact_id = row.backtest_artifact_id;
    ```

### 5.2 Chart Workspace Resolution (`CandidateChartWorkspace`)
- **Resolution Hook:** `useOriginalBacktest` (`frontend/lib/useOriginalBacktest.ts`).
- **Pre-Breakout / Fib Behavior:**
  Returns `{ status: 'unavailable', reason: 'unsupported' }`.
  The chart workspace displays:
  > *"Original backtest unavailable: unsupported. Live chart below; no historical result has been substituted."*
  No synthetic or fabricated backtest curve is displayed. The live candlestick chart renders normally.
- **Fresh Backtest Separation:**
  The `FreshBacktestControls` panel allows running an on-demand backtest with separate provenance (`provenance: 'fresh'`), ensuring complete demarcation from original scan results.
- **Pullback Behavior:**
  Hydrates the original backtest artifact via `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`.
  Verifies:
  - `artifact.schema_version === 1`
  - `artifact.symbol === symbol`
  - `artifact.provenance === 'original'`
  Renders exact historical backtest metrics (`win_rate`, `expectancy`, trade markers).

---

## 6. Selected Setup Chart Price Lines

- **Source Module:** `frontend/app/(frame)/screener/step-4-prebreakout/scanChartLines.ts:1-75`
- **Setup-Only Overlays:**
  - **Pre-Breakout Mode:** Plots setup swing level (`Scan swing high` or `Scan swing low`) derived from row evidence.
  - **Fibonacci Pullback Mode:** Plots swing high (`Scan swing high`), swing low (`Scan swing low`), and selected Fibonacci retracement level (`Scan Fib {lvl}%`).
  - **Pullback Mode:** Returns `[]` (no speculative lines plotted).
- **Audit Verification:**
  - The overlay strictly plots setup swing and retracement levels.
  - It does NOT plot trade entry prices, profit targets, stop-loss levels, or speculative ATR bands.
  - In-flight candlestick requests implement cancellation cleanup (`cancelled = true` and `current = state.row === row && state.scope === scope`), eliminating stale chart flicker during rapid selection.

---

## 7. UI Presentation, Accessibility & Boundaries

- **Candidate Table:** Renders candidate symbol, company name, pattern confidence score (or stock score in Pullback mode), pattern status badge, ATR/volume ratios, and action controls (`WatchStar`, `CompositeAlertDialog`, Chart link ↗).
- **Accessibility:**
  - Candidate row selection uses standard button semantics with `aria-pressed`.
  - Full keyboard operability via `Enter` and `Space`.
  - Accessible names and tooltips provided on all icon triggers.
- **Boundary States:**
  - **Empty Universe:** Displays informative alert guiding the user to select valid symbols or universes.
  - **Zero Candidates:** Clear notification stating no candidates matched the consolidation or pullback criteria.
  - **Network Errors:** Graceful error banner displaying backend failure message with retry capability.
  - **Loading Shimmer:** Displays skeleton rows while network scan is in flight.
- **Theme & Token Compliance:** Strict adherence to CSS custom properties (`--bg-surface`, `--border-subtle`, `--text-primary`, `--pass`, `--caution`, `--reject`); zero card shadows and zero hardcoded HEX values.

---

## 8. Defect Catalog & Non-Gate Follow-ups

All cataloged items are low-severity or feature-parity enhancements; none violate the numerical and persistence gate:

| Defect ID | Category | Severity | Description | Remediation / Tracking |
|---|---|---|---|---|
| `DEFECT-PREBREAKOUT-1` | State Reflection | Low | Inspection inputs sizing resolution disparity in Pullback mode (`portfolioValue` vs `scanSizingFromRisk`). | Update `inspectionInputs` in Pullback mode to call `scanSizingFromRisk()`. |
| `DEFECT-PREBREAKOUT-2` | Run Tracking | Low | Asynchronous `run_id` capture latency in Pre-Breakout / Fib scan metadata callback. | Return `run_id` synchronously in the response envelope. |
| `DEFECT-PREBREAKOUT-3` | Feature Limitation | Info | Setup-origin candidate chart backtest hydration unsupported for Pre-Breakout and Fib setups. | Natively tracked under Issue #391 (`SETUP-BACKTEST-CHART`). |

---

## 9. Verification Test Evidence

### 9.1 Backend Test Execution
All 62 backend test cases passed cleanly with Python 3.11:
- `backend/tests/test_audit_prebreakout_lane_e.py` (5 passed)
  - `test_breakout_confidence_breakdown_without_fib` (verifies 30/25/45 weights summing to 100%)
  - `test_breakout_confidence_breakdown_with_fib` (verifies 24/20/36/20 weights summing to 100%)
  - `test_atr_series_true_range_sma14_calculation` (pins 14-period SMA of True Range)
  - `test_fibonacci_confidence_formula_bounds_and_tolerance` (pins 0/60/100 bounds and tolerance scaling)
  - `test_prebreakout_and_fib_scan_endpoints_dispatch_parity` (pins `/api/scan/prebreakout` and `/api/scan/fib-pullback` parameter validation)
- Existing suites:
  - `test_prebreakout_params.py` (2 passed)
  - `test_prebreakout_universe.py` (10 passed)
  - `test_fib_pullback_endpoint.py` (14 passed)
  - `test_fibonacci_signal.py` (7 passed)
  - `test_strategy_engine_fib.py` (9 passed)
  - `test_stock_pres_p1_prebreakout_evidence.py` (15 passed)

### 9.2 Frontend Test Execution
All 143 frontend test cases passed cleanly with Jest:
- `frontend/app/(frame)/screener/step-4-prebreakout/__tests__/auditPrebreakoutLaneE.test.ts` (7 passed)
  - Integer parameter truncation (`truncPreBreakoutInts`, `truncFibInts`)
  - Snapshot threshold immutability on parameter slider adjustment
  - Candidate chart URL construction for `prebreakout`, `fib`, and `pullback`
  - Setup chart price lines isolation (swing/fib levels only; no entry/stop lines)
  - Request token race condition invalidation
- Existing suites:
  - `PreBreakoutIdentityClick.test.tsx` (8 passed)
  - `chartActions.test.tsx` (7 passed)
  - `filterBreakdown.test.tsx` (6 passed)
  - `modeEvidence.test.tsx` (15 passed)
  - `presentationShell.test.tsx` (12 passed)
  - `CandidateChartWorkspace.test.tsx` (18 passed)
  - `useOriginalBacktest.test.ts` (14 passed)
  - Additional prebreakout component tests (56 passed)

### 9.3 Typecheck Verification
`npm run typecheck` (`tsc --noEmit`) passes with zero errors.

### 9.4 State Integrity
`python scripts/state.py` verified with zero drift.

---

## 10. Conclusion & Handoff

Lane E audit of Step 4 Pre-Breakout is complete and mathematically reconciled. All setup detection algorithms, confidence scoring formulas, snapshot isolation mechanisms, and candidate chart handoff contracts have been rigorously verified against real backend and frontend code.
The audit artifacts (`report.md`, `defects.json`, `provenance.json`) are finalized and ready for independent adversarial Code Audit Round 1.
