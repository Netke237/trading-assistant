# APP-AUDIT-PREBREAKOUT — Plan Audit Round 1

- **Date**: 2026-10-21
- **Reviewer**: Subagent `c0141f78-6cb4-45d1-8fcd-c434ab7deaa2` (independent adversarial auditor)
- **Target**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md`
- **Branch**: `board/app-audit-prebreakout-b4f0d823` in `.worktrees/app-audit-prebreakout`
- **Skill**: `bmad-review-adversarial-general`
- **Result**: **11 Gate Findings (NOT CLEAN)**

---

## Executive Summary

The plan for phase `APP-AUDIT-PREBREAKOUT` (#353) lays out comprehensive structural coverage across the Step 4 Pre-Breakout surfaces, but contains critical inaccuracies regarding API endpoint paths, confidence scoring weights, parameter panel defaults, ATR calculation mechanisms, chart line overlay semantics, and endpoint query contracts. Under the Numeric & Persistence Gate, these misstatements block because any reader or verification test acting on them would produce wrong numbers, fail API routes with 404 or 422 errors, or alter core strategy and presentation mechanisms.

---

## Findings

### F-1: Pre-Breakout confidence weights misstated (35% / 25% / 40% vs 30% / 25% / 45%)
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:48-49` (Section 2.A) and `line 118` (Section 3, Task 1)
- **trigger_condition**: The plan asserts Pre-Breakout confidence breakdown components are ATR compression (35%), volume compression (25%), and resistance proximity (40%).
- **guard_snippet**: In `backend/app/services/strategy_engine.py:1603-1652`, the authoritative base weights are:
  - ATR compression: **30%** (`0.30`)
  - Volume compression: **25%** (`0.25`)
  - Resistance proximity: **45%** (`0.45`)
  When Fib is enabled (`fib_enabled=True`), the weights scale to:
  - ATR compression: **24%** (`0.24`)
  - Volume compression: **20%** (`0.20`)
  - Resistance proximity: **36%** (`0.36`)
  - Fibonacci retracement score: **20%** (`0.20`)
  Update Section 2.A and Task 1 to cite the exact 30/25/45 base weights and the 24/20/36/20 Fib-enabled weights.
- **potential_consequence**: Independent derivation tests or score verifications will calculate wrong confidence values and flag valid backend candidates as failing confidence arithmetic.

---

### F-2: Pre-Breakout scanner endpoint misstated as `POST /api/stock-scan/prebreakout`
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:41` (Section 2.A)
- **trigger_condition**: The plan asserts the API endpoint is `POST /api/stock-scan/prebreakout`.
- **guard_snippet**: In `backend/app/routers/stock_scan.py:187, 2319` (`prefix="/api"`, `@router.post("/scan/prebreakout")`) and `frontend/lib/api.ts:946`, the route is:
  `POST /api/scan/prebreakout`
  (`POST /api/stock-scan/prebreakout` does not exist).
- **potential_consequence**: Direct endpoint probes or integration tests fail with HTTP 404 Not Found.

---

### F-3: Fibonacci pullback scanner endpoint misstated as `POST /api/stock-scan/fibonacci`
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:58` (Section 2.B)
- **trigger_condition**: The plan asserts the Fibonacci scan endpoint is `POST /api/stock-scan/fibonacci`.
- **guard_snippet**: In `backend/app/routers/stock_scan.py:187, 2159` (`prefix="/api"`, `@router.post("/scan/fib-pullback")`) and `frontend/lib/api.ts:959`, the route is:
  `POST /api/scan/fib-pullback`
  (`POST /api/stock-scan/fibonacci` does not exist).
- **potential_consequence**: Direct endpoint probes or integration tests fail with HTTP 404 Not Found.

---

