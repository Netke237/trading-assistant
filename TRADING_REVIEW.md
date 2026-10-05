# Bamendjou Trading Review

**Date**: 2026-10-04 · **Commit**: `e4d4d80e` (`main`, clean tree) · **Mode**: A — full review
**Method**: k-trading-software-reviewer (three-voice panel + Chair). Scope confirmed with Kenneth before starting: full review.

## Overall: **REJECT**

> "The Phase A fixes are real and they hold: the tuner grades the right trade, earnings veto, the option premium cap is the loss limit, and the basket tells the truth. But this run finally had five years of data, and it says three hard things: the price history the backtests read is corrupt, the Swing score does not pick better trades than chance, and the per-symbol backtest gate picks noise. I would not put money behind it yet."

| Area | Grade | Why, in one line |
|---|---|---|
| 1. Edge & strategy logic | **REJECT** | On 5 years × 61 names the Swing score does not separate outcomes: PASS setups +0.140R vs every bar +0.135R vs REJECT +0.113R (CIs overlap). Every bearish strategy loses net |
| 2. Statistical evidence | **REJECT** | `get_bars` returns split/dividend-adjusted **closes** with **raw** open/high/low: 44% of scan-window bars have a close outside their own range; the backtest gate's verdict flips on 29 of 248 combos. The gate itself has no persistence (rank correlation −0.25…+0.05 between halves) |
| 3. Options & contract selection | **CAUTION** | Earnings now veto (fixed). Still open: long-hold presets hold through prints, spreads half-built, flat +8% target, R/R computed on a 60% loss basis while sizing assumes 100% |
| 4. Risk parameters & sizing | **CAUTION** | Option premium cap is now `min(5%, 3.75%)` (fixed). Still open: every % cap multiplies a client-typed account value; the daily-loss gate is in-memory, auto-only, spend not loss |
| 5. Execution safety | **CAUTION** | Basket honesty fixed. Still open: "market open" = "a price exists"; Stocks "After scan — fire when next scan PASS" also fires on CAUTION; no protective orders |

Overall = worst area = **REJECT**. Graded as if live: every broker key is paper today (`broker_router.py` refuses `*_live`, `routers/broker.py` `/status` shows them locked). That is said once here and is not counted as mitigation anywhere below.

---

## Since last run (2026-10-02, commit `0caf2661`, overall REJECT)

Phase A of the fix plan (`docs/superpowers/plans/2026-10-03-trading-review-fixes-plan.md`) merged on 2026-10-03 as PR #28 and follow-up PR #32. Every item below was re-checked against the code at `e4d4d80e`, not carried over.

**Fixed (re-verified)**
- **#1 WFO tuned the bearish branch for bullish.** `normalize_direction` (`strategy_backtest.py:16-29`) is applied in the engine (`:93`), the store (`strategy_param_store.py:113-114`), the optimizer (`strategy_param_optimizer.py:258`) and the adopt request, where `direction` is now required (`routers/strategy_tuning.py:26-33`). Fixed.
- **#2 WFO out-of-sample never ran.** Folds now carry a 260-bar warm-up prefix (`walk_forward.py:19, 144-160`) and score only bars inside the fold (`MIN_SCORED_BARS = 40`, `:22`); the first fold is warmed by a 14-month pre-fetch (`strategy_param_optimizer.py:19`). Confirmed by running the tuner on real data (see Quant Q3). Fixed — but see the two new cost findings in Q3.
- **#3 Earnings was a score, not a gate.** `_earnings_veto` and `_earnings_unknown_caps` cap `finalStatus` (`routers/scan.py:148-178, 1256-1264`); the auto-fire re-looks-up earnings with a source chain and per-source deadlines and refuses on an unknown date for a stock (`auto_trader.py:208-363`); Step 7 ages the scan's distance and blocks send/arm/fire (`frontend/lib/earningsGate.ts`). Fixed on those paths. Residuals below.
- **#4 Per-trade loss limit vs premium cap.** The option cap is `min(max_single_position_pct, max_loss_per_trade_pct)` = 3.75% (`portfolio_risk.py:181-192`), judged at the fill basis (`premium_cap_basis`, `:50-80`), and refuses a trade that does not fit one contract. The Portfolio save is a hard block when gates are on (`position_writer.py:489-501`). Fixed for long options.
- **#5 Basket said "sent to broker".** Rows are `source: 'manual'` (`step-7-trade-card/page.tsx:203-204`) and the toast reads "N added to Portfolio" (`:1754`); the dialog says "no broker order is placed" (`SendToBrokerDialog/index.tsx:162`). Fixed (tracked rows still reserve caps; deliberate, D6).

**Partly fixed / mechanism only**
- **#6 `pullback_ema` books tiny targets.** The skip-floor exists (`strategy_engine.py:512-519`) but ships at `min_signal_rr: 0.0` (`strategy_params.yaml`, D7). On 5 years × 61 names the consequence is now measured: median planned rung-1 R/R **0.60**, **74%** of signals below 1:1, pooled net expectancy **−0.075% per trade** over 1,468 bullish trades. Still open in consequence.

**Still open (re-verified at current lines)**
- #7 Server caps multiply the client's `portfolioValue` (`position_writer.py:497`; `schemas/__init__.py:1114` default 50,000; `routers/auto_trade.py:136` 50,000; YAML 100,000).
- #8 `_market_is_open` is a price-exists probe (`auto_trader.py:648-670`). Correction to the last report: the probe runs **before** the disarm (`:2586`), so a missing price preserves the arm; a stale price still passes, disarms and sends.
- #9 Daily-loss gate: premium spend, in-memory history (`auto_trader.py:591-595, 3430-3466`), auto-trader only.
- #10 Regime row built from stride transitions; `min_obs` counts daily labels (`regime_omm.py:92-114, 194`); options-scan window 441 calendar days (`scan.py:1705`).
- #11 Confidence replay counts overlapping days; cut-offs ignore payoff (`signal_confidence.py:150-168`).
- #12 Spreads: no leg liquidity checks, long-put R/R on the card, not routable (`spread_builder.py:31-89`).
- #13 Options target flat +8% (`trade_plan.py:106-109`, `risk_rules.yaml reward_risk`).
- #14 Swing DTE floor `hold_max + 1` = 16 (`dte_window.py:43-46`).
- #15 `summary_text` labels % expectancy as `$` (`strategy_backtest.py:229`).
- #16 Dead config: `regime.enhanced_states` (no reader), `pullback.max_days_in_pullback`, `pullback.theta_caution_days` (only `config_health.py:127`).
- Phase B items logged by the fix plan and still open: A1-F6 (long-hold earnings), A1-F4b (no server-side earnings re-check on manual sends), A2-F7 (yfinance window start), A4-F1 (MKT arm fired late).

