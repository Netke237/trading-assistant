# Bamendjou Trading Review

**Date**: 2026-10-02 · **Commit**: `0caf2661` (branch `claude/pipeline-inspector-fixes`, clean tree) · **Mode**: A — full review
**Method**: k-trading-software-reviewer (three-voice panel + Chair)

## Overall: **REJECT**

> "The plumbing is careful and the fail-closed work is real. But the tuner is grading the wrong trade, an earnings 'gate' that only shows a badge, and a per-trade loss limit nothing enforces mean I would not put money behind it yet."

| Area | Grade | Why, in one line |
|---|---|---|
| 1. Edge & strategy logic | **CAUTION** | `pullback_ema`'s own target sits a median 0.11R away on SPY; options targets are a flat +8% on every symbol and horizon; the regime gate rests on 0–15 transitions |
| 2. Statistical evidence | **REJECT** | The WFO tuner runs the **bearish** branch when tuning bullish params, and every out-of-sample fold is skipped on real data (61–62 bars < the 100-bar minimum) |
| 3. Options & contract selection | **REJECT** | Earnings inside the reject window only lowers the score: 37 of 440 measured PASS setups stay PASS with earnings 3 days out, and nothing downstream blocks them |
| 4. Risk parameters & sizing | **REJECT** | A 5%-of-account premium cap with no protective order lets one trade lose more than the 3.75% per-trade loss limit, which is warning-only. All % caps multiply a client-typed account value |
| 5. Execution safety | **CAUTION** | The basket says "N sent to broker" but places no order; "market open / halted" is really "a price exists"; the daily-loss gate is in-memory and auto-trader-only |

Overall = worst area = **REJECT**. Grade the behaviour as if live: every broker key is paper today (`routers/broker.py:18`, `broker_router.py` blocks `*_live`). That is said once here and is not counted as mitigation anywhere below.

---

## Since last run (predecessor: `TRADING_QUALITY_BENCHMARK.md`, 2026-08-19, round 4)

The predecessor graded three axes. Its trading-logic findings map to areas 1–2 here and its config findings to areas 3–4. Its code-quality axis (ESLint warnings, `xlsx` advisory, build/typecheck) is **out of scope** for this skill and was not re-graded.

**Fixed (re-verified in this run)**
- `breakout_base` `atr_tight_max` is 4.0 (`strategy_params.yaml` active blocks). It now fires on real data (1–2 bearish trades per symbol, 2 bullish on SPY).
- The live Step-6 backtest charges cost. `_backtest_commission()` = fee 0.001 + slippage 0.001 = **0.002 per leg** (`routers/stock_scan.py:203-209`), passed through to `run_strategy_backtest(commission=…)`.
- `contract_rules.yaml` `min_stock_score: 55` matches the stock `pass` bar.
- `SCORING_RULES.md` agrees with the YAML on 55/35 (`SCORING_RULES.md:195-197`). The frontend mirrors agree too: `frontend/lib/status.ts:31` `{passAt: 55, cautionAt: 35}`, `frontend/lib/confidenceText.ts:4-11` 50/35.
- The DTE floor equality (`soft_rank.preferred_dte_min == hard_reject.min_dte`) is still intentional and documented. Closed.

**Still open (re-verified)**
- **Real-data evidence is thin.** 1 of 40 strategy×symbol×direction combos now reaches `_MIN_TRADES=10`: SPY `pullback_ema` Bullish, n=11. It fails on expectancy (see Quant). The predecessor tested 20 bullish-only combos; this run adds the bearish side.
- `signal_confidence` is still a single in-sample replay. It is now worse than reported, because the samples overlap and the history window is shorter than configured (Quant Q4).
- The complexity penalty (0.05/param) is still unmeasured. It is also moot until the WFO runs out-of-sample at all (Quant Q2).
- `backtesting.py` same-bar SL/TP warning: 1,057 warnings across the quant suite, 42 in the fixture backtest.
- `mean_reversion_rsi` / `mean_reversion_bb`: still 0 trades on 251 bars (warm-up of 200-SMA plus indicator).
- Predecessor config table, "`max_daily_loss_pct` is a real circuit breaker": **partly wrong**. It caps premium *deployed* per UTC day by the auto-trader only, from in-memory history (Risk Manager R4).

**New this run** (details in the panel sections)
1. WFO tunes bullish params on the bearish branch: config vocabulary `bullish` vs code `"Bullish"` (High).
2. WFO out-of-sample folds can never run on trading-day data (High).
3. The earnings / event "gate" is not a gate on the options path. The Step-7 checklist uses a different, fixed 7/3-day window (High).
4. `pullback_ema` targets sit far closer than its stops (High). The design is deliberate; the consequence is measured.
5. The basket "Auto-send" places no broker order but reports "sent to broker" (High).
6. Per-trade loss limit vs single-position premium cap contradiction, with no protective order (High).
7. Server-side % caps multiply a client-supplied `portfolioValue`; the defaults are 50,000 in the schemas vs 100,000 in the YAML and frontend (Medium).
8. The auto-trader's "market open / halted" check passes on any last or previous close (Medium).
9. The regime transition row is estimated from 0–15 transitions (Medium).
10. The confidence gate's cut-offs ignore the 2:1 barrier asymmetry: a 50% hit rate is +0.5R, yet it is demoted (Medium).
11. Bearish spreads: no liquidity checks on legs, not routable, and the card shows the long put's R/R (Medium).
12. The Swing DTE floor allows `hold_max + 1` = 16 DTE (Medium).
13. Dead config: `regime.enhanced_states`, `pullback.max_days_in_pullback`, `pullback.theta_caution_days` (Low).
14. `strategy_backtest` summary labels a %-per-trade expectancy as `$` (Low).

---

## The thesis

Bamendjou hunts **trend-pullback continuation** in liquid US large caps (S&P 500 / NDX-100 / Dow universes). It enters when a weighted five-rule score clears 55/100 (trend, pullback, trigger, event, vol; `scoring_rules.yaml` `horizons.*.weights`), and four demote-only gates (confidence replay, regime headwind, fundamentals, pullback timing) can veto it.

It trades three things:
- **long single-leg options**: calls for bullish, puts for bearish (`scan.py:546`);
- **defined-risk bearish vertical spreads**: bear put or bear call, picked by IV level (`scan.py:380-464`, `spread_builder.py`), displayed but not routable;
- **stocks**, long or short, sized by a 1%-risk rule against a strategy-specific stop, through seven named daily strategies (`stock_scan.py:1085-1101`, `strategy_engine.py`).