### F-4: `PreBreakoutParamsPanel` parameter defaults and slider ranges misstated
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:33-40` (Section 2.A)
- **trigger_condition**: The plan asserts `PREBREAKOUT_DEFAULTS` has `atrCompressionRatio: 0.75` (range 0.1–2.0), `atrAvgLookback: 50` (range 20–200), `rangeAtrMult: 3.0` (range 1.0–10.0), `volCompressionRatio: 0.80` (range 0.1–2.0), `resistanceProximityPct: 0.03` (range 0.005–0.10), and `swingLookback: 20` (range 10–60).
- **guard_snippet**: In `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx:6-24, 58-185` and `backend/config/strategy_params.yaml:603-618`:
  - `atrCompressionRatio`: default **0.85**, range `0.1–1.0`, step `0.05`
  - `atrAvgLookback`: default **20**, range `5–50`, step `1`
  - `rangeAtrMult`: default **3.0**, range `0.1–5.0`, step `0.1`
  - `rangeLookbackBars`: default **10**, range `3–30`, step `1`
  - `volCompressionRatio`: default **0.90**, range `0.1–1.0`, step `0.05`
  - `resistanceProximityPct`: default **0.08** (8%), range `0.01–0.20` (1%–20%), step `0.005` (0.5%)
  - `swingLookback`: default **50**, range `10–100`, step `5`
  Update Section 2.A to reflect these exact values.
- **potential_consequence**: Automated parameter verification and reset-to-defaults tests fail; audit asserts wrong user-facing values.

---

### F-5: `FibPullbackParamsPanel` parameter defaults and slider ranges misstated
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:53-57` (Section 2.B)
- **trigger_condition**: The plan asserts `FIB_PULLBACK_DEFAULTS` has `fibSwingLookback: 50` (min 10), `fibLevels: [38.2, 50.0, 61.8]`, `fibTolerancePct: 0.02` (range 0 < tol <= 0.20), and `emaFilterPeriod: 50`.
- **guard_snippet**: In `frontend/components/organisms/FibPullbackParamsPanel/index.tsx:6-20, 74-118` and `backend/app/routers/stock_scan.py:2142-2149` (`_FIB_DEFAULTS`):
  - `fibSwingLookback`: default **100**, range `20–200`, step `5` (backend min 10)
  - `fibLevels`: default **`[38.2, 61.8]`** (subset of allowed `[23.6, 38.2, 50.0, 61.8, 78.6]`)
  - `fibTolerancePct`: default **0.015** (1.5%), UI slider range `0.005–0.050` (0.5%–5.0%), step `0.001` (0.1%); backend override limit is `0 < tol <= 0.20`
  - `emaFilterPeriod`: default **20**, range `0–200`, step `1` (0 disables)
  Update Section 2.B to reflect the actual defaults and distinguish the UI input range from the backend validation bound.
- **potential_consequence**: UI default state and slider boundary assertions will fail; tests assert 50.0% is checked by default when only 38.2% and 61.8% are enabled.

---

### F-6: ATR calculation mechanism misstated as Wilder ATR instead of Simple Moving Average of True Range
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:43` (Section 2.A) and `line 117` (Section 3, Task 1)
- **trigger_condition**: The plan specifies: "ATR calculation: 14-period Wilder ATR compared against N-period SMA of ATR (atr_avg_lookback)" and tasks an independent derivation of Wilder ATR(14).
- **guard_snippet**: In `backend/app/services/strategy_engine.py:95-104`, `_atr_series(bars, period=14)` computes a rolling **Simple Moving Average (SMA)** of True Range:
  `window = trs[max(0, i - period + 1): i + 1]; result.append(sum(window) / len(window))`
  It does NOT use Wilder's exponential smoothing (`(prior * 13 + current) / 14`), which is explicitly distinguished in `backend/app/routers/stock_scan.py:56-58` from `stock_scorer.py:_atr`.
- **potential_consequence**: An auditor or developer verifying against Wilder ATR(14) will observe mathematical divergence and conclude there is an algorithmic defect, or rewrite the calculation to Wilder ATR, breaking baseline scan output.

---

### F-7: `SelectedSetupChart` price lines asserted to plot nonexistent ATR bands and stop/entry levels
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:83` (Section 2.D)
- **trigger_condition**: The plan asserts `scanChartLines` plots "Swing level, ATR band, Fib retracement levels, stop/entry levels".
- **guard_snippet**: In `frontend/app/(frame)/screener/step-4-prebreakout/scanChartLines.ts:1-41`, `scanChartLines` explicitly states:
  *"These are returned setup evidence, never entry, stop or target prices."*
  It plots only:
  - `Scan swing high` / `Scan swing low` (`row.metrics.swing_level`)
  - `Scan swing low` / `Scan swing high` or `Scan Fib swing low` / `Scan Fib swing high` (`row.fib_swing`)
  - `Scan Fib {lvl}%` (`fibLevelPrice`)
  For Pullback mode, it returns `[]`. It contains NO ATR bands and NO stop/entry levels. Update line 83 to reflect exact setup-only price lines.
- **potential_consequence**: Misstates mechanism, causing an auditor or implementer to claim stop/entry lines or ATR bands are missing from setup charts, violating the architectural isolation between setup evidence and trade execution levels.

---