**New this run** (details in the panel sections)
1. **Mixed-basis price history** — `_read_bars` adjusts only the close (High, REJECT-grade, area 2).
2. **The Swing score does not discriminate** on 5 years of data (High, area 1).
3. **The per-symbol backtest gate has no persistence** (High, area 2).
4. **Backtest limit orders are good-till-cancelled**; 8–13% of trades are stale fills, live orders are DAY (Medium, area 2).
5. **WFO selects on gross Sharpe and charges one round trip per fold**, however many trades the fold made; and its eligibility bar (20 OOS trades per symbol) is unreachable for every strategy (Medium, area 2).
6. **Trigger rule needs four events on the same bar**; `setup_window_bars` is dead config; trigger PASS on 0.5–1.2% of bars (Medium, area 1).
7. **Every bearish strategy loses net over 5 years**; `breakout_base` and `mean_reversion_rsi` can essentially never reach the backtest gate (Medium, area 1).
8. **R/R uses a 60%-of-premium loss while sizing uses 100%** (Medium, area 3).
9. **Stocks "After scan" auto-execute fires on CAUTION** while labelled "PASS", and books a paper row under "Auto-trade mode" (Medium, area 5).
10. A1-F6 is wider than logged: the **Position** preset (hold 15–45 d) also outlasts its 30-day earnings window (Medium, area 3).
11. Sector-blind fundamentals thresholds; adapter polish; adjusted-close cliffs in the data (Low).

Checked and **not** a finding: the pullback rule's ATR fallback can in principle PASS a break below the swing low; measured on 144,556 bars it fired on 17 bars and on zero PASS cards. Dropped.

---

## The thesis

Bamendjou hunts **trend-pullback continuation** in liquid US large caps. A five-rule weighted score (trend, pullback, trigger, event, vol; `scoring_rules.yaml horizons.*.weights`) must reach 55/100, and demote-only gates (confidence replay, regime headwind, fundamentals, direction conviction, earnings veto) can cap it.

It trades:
- **long single-leg options** — calls bullish, puts bearish — the auto-trader's only instrument;
- **bearish vertical spreads** (bear put / bear call by IV level), shown but not routable;
- **stocks**, long or short, through seven named daily strategies with a 1%-risk share size and a per-symbol 5-year backtest gate (`routers/stock_scan.py`, `_HISTORY_YEARS = 5` at `:466`).

It deliberately leaves out: premium selling as a primary structure, bullish spreads, and automated exits — every stop and target is an alert, never a broker order. Only two code paths place orders: `routers/broker.py` (manual) and `auto_trader.execute_option_order` (`auto_trader.py:2460`).

---

## Evidence gathered

### 1. Quant regression suite — all green
```
cd backend && ./.venv/Scripts/python.exe -m pytest -q  (17 files)
  test_confidence_cache test_confidence_gate test_confidence_gate_stocks test_data_leakage
  test_regime_no_lookahead test_signal_confidence test_strategy_backtest test_strategy_backtest_bearish
  test_strategy_direction_normalise test_strategy_param_optimizer test_strategy_param_store
  test_strategy_param_store_direction test_strategy_params test_strategy_params_config_sanity
  test_walk_forward test_walk_forward_warmup test_wfo_train_warmup
→ 145 passed, 1079 warnings in 451 s   (Python 3.11.9)
```
The warnings are `backtesting.py`'s same-bar SL/TP notices. CI runs the full backend `pytest` on Python 3.11 (`.github/workflows/ci.yml:17-25`).

**What the suite does not catch:** the mixed-basis bug is *pinned* by a test — `tests/test_historical_store_guard.py:46-59` stores a bar with high 102.0 and asserts `_read_bars` returns close 110.0, a close above its own high.

### 2. Data: five years were available this time
The last run had only the 251-bar fixtures. This run read the app's own Postgres store **read-only**: 538 symbols, 518 with ≥1,200 daily bars, 2020-10-05 → 2026-10-02. The stored rows were last bulk-refreshed by the nightly ingestion at 2026-10-04 00:28 UTC, 17 hours before this session; nothing was written by the review (all reads were plain `SELECT`s or `get_bars` calls on symbols already current).

All strategy evidence below uses the app's own WFO basket — `propose_basket(per_sector=5)` + SPY, **61 symbols** — over 2021-10-03 → 2026-10-02 (≈1,255 bars each), on **consistently adjusted** bars (open/high/low/close all × `adj_factor`), net of the live gate's cost `_backtest_commission()` = 0.001 fee + 0.001 slippage = **0.002 per leg** (`stock_scan.py:203-209`), with the `active:` params the live scan uses (`_merge_strategy_params`). Survivorship: the basket is today's S&P 500 members applied to the past.

### 3. Real-data backtest, 5 years × 61 symbols, net
| Strategy | Dir | Trades | Pooled win | Net exp %/trade | Gross ≈ net+0.4 | Combos passing gate | Median planned R/R | Share R/R < 1 |
|---|---|---|---|---|---|---|---|---|
| pullback_ema | Bull | 1,468 | 59.9% | **−0.075** | +0.325 | 25 / 61 | **0.60** | **74%** |
| pullback_ema | Bear | 877 | 47.3% | **−1.380** | −0.980 | 5 / 61 | 0.74 | 66% |
| breakout_base | Bull | 345 | 36.2% | +0.132 | +0.532 | **0 / 61** | 2.93 | 16% |
| breakout_base | Bear | 397 | 26.4% | **−0.523** | −0.123 | **0 / 61** | 3.62 | 11% |
| ma_crossover | Bull | 1,117 | 44.9% | **+0.572** | +0.972 | 29 / 61 | 1.29 | 37% |
| ma_crossover | Bear | 1,098 | 29.2% | **−1.491** | −1.091 | 6 / 61 | 1.63 | 27% |
| mean_reversion_rsi | Bull | 37 | 21.6% | −0.344 | +0.056 | 0 / 61 | 4.34 | 0% |
| mean_reversion_rsi | Bear | 18 | 5.6% | −2.264 | −1.864 | 0 / 61 | 4.67 | 0% |
| mean_reversion_bb | Bull | 1,299 | 44.6% | −0.146 | +0.254 | 21 / 61 | 1.35 | 38% |
| mean_reversion_bb | Bear | 581 | 34.8% | **−0.988** | −0.588 | 4 / 61 | 1.52 | 34% |

"Planned R/R" = |rung-1 target − entry| / |entry − stop| for every signal the engine emitted. "Gross" is approximate: `backtesting.py` charges commission as a fraction of each leg, so removing 0.002 × 2 adds ≈0.4 points per trade. `mean_reversion_vwap` is N/A on daily bars (intraday-only).