What it deliberately leaves out:
- no premium selling outside the bear-call alternative;
- no bullish spreads;
- no short options as a primary structure;
- no automated exits: every stop and target is an **alert**, not a broker order (`alert_generator.py:47`, and the only order-placing call sites are `routers/broker.py` and `services/auto_trader.py`);
- event risk does not count on the stock side (weight zeroed, `stock_scorer.py:1150-1157`).

An auto-trader fires one armed option order on scan completion, behind regime and exposure gates.

---

## Evidence gathered

### Quant regression suite
```
cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_confidence_cache.py tests/test_confidence_gate.py \
  tests/test_confidence_gate_stocks.py tests/test_data_leakage.py tests/test_regime_no_lookahead.py \
  tests/test_signal_confidence.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py tests/test_walk_forward.py
→ 94 passed, 1057 warnings in 199.50s
```
The warnings are all `backtesting.py`'s "contingent SL/TP … executed on the next bar". CI (`.github/workflows/ci.yml:17-25`) runs the full `pytest` on Python 3.11, so this suite is in the CI gate.

**What the suite does not catch:** both WFO defects below pass it. `tests/test_strategy_param_optimizer.py:50-52` uses synthetic calendar-day bars, where `test_months=4` gives "~123 days". On trading-day bars the same window is about 84. Every test passes `direction` capitalised.

