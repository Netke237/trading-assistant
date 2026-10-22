# Adversarial Audit Report (Round 2): `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md`

**Auditor:** Independent Subagent `83a7d04f-2827-4d7b-9249-042b0e74140f` (bmad-review-adversarial-general)  
**Target:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md` (APP-AUDIT-STOCKS, Issue #352)  
**Round:** Plan Round 2  
**Gate Findings:** 0  

---

## 1. Review of Round 1 Fixes

### Fix 1 (FINDING-1): Position Sizing Formula & UI Concentration Flag
- **Plan Locations:** Section 3 Task 5 (lines 138–144) & Section 4 Item 4 (line 186)
- **Verified Against:** `backend/app/routers/stock_scan.py:1382-1397`, `1700-1725`, and `frontend/components/organisms/StockPositionCard/index.tsx:69-97`, `1379-1400`.
- **Verification Details:**
  The plan now accurately states the production formula:
  $$\text{Risk per Share} = |\text{Entry Price} - \text{Stop Price}|$$
  $$\text{Dollar Risk} = \text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})$$
  $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Dollar Risk}}{\text{Risk per Share}} + 10^{-9} \right\rfloor\right)$$
  The plan explicitly documents that single-position concentration flags in the UI under decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09` without clamping `recommendedShares` or broker order quantities. Zero-dollar and boundary protections (`entry == stop`, non-positive prices) are correctly specified.
- **Status:** **CLEAN** — No gate defect.

---

### Fix 2 (FINDING-2): Stock-Mode Event Exclusion & Weight Renormalization
- **Plan Locations:** Section 3 Task 2 (lines 71–76) & Section 4 Item 1 (line 176)
- **Verified Against:** `backend/app/scoring/stock_scorer.py:1223-1241`.
- **Verification Details:**
  The plan now correctly documents that in stock mode (`scoring_mode == "stock"`), event weight is unconditionally zeroed ($w_{\text{event}} = 0.0$) and non-event weights ($w_{\text{trend}}, w_{\text{pullback}}, w_{\text{trigger}}, w_{\text{vol}}$) are proportionally renormalized so they sum to 1.0. Upcoming earnings/dividend proximity is retained purely for display and the pipeline earnings veto gate, contributing zero points to `final_score`.
- **Status:** **CLEAN** — No gate defect.

---

### Fix 3 (FINDING-3): Fundamentals Gate Directional Thresholds & Safety Flags
- **Plan Locations:** Section 3 Task 2 (lines 94–98) & Section 4 Item 1 (line 178)
- **Verified Against:** `backend/config/scoring_rules.yaml:454-460`, `backend/app/scoring/stock_scorer.py:1293-1342`, and `backend/app/scoring/fundamentals_scorer.py:220-231`.
- **Verification Details:**
  The plan has been updated to reflect the true defaults and directional logic:
  - Bullish: `cautionBelow: 45` caps at `CAUTION`, `rejectBelow: 30` caps at `REJECT`.
  - Bearish: `cautionAbove: 70` caps at `CAUTION`, `rejectAbove: 80` caps at `REJECT`.
  - Safety flags: `debt_to_equity >= 3.0` (`extreme_leverage`) and `stockholders_eq < 0` (`negative_equity`) trigger `REJECT` across both directions.
  - Intraday scans remain strictly exempt from the fundamentals gate (`is_intraday`).
- **Status:** **CLEAN** — No gate defect.

---

### Fix 4 (FINDING-4): Confidence Gate Evaluation of Integer Confidence Score
- **Plan Locations:** Section 3 Task 2 (lines 89–92) & Section 4 Item 1 (line 178)
- **Verified Against:** `backend/app/scoring/signal_confidence.py:175-191` and `backend/app/scoring/stock_scorer.py:1260-1278`.
- **Verification Details:**
  The plan now specifies that the confidence gate evaluates the forward-replay integer `confidence` score (0–100) rather than float `win_rate`:
  - `confidence < cautionBelow` (default 50) caps status at `CAUTION`.
  - `confidence < rejectBelow` (default 35) caps status at `REJECT`.
  - `confidence is None` (unvalidated / sample size < min_samples) unconditionally caps status at `CAUTION`.
- **Status:** **CLEAN** — No gate defect.

---

### Fix 5 (FINDING-5): Backtest Artifact Endpoint Signature
- **Plan Locations:** Section 2 (line 44), Section 3 Task 4 (line 133), Section 4 Item 3 (line 185)
- **Verified Against:** `backend/app/routers/backtest_artifacts.py:26-28` and `frontend/lib/api.ts:429-436`.
- **Verification Details:**
  The artifact retrieval endpoint has been updated to `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}`, including the required `symbol` query parameter matching the backend FastAPI route definition and client API wrapper.
- **Status:** **CLEAN** — No gate defect.

---

### Fix 6 (FINDING-6): 7 Exposed Primary Strategies Alignment with Schema
- **Plan Locations:** Section 3 Task 3 (lines 101–109) & Section 4 Item 2 (line 180)
- **Verified Against:** `backend/app/schemas/stock_scan.py:10`, `backend/app/services/strategy_engine.py`, and `frontend/app/(frame)/screener/step-4-stocks/page.tsx:49-65`.
- **Verification Details:**
  The plan aligns with the `Strategy` enum literal:
  1. `pullback_ema`
  2. `breakout_base`
  3. `ma_crossover`
  4. `mean_reversion_rsi`
  5. `mean_reversion_bb`
  6. `mean_reversion_vwap`
  7. `mean_reversion_multi`
  `mean_reversion_vwap_daily_signal` is correctly documented as an internal helper combined within `mean_reversion_multi`.
- **Status:** **CLEAN** — No gate defect.

---

### Fix 7 (FINDING-7): BacktestOut Schema Fields & Metric Parity
- **Plan Locations:** Section 2 (line 44), Section 3 Task 4 (lines 120–125), Section 4 Item 3 (line 183)
- **Verified Against:** `backend/app/schemas/stock_scan.py:142-159`, `backend/app/services/strategy_backtest.py:425-430`, and `frontend/app/(frame)/screener/step-6-backtest/page.tsx:74-97`.
- **Verification Details:**
  The non-existent field `profit_factor` has been completely excised. Assertions are now pinned to the real schema fields: `n_trades`, `win_rate`, `expectancy`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, `n_time_exits`, and `hold_max_days`.
- **Status:** **CLEAN** — No gate defect.

---

## 2. Interaction & Regression Checks

1. **Sizing vs Gates Interaction:**  
   Verified that regime conviction multiplier (`conviction_mult`) scales risk budget without overriding the share floor `max(1, ...)` or mutating `risk_pct` storage. Verified that status caps (confidence, regime, fundamentals) govern candidate visibility and card status without altering share sizing mathematics.
2. **Scorer Weighting vs Demotion Monotonicity:**  
   Verified that zeroing event weight and renormalizing non-event weights produces a deterministic raw score and status, which is strictly demoted (never promoted) by the 4-tier gate hierarchy.
3. **Strategy Engine vs Backtest Execution:**  
   Verified that `mean_reversion_multi` correctly executes multi-variant confirmation logic across RSI, Bollinger Bands, and rolling daily VWAP, generating trade records consistent with `BacktestOut`.
4. **State Consistency:**  
   Ran `python scripts/state.py`; verified zero drift across project state registrations.

---

GATE FINDINGS: 0