Trades per symbol vs the gate's minimum of 10: `breakout_base` median **6** (5–10% of symbols reach 10); `mean_reversion_rsi` median **0** (max 4); `mean_reversion_bb` Bearish median 8.5; the rest reach 10 on most symbols.

### 4. Does the backtest gate pick symbols that keep working? (split-half test)
Same engine, same params, Bullish, first half (2021-10 → 2024-04) vs second half (2024-04 → 2026-10), each half warmed with 260 prior bars.

| Strategy | H1 gate PASS → H2 net exp | H1 gate FAIL → H2 net exp | Pass again in H2 | Spearman ρ (H1 vs H2 expectancy) |
|---|---|---|---|---|
| pullback_ema | 13 syms → **−0.378%** (181 trades) | 48 syms → **+0.080%** (655) | 5 / 13 | −0.04 (n = 59) |
| ma_crossover | 15 syms → **+0.180%** (155) | 46 syms → **+1.426%** (413) | 2 / 15 | −0.25 (n = 57) |
| mean_reversion_bb | 13 syms → −0.049% (172) | 48 syms → −0.235% (688) | 4 / 13 | +0.05 (n = 58) |

The 95% noise band for ρ at n ≈ 58 is ±1.96/√57 = **±0.26**. All three sit inside it; two point the wrong way.

### 5. Does the Swing score pick better setups? (calibration study)
For every bar of the 61 symbols (306-bar window, as the options scan uses), `score_stock(..., "Swing")` on consistent bars, then the confidence replay's **own** outcome rule: target 3 ATR vs stop 1.5 ATR within 10 bars (`scoring_rules.yaml confidence_backtest.swing`), stop first if both touch on one bar, else the 10-day close in R. No IV and no earnings inputs — exactly the replay's own design (`signal_confidence.py:221-222`). 144,556 scored bars. "Distinct" = one setup per symbol per 10 bars (de-overlapped).

| Direction | Group | n (distinct) | Mean R (95% CI) | Target hit | Stop hit |
|---|---|---|---|---|---|
| Bullish | every bar (base rate) | 72,278 bars | +0.135 (+0.126…+0.144) | 19.6% | 44.5% |
| Bullish | **PASS** | 4,113 | **+0.140** (+0.103…+0.177) | 20.4% | 44.5% |
| Bullish | CAUTION | 4,923 | +0.129 (+0.095…+0.163) | 19.6% | 45.0% |
| Bullish | **REJECT** | 2,911 | **+0.113** (+0.070…+0.157) | 18.6% | 44.2% |
| Bullish | score 55–69 / 45–54 / 35–44 / 0–34 | 4,134 / 4,020 / 3,091 / 2,911 | +0.138 / +0.122 / +0.108 / +0.113 | | |
| Bearish | every bar | 72,278 bars | −0.093 (−0.101…−0.085) | 15.9% | 52.5% |
| Bearish | **PASS** | 3,205 | **−0.081** (−0.120…−0.041) | 15.6% | 51.8% |
| Bearish | REJECT | 4,092 | −0.125 (−0.160…−0.090) | 15.1% | 54.5% |

Trigger anatomy (Bullish / Bearish): trigger PASS on **0.53% / 1.20%** of bars; a reversal candle on the last bar 7.8% / 8.4%; two momentum signals on the same bar 3.2% / 5.4%. Only **57 of 25,937** Bullish PASS cards (and 110 of 17,915 Bearish) had a passing trigger.

### 6. How much does the mixed-basis bug change what the app decides?
| Consumer | What changes (app bars vs consistent bars) |
|---|---|
| Stored data | **44.2%** of bars in the options scan's 441-day window have close outside [low, high]; **69.6%** over 5 years; 252 of 538 symbols are broken on most of their scan-window bars. Worst: BKNG 96%, KLAC 90%, NFLX 90%, NOW 80% close-below-low (post-split names); median worst gap 1.8% |
| Stock backtest gate (5 y) | On 248 strategy × symbol × direction combos run both ways: trade count differs on 156, expectancy by > 0.5 pt on 138, **gate verdict flips on 29 (12%)** — e.g. NVDA `ma_crossover` Bull passes on true bars (n = 23, +4.23%) and shows **0 trades** on app bars; ABBV `pullback_ema` Bull fails on true bars (−1.01%) and **passes** on app bars (+4.64%) |
| Options-scan confidence replay | Of 122 basket replays: **14 move across a gate tier** (35/50), **14 gain or lose a confidence value** (sample < 20 on one side); sample sizes swing (HON Bullish 65 vs 35 samples) |
| Today's scan score | Small: latest bars carry `adj_factor` ≈ 1, ATR(14) unchanged at the median (p90 ratio 1.001, max 1.25); 6 Bullish and 8 Bearish Swing verdicts flip out of 517 |

### 7. Stale limit fills in the backtest engine
Synthetic proof: one signal places `buy(limit=105, sl=100, tp=130)` and never re-issues; it fills **35 bars later**. On real data (12 symbols × 5 strategies × 2 directions), the share of trades entered more than one bar after the last signal: `pullback_ema` 8% (37 / 459, max 9 bars), `breakout_base` **13%** (17 / 135, max **107** bars), `mean_reversion_bb` 9% (34 / 371, max 34), `ma_crossover` 1%, `mean_reversion_rsi` 0%.

### 8. The WFO tuner on real data
`ma_crossover`, 6 symbols, 3 years + warm-up, shipped 12/3-month windows: 8 folds, out-of-sample runs (31 OOS trades), proposal ineligible on `min_trades`. Details in Quant Q3.

---

## The Trader

**T1. The Swing score does not pick better trades than picking at random (High, area 1).**

Evidence §5. On 4,113 distinct bullish PASS setups across 61 names and five years, the replay's own barrier race averages +0.140R. Every bar in the sample averages +0.135R. REJECT setups average +0.113R. The confidence intervals sit on top of one another, and the score buckets are flat from 0 to 69. The positive number is the market's drift over 2021–2026 in today's S&P members, not the screen's selection. Bearish is the mirror: everything loses, PASS slightly less than REJECT, all inside noise.

This is not a bug in the arithmetic; I worked the rules and they do what they say. It is the absence of the thing the score exists to provide. For long options, which pay spread and theta, a selector that matches the base rate loses money by construction.

The caveats are honest and do not rescue it: the replay runs without IV and earnings (by its own design), and it scores the underlying, not the option. Neither of the omitted rules is a directional edge rule; they are filters.

**T2. The trigger rule almost never fires, so it is a constant penalty, not a trigger (Medium, area 1).**