### Real-data backtest
- Fixtures: `backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 daily bars each, 2024-04-30 → 2025-04-30.
- Engine: `run_strategy_backtest`, active params from `strategy_params.yaml`.
- "net" = `commission=0.002` per leg, which is what the live gate charges.
- Expectancy is % per trade. Max DD is reported only where pulled. `mean_reversion_vwap` is N/A: intraday-only, and daily bars cannot represent it.

| Symbol | Strategy | Dir | n | Win gross→net | Exp % gross→net | Sharpe net | Gate |
|---|---|---|---|---|---|---|---|
| AAPL | pullback_ema | Bull | 6 | 67%→67% | +0.48→+0.08 | 0.01 | n<10 |
| AAPL | pullback_ema | Bear | 1 | 100% | +8.18→+7.80 | 0.63 | n<10 |
| AAPL | breakout_base | Bull/Bear | 0 / 1 | — / 0% | — / −2.51 | — | n<10 |
| AAPL | ma_crossover | Bull | 5 | 40% | −0.98→−1.38 | −1.23 | n<10 |
| AAPL | ma_crossover | Bear | 6 | 17% | −0.90→−1.31 | −0.64 | n<10 |
| MSFT | pullback_ema | Bull | 1 | 0% | −3.37→−3.76 | −0.46 | n<10 |
| MSFT | pullback_ema | Bear | 5 | 60% | +0.20→−0.20 | −0.93 | n<10 |
| MSFT | breakout_base | Bear | 2 | 0% | −1.66→−2.07 | −1.09 | n<10 |
| MSFT | ma_crossover | Bull | 3 | 0% | −2.72→−3.12 | −1.71 | n<10 |
| MSFT | ma_crossover | Bear | 4 | 25% | −1.56→−1.96 | −0.63 | n<10 |
| NVDA | pullback_ema | Bull | 4 | 50% | +0.82→+0.42 | 0.01 | n<10 |
| NVDA | breakout_base | Bear | 1 | 0% | −7.38→−7.80 | −0.77 | n<10 |
| NVDA | ma_crossover | Bull | 4 | 50% | +5.39→+4.97 | 0.99 | n<10 |
| NVDA | ma_crossover | Bear | 4 | 0% | −7.73→−8.14 | −2.68 | n<10 |
| **SPY** | **pullback_ema** | **Bull** | **11** | **82%→55%** | **−0.12→−0.52** | **−0.92** | **fails expectancy** |
| SPY | pullback_ema | Bear | 2 | 100% | +3.08→+2.69 | 0.36 | n<10 |
| SPY | breakout_base | Bull | 2 | 0% | −0.64→−1.04 | −1.13 | n<10 |
| SPY | breakout_base | Bear | 2 | 50% | +0.24→−0.16 | −0.19 | n<10 |
| SPY | ma_crossover | Bull | 4 | 25% | +0.39→−0.02 | −0.04 | n<10 |
| SPY | ma_crossover | Bear | 4 | 25% | +0.36→−0.04 | −0.05 | n<10 |
| all 4 | mean_reversion_rsi / _bb | both | 0 | — | — | — | 0 trades (warm-up) |
| NVDA | pullback_ema Bear, breakout_base Bull | — | 0 | — | — | — | — |

SPY `pullback_ema` Bullish: gross return −1.59%, max DD −4.96%; net return −5.83%, max DD −7.43%. Six runs logged "Some trades remain open at the end of backtest". The engine excludes those trades from the stats, which biases toward closed (often target-hit) trades.

### Planned R/R of every signal the engine emitted on the fixtures
Every bar where the live signal function returned a signal, measured as |target − entry| / |entry − stop|:

| Symbol | Strategy · Dir | Signal bars | Median planned R/R | Share below 1:1 |
|---|---|---|---|---|
| SPY | pullback_ema · Bull | 43 | **0.11** | **95%** |
| AAPL | pullback_ema · Bull | 21 | 0.32 | 90% |
| MSFT | pullback_ema · Bear | 21 | 0.41 | 100% |
| NVDA | pullback_ema · Bull | 14 | 1.08 | 36% |
| SPY | ma_crossover · Bull | 19 | 1.94 | 0% |
| NVDA | ma_crossover · Bear | 24 | 2.49 | 0% |
| (all others) | | 1–24 | 0.79–5.08 | 0–78% |

### Data available vs data required
| Requirement | Configured | Available | Fits? |
|---|---|---|---|
| Fixture history | — | 251 bars (1 year, one regime) | — |
| Options-scan bar window | `scan.py:1659` 1.75×252 calendar days | ≈306 trading bars | — |
| Confidence replay, Swing | `history_years: 4` → 1,008+10 bars | ≈306 bars in the options scan | **No**: `history_years` is inert there; ≈236 decision bars |
| Regime window, Swing / Position | 500 / 750 bars | ≈306 bars | **No**: the window is truncated to the data |
| WFO train / test | 12 / 3 months, 3 years of data (`strategy_param_optimizer.py:252`) | 12 months ≈ 252 bars ✓; 3 months ≈ **61–62 bars** (measured) | **No**: the test fold is below the 100-bar engine minimum |
| Signal warm-up in test folds | `trend_ema` up to 200, `trend_sma` 200 | the test slice carries no warm-up prefix (`walk_forward.py:128-133`) | **No** |

The production database (Postgres per `.env`) was not opened, so multi-year stored history was **not measured** in this run.

---

## The Trader

**T1. `pullback_ema` books a coin's-width target against a full stop (High).**

Its rung-1 target is the prior 20-bar swing extreme (`strategy_engine.py:495-509`). Its stop is `fast EMA − 1.5×ATR` (`:462`). When price is already at the swing high (and in a pullback-in-uptrend it often is), the target sits a few cents above entry.

Measured on SPY:
- entry 596.98, TP 597.23 (+0.04%), SL 567.14 (−5.0%);
- entry 563.09, TP 564.61, SL 539.78: planned R/R = 1.52 / 23.31 = **0.065**.

That is why the strategy shows an 82% gross win rate with negative expectancy. You need to win about 94% of the time at R/R 0.065 just to break even: 1 / (1 + 0.065).

The builder made this deliberate. `_build_target_ladder`'s docstring (`strategy_engine.py:253-264`) refuses an R-floor and says "a poor reward:risk … is real information; rr_ratio and the backtest are where it belongs." I respect the intent, but the consequence is the problem. The live stock path's only defence is the backtest gate (`stock_scan.py:439`), and when the backtest says "only N trades" the trade is dropped, not repaired. Fix within intent: keep the primary, but skip a signal whose rung-1 R/R is below a configurable floor. That rejects the signal; it does not clamp the target.

**T2. Earnings inside the holding window does not stop an options trade (High → area 3).**

`_rule_event` (`stock_scorer.py:858-904`) returns `REJECT` with score 5. But it is a weighted component (Swing weight 0.15), not a veto. Only a REJECT pullback caps status (`:1171-1175`).

Worked example from the run: AAPL Bearish Swing, 2024-11-07. Trend 70, pullback 96, trigger 20, event 5, vol 90:
0.30×70 + 0.20×96 + 0.25×20 + 0.15×5 + 0.10×90 = 21 + 19.2 + 5 + 0.75 + 9 = **54.95**, which rounds to **55 → PASS**, with earnings 3 days out.

Across all four fixtures, **37 of 440** Swing PASS bars (8.4%) stay PASS with earnings 3 days out. Step 5 paints these REJECT (`step-5-vol-events/page.tsx:247-251`), but nothing downstream reads that verdict:
- `finalStatus` is the worst of stock, contract and entry (`scan.py:142-143, 1219`);
- the Step-7 send dialog and `/auto-trade/arm` never look at events;
- the Step-7 checklist grades earnings on a **fixed** 7/3-day rule (`@contextRail/screener/step-7-trade-card/page.tsx:119-123`), so a Swing trade 10 days from earnings is REJECT on Step 5 (21-day window) and PASS on Step 7.

Unknown earnings fail **open**: no date means PASS 90 (`stock_scorer.py:879-883`). For a long call or put held through earnings, that is IV crush inside the trade.

**T3. Options target is a flat +8% move for every symbol and every horizon (Medium).**

`trade_plan.py:107-110` reads `reward_risk.bullish_target_pct: 0.08`. An Intraday preset (hold 0–2 days) and an Annual preset (165–200 days) get the same +8% target. A 1%-ATR utility and a 4%-ATR semiconductor get the same +8%. The stop side was moved to structure + 2×ATR in "piece 3" (`trade_plan.py:122-134`), but the target side was not. The card's R/R therefore mixes a volatility-aware stop with a volatility-blind target. Note the R/R risk term is `premium × 0.60` (`reward_risk.py:148`) and ignores the stock stop entirely (`invalidation_price` is "reserved", `:114`). So the headline R/R is neither the chart R/R nor the R/R at the stop.

**T4. Bearish spreads are half-built (Medium).**
- Legs get no liquidity checks at all. `build_bear_put` / `build_bear_call` pick by delta and strike only (`spread_builder.py:27-89`), with no OI, volume or spread filter, while the single-leg path hard-rejects below OI 200 / volume 50 / spread 20%.
- The primary spread's fields are attached to a card whose `contract`, `contractDetails`, `rrRatio` and `contractScore` still describe the long put (`scan.py:1257-1275, 1155-1219`). The alternative spread row copies `rrRatio=rr.rr_ratio`, the long put's (`:1367`).
- Leg pricing is natural (buy at ask, sell at bid), which is good, but the send dialog's "EST $" uses the long put's mid (`SendToBrokerDialog/index.tsx:189-191`). Neither the basket nor the direct path can route a spread: "Copy manually — IBKR multi-leg not routed" (`:236`), and the direct path sends `toOptionSymbol(card)`, the single put (`step-7-trade-card/page.tsx:1112, 1175-1185`).
- No ex-dividend / early-assignment check on the short call.

**T5. Swing DTE floor can leave one day of time value at planned exit (Medium).**

`widened_min_dte` clamps the floor at `hold_max + 1` (`dte_window.py:28-46`). For Swing (hold 5–15 days, multiplier 2.0): lo = 10, floor = max(10 − 10, 15 + 1) = **16 DTE**. The config's own rule says "Never hold an option to expiry — this buffer leaves time value at exit" (`contract_rules.yaml`, `dte_holding_multiplier`). A 16-DTE contract held 15 days exits with 1 DTE. Expiry selection aims at the centre of the window (`market.py:686+`), so this is the edge case, not the norm. Position (lo 30 → floor 46) and longer presets are fine.

**T6. Regime gate: real wiring, shaky instrument.**

The gate does gate:
- the scan demotes or drops (`stock_scorer.py:1011-1021, 1195-1204`);
- the auto-trader re-measures the traded symbol and refuses a REJECT (`auto_trader.py:1116-1388`).

The refusal needs a **Stable** regime (`require_stable_for_reject: true`), and Stable needs p_stay ≥ 0.75 estimated from a handful of transitions (Quant Q5). A −80 Fragile headwind fires at the `min_mult` floor (`auto_trader.py:1503-1508`, stated in the code).

**T7. Liquidity floors vs exit at size.**

OI 200 / volume 50 / spread ≤ 20% (`contract_rules.yaml`). The 5-contract cap (`sizing.max_contracts_per_trade`) is small relative to OI 200, so exit at size is plausible. Exit at the **assumed price** is not: R/R and targets are priced at mid both ways. On a 20%-wide market, the half-spread on exit alone is 10% of premium, which is not modelled anywhere (see the cross-parameter table).

---

## The Quant

**Q1. The WFO tuner tunes the bearish strategy and labels it bullish (High, REJECT-grade).**

The chain:
- `strategy_params.yaml` `direction: bullish` (lowercase) → `store.get_direction()` (`strategy_param_store.py:111-113`) → `run_optimization(direction="bullish")` (`routers/strategy_tuning.py:77`) → `run_strategy_backtest(direction="bullish")`.
- The engine compares `direction == "Bullish"` (`strategy_backtest.py:20`), as does every signal function. Lowercase falls to the bearish branch.

Measured on SPY `pullback_ema`:
- `"Bullish"` → 11 trades, 82% win, −0.124% expectancy;
- `"bullish"` → 2 trades, 100%, +3.084%, **identical to `"Bearish"`**.

A lowercase signal sample came back with entry 562.14, stop 588.98, target 541.82: a short.

Then "Adopt" posts no direction (`frontend/lib/api.ts:1157-1158`), the router defaults to `"Bullish"` (`routers/strategy_tuning.py:26, 187`), and `adopt()` writes `active.bullish` (`strategy_param_store.py:152`). So every adopted proposal puts **bearish-optimised params into the bullish slot**.

**Q2. Walk-forward out-of-sample never runs on real data (High, REJECT-grade).**

With the shipped `test_months: 3`, a test fold holds 61–62 trading bars (measured on the SPY fixture: folds 2024-10-30→2025-01-30 = 61, 2025-01-30→2025-04-30 = 62). The OOS loop skips any slice under 100 bars (`strategy_param_optimizer.py:122`), and so does the engine (`strategy_backtest.py:89-90`).

So `test_returns` is always empty. Then `consistency([]) = 0.0` (`walk_forward.py:266-267`), `n_trades = 0`, `eligible = False`, and every proposal reads "Edge looks fake — consider dropping" (`strategy_param_optimizer.py:47-50`). The fold winner is still chosen in-sample and can still be adopted.

Even at `test_months ≥ 5`, the test slice has no warm-up prefix (`walk_forward.py:128-133`). A `trend_ema: 200` combo cannot fire inside a 100-bar slice. The non-overlap of folds is correct (`build_folds`, `walk_forward.py:69-86`); the problem is that the test half is empty.

**Q3. Multiple testing.**

Grid sizes per strategy, from `strategy_params.yaml` `search`:
- `pullback_ema` 3×3×3×3×4 = **324**;
- `breakout_base` 3×4×3×4 = **144**;
- `mean_reversion_bb` 3×3×2×3 = **54**;
- `ma_crossover` 2×2×2×3 = **24**;
- `mean_reversion_rsi` 2×3×2×2 = **24**.

Total **570 combos per fold**, about 8 folds over 3 years at 12/3 months: (36 − 12) / 3 = 8. The only correction is a complexity penalty of at most 0.05 Sharpe per parameter at grid edges (`walk_forward.py:136-176`), applied before selection. There is no deflated Sharpe, and since Q2 there is no working OOS check.

Plain-English deflated Sharpe: the best of 324 noisy backtests looks good by luck alone. A deflated Sharpe subtracts what luck would hand you for that many tries.

The basket is drawn from today's `sp500.csv` (`strategy_basket.py:5`), which is survivorship bias: past losers that left the index are missing.

**Q4. Confidence replay counts overlapping days as independent samples, on about one year of data (Medium).**

`compute_confidence` (`signal_confidence.py:209-286`) scores every bar where `score_stock(...).status == "PASS"`. A setup that stays PASS for 10 straight days contributes 10 samples whose 10-day forward windows overlap 9/10. `min_samples: 20` can therefore be met by two or three distinct setups.

In the options scan the bars come from a 441-calendar-day window (`scan.py:1659`), about 306 bars. With warm-up 60 and n_days 10, about 236 decision bars remain, so `history_years: 4` (`scoring_rules.yaml` `confidence_backtest.swing`) never binds. One year is one regime.

Intervals on the gate's own minimum (p ± 1.96·√(p(1−p)/n)):
- n = 20, p = 0.5 → ±21.9 points;
- n = 10 (the backtest gate), p = 0.5 → ±31 points.

On the one combo that cleared n = 10 (SPY `pullback_ema` Bullish, n = 11):
- gross p = 0.82 → ±22.7 → **[59%, 100%]**;
- net p = 0.545 → ±29.4 → **[25%, 84%]**.

That is noise, and the gate correctly refuses it on expectancy.

**Q5. The regime model's transition row is a handful of observations (Medium).**

`compute_omm` builds the matrix from **stride** samples, one per `lookback` bars (`regime_omm.py:94-114`). Computed:
- Swing (lookback 20) on ≈306 bars → 16 samples → 15 transitions spread over 3 states;
- Position (lookback 50) → 7 samples → **6 transitions**.

On the fixtures, the current state's row held 0–5 transitions. MSFT Position published **conviction −50 from 2 transitions** (p_stay 0.5, Fragile). That one number drives the headwind CAUTION, and sizing at the floor via `conviction_mult`.

"Stable" (p_stay ≥ 0.75) on 3–5 observations is a coin flip, and the REJECT arm depends on it. The `min_obs: 100` check counts **daily** labels (`regime_omm.py:208-210`), not the stride transitions the row is built from, so it does not protect the row. Labels are causal (rolling past return), so no lookahead. The HMM (`regime_hmm_daily.py`) is used only for the "alignment" display (`scan.py:658-673`).

**Q6. Confidence cut-offs ignore the payoff asymmetry the replay itself uses (Medium).**

The barriers are a 3.0 ATR target vs a 1.5 ATR stop (`confidence_backtest.swing`), so break-even hit rate = 1.5 / (3.0 + 1.5) = **33.3%**. Confidence ≈ `hit_rate × min(1, payoff)` (`signal_confidence.py:166-172`), and the payoff is usually ≥ 1 because wins are ≥3 ATR excursions and losses ≥1.5. So confidence ≈ hit rate.

`cautionBelow: 50` therefore demotes setups whose replay shows up to 0.5×2 − 0.5×1 = **+0.5R** per trade. `rejectBelow: 35` sits just above break-even. The `min(1, …)` cap also means a strong payoff earns nothing while a weak one is penalised. Status: **uncalibrated**. Nobody has measured whether a 70 hits 70%.

**Q7. Costs.**

Stocks are charged 0.2% per leg, 0.4% round trip (`stock_scan.py:203-209`). Against the measured `pullback_ema` targets of +0.04–0.5%, that cost **is** the expectancy: SPY gross 82% win becomes 55% net. Options are never backtested at all. The confidence replay prices the underlying, not the contract, so no option cost (spread up to 20%, theta) enters any evidence the options path shows.

**Q8. Monte Carlo drift is assumed, not measured.**

`mu = sign × (trend_score − 50) / 50 × 0.40` annualised (`first_passage.py:384, 847`). That is a modelling choice; the code says so itself (`first_passage.py:828-830`). The sigma floor 0.10 and ceiling 1.50 (`risk_rules.yaml first_passage`) can mask bad ATR inputs. Hit probabilities from it are **uncalibrated**.

**Q9. Lookahead.**

None found:
- `backtesting.py` fills on the next bar;
- the signal slice is `bars[:i+1]` (`strategy_backtest.py:115-126`);
- the confidence replay uses `bars[:i+1]` for the signal and `bars[i+1:i+1+n]` only for the outcome (`signal_confidence.py:268-276`);
- OMM labels are trailing.

The leakage and lookahead tests pass (94/94).

---

## The Risk Manager

**R1. Per-trade loss limit vs position cap: one trade can blow through the limit with no hard stop (High, REJECT-grade).**

The two settings:
- `max_single_position_pct: 0.05` caps option **premium** at 5% of the account (`portfolio_risk.py:136-157`);
- `max_loss_per_trade_pct: 0.0375` is "warning-only, never auto-clamps" (`risk_rules.yaml` comment).

The backend never checks the loss limit (no reader in `portfolio_risk.py` or `position_writer.py`). The frontend checks it only once an exit plan has been computed, and offers "Override & Submit" (`lib/risk.ts:595-615`; `SendToBrokerDialog/index.tsx:138-145, 296-299`).

There is no protective order anywhere (orders are MKT/LMT only, `broker.py:181, 202`). The premium stop is an alert (`alert_generator.py:310-353`). So a long option at the cap can lose 5.0% of the account, which is **1.33×** the per-trade limit, with no hard stop. The design is deliberate, and still REJECT, because this is exactly the "loss limit a single trade can blow through" case.

**R2. Losing-streak arithmetic (non-compounding; see R3 for why that is the honest assumption).**

| Basis | Loss per trade | −10% after | −20% after |
|---|---|---|---|
| Option at 5% cap, premium stop ignored (no broker stop) | 5.00% | **2** losers | **4** losers |
| Option at 5% cap, 60% premium stop honoured manually | 3.00% | 4 (12%) | 7 (21%) |
| `max_loss_per_trade_pct` 3.75% | 3.75% | 3 (11.25%) | 6 (22.5%) |
| Stock, default 1% risk × conviction mult ≤ 1 (`stock_scan.py:1342-1364`) | ≤1.00% | 10 | 20 |

Options total exposure is capped at 25% (`max_total_exposure_pct`), i.e. 5 full-size positions. If all five are long beta and the market gaps, the book can lose up to 25% before any human acts. Stocks: total 100%, single 20% (`risk_rules.yaml`). A 20% name gapping 20% through its stop costs 4% of the account against a planned 1%.

**R3. Every % cap multiplies an account value the client types (Medium).**
- `create_position` passes `portfolio_value=body.portfolioValue` (`position_writer.py:443-451`). The schema default is **50,000** (`schemas/__init__.py:1019`).
- `ArmRequest.portfolio_value` defaults to **50,000** (`routers/auto_trade.py:127`). The frontend sends `useRiskStore` `limits.portfolioValue` from localStorage (`frontend/lib/portfolioStore.ts:205`, `AutoTradeArm/index.tsx:370`), default **100,000**.
- It syncs with the YAML only when the Settings page mounts (`settings/page.tsx:1155-1186`). `updateLimit` writes the store before Save (`:1190-1194`), so an unsaved edit already loosens the server cap.
- The value is never tracked from P&L (`riskStore.ts:54-58`), so after a drawdown every cap still multiplies the pre-drawdown number. Sizes do not shrink as the account does.
- `risk_rules.yaml portfolio.portfolio_value: 100000` is read only by the stock exit-plan risk budget (`stock_scan.py:2430-2432`) and Settings.

**R4. The daily-loss "circuit breaker" is a premium-spend cap, auto-trader-only, in memory (Medium).**

`_check_daily_loss` sums `premium_at_risk` over **today's in-memory history** (`auto_trader.py:3087-3131`; history is in-memory, `:2993`). A process restart resets it. It never counts realised losses, manual sends, or the basket. 2% of the typed account value per UTC day caps what the auto-trader can deploy. That is conservative for the auto path (it blocks any single 5% trade), but the manual path has no daily limit at all.

`max_daily_recommendations: 5` is likewise never passed server-side: `daily_recommendation_count` defaults to 0 and no caller supplies it (`portfolio_risk.py:76, 108`). It is enforced only in the frontend counter, which is overridable.

**R5. Sizing is regime-aware, not volatility-aware, for options (Low/Medium).**

The option quantity is whatever the trader types, capped at 5 contracts and 5% premium. The conviction ramp `min_mult + (1 − min_mult)(conv + full) / (2·full)` (`scoring_rules.yaml regime_sizing`) scales the auto-trader's quantity on the noisy Q5 number. A high-vol name gets the same contract count. The stock side **is** vol-aware via stop distance (`stock_scan.py:1085-1101`).

**R6. Missing data, gate by gate.**

| Gate | Input missing | Behaviour | Verdict |
|---|---|---|---|
| Event / earnings | no date | PASS 90 (`stock_scorer.py:879-883`); yfinance fallback tried first (`scan.py:603-608`) | **fail-open** |
| IV (stock vol rule) | no IV | CAUTION 50 (`stock_scorer.py:968-969`) | soft |
| IV (contract ceiling) | no IV | ceiling skipped (`contract_validator.py:130`); scan back-fills a BS IV (`scan.py:786-804`) | mostly covered |
| Contract liquidity | no volume / OI / quote | treated as 0 → hard reject (`contract_validator.py:87-110`) | **fail-closed** ✓ |
| Regime (scan) | no signal | gate skipped (`scan.py:728, 836`); Intraday with no bars is dropped (`:703-707`) | fail-open (daily) |
| Regime (auto-trader) | bars missing | refuses (`RegimeDataUnavailableError`); unmeasurable → abstains but sizes at the **floor** (`auto_trader.py:1486-1501`) | balanced ✓ |
| Fundamentals | no EDGAR record | gate skipped (`stock_scorer.py:1207`) | fail-open |
| Confidence | n < 20 | `confidence=None` → cap PASS (`signal_confidence.py:203`) | fail-open |
| Config blocks | malformed | money blocks refuse (`money_config.py`; `auto_trader.py:1173-1297`) | **fail-closed** ✓ |

---

## Execution safety (Risk Manager, continued)

**E1. "Send basket" reports orders sent; none are (High).**

`handleSubmit` (`step-7-trade-card/page.tsx:1279-1375`) calls only `addPosition`. It writes a Portfolio row tagged `source: 'broker'` (`:189`) and never calls `/broker/option-order`. The only order call on the page is the direct path (`:1175`). The toast then says "**{auto} sent to broker**" (`:1683`). The file header calls it "(sent to broker mock)" (`:7`, and `SendToBrokerDialog/index.tsx:7`).

Consequences:
- the trader believes they are in, and they are not;
- the phantom rows count against `max_concurrent_positions`, the duplicate-symbol rule and total exposure (`portfolio_risk.py:115-133`), blocking real trades;
- every STOP / TP alert fires on a position that does not exist.

**E2. The auto-trader's "market closed or halted" guard is a price-exists check (Medium).**

`_market_is_open` returns True whenever `fetch_price` returns > 0 (`auto_trader.py:418-441`). `fetch_price` falls back to `quote.close`, then yfinance `last_price or previous_close` (`data/market.py:665, 680`). So it passes on weekends, after hours and during a halt. A real session clock exists (`strategy_watch_scheduler._market_open`, re-exported by `market_session.py:39`) and is not used here. Because the fire disarms first (`auto_trader.py:2336-2341`), a DAY order the broker rejects or queues still consumes the arm.

**E3. No protective orders; exits are alerts (Medium, deliberate).**

Stated in the code: "The auto-trader places no protective order" (`auto_trader.py:3096-3100`). Overnight gaps, regime flips with open positions (`regime_monitor.py` broadcasts a WebSocket warning, `:5`), and premium stops are all notifications (Gmail / Telegram / WebSocket). They need a human awake.

**E4. What is done well (verified).**
- Idempotent order endpoints with a natural-key claim (`broker.py:58-128`).
- IBKR "confirmation question" treated as not-placed (`broker.py:139-172`; `auto_trader.py:2201-2210`).
- Pre-broker vs may-have-landed failure split (`auto_trader.py:2160-2211, 2593-2664`).
- A may-have-landed order books its full premium against the daily budget (`:2642-2652`).
- Double-fire prevention via disarm-under-lock plus `expect` identity (`:2304-2341`).
- Stale-arm expiry with alert (`:2780-2841`).
- The direct send saves before it orders and deletes the row when the order provably failed (`step-7-trade-card/page.tsx:1124-1225`).

This is careful engineering.

**E5. Server-side risk on the broker endpoints.**

`/broker/stock-order` and `/broker/option-order` run **no** risk check of their own (`broker.py:217-349`). The UI's path runs the portfolio-save check first, but any other client can place an unchecked paper order. Low today (single-user, local), Medium once live keys exist.

---

## Cross-parameter table

| Check | Values (file:line) | Consistent? | Severity |
|---|---|---|---|
| Per-trade loss vs single-position cap | `max_loss_per_trade_pct 0.0375` (warning-only) vs `max_single_position_pct 0.05` premium, no protective order | **No**: one trade can lose 5% > 3.75% | **High** |
| Per-trade loss vs daily loss | 3.75% per trade vs `auto_trade.max_daily_loss_pct 0.02` | Auto path: the 2% premium cap blocks any trade over 2%. Manual path: no daily gate | Medium |
| Stock vs option caps | options 5% single / 25% total on premium; stocks 20% / 100% on notional; each judged only against its own kind (`portfolio_risk.py:103-106`) | No combined cap; worst case 25% premium + 100% stock notional at once | Medium |
| Backtest costs vs allowed liquidity | stocks 0.2% per leg; options: none modelled, yet the filter accepts spreads ≤ 20% (`contract_rules.yaml`) and entry at mid (`entry_quality.py:69`) | **No**: half-spread on exit up to 10% of premium, unpriced | Medium |
| WFO windows vs data | train 12m (≈252 bars) ✓; test 3m (≈61–62 bars) | **No** | **High** |
| WFO windows vs code minimums | engine and OOS loop require ≥100 bars (`strategy_backtest.py:89`; `strategy_param_optimizer.py:122`) vs 3-month test | **No**: every OOS fold silently skipped | **High** |
| Minimum-trade gates | backtest 10 (`strategy_backtest.py:24`), optimizer 20 OOS per symbol (`strategy_params.yaml optimization`), confidence 20 **overlapping** (`scoring_rules.yaml`) | Inconsistent; at n=10 the 95% interval is ±31 pts | Medium |
| Stop definitions | options card: structural / 2×ATR stock stop (`scan.py:1007-1028`); R/R risk = 60% premium (`reward_risk.py:148`); premium-stop alert = entry×(1−0.60); auto-trader daily gate = 100% premium; Step-7 checklist R/R ≥2.0 | Four stops, and the headline R/R uses one the trader does not see on the chart | Medium |
| DTE vs holding horizon | `dte_holding_multiplier 2.0`; floor clamp `hold_max+1` (`dte_window.py:43-45`) | Swing can land at 16 DTE for a 15-day hold | Medium |
| Config vocabulary vs code | `strategy_params.yaml direction: bullish` vs `== "Bullish"` (`strategy_backtest.py:20`) | **No**: the wrong branch runs | **High** |
| Account value basis | YAML 100,000; schemas default 50,000 (`schemas/__init__.py:1019`, `auto_trade.py:127`); frontend localStorage 100,000 | Three sources; server trusts the client | Medium |
| Event window vs its mirrors | scan Swing 21/45d (`scoring_rules.yaml`); Step 5 uses the scan's echoed window ✓; Step-7 rail fixed 7/3d (`@contextRail/…/step-7-trade-card/page.tsx:123`) | **No** | Medium |
| Score thresholds vs mirrors | YAML 55/35, 50/35 = `status.ts:31`, `confidenceText.ts:4-11`, `SCORING_RULES.md:195-197` | Yes | — |
| Regime window vs data | `regime.swing.window 500`, `position 750` vs ≈306 bars fetched (`scan.py:1659`) | Window never reached | Low/Medium |
| Confidence `history_years` vs data | Swing 4y vs ≈306 bars in the options scan | Inert there | Low |
| Dead or unmeasured config | dead: `regime.enhanced_states`, `pullback.max_days_in_pullback`, `pullback.theta_caution_days` (only in `config_health.py:127` key list), `auto_trade.premium_stop_pct` (marked NOT READ), `gap_threshold_pct` (marked intentional). Unmeasured and live: `max_iv_rank`, `iv_rank_*`, `bearish_min_trend`, `stop_premium.pass_max_fraction` (all marked UNMEASURED in YAML) | Marked honestly; the unmeasured ones sit in live gates | Low |

---

## Stress test

| Scenario | What the code does | Exposure |
|---|---|---|
| Clean uptrend | Bullish setups pass. `pullback_ema` puts rung 1 at the prior swing high: median planned R/R 0.11 on SPY. The options target is a flat +8% | Stock side: many small wins, few large losses, negative net expectancy measured on SPY. Options: fine if the move comes |
| Downtrend | Bearish mirrors: `bearish_min_trend` 30/40 is UNMEASURED (YAML); spreads offered but not routable | Long puts only, in practice |
| VIX 20 → 40 | No VIX input to the gate. Symbol IV: Swing vol rule CAUTION above 34, REJECT above 55 absolute; contract hard-reject above 70 absolute IV. Regime = symbol's 20-day return label; sizing on the conviction ramp | Long premium bought at elevated IV until 55/70; not handled at the portfolio level |
| Earnings inside the hold | Options: score penalty only; 8.4% of measured PASS setups survive with earnings in 3 days; unknown date = PASS. Stocks: event weight 0 by design | **Not handled for options**: IV crush plus gap on up to 5% of account per position |
| Overnight gap through the stop | `regime_monitor._check_overnight_gaps` alerts (`regime_monitor.py:145-197`); no broker stop | Options: up to 100% premium (5% of account). Stocks: unbounded below the stop (20% position) |
| Trading halt | `_market_is_open` passes on last price; the fire disarms and sends | Order rejected or queued at the broker; arm consumed; alert sent |
| Regime flip with open positions | WebSocket warning once the sustain clock passes (`regime_flip_sustain_minutes: 0`); no auto-exit | Human-dependent |
| Broker API down at order time | Auto: `not_submitted` vs `order_failed` rows plus alerts, full premium booked on may-have-landed (`auto_trader.py:2593-2664`). Direct: save first, classify, delete or keep with note | **Handled well** |

---

## The Chair

**Where the voices disagreed, and who is right.**

1. *`pullback_ema`'s tiny targets.* The Trader calls it broken. The builder's docstring calls it honest information that the backtest should judge. The Quant sides with the builder on mechanism: the gate did refuse SPY on expectancy. **The Trader is right on consequence.** When a strategy needs a 94% win rate to break even, every one of its signals is a near-certain cost drag, and the gate only catches it when n ≥ 10. On a 5-year live history most symbols will show "Only N trades" and drop, which hides the defect rather than fixing it. Deliberate, and still a High: fix it within the intent by skipping signals below an R floor, not by clamping targets.

2. *The daily-loss limit.* The predecessor called it a real circuit breaker. The Risk Manager calls it a spend cap. **The Risk Manager is right**: it never sees realised P&L, forgets on restart, and does not cover two of the three send paths. It is still a useful guard on the auto path.

3. *Per-trade loss vs position cap.* The YAML marks the loss limit warning-only on purpose. **Deliberate, and still REJECT**: with no protective order, the 5% premium cap is the real per-trade loss limit, and it is above the stated 3.75%.

4. *Regime gate.* The Trader credits the wiring (it really gates, in both scan and fire). The Quant says the instrument is too noisy to trust. **Both are right.** Grade the wiring PASS and the measurement CAUTION. Lengthen the data window before tightening any threshold.

**Deliberate choices respected:** event weight zero for stocks; the DTE floor equality; fail-closed money blocks; sizing at the floor when the regime is unmeasurable; IV basis split; UNMEASURED thresholds clearly labelled. None of these is graded as a bug.

---

## Fix list (worst first)

| # | Severity | Area | Problem | Fix | Why it costs money |
|---|---|---|---|---|---|
| 1 | High | 2 | WFO tunes the bearish branch for bullish (`direction: bullish` vs `"Bullish"`) and Adopt writes it into `active.bullish` | Normalise direction once (`.capitalize()`) at `get_direction()` / `run_optimization`; make Adopt send the proposal's direction; add a test with lowercase input | Adopted params trade the opposite thesis |
| 2 | High | 2 | OOS folds (61–62 bars) below the 100-bar minimum; no warm-up prefix | Slice test bars with a warm-up prefix of max indicator period, and judge only trades entered inside the test dates; or raise `test_months` and lower the guard. Test on trading-day bars | Every proposal is in-sample only |
| 3 | High | 3 | Earnings inside the reject window is not a veto; unknown earnings = PASS; Step-7 rail uses a 7/3-day window | Make event REJECT cap `finalStatus` on the options path, block arm and send on it, treat an unknown date as CAUTION, and make the rail read the scan's echoed window | IV crush and gap inside the trade |
| 4 | High | 4 | 5% premium cap > 3.75% per-trade loss limit, warning-only, no stop order | Size options so `premium × contracts ≤ max_loss_per_trade_pct × account` (long premium can lose 100%), or make the limit a server-side hard check | One loser exceeds the stated limit |
| 5 | High | 5 | Basket "Auto-send" places no order but says "sent to broker" | Route auto rows through the direct send path (save → order → classify), or relabel as "tracked, not sent" and tag rows `manual` | Phantom positions; real trades blocked by phantom caps |
| 6 | High | 1 | `pullback_ema` rung-1 R/R median 0.11 on SPY, 95% of signals < 1:1 | Configurable min rung-1 R/R per strategy (skip the signal, don't clamp); re-tune after fix #1/#2 | Wins too small to pay costs |
| 7 | Medium | 4 | Server caps trust the client's `portfolioValue`; defaults 50k vs 100k; never updated from P&L | Read the account value server-side (YAML, or the broker balance when live); ignore or validate the client value; one default | Caps loosen silently; no shrink after drawdown |
| 8 | Medium | 5 | `_market_is_open` passes on last close | Use the real session clock plus a halt flag from the quote; check before disarm | Orders after hours / in halts consume the arm |
| 9 | Medium | 4 | Daily-loss gate: in-memory, auto-only, spend not loss | Persist history; include manual sends; count realised losses | Limit resets on restart; manual path unlimited |
| 10 | Medium | 2 | Regime row from 0–15 transitions; windows truncated to ≈306 bars | Fetch ≥ window bars for regime; use overlapping counts with an autocorrelation-aware interval, or require a minimum number of transitions per row before publishing | Gate and sizing decided on noise |
| 11 | Medium | 2 | Confidence replay counts overlapping days; 50/35 cut-offs ignore 2:1 payoff | Count distinct setups (de-overlap by n_days); gate on replayed expectancy in R, not hit rate | Good setups demoted, weak ones pass on luck |
| 12 | Medium | 3 | Spreads: no liquidity checks on legs, wrong R/R on the card, not routable | Run `validate_contract` hard rules on each leg; compute spread R/R from net debit/credit; hide Send until multi-leg is routed | Illiquid short legs; misleading R/R |
| 13 | Medium | 1 | Options target flat +8% for every horizon and symbol | ATR or structure-based target matching the stop basis | R/R overstated on low-vol names, understated on high-vol |
| 14 | Medium | 3 | Swing DTE floor 16 for a 15-day hold | Floor at `ceil(hold_max × multiplier × k)` (k < 1), not `hold_max + 1` | Theta and gamma at exit |
| 15 | Low | 2 | `summary_text` labels % expectancy as `$` (`strategy_backtest.py:189`) | Fix the label | Misread evidence |
| 16 | Low | 4 | Dead config keys (`enhanced_states`, `max_days_in_pullback`, `theta_caution_days`) | Remove, or mark NOT READ like the others | Trader may tune a knob that does nothing |

---

## Not measured

- **Multi-year real performance.** Only 251-bar fixtures were available locally (the app DB is Postgres via `.env`, not opened). *Measure:* run the same matrix on 5+ years from `historical_store` for a 50-name basket, net of 0.2% per leg.
- **Option-level P&L of any strategy.** No backtest prices the contract (spread, theta, IV changes). *Measure:* replay recorded chains, or at minimum BS-reprice at entry and exit with the historical IV proxy and a half-spread charge.
- **Confidence calibration** (does 70 hit 70%?). *Measure:* bucket historical confidence against realised outcomes on distinct setups.
- **Regime model predictive value.** *Measure:* the forward 20-day return conditional on the published state and conviction, out of sample.
- **Heston / BS repricing error at targets.** The Heston fit is used only when `method == "heston_grid"` (`scan.py:983`). *Measure:* the predicted vs observed option price at a later date.
- **Monte Carlo hit probabilities** (drift assumed from score). *Measure:* calibration of the predicted P(hit) against realised outcomes.
- **Actual WFO output on live data.** The tuner was not run (no DB, and it would also exercise bug #1).
- **Fill quality at mid** on OI-200 / 20%-spread contracts. *Measure:* paper fills vs mid at order time.
- **Fundamentals scorer correctness** (EDGAR parsing) — not reviewed.

---

## Coverage

**Tested by running (this session)**
- Quant regression suite (9 files, 94 tests).
- `run_strategy_backtest`: 5 strategies × 2 directions × 4 symbols × gross/net.
- Per-trade detail for SPY `pullback_ema`.
- Planned R/R of every signal (`pullback_ema`, `ma_crossover`, `breakout_base`).
- Lowercase-direction reproduction.
- WFO fold bar counts on real data.
- `score_stock` with and without an earnings date (440 PASS bars).
- `compute_omm` transition counts and fixture outputs.
- Confidence intervals and losing-streak arithmetic (shown above).
- `scripts/state.py`: no drift.

**Read (logic reviewed)**
- `backend/app/routers/scan.py` (symbol pipeline, spreads, bars window).
- `routers/broker.py`, `routers/auto_trade.py` (ArmRequest).
- `routers/stock_scan.py` (gate, sizing, cost, multi-signal; partial).
- `routers/strategy_tuning.py` (job and adopt).
- `routers/risk_settings.py` (load/save; partial).
- `services/auto_trader.py`: fire, sizing, gate, daily loss, market check, scan trigger.
- `services/portfolio_risk.py`; `services/position_writer.py` (risk and premium-stop sections).
- `services/regime_omm.py`; `services/strategy_backtest.py`; `services/walk_forward.py`; `services/strategy_param_optimizer.py`; `services/strategy_param_store.py` (direction, adopt).
- `services/strategy_engine.py` (`pullback_ema_signal`, `_build_target_ladder`).
- `scoring/stock_scorer.py` (event, vol, regime cap, score_stock); `scoring/signal_confidence.py`; `scoring/contract_validator.py` (hard rejects); `scoring/spread_builder.py`; `scoring/trade_plan.py`; `scoring/reward_risk.py` (`estimate_rr`); `scoring/entry_quality.py`; `scoring/dte_window.py`.
- `data/market.py` (`fetch_price`, `fetch_candles_async`).
- All `backend/config/*.yaml` except credentials.
- Frontend:
  - `SendToBrokerDialog`;
  - `step-7-trade-card/page.tsx` (basket, direct send, toast);
  - `step-5-vol-events/page.tsx` (event gate);
  - the Step-7 `@contextRail` checklist;
  - `lib/risk.ts` (`checkTradeRisk`), `lib/riskStore.ts`, `lib/portfolioStore.ts` (account value);
  - `lib/horizonPresets.ts`, `lib/status.ts`, `lib/confidenceText.ts`;
  - `settings/page.tsx` (risk sync).
- `SCORING_RULES.md` thresholds; `.github/workflows/ci.yml`.

**Skimmed (header and purpose only, not graded in depth)**
- `scoring/first_passage.py` (drift line read), `scoring/conviction_sizing.py` (header and formula), `scoring/structural_stop.py`, `scoring/exit_plan.py`, `scoring/stop_cost.py`, `scoring/reprice_horizon.py`.
- `services/regime_gate.py`, `services/regime_hmm_daily.py`, `services/regime_monitor.py` (function list), `services/fundamentals_gate.py`, `services/strategy_basket.py`, `services/picked_method.py`, `services/portfolio_alert_monitor.py`, `services/strategy_watch_evaluator.py`, `services/composite_trigger_evaluator.py`, `services/auto_trade_booking.py`, `services/broker_router.py`, `services/alert_generator.py` (stop alerts), `services/config_health.py` (key list).

**Not reviewed in this run (by name, with reason)**
- **Broker adapters** `data/ibkr_paper.py`, `tradier_paper.py`, `alpaca_paper_execution.py`, `tastytrade_paper.py`, `tastytrade_bridge.py`, `ibkr.py`, `alpaca.py`: order-translation internals. Only their interface and error contract were checked.
- **Scoring internals not on a finding path:** `scoring/fundamentals_scorer.py` (EDGAR math), `models/heston*`, `services/market_structure.py`, `services/indicator_compute.py`, `services/alert_evaluator.py`; the trend / pullback / trigger rule internals in `stock_scorer.py` (only outputs exercised); `strategy_engine.py` bodies for `breakout_base`, `ma_crossover`, the mean-reversion family, `breakout_setup` and `_fibonacci_pullback` (Pre-Breakout mode), exercised by running only.
- **Partially or not read:** `routers/contracts.py` (recompute endpoint, shares `build_trade_plan`); `routers/portfolio.py`; `routers/stock_scan.py` beyond the sections cited.
- **Out of trading-logic scope:** schedulers (`edgar_`, `sp500_`, `tuning_`, `scan_schedule_`, `ingestion_`, `strategy_watch_`, `chart_alert_`, `ibkr_keepalive_`), `services/notifications/*`, `credential_store.py`, `historical_store.py` internals, and the routers for alerts, chart, chart_alerts, chart_drawings, journal, news, sectors, symbols, symbol_notes, watchlist, watched_contracts, ws_alerts, events, health, data_sources, ingestion, historical_data, scan_schedule, notification_settings, candles, config, credentials, tradecards, composite_watch, strategy_watch, regime.
- **Frontend outside the order and risk path:** Step 1–4 and Step 6 pages, Stocks-mode Steps 4–7 UI, `StockSendDialog`, `StockAutoTradeArm`, `AutoTradeArm` (only the `portfolio_value` line), and the Pre-Breakout UI.

Next run: re-verify fixes #1–#6 first, then extend coverage to the stock-mode send path (`StockSendDialog`, `StockAutoTradeArm`) and the broker adapters.
