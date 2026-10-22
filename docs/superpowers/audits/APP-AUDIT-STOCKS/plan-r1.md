# Adversarial Audit Report: `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md`

**Auditor:** Independent Subagent `549c7cdb-7845-4b88-97fb-881c00a06343` (bmad-review-adversarial-general)  
**Target:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md` (APP-AUDIT-STOCKS, Issue #352)  
**Round:** Plan Round 1  
**Gate Findings:** 7  

---

## Gate Findings

### FINDING-1
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:128-133`, `176`
- **Concrete Failing Scenario:**  
  The plan asserts the position sizing formula as:
  $$\text{Risk per Share} = |\text{Entry Price} - \text{Stop Price}|$$
  $$\text{Risk Shares} = \left\lfloor \frac{\text{Account Size} \times \text{Risk Pct}}{\text{Risk per Share}} \right\rfloor$$
  $$\text{Max Shares} = \left\lfloor \frac{\text{Max Capital}}{\text{Entry Price}} \right\rfloor$$
  $$\text{Final Shares} = \min(\text{Risk Shares}, \text{Max Shares})$$
  Scenario: Account Size = $100,000, Risk Pct = 1% ($1,000 risk), Entry Price = $200.00, Stop Price = $198.00 ($\text{Risk per Share} = \$2.00$). The portfolio single-position cap is 5% ($5,000 max capital).
  - In production (`backend/app/routers/stock_scan.py:_position_size` and `StockPositionCard/index.tsx:69-83` under decision `SHARE-SIZING-CONCENTRATION-FLAG-2026-09-09`):  
    $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Dollar Risk}}{\text{Risk per Share}} + 10^{-9} \right\rfloor\right) = 500\text{ shares}$$
    The UI flags the $100,000 position against the $5,000 cap (`concentrationFlag`), but **never clamps** `recommendedShares`.
  - Under the plan's formula:  
    $$\text{Max Shares} = \lfloor 5000 / 200 \rfloor = 25\text{ shares}$$
    $$\text{Final Shares} = \min(500, 25) = 25\text{ shares}$$
  If a test harness or implementer acts on the plan's formula, the share quantity calculated and placed on broker orders becomes 25 shares instead of 500 shares (a 20-fold truncation on order quantity). In addition, the plan omits the conviction multiplier `mult` (`sized_risk_pct = _base_pct * mult`) and the `max(1, ...)` floor.
- **Why it meets the gate:**  
  Misstates the share sizing formula. Acting on it places wrong share counts on broker orders and miscalculates trade sizing.
- **Suggested Fix:**  
  Update lines 128-133 to state the true production formula:
  $$\text{Risk per Share} = |\text{Entry Price} - \text{Stop Price}|$$
  $$\text{Dollar Risk} = \text{Account Size} \times (\text{Risk Pct} \times \text{conviction\_mult})$$
  $$\text{Shares} = \max\left(1, \left\lfloor \frac{\text{Dollar Risk}}{\text{Risk per Share}} + 10^{-9} \right\rfloor\right)$$
  Explicitly document that single-position concentration flags in the UI without clamping `recommendedShares` or `Final Shares`.

---