In options mode a trigger PASS needs a reversal candle on the **last bar** and two of MACD cross, RSI cross and stochastic cross on **that same bar** (`stock_scorer.py:658-855`). The YAML carries `setup_window_bars: 8 / 10 / 5` per horizon, which reads like an 8-bar setup window; no code reads it — it appears only in `config_health.py:133`. Measured: trigger PASS on 0.53% of bullish bars; 57 of 25,937 bullish PASS cards had a passing trigger. With weight 0.25, the trigger's typical 10–35 points mean a PASS card is almost always trend + pullback + event + vol. Fix within intent: wire `setup_window_bars` (any of the momentum events within the window) or drop the weight.

**T3. `pullback_ema` still books targets nearer than its stops (High, area 1; deliberate, still open).**

Five-year evidence, not fixtures: median planned R/R **0.60**, 74% below 1:1; pooled net −0.075% per trade on 1,468 trades; gross +0.325%. The stop is `fast MA − 1.5×ATR` while entry may sit up to 4% above the MA (`strategy_engine.py:450-463`), and rung 1 is the 20-bar high including today (`:496-508`). The skip-floor is built and disabled (D7). The Chair's ruling from last time stands: deliberate, and the consequence is negative expectancy after cost.

**T4. Every bearish strategy loses over five years (Medium, area 1).**

Net per trade: `pullback_ema` −1.38%, `ma_crossover` −1.49%, `mean_reversion_bb` −0.99%, `breakout_base` −0.52% (§3). Part of that is the 2021–2026 tape (a bull market with a 2022 bear leg). But 877–1,098 trades per strategy is not a small sample, and the calibration study (§5) shows the bearish score adds nothing either. Short stock and long puts are both offered with equal prominence.

**T5. Two of the seven picker strategies cannot reach their own gate (Medium, area 1).**

`breakout_base` median 6 trades per symbol in 5 years (0 of 122 combos pass); `mean_reversion_rsi` 37 trades across all 61 symbols in 5 years (`rsi_oversold: 30` under `trend_sma: 200`). On the live stock scan they will almost always read "Only N trades — need 10" and drop. The trader sees a menu item that never produces a candidate.