### F-8: Pullback vectorised backtest runner function misnamed as `run_stock_backtest`
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:72` (Section 2.C)
- **trigger_condition**: The plan asserts backtest execution runs via `run_stock_backtest`.
- **guard_snippet**: In `backend/app/routers/stock_scan.py:74, 831, 1112`, the backtest engine is `run_strategy_backtest` from `backend/app/services/strategy_backtest.py`. There is no `run_stock_backtest` function in the codebase.
- **potential_consequence**: Automated audit scripts or developers referencing `run_stock_backtest` will encounter `ImportError` or `AttributeError`.

---

### F-9: Fibonacci confidence formula boundary condition for missing distance omitted
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:63-65` (Section 2.B)
- **trigger_condition**: The plan specifies the confidence formula only for `dist_pct <= tolerance` and `dist_pct > tolerance`, omitting the `None` case.
- **guard_snippet**: In `backend/app/routers/stock_scan.py:2288-2295`, `dist_pct` is `None` whenever impulse or recency checks fail in `_fibonacci_pullback_detail`, in which case:
  `if dist_pct is None: confidence = 0`
  Furthermore, `dist_pct` is in percentage units and is normalized by `tol = scan_params["fib_tolerance_pct"] * 100`. Update lines 63-65 to include the `dist_pct is None -> 0` branch and explicit unit scaling.
- **potential_consequence**: Direct evaluation of plan formulas on setup failures causes `TypeError: '<=' not supported between instances of 'NoneType' and 'float'`.

---

### F-10: Artifact fetch endpoint specification in Candidate Chart handoff omits mandatory `symbol` query parameter
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:102` (Section 2.E)
- **trigger_condition**: The plan specifies artifact hydration as `GET /api/backtest-artifacts/{id}`.
- **guard_snippet**: In `backend/app/routers/backtest_artifacts.py:26-28` and `frontend/lib/api.ts:430`, the route requires the `symbol` query parameter:
  `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`
  FastAPI strictly validates `symbol: str = Query(...)` and returns HTTP 422 if omitted. Update line 102 to include `?symbol={symbol}`.
- **potential_consequence**: Verifications fetching artifacts according to the plan contract receive HTTP 422 Unprocessable Entity.

---

### F-11: Snapshot integer truncation mechanism omitted from state verification
- **location**: `docs/superpowers/plans/2026-10-21-app-audit-prebreakout-plan.md:78-80` (Section 2.D) and `lines 123-128` (Section 3, Task 2)
- **trigger_condition**: The plan covers snapshot isolation but omits verifying that integer parameters are truncated before snapshot storage.
- **guard_snippet**: In `frontend/app/(frame)/screener/step-4-prebreakout/scanThresholds.ts:8-25` and `page.tsx:146`, `truncPreBreakoutInts` (`atrAvgLookback`, `rangeLookbackBars`, `swingLookback`) and `truncFibInts` (`fibSwingLookback`, `emaFilterPeriod`) apply `Math.trunc` to mirror backend `int()` coercion (`stock_scan.py:2201, 2361`). Add a verification item to Task 2 pinning integer truncation.
- **potential_consequence**: Fractional inputs on integer fields could cause snapshot display to diverge from backend integer evaluation without failing the audit.

---

## Required Plan Changes for Round 2

1. **Update Section 2.A (Pre-Breakout)**:
   - Correct `PREBREAKOUT_DEFAULTS` and slider ranges (ATR ratio 0.85, ATR lookback 20, range mult 3.0, range lookback 10, vol ratio 0.90, proximity 0.08 [8%], swing lookback 50).
   - Correct endpoint to `POST /api/scan/prebreakout`.
   - Specify ATR calculation as 14-period SMA of True Range via `_atr_series`, distinguishing from `stock_scorer.py:_atr`.
   - Correct base confidence weights to ATR 30%, Vol 25%, Proximity 45% (and 24/20/36/20 when Fib enabled).
2. **Update Section 2.B (Fibonacci)**:
   - Correct `FIB_PULLBACK_DEFAULTS` (lookback 100, levels `[38.2, 61.8]`, tolerance 0.015 [1.5%], EMA period 20).
   - Correct endpoint to `POST /api/scan/fib-pullback`.
   - Specify `dist_pct is None -> confidence = 0` and scaling by `tol = fib_tolerance_pct * 100`.
3. **Update Section 2.C (Pullback)**:
   - Correct backtest runner function to `run_strategy_backtest`.
4. **Update Section 2.D (Setup Evidence & Chart)**:
   - Update `scanChartLines` description to swing and Fib levels only; remove mentions of ATR bands and entry/stop levels.
   - Add integer parameter truncation via `truncPreBreakoutInts` and `truncFibInts` to snapshot verification.
5. **Update Section 2.E (Candidate Chart Handoff)**:
   - Specify artifact hydration endpoint with query parameter: `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`.
6. **Update Section 3 (Tasks)**:
   - Update Task 1 formula verification to 30/25/45 weights and True Range SMA(14).
   - Add snapshot integer truncation check to Task 2.