### FINDING-2
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:71-74`, `166`
- **Concrete Failing Scenario:**  
  The plan asserts:
  $$S = \text{round}\left(w_{\text{trend}} S_{\text{trend}} + w_{\text{pullback}} S_{\text{pullback}} + w_{\text{trigger}} S_{\text{trigger}} + w_{\text{event}} S_{\text{event}} + w_{\text{vol}} S_{\text{vol}}\right)$$
  "Audit event absence weight renormalization: when upcoming earnings/dividends are absent or outside the event window, verify that non-event weights ($w_{\text{trend}}, w_{\text{pullback}}, w_{\text{trigger}}, w_{\text{vol}}$) re-scale proportionally so they sum to 1.0."  
  Scenario: A stock has earnings in 5 days (inside the event window). In `_rule_event`, $S_{\text{event}} = 5$. Sub-scores: Trend=80, Pullback=80, Trigger=80, Vol=80. Configured weights in `scoring_rules.yaml`: Trend 0.35, Pullback 0.25, Trigger 0.15, Event 0.10, Vol 0.15.
  - In production (`backend/app/scoring/stock_scorer.py:1223-1231` with `scoring_mode == "stock"`):  
    Event weight is **unconditionally** set to 0.0, and non-event weights are always renormalized to sum to 1.0 ($w_i / 0.90$). The event score $S_{\text{event}} = 5$ has zero impact on the composite score:
    $$S = \text{round}(80) = 80 \implies \text{PASS}$$
  - Under the plan:  
    Because an event date is present inside the window, the plan states renormalization does not occur and $w_{\text{event}} S_{\text{event}}$ is included:
    $$S = \text{round}(0.35(80) + 0.25(80) + 0.15(80) + 0.10(5) + 0.15(80)) = \text{round}(72.5) = 73$$
  The candidate receives a score of 73 instead of 80. Near threshold boundaries (e.g. 55), this formula error demotes passing candidates to CAUTION or REJECT.
- **Why it meets the gate:**  
  Misstates the stock-mode scoring algorithm. Acting on it calculates wrong composite stock scores and wrong rankings for any symbol with an upcoming earnings or dividend date.
- **Suggested Fix:**  
  Clarify in lines 71-74 and 166 that in stock mode (`scoring_mode="stock"`), $w_{\text{event}}$ is unconditionally zeroed and non-event weights are always renormalized to sum to 1.0. Event proximity is displayed for informational context and earnings veto gating only, and never contributes points to `final_score`.

---

### FINDING-3
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:89`
- **Concrete Failing Scenario:**  
  The plan asserts:
  "When enabled for Swing/Position horizons, verify status caps: FundamentalHealth $< 40$ caps at CAUTION, $< 20$ caps at REJECT, and Debt-to-Equity $> 3.0$ triggers extreme_leverage cap."  
  Scenario A: A Bullish candidate has `FundamentalHealth = 42` and raw score 80 (`PASS`).
  - Production code (`scoring_rules.yaml:454-460` and `stock_scorer.py:1301-1318`): `cautionBelow: 45` and `rejectBelow: 30`. Since $42 < 45$, status caps at `CAUTION`.
  - Under plan assertions: $42 \ge 40$, so the plan asserts it should `PASS`.
  Scenario B: A Bullish candidate has `FundamentalHealth = 25`.
  - Production code: $25 < 30$ (`rejectBelow`), so status caps at `REJECT`.
  - Under plan assertions: $25 \ge 20$, so the plan asserts it should only cap at `CAUTION`.
  Scenario C: Bearish scans (`stock_scorer.py:1319-1329`).
  - Production code enforces inverted fundamentals gates: `cautionAbove: 70`, `rejectAbove: 80` ("don't short strong companies"). A short candidate with `FundamentalHealth = 85` is capped at `REJECT`. The plan omits Bearish fundamentals logic entirely.
  Scenario D: Extreme leverage threshold in `fundamentals_scorer.py:229` is `snap.debt_to_equity >= safety_cfg.get("debt_to_equity_reject", 3.0)` (inclusive $\ge 3.0$, not $> 3.0$), and the plan omits the `negative_equity` safety flag (`stockholders_eq < 0`).
- **Why it meets the gate:**  
  Misstates the numerical thresholds and directional logic of the Fundamentals Gate, causing test harnesses and reviewers to accept wrong status verdicts (`PASS` instead of `CAUTION`, `CAUTION` instead of `REJECT`).
- **Suggested Fix:**  
  Update line 89 to reflect `scoring_rules.yaml` defaults:
  - Bullish: `cautionBelow: 45` caps at `CAUTION`, `rejectBelow: 30` caps at `REJECT`.
  - Bearish: `cautionAbove: 70` caps at `CAUTION`, `rejectAbove: 80` caps at `REJECT`.
  - Safety flags: `debt_to_equity >= 3.0` (`extreme_leverage`) and `stockholders_eq < 0` (`negative_equity`) trigger `REJECT` across both directions.

---

### FINDING-4
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:87`
- **Concrete Failing Scenario:**  
  The plan asserts:
  "2. **Confidence Gate:** When confidence_gate is enabled, verify status cap based on signal backtest win rate: win rate below caution_below caps at CAUTION; below reject_below caps at REJECT."  
  Scenario: A candidate has a backtest win rate of 60% (`win_rate = 0.60`), but historical excursion replay yields integer `confidence = 40`. Gate thresholds in `scoring_rules.yaml`: `cautionBelow: 50`, `rejectBelow: 35`.
  - In production (`stock_scorer.py:1260-1278` and `signal_confidence.py:175-191`):  
    `status_cap(confidence, confidence_gate)` compares the integer `confidence` (40 vs 50) and caps status at `CAUTION`.
  - Under the plan's instruction:  
    The gate is asserted to evaluate "signal backtest win rate". Comparing `win_rate` (a float $\le 1.0$) against integer thresholds 35 and 50 results in $0.60 < 35 \implies \text{REJECT}$ on every single candidate. If scaled to percentage (60%), $60 \ge 50 \implies \text{PASS}$, failing to apply the caution cap.
- **Why it meets the gate:**  
  Misstates the gate's input and mechanism. A reader acting on it will write verification checks comparing the wrong metric (`win_rate` instead of `confidence`), leading to false rejections or missed demotions.
- **Suggested Fix:**  
  Reword line 87:
  "Confidence Gate: When `confidence_gate` is enabled, verify status cap based on forward-replay `confidence` score (0–100 integer): `confidence < cautionBelow` caps at `CAUTION`; `< rejectBelow` caps at `REJECT`; `confidence is None` (unvalidated / sample size < min_samples) unconditionally caps at `CAUTION`."

---

### FINDING-5
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:44`, `124`
- **Concrete Failing Scenario:**  
  The plan asserts the endpoint for loading candidate backtest artifacts is:
  `GET /api/backtest-artifacts/{id}`
  Scenario: An automated audit script or client requests an artifact by ID without a `symbol` query parameter: `client.get(f"/api/backtest-artifacts/{artifact_id}")`.
  - In production (`backend/app/routers/backtest_artifacts.py:26-28` and `frontend/lib/api.ts:258-261`):  
    The route definition is:
    ```python
    @router.get('/{artifact_id}')
    async def get_original_artifact(artifact_id: UUID, symbol: str = Query(pattern=r'^[A-Z][A-Z0-9.\-^]{0,14}$'), db: AsyncSession = Depends(get_db)):
    ```
    The query parameter `symbol` is required. The call fails immediately with HTTP 422 Unprocessable Entity (`[{"loc":["query","symbol"],"msg":"Field required","type":"missing"}]`).