**T6. Options target is still a flat +8% (Medium, area 3; open #13).** `trade_plan.py:106-109`. Same +8% on a 2-day Intraday hold and a 200-day Annual hold, on a utility and a semiconductor.

**T7. Earnings — fixed, with two residuals (Medium, area 3).**
- *Long holds.* The veto covers `reject_days`, not the hold. **Position** (hold 15–45 d, `horizonPresets.ts`) has a 30-day window: a 40-day hold with earnings 35 days out passes and is held through the print. Quarterly (45–60), Semi-annual (90–105, which always contains a print) and Annual are the same. Logged as A1-F6 for the longer presets; it includes Position.
- *Manual sends server-side.* `POST /api/portfolio` and `/broker/option-order` do not re-check earnings; only Step 7 (client) and the auto-fire do (A1-F4b).

**T8. Bearish spreads are still half-built (Medium, area 3; open #12).** No leg liquidity checks (`spread_builder.py:31-89`), long-put R/R on the card, not routable.

**T9. Swing DTE floor 16 for a 15-day hold (Medium, area 3; open #14).** `dte_window.py:43-46`.

**T10. Liquidity floors are tighter than they look (good).** Three soft flags reject a contract (`contract_validator.py:516-517`, `max_soft_fail_count: 3`), so a 20%-wide contract survives only if volume ≥ 200 or OI ≥ 1,000 *and* delta, DTE and IV are in band. The half-spread exit cost is still unmodelled.

---

## The Quant

**Q1. The price history the backtests read mixes two bases (High, REJECT-grade, area 2).**

`historical_store._read_bars` returns `close = raw_close × adj_factor` but `open`, `high`, `low` raw (`historical_store.py:238-246`). `adj_factor` is Alpaca's adjusted/raw close ratio and includes splits and dividends (`data/alpaca.py:106-118`): NVDA 2020-10-05 has 0.0249 (≈ 1/40 for the 4:1 and 10:1 splits). So on 2024-06-07 `get_bars` hands NVDA out as open 1,197.70 / high 1,216.21 / low 1,180.85 / **close 120.50**.

Every consumer of `get_bars` sees this: the options scan (`scan.py:1702-1707`), the stock scan and its 5-year backtest gate (`stock_scan.py:1127`), the confidence replay, the regime routes, composite watches and the WFO tuner. The effect is measured in §6: 44% of scan-window bars are impossible bars; the stock backtest gate's verdict flips on 12% of combos; the confidence gate changes outcome on 23% of basket replays. Today's score is barely touched (the latest bars carry factor ≈ 1), which is why nobody noticed on the screen.

Fix: scale open/high/low by the same factor in `_read_bars` (one line each), then fix the test that pins the bug (`tests/test_historical_store_guard.py:46-59`) and add an invariant test `low ≤ close ≤ high` over a stored series.

**Q2. The per-symbol backtest gate selects noise (High, area 2).**

Split-half test, §4. A symbol that passes the gate in 2021–2024 does no better in 2024–2026 than one that failed — for `pullback_ema` and `ma_crossover` it did worse. Rank correlations −0.04, −0.25, +0.05, all inside the ±0.26 noise band. At 10–25 trades per symbol the gate's three tests (n ≥ 10, win ≥ 45%, expectancy ≥ 0) are decided by luck: at n = 20 and p = 0.5 the 95% interval on the win rate is 0.5 ± 1.96·√(0.25/20) = ±21.9 points. Across 61 symbols, about 40% passing (`pullback_ema` 25/61) is what noise alone delivers around a near-zero pooled edge.

Plain-English: the gate looks like quality control, but it is a coin that has been flipped 20 times per symbol.

**Q3. The WFO tuner: OOS now runs; costs are under-charged and selection is gross (Medium, area 2).**

Run on real data (`_optimize_strategy_sync` with the shipped search grid, costs and eligibility; `ma_crossover`, Bullish, 6 symbols AAPL/JPM/XOM/HD/KO/CAT, 3 years + 14-month warm-up, 12/3-month rolling folds), 777 s:
- **8 folds; out-of-sample now runs**: 23 of 48 symbol-folds traded, 31 OOS trades (1.35 per traded symbol-fold). Fix #2 holds.
- Proposal `fast 20, slow 100, lookback 10, atr_target_mult 2.0`; consistency 0.625; OOS Sharpe 0.16, expectancy +0.57%; in-sample return 1.65% vs walk-forward 0.80% (degradation 51%); `eligible: false`; recommendation **"Edge looks fake — consider dropping."**

**The eligibility bar cannot be reached by any strategy (Medium, new).** `oos_metrics.n_trades` is the OOS trade count **per contributing symbol** (`strategy_param_optimizer.py`, `total_n_trades / len(contributing_symbols)`), and `optimization.min_trades: 20` (`strategy_params.yaml`). Eight 3-month folds are 24 months of OOS. From the 5-year trade rates in §3: `pullback_ema` 1,468 / 61 / 5 × 2 = **9.6**, `ma_crossover` 7.3, `mean_reversion_bb` 8.5, `breakout_base` 2.3, `mean_reversion_rsi` 0.2 OOS trades per symbol. None can reach 20, so every proposal is labelled "Edge looks fake" whatever it shows, and the label stops carrying information. Fix: judge eligibility on **pooled** OOS trades across the basket (the quantity that actually has a sample), or scale `min_trades` to the OOS span.

Two cost defects, both in code untouched by Phase A:
- *Selection on gross.* `train_fold` calls `run_strategy_backtest` with no `commission` (`walk_forward.py:239-240`), so the in-sample winner is chosen on gross Sharpe. A high-turnover combo wins selection on edge that costs remove.
- *One round trip per fold.* `apply_costs` subtracts `(fee + slippage) × 2` = 0.4% from a fold's **total** return (`walk_forward.py:121-122`; called at `strategy_param_optimizer.py:126, 153`), regardless of how many trades the fold made. The live gate charges 0.2% per leg per trade. Measured in the run above: 1.35 trades per traded symbol-fold, so the true charge is 0.54% against 0.40% applied (a quarter under-charged for `ma_crossover`; more for any higher-turnover combo).

The run used consistently adjusted bars; the live tuner reads `get_bars`, so it also inherits Q1.

**Q4. Backtest entries are good-till-cancelled limits; live entries are DAY (Medium, area 2).**

`_Strategy.next` issues `buy/sell(limit=entry, sl, tp)` and never cancels it (`strategy_backtest.py:155-162`). `backtesting.py` keeps an unfilled limit queued until filled or replaced (proved in §7: a 35-bar-late fill). On real data 8–13% of `pullback_ema`, `breakout_base` and `mean_reversion_bb` trades are such stale fills, up to 107 bars after the signal, at the old price with the old stop and target. The live stock send is `LMT` with `tif: 'DAY'` (`frontend/lib/stockDirectSend.ts:179`; `routers/broker.py` `StockOrderRequest.tif` defaults to DAY). Fix: cancel open orders at the start of `next()` when flat, or give the order a one-bar life.

**Q5. Multiple testing (open).** Grid sizes unchanged — `pullback_ema` 324, `breakout_base` 144, `mean_reversion_bb` 54, `ma_crossover` 24, `mean_reversion_rsi` 24 combos per fold. The only correction is the ≤0.05-Sharpe-per-parameter edge penalty (`walk_forward.py:162-202`). No deflated Sharpe. Given Q2, any per-symbol or per-combo winner should be presumed lucky until it survives a hold-out.

**Q6. Confidence replay (open #11).** Still counts every PASS bar, so overlapping 10-day windows inflate n; `min(1, payoff)` caps the reward side (`signal_confidence.py:150-168`). New context from §5: since the replay uses only price-derived rules and those rules do not separate outcomes, the confidence number is mostly a measure of the symbol's recent drift, and it is computed on mixed-basis bars (§6). Status: **uncalibrated**; partly measured here — it does not discriminate.

**Q7. Regime transitions (open #10).** Unchanged. On the stock path's 5-year bars the Swing window (500 bars, stride 20) gives 24 transitions; on the options path's ≈306 bars, ≈15.

**Q8. Monte Carlo drift assumed (open).** `mu = sign × (trend_score − 50)/50 × 0.40` (`first_passage.py:384, 847`). Uncalibrated.

**Q9. Lookahead — none found.** Signals see `bars[:i+1]`, fills on the next bar, replay outcomes from `bars[i+1:]`, OMM labels trailing; the WFO test slice cannot place an entry before `entry_start` (`strategy_backtest.py:141-142`). The suite's leakage tests pass.

**Q10. Data anomalies (Low).** Adjusted-close day-over-day jumps outside ×0.6–1.6 in the stored series: GE 2021-08-02 ×7.76 (the 1:8 reverse split, unadjusted), FI 2023-06-07 ×36.7 (ticker reuse), plus AVB 2026-08-21 ×0.36, CTVA 2026-10-01 ×0.16, MRNA 2026-08-19 ×2.77 — not verified against market history; check them. Some real moves also appear (CNC, DXCM, EPAM, FMC). Factors are refreshed by the nightly full ingestion (every row's `fetched_at` = 2026-10-04 00:28 UTC), so a frozen factor is only a risk if that job stops.

---

## The Risk Manager

**R1. Losing-streak arithmetic (non-compounding; the account value is never updated from P&L, R3).**

| Basis | Loss per trade | −10% after | −20% after |
|---|---|---|---|
| Option at the new cap, premium stop ignored (no broker stop) | 3.75% | 3 losers (11.25%) | 6 losers (22.5%) |
| Option at the cap, 60% premium stop honoured by hand | 2.25% | 5 (11.25%) | 9 (20.25%) |
| Stock card, 1% risk × conviction ≤ 1 | ≤ 1.00% | 10 | 20 |

Total option premium is capped at 25%: at 3.75% each that is 6 full-size positions (7 × 3.75 = 26.25% > 25%). Six correlated long-beta options going to zero cost 22.5% before anyone acts. Stocks: 20% single / 100% total notional, no combined cap with options.

**R2. Fixed: the option per-trade loss limit is now a hard cap.** `min(5%, 3.75%)` judged at the fill basis, refused when one contract does not fit (`portfolio_risk.py:181-202`). The fire-time check uses the same function (`auto_trader.py:3011-3045`).

**R3. Every % cap multiplies an account value the client types (Medium, open #7).** `position_writer.py:497` passes `body.portfolioValue`; defaults 50,000 in `schemas/__init__.py:1114` and `routers/auto_trade.py:136`, 100,000 in the YAML and the frontend store; never updated from P&L.

**R4. Daily loss is a spend cap, in memory, auto-only (Medium, open #9).** `auto_trader.py:3430-3466`; a restart resets it; manual sends have no daily limit. `max_daily_recommendations` is still never passed server-side (`check_position_risk` default 0, no caller supplies it).

**R5. Stocks: no per-trade loss check server-side, shorts with no protective order (Medium).** The stock card sizes at 1% risk, but the share field is editable and the server judges only notional (20% / 100%). A short stock (Bearish `|STOCK`, `premium_stop.is_short_stock_position`) has an alert on a rise, no broker stop; gap risk is unbounded. The 5-year evidence (T4) says bearish strategies lose.

**R6. Missing-data behaviour** — as last run, with one change: unknown earnings on a single stock is now fail-**closed** (CAUTION cap and auto-fire refusal; ETFs exempt via `data/etfs.py:63`). Still fail-open: fundamentals missing (gate skipped), confidence n < 20 (no cap), regime missing on the daily scan (gate skipped). Contract liquidity and money config blocks remain fail-closed.

---

## Execution safety (Risk Manager, continued)

**E1. Stocks "After scan" auto-execute fires on CAUTION and does not trade (Medium, new).**
`StockAutoTradeArm` sits under the heading "Auto-trade mode" with the option "After scan — fire when next scan PASS" and the note "Will execute when next scan finds a PASS" (`StockAutoTradeArm/index.tsx:12, 118`). The handler adds **every** armed candidate in the scan result as a `source: 'paper'` Portfolio row (`step-4-stocks/page.tsx:243-262`, `lib/paperTrade.ts:177`). The stock scan returns CAUTION candidates too (`stock_scan.py:1680-1684`), and the loop never checks `status`. So a CAUTION setup is "executed", and "executed" means a tracked row, not an order. Fix: filter `c.stock_status === 'PASS'`, and relabel "Track automatically after the next scan (no order)".

**E2. "Market open" is still "a price exists" (Medium, open #8).** `auto_trader.py:648-670`.

**E3. No protective orders; exits are alerts (Medium, deliberate).** Unchanged. Overnight gaps, halts and regime flips need a human awake.

**E4. Broker endpoints run no risk check of their own (Low → Medium when live).** `/broker/stock-order` and `/broker/option-order` (`routers/broker.py:217-349`); A1-F4b adds earnings to that list.

**E5. A scan-triggered fire does not consult the scan's verdict (Low, deliberate).** `maybe_fire_on_scan` checks arm age ≤ 30 min, then the fire re-checks market, regime, earnings, exposure and daily loss (`auto_trader.py:3053-3132, 2560-2640`). The setup itself is not re-graded; with the 30-minute cap this is acceptable and documented.

**E6. Broker adapters (first read this run, Low).** Side/effect mapping is correct (Tradier `buy_to_open` etc., `tradier_paper.py`; IBKR/Alpaca infer open/close). No broker-side client order id on Tradier/Alpaca, so the app's natural-key dedup window (`routers/broker.py` `_claim_or_wait`) is the only duplicate guard. An IBKR option order without a `conid` carries only the underlying symbol with `secType: OPT` (`ibkr_paper.py` `_build_payload`) and will be rejected by the broker. Limit prices are not rounded to the option tick.

**E7. Done well (re-verified).** Idempotent order endpoints; IBKR confirmation question answered as not-placed; pre-broker vs may-have-landed split with full premium booked; double-fire prevention under lock with `expect` identity; the stock and option direct sends save first, order second, classify the reply and remove a provably-unplaced row (`lib/stockDirectSend.ts`). Careful engineering.

---

## Cross-parameter table

| Check | Values (file:line) | Consistent? | Severity |
|---|---|---|---|
| Per-trade loss vs single-position cap (options) | `max_loss_per_trade_pct 0.0375` now caps premium via `min(...)` (`portfolio_risk.py:189-192`) | **Yes** (fixed) | — |
| Per-trade loss vs daily loss | 3.75% per trade vs `auto_trade.max_daily_loss_pct 0.02` premium spend | Auto path blocks any trade > 2%; manual path has no daily gate | Medium |
| Stop definitions | Sizing: loss = 100% premium (D5). R/R risk = 60% premium (`reward_risk.py:148`). Premium-stop alert at entry × 0.40 (`premium_stop.py`). Card stock stop = structure / 2×ATR. Step-7 checklist wants R/R ≥ 2.0 | **No**: the R/R the checklist grades uses a 60% loss the system itself does not believe; a shown 2.0 is 1.2 on the sizing basis | Medium |
| Stock vs option caps | options 3.75% / 25% premium; stocks 20% / 100% notional; each counted only against its own kind | No combined cap | Medium |
| Backtest costs vs allowed liquidity | stocks 0.2%/leg; options never backtested; contract filter accepts ≤ 20% spread at mid | Half-spread on exit unpriced | Medium |
| Backtest costs vs WFO costs | live gate 0.2%/leg **per trade**; WFO selects gross and charges 0.4% **per fold** | **No** | Medium |
| Backtest order type vs live | backtest GTC limit (`strategy_backtest.py:160`); live `LMT`, `tif: DAY` | **No** | Medium |
| WFO windows vs data | 12/3 months + 260-bar warm-up; DB holds ≈ 6 years | **Yes** (fixed) | — |
| WFO windows vs code minimums | test fold ≈ 62 bars ≥ `MIN_SCORED_BARS` 40; window with warm-up ≥ 100 | **Yes** (fixed) | — |
| Minimum-trade gates | backtest 10; WFO 20 OOS **per contributing symbol** over 24 months; confidence 20 overlapping | **No**: the WFO bar is unreachable (best strategy ≈ 9.6 OOS trades per symbol); Q2 shows 10–25 is noise anyway | Medium |
| Config vocabulary vs code | `direction: bullish` normalised (`strategy_backtest.py:16`) | **Yes** (fixed) | — |
| `setup_window_bars` | 8 / 10 / 5 in YAML; no reader | **Dead** — trigger is same-bar only | Medium |
| Earnings window vs hold | Swing reject 21 ≥ hold 15 ✓; Position reject 30 < hold 45; Quarterly/Semi/Annual likewise | **No** for four presets | Medium |
| DTE vs hold | `hold_max + 1` floor → Swing 16 DTE for 15-day hold | Edge case leaves 1 DTE | Medium |
| Account value basis | YAML 100,000; schema/arm defaults 50,000; client sends its own | Three sources; server trusts the client | Medium |
| Price basis vs bar invariant | close × `adj_factor`, O/H/L raw (`historical_store.py:238-246`) | **No**: 44% of scan-window bars violate low ≤ close ≤ high | **High** |
| Score thresholds vs mirrors | 55/35, 50/35 = `status.ts`, `confidenceText.ts`, `SCORING_RULES.md` | Yes | — |
| Dead or unmeasured config | dead: `enhanced_states`, `max_days_in_pullback`, `theta_caution_days`, `setup_window_bars`, `auto_trade.premium_stop_pct` (marked NOT READ), `gap_threshold_pct` (marked intentional). Unmeasured and live: `max_iv_rank`, `iv_rank_*`, `bearish_min_trend`, `stop_premium.pass_max_fraction`, `min_signal_rr` (0.0, disabled) | Marked honestly except `setup_window_bars` | Low / Medium |

---

## Stress test

| Scenario | What the code does | Exposure |
|---|---|---|
| Clean uptrend | Bullish setups pass about as often as chance (§5); `pullback_ema` rung 1 a median 0.60R away; `ma_crossover` is the one strategy with positive net expectancy (+0.57%/trade) | Options: drift-dependent, no selection edge. Stocks: `pullback_ema` slightly negative net |
| Downtrend | Bearish mirrors are sound in code; every bearish strategy loses net over 2021–26; spreads not routable | Long puts and short stock with no measured edge |
| VIX 20 → 40 | No VIX input; symbol IV caps CAUTION > 34, REJECT > 55 (Swing abs), contract hard reject > 70 | Long premium bought at elevated IV up to the caps |
| Earnings inside the hold | **Swing: vetoed** (fixed); unknown date on a stock caps CAUTION and refuses auto-fire. Position and longer presets: not vetoed beyond 30 days | IV crush on long holds; manual server-side paths unchecked |
| Overnight gap through the stop | Alert only | Option: up to 100% premium = 3.75% of account. Stock: unbounded below the stop (20% position) |
| Trading halt | `_market_is_open` passes on a last price; fire disarms and sends | Order rejected or queued; arm consumed |
| Regime flip with open positions | WebSocket warning; no auto-exit | Human-dependent |
| Broker API down at order time | Classified not-submitted vs may-have-landed; full premium booked on may-have-landed | **Handled well** |
| Stock split in the lookback | `get_bars` returns adjusted closes against raw highs/lows | Backtest gate and confidence replay decide on impossible bars (NVDA `ma_crossover`: 23 trades true, 0 shown) |

---

## The Chair

**Where the voices disagreed, and who is right.**

1. *Is "the score has no edge" a REJECT or a CAUTION?* The Quant says CAUTION: the mechanism works and the REJECT examples in the rubric are bugs, not disappointing results. The Trader says REJECT: an options selector that matches the base rate loses spread and theta on every trade. **The Trader is right.** "Insufficient data" earns CAUTION because the edge is unproven. This is not unproven; 4,113 distinct setups measured it, and the intervals say the score adds nothing over the universe's drift. The REJECT line exists for "real money would be at risk", and it is.

2. *Phase A credit.* The Risk Manager wanted area 4 kept at REJECT until the account value is server-side. **No.** The REJECT was "a loss limit a single trade can blow through"; that is closed, judged at the fill basis, and refused when one contract does not fit. The client-supplied account value is a real Medium, not the same defect.

3. *Mixed-basis data.* The Trader called it a plumbing bug outside his lens. **It is the most consequential finding of the run for the evidence.** It is invisible on today's screen and decisive in every backtest, gate and replay that looks back. It also explains why five strategies' per-symbol results looked unstable in earlier runs.

4. *The backtest gate.* The builder's design treats a per-symbol backtest as protection. The Quant's split-half test shows it selects noise. **The Quant is right, and the fix is not a tighter threshold.** At 10–25 trades per symbol no threshold separates signal from luck; pool across symbols (the WFO's basket design) and judge on out-of-sample.

**Deliberate choices respected:** event weight zero for stocks; no protective orders (graded on consequence, not called a bug); D7's disabled floor (the Trader's fix-within-intent stands); ETFs exempt from unknown-earnings; fail-closed money blocks; UNMEASURED thresholds honestly labelled.

---

## Fix list (worst first)

| # | Severity | Area | Problem | Fix | Why it costs money |
|---|---|---|---|---|---|
| 1 | High | 2 | `_read_bars` adjusts close only; O/H/L raw (`historical_store.py:238-246`) | Multiply open/high/low by `adj_factor` too; replace the test that pins the bug; add a `low ≤ close ≤ high` invariant test over stored series; re-run every cached backtest | Gate verdicts flip on 12% of combos; confidence on 23% of replays |
| 2 | High | 1 | Swing score does not separate outcomes on 5 y × 61 names | Stop trading it as a selector until a rule set beats the base rate out of sample. Use §5's harness (score → barrier R, de-overlapped, with CI) as the acceptance test for any scoring change | Long premium on a no-edge selector pays spread + theta every time |
| 3 | High | 2 | Per-symbol backtest gate has no persistence | Replace with a pooled, out-of-sample gate (strategy × basket over walk-forward folds); show per-symbol stats as information only | Gate passes noise and blocks equally good names |
| 4 | High | 1 | `pullback_ema` median R/R 0.60, net −0.075%/trade | After fixes 1, 5 and 6, re-tune and set `min_signal_rr` from out-of-sample results (D7's own plan) | Wins too small to pay costs |
| 5 | Medium | 2 | WFO picks on gross, charges 0.4% per fold | Pass the live commission into `train_fold` and the OOS run; drop `apply_costs` | Over-traded combos win selection |
| 5b | Medium | 2 | WFO eligibility needs 20 OOS trades per symbol; best strategy ≈ 9.6 | Judge on pooled basket OOS trades | Every proposal reads "Edge looks fake"; the verdict carries no information |
| 6 | Medium | 2 | Backtest limits are GTC; live is DAY | Cancel queued orders when flat at each `next()` | 8–13% of trades are stale fills |
| 7 | Medium | 1 | Trigger needs four same-bar events; `setup_window_bars` dead | Implement the window or drop the weight; re-measure with the §5 harness | A 25% weight that is almost always 10–35 points |
| 8 | Medium | 5 | Stocks "After scan" fires on CAUTION, label says PASS, books paper rows under "Auto-trade" | Filter `PASS`; relabel as tracking, no order | Trader believes setups were taken |
| 9 | Medium | 4 | Server caps trust client `portfolioValue` (50k vs 100k defaults) | Server reads account value (YAML, later broker); one default | Caps loosen silently; no shrink after drawdown |
| 10 | Medium | 3 | R/R uses 60% loss; sizing uses 100% | Compute the headline R/R on the same loss basis sizing uses, or show both | Checklist passes trades at 1.2 R/R |
| 11 | Medium | 3 | Earnings veto shorter than Position/Quarterly/Semi/Annual holds | `max(reject_days, hold_max)` per preset, or disclose on the card (A1-F6) | IV crush inside long holds |
| 12 | Medium | 1 | Bearish strategies lose net; `breakout_base` / `mean_reversion_rsi` can't reach the gate | Mark bearish stock strategies experimental; retune or hide the two dead strategies | Menu items with no measured edge or no candidates |
| 13 | Medium | 5 | `_market_is_open` is a price probe | Session clock + halt flag, before disarm | Orders after hours / in halts |
| 14 | Medium | 4 | Daily loss in memory, auto-only, spend not loss | Persist; include manual sends; count realised P&L | Limit resets on restart |
| 15 | Medium | 3 | Spreads half-built; flat +8% target; Swing DTE 16 | Phase B #12, #13, #14 | Misleading R/R; theta at exit |
| 16 | Medium | 2 | Confidence overlap; regime transitions thin | Phase B #10, #11 | Gates decided on noise |
| 17 | Low | 2 | Adjusted-close cliffs (GE ×7.76, FI ×36.7, AVB, CTVA, MRNA) | Verify and repair those rows; add a cliff check to ingestion | Fake 600%+ days in any backtest touching them |
| 18 | Low | 5 | Adapters: no client order id; IBKR option without `conid`; no tick rounding | Send `client_order_id`; require `conid` for IBKR options; round to tick | Duplicate or rejected orders |
| 19 | Low | 1 | Fundamentals thresholds sector-blind | Sector-relative thresholds or exempt financials/utilities from D/E and current ratio | Systematic bias against two sectors |
| 20 | Low | 2/4 | `$` label (#15); dead keys (#16) | As Phase B | Misread evidence; dead knobs |

---

## Not measured

- **Option-level P&L of any strategy.** No backtest prices the contract. *Measure:* replay recorded chains, or BS-reprice at entry/exit with a half-spread charge.
- **Calibration with the live IV and earnings inputs, and for the Position / Intraday horizons.** §5 is Swing, price-only (the replay's own design). *Measure:* the same harness with historical IV and earnings dates.
- **Edge vs buy-and-hold.** `ma_crossover` Bullish's +0.57% per trade was not compared with simply holding the basket over the same days. *Measure:* exposure-matched buy-and-hold over the same bars.
- **Survivorship-free results.** Basket = today's S&P members. *Measure:* point-in-time constituents.
- **The full WFO on all strategies.** Only `ma_crossover` on 6 symbols was run (Q3).
- **Regime model predictive value; Monte Carlo hit probabilities; Heston repricing error; fill quality at mid on OI-200 / 20%-spread contracts.** As last run.
- **The data anomalies in Q10** were not checked against an independent price source.

---

## Coverage

**Tested by running (this session)**
- Quant regression suite: 17 files, 145 tests (§1).
- `scripts/state.py`: no drift.
- Database survey (read-only): 538 symbols; bar-invariant violations across all of them; adjusted-close cliff scan.
- `score_stock` app-basis vs consistent on all 517 symbols with ≥250 scan-window bars (§6).
- `run_strategy_backtest`: 5 strategies × 2 directions × 61 symbols × 5 years, consistent basis, net (610 runs) + app basis on 14 symbols plus 36 earlier rows (265 runs) (§3, §6).
- Split-half gate persistence: 3 strategies × 61 symbols × 2 halves (§4).
- Calibration study: 144,556 `score_stock` calls with barrier outcomes (§5).
- Confidence replay app-basis vs consistent, 122 replays (§6).
- Stale-fill proof (synthetic) and measurement (120 runs) (§7).
- WFO `_optimize_strategy_sync` on real data, `ma_crossover`, 6 symbols (Q3).
- Arithmetic: losing streaks, confidence intervals, noise bands (shown inline).

**Read (logic reviewed)**
- Backend: `routers/scan.py` (earnings veto, final status, bars window), `routers/stock_scan.py` (cost, param merge, backtest gate, bars window, candidates), `routers/strategy_tuning.py`, `routers/broker.py` (both order routes), `routers/auto_trade.py` (ArmRequest default).
- `services/strategy_backtest.py`, `walk_forward.py`, `strategy_param_optimizer.py`, `strategy_param_store.py`, `portfolio_risk.py`, `position_writer.py` (risk section), `premium_stop.py`, `historical_store.py` (`get_bars`, `_read_bars`), `strategy_basket.py`, `broker_router.py`, `auto_trader.py` (event veto, earnings lookup, cap basis, market check, fire ordering, daily loss, scan trigger), `fundamentals_gate.py`, `config_health.py` (key lists).
- Scoring: `stock_scorer.py` (additive trend, pullback, candles, trigger, event window), `contract_validator.py` (hard rejects, all component scores, soft-fail rule), `trade_plan.py`, `reward_risk.py` (risk basis), `exit_plan.py` (`resolve_stock_stop`), `conviction_sizing.py` (header and failure posture), `fundamentals_scorer.py`, `signal_confidence.py` (formula, replay contract), `regime_omm.py` (stride, min_obs), `dte_window.py`, `first_passage.py` (drift lines), `spread_builder.py` (builders).
- `strategy_engine.py`: `pullback_ema_signal` in full; other strategies through their measured behaviour.
- Data: `data/alpaca.py` (adjustment), `data/alpaca_paper_execution.py`, `data/tradier_paper.py`, `data/ibkr_paper.py` (order build), `data/etfs.py` (presence).
- All `backend/config/*.yaml` except credentials (settings.yaml read with secrets filtered).
- Frontend: `lib/earningsGate.ts`, `lib/horizonPresets.ts`, `lib/premiumStop.ts` (semantics), `lib/stockDirectSend.ts`, `lib/paperTrade.ts` (source tag), `StockSendDialog`, `StockAutoTradeArm`, `step-4-stocks/page.tsx` (auto-execute), `step-7-trade-card/page.tsx` (basket tag, toast, premium-stop notes), `SendToBrokerDialog` (labels), `TradeCard` (premium-stop field).
- Plans and records: `docs/superpowers/plans/2026-10-03-trading-review-fixes-plan.md` (decisions, Phase B), `docs/superpowers/audits/2026-10-03-trading-review-fixes.md`, `PROJECT_STATE.json` (TRADING-REVIEW entries), `.github/workflows/ci.yml`, `tests/test_historical_store_guard.py`.

**Skimmed (purpose only, not graded in depth)**
- `scoring/structural_stop.py`, `stop_cost.py`, `reprice_horizon.py`, `entry_quality.py`; `data/tastytrade_paper.py`; `services/regime_gate.py`, `regime_hmm_daily.py`, `regime_monitor.py`, `alert_generator.py` (premium-stop path), `strategy_watch_evaluator.py` (confirmed it places no orders), `composite_trigger_evaluator.py`, `auto_trade_booking.py`.

**Not reviewed in this run (by name, with reason)**
- `strategy_engine.py` bodies of `breakout_base`, `ma_crossover`, the mean-reversion family, `breakout_setup` and `_fibonacci_pullback`: exercised by running only (5 years × 61 symbols); code not read line by line.
- `models/heston*`, `services/market_structure.py`, `indicator_compute.py`, `alert_evaluator.py`: not on an order or gate path reviewed here.
- `routers/contracts.py` (recompute endpoint) and `routers/portfolio.py` beyond the create path: share `build_trade_plan` / `create_position`, already read.
- Schedulers, notifications, credential store, and the routers for alerts, chart, journal, news, sectors, symbols, watchlists, websockets, health, data sources, ingestion, events, config, candles, tradecards, composite and strategy watches, regime: outside trading logic.
- Frontend outside the send/risk path: Steps 1–3, Step 4 ranking, Step 5–6 pages, Pre-Breakout UI, Analysis, Chart, Settings.

Next run: re-run §3–§6 after fix 1 (the numbers in this report were measured on corrected bars, so they should hold; the app's own cached backtests will change), then extend calibration to Position and Intraday with IV and earnings inputs.