- **Why it meets the gate:**  
  Misstates the API contract. Following the plan causes artifact retrieval to fail with HTTP 422, breaking Step 6 Backtest Inspector verification.
- **Suggested Fix:**  
  Update lines 44 and 124 to specify `GET /api/backtest-artifacts/{artifact_id}?symbol={symbol}` matching the router signature and `api.getOriginalBacktest`.

---

### FINDING-6
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:93-100`
- **Concrete Failing Scenario:**  
  The plan lists the 7 exposed primary strategies in `strategy_engine.py` as:
  1. `pullback_ema_signal`
  2. `breakout_base_signal`
  3. `ma_crossover_signal`
  4. `mean_reversion_rsi_signal`
  5. `mean_reversion_bb_signal`
  6. `mean_reversion_vwap_signal`
  7. `mean_reversion_vwap_daily_signal`  
  Scenario: A scan request is constructed with `strategy: "mean_reversion_vwap_daily"`.
  - In production (`backend/app/schemas/stock_scan.py:10` and `frontend/app/(frame)/screener/step-4-stocks/page.tsx:28-50`):  
    The schema defines:
    `Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap", "mean_reversion_multi"]`  
    The value `"mean_reversion_vwap_daily"` is an internal helper signal function used inside `mean_reversion_multi`; it is not a valid strategy literal and Pydantic raises HTTP 422 ValidationError. The actual 7th exposed primary strategy is `"mean_reversion_multi"`.
- **Why it meets the gate:**  
  Misstates the strategy enum and schema contract, causing HTTP 422 scan failures while leaving the primary multi-signal strategy (`mean_reversion_multi`) omitted from primary strategy verification.
- **Suggested Fix:**  
  Update lines 93-100 to list the 7 exposed primary strategies: `pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_vwap`, and `mean_reversion_multi`, noting that `mean_reversion_vwap_daily` is an internal variant executed within `mean_reversion_multi`.

---

### FINDING-7
- **File & Line:** `docs/superpowers/plans/2026-10-22-app-audit-stocks-plan.md:44`, `115`
- **Concrete Failing Scenario:**  
  The plan asserts:
  - Line 44: "Displays candidate backtest metrics (win rate, expectancy, total return, profit factor, max drawdown)..."
  - Line 115:
    $$\text{Profit Factor} = \frac{\sum \text{Gains}}{\sum \text{Losses}}$$
  Scenario: A test harness or inspector parses `candidate.backtest` or `BacktestOut` looking for `profit_factor`.
  - In production (`backend/app/schemas/stock_scan.py:142-159`, `strategy_backtest.py:64-75`, and `frontend/app/(frame)/screener/step-6-backtest/page.tsx:74-97`):  
    `BacktestOut` and `BacktestResult` do not contain `profit_factor`. The metrics are: `n_trades`, `win_rate`, `total_return_pct`, `max_drawdown_pct`, `expectancy`, `sharpe`, `n_time_exits`, and `hold_max_days`.
  A reader acting on this will write test assertions expecting `profit_factor` or alter schemas to add an unvetted field, breaking type contracts.
- **Why it meets the gate:**  
  Misstates the backtest schema and calculations.
- **Suggested Fix:**  
  Remove `profit factor` from lines 44 and 115, and assert the actual schema fields: `win_rate`, `expectancy`, `total_return_pct`, `max_drawdown_pct`, `sharpe`, and `n_time_exits`.
