# Bamendjou Trading Review

**Date**: 2026-10-02 · **Commit**: b036a36 · **Mode**: A full
**Method**: k-trading-software-reviewer v1

## Overall: **REJECT**

> The setup scoring is honest work, but the walk-forward tuner can't produce a single out-of-sample trade and would tune the wrong side if it could, the earnings "reject" never blocks a long option, and once real money is on there is no stop order at any broker.

| Area | Grade | Why, in one line |
|---|---|---|
| 1. Edge & strategy logic | **CAUTION** | The scoring stack hangs together; the regime gate drops out silently when the regime can't be measured, and pullback_ema's targets sit so close that 0.4% of costs turns winners into losers. |
| 2. Statistical evidence | **REJECT** | The WFO out-of-sample step never runs (65-bar test windows against a 100-bar guard), and the tuner passes `"bullish"`, which every signal function treats as Bearish. |
| 3. Options & contract selection | **REJECT** | Earnings inside the event "reject" window only costs points (9 measured Swing PASSes with earnings 5 days out); a missing earnings date scores full marks; Swing/Position DTE floors leave 1 day of time value at max hold. |
| 4. Risk parameters & sizing | **CAUTION** | Caps are real hard blocks, but the 3.75% per-trade loss limit is warning-only and sits below the 5% option premium cap, stocks and options together can reach 125% of the account, and the account value is typed by hand. |
| 5. Execution safety | **REJECT** | No protective order at any broker (stops are 60-second alerts), bearish stock trades open uncapped shorts, the auto-trader's daily limit lives in memory, and the "halt" check only tests whether a quote exists. |

Overall = worst area = REJECT. The system is **paper-only today** (every broker key is `*_paper`, live is locked at `backend/app/routers/broker.py:365-368`; the auto-trader accepts only paper brokers, `backend/app/routers/auto_trade.py:77`). This review grades what happens when live money is switched on (rule 7).

## Since last run (2026-08-19, `TRADING_QUALITY_BENCHMARK.md`, round 4)

The predecessor graded three axes; its findings carry over, its grades don't. Its "code quality" axis is out of scope here and was not re-graded.

- **Fixed (re-verified)**
  - `min_stock_score` raised to 55: `backend/config/contract_rules.yaml:43`.
  - `breakout_base` tight-base gate no longer impossible: `atr_tight_max: 4.0` (`strategy_params.yaml`, `breakout_base.active`). It fires 0–2 times per symbol-year on the fixtures (table below).
  - Live Step-6 backtest is cost-aware: `_backtest_commission()` = fee 0.001 + slippage 0.001 = 0.002 per leg (`backend/app/routers/stock_scan.py:203-209`), passed at `:839-850`.
  - Frontend mirrors match the YAML: `frontend/lib/status.ts:31` (55/35), `frontend/lib/confidenceText.ts:10-11` (50/35), `SCORING_RULES.md:169-170,195-197`.
- **Still open**
  - *No real-data evidence any strategy clears its significance bar.* Re-measured: now 1 of 20 strategy×symbol pairs reaches 10 trades (SPY `pullback_ema` Bullish, 11 trades), and it has **negative** net expectancy. Unchanged cause: 251-bar fixtures.
  - *`signal_confidence` is a single in-sample replay* (`backend/app/scoring/signal_confidence.py:254-276`). Still true, plus two new problems (Quant §3).
  - *Complexity penalty untested against real optimizer runs.* Still untested, and moot until the tuner can score out of sample.
- **Predecessor claims this run overturns**
  - "OOS eligibility requires n_trades>=20 and consistency>=0.5, both wired into the recommendation verdict, not decorative." It is wired, but the OOS backtest it reads never runs. Measured: `n_trades: 0`, `consistency 0.0` on every run (Quant §1).
  - "Real circuit breaker, enforced in `auto_trader.py`." It is enforced, but it caps premium *deployed* by the auto-trader, it is held in memory (lost on restart), and manual sends never touch it (Risk §2).
  - "DTE: confirmed intentional design." The equality of `min_dte` and `preferred_dte_min` is intentional. The new finding is different: the `hold_max+1` floor leaves one day of time value (Trader §3).
- **New**: the WFO direction-case bug, the empty OOS step, the event non-veto, the event and regime fail-opens, overlapping confidence samples, the DTE floor, display-only spreads, the 5% vs 3.75% contradiction, the 125% combined exposure, uncapped stock shorts with no broker stop, the in-memory daily limit, the quote-only "halt" check, and the ungated `/broker/*` endpoints. All detailed below.

## The thesis

Bamendjou hunts **trend-aligned pullback-and-trigger confluence**: trend + pullback + momentum trigger, weighted per horizon, filtered by event proximity, IV, fundamentals and a per-symbol Markov regime (`backend/app/scoring/stock_scorer.py:1135-1167`, `backend/config/scoring_rules.yaml`). It trades three things:
- **Options**: single-leg long calls (Bullish) and long puts (Bearish), bought at mid (`backend/app/scoring/entry_quality.py:71`).
- **Bear spreads**: built and shown on Bearish cards only (`backend/app/routers/scan.py:380-462`). They are **display-only**: the order schema carries one `option_symbol` (`backend/app/routers/broker.py:192-206`).
- **Stocks**: long, and short via SELL/OPEN for bearish (`frontend/lib/stockDirectSend.ts:174-175`), risk-sized at 1% × a regime multiplier.

The auto-trader is options-only and buy-to-open only (`backend/app/routers/auto_trade.py:93`, `backend/app/services/auto_trader.py:2182`). It deliberately leaves out naked option selling, multi-leg execution and intraday stock VWAP backtesting on daily bars.

## Evidence gathered

- **Quant suite**: `cd backend && .venv/bin/python -m pytest -q` over all 9 files matching leak/lookahead/walk_forward/confidence/strategy_backtest → **94 passed, 1057 warnings** (95 s). CI runs the full backend `pytest` on push/PR to main (`.github/workflows/ci.yml:22-25`), so these run in CI. **None of them catches the two High WFO bugs below.** `tests/test_walk_forward.py:129,284,316` itself passes lowercase `"bullish"`.
- **Real-data backtest**: `run_strategy_backtest` on the 4 committed fixtures, params from `_merge_strategy_params`. Gross = commission 0; net = the live cost, 0.002 per leg (0.4% round trip). Format: n trades / win rate / expectancy % per trade / Sharpe / max DD %.

| Symbol | Strategy | Bullish gross | Bullish net | Bearish net |
|---|---|---|---|---|
| AAPL | pullback_ema | 6 / 67% / +0.48 / 0.28 / −6.1 | 6 / 67% / +0.08 / 0.01 / −6.1 | 1 / 100% / +5.29 |
| AAPL | breakout_base | 0 | 0 | 1 / 0% / −2.51 |
| AAPL | ma_crossover | 5 / 40% / −0.98 / −0.92 / −5.8 | 5 / 40% / −1.38 / −1.23 / −7.5 | 6 / 17% / −1.31 / −0.64 / −21.0 |
| MSFT | pullback_ema | 1 / 0% / −3.37 | 1 / 0% / −3.76 | 5 / 60% / −0.65 / −1.15 / −10.8 |
| MSFT | breakout_base | 0 | 0 | 2 / 0% / −2.07 |
| MSFT | ma_crossover | 3 / 0% / −2.72 | 3 / 0% / −3.12 / −1.71 / −9.5 | 4 / 25% / −1.96 |
| NVDA | pullback_ema | 4 / 50% / +0.82 / 0.12 / −13.5 | 4 / 50% / +0.42 / 0.01 / −13.7 | 1 / 100% / +12.23 |
| NVDA | breakout_base | 0 | 0 | 1 / 0% / −7.80 |
| NVDA | ma_crossover | 4 / 50% / +5.39 / 1.07 / −7.6 | 4 / 50% / +4.97 / 0.99 / −7.7 | 4 / 0% / −8.14 / −2.68 / −32.8 |
| SPY | pullback_ema | **11 / 82% / −0.12 / −0.24 / −5.0** | **11 / 55% / −0.52 / −0.92 / −7.4** | 2 / 100% / +2.42 |
| SPY | breakout_base | 2 / 0% / −0.64 | 2 / 0% / −1.04 | 2 / 50% / −0.16 |
| SPY | ma_crossover | 4 / 25% / +0.39 / 0.36 / −3.1 | 4 / 25% / −0.02 / −0.04 / −3.3 | 4 / 25% / −0.04 |
| all | mean_reversion_rsi, mean_reversion_bb | 0 | 0 | 0 |
| all | mean_reversion_vwap | N/A, intraday-only, not run on daily bars | | |

  - Under the *live* gate (`bt_min_trades: 5`, `bt_min_win_rate: 0.45`, expectancy ≥ 0; `backend/app/schemas/stock_scan.py:61-62`), exactly one pair passes net: AAPL `pullback_ema` Bullish, on 6 trades at +0.08% per trade.
  - Engine warnings: 14× "Some trades remain open at the end of backtest" (open trades left out of the stats), and repeated "contingent SL/TP order would execute in the same bar … executed on the next bar". Both bias results, direction unknown per trade.
- **Data available vs required**:
  - Fixtures: 251 daily bars, 2024-04-30 → 2025-04-30.
  - `mean_reversion_rsi`/`bb` need `trend_sma: 200` plus the engine's 60-bar start, so they can't fire.
  - The live scan uses 5 years (`stock_scan.py:466`), confidence 4–5 years (`scoring_rules.yaml` `confidence_backtest`), and the tuner 3 years (`strategy_param_optimizer.py:252`). **None of that history exists in this environment.**
- **WFO run** on 3 years of synthetic bars (4 symbols, real `_optimize_strategy_sync`, real config):
  - 7 folds; train windows 261 bars; **test windows 65–66 bars**.
  - Result: `eligible False, consistency 0.0, oos n_trades 0, "Edge looks fake — consider dropping."`

## The Trader

1. **Earnings inside the "reject" window doesn't block a long option (High).**
   - In options mode the event rule's REJECT is only a 5-point score on a 0.15 weight (`stock_scorer.py:900-904`). Only a pullback REJECT has a veto (`:1171-1173`).
   - Worked example (Swing): trend 90, pullback 90, trigger 90, vol 90, earnings in 5 days → 0.30·90 + 0.20·90 + 0.25·90 + 0.15·5 + 0.10·90 = 77.25 → **PASS**.
   - Measured with the real scorer on the fixtures, earnings set 5 days out: **9 PASS** (e.g. AAPL Bearish 2025-01-14, score 62, event REJECT 5) out of 272 evaluations.
   - Step 5 paints the row REJECT (`frontend/app/(frame)/screener/step-5-vol-events/page.tsx:248-250`), but nothing in Step 6, Step 7, `checkTradeRisk` or the auto-trader reads it (grep for `nextEventDays` in those paths: no hits).
   - Consequence: a 5–15 day long call bought straight into an IV crush, graded PASS.
2. **A missing earnings date scores full marks (Medium).** `worst_days is None` returns PASS 90 (`stock_scorer.py:879-883`). The date comes from fundamentals, then a yfinance fallback (`scan.py:599-608`); if both miss, the trade is treated as event-free.
3. **The DTE floor leaves one day of time value at max hold (Medium).**
   - `widened_min_dte` floors at `hold_max_days + 1` (`backend/app/scoring/dte_window.py`, `widened_min_dte`), and the scan applies it (`scan.py:856`).
   - Measured hard-reject windows: Swing 5–15d hold → **16–40 DTE**; Position 15–45d → **46–100 DTE**; Intraday → 3–14.
   - A 15-day Swing hold in a 16-DTE contract exits at 1 DTE, at peak theta. `contract_rules.yaml:13-14` says the multiplier "leaves time value at exit", and the 2.0 multiplier's intent was 30 DTE for that hold. This also overrides the static `min_dte: 21`.
   - Soft-rank uses the same widened bounds, so nothing steers toward the longer end of the window.
4. **Bear spreads are shown, never sent (Medium).**
   - `_build_spreads` picks bear call (credit) when IV ≥ threshold, else bear put (`scan.py:405-462`), and the card renders the legs (`frontend/components/organisms/TradeCard/index.tsx:2243-2256`).
   - The order request has a single `option_symbol` and no legs (`broker.py:192-206`), and the basket books the single contract.
   - The trader sees a defined-risk spread and executes a naked long put.
   - The short legs have no ex-dividend/assignment check (no dividend reference in `spread_builder.py`). Moot while spreads aren't executed.
5. **The bearish mirror looks correctly signed (no finding).** Every signal flips on `direction == "Bullish"` (`strategy_engine.py:157-1374`), and the Bearish backtests produce trades with stops above and targets below (`_entry_side`, `strategy_backtest.py:15-22`). The defect is the *caller's* string (Quant §2), not the mirror.
6. **Liquidity floors are thin for exits but coherent with 5-contract max size.** Volume 50/day, OI 200, spread ≤ 20% of mid (`contract_rules.yaml:18-20`). At a 20% spread, a marketable exit from a mid fill costs 10% of premium on that leg. Nothing models it (Quant §5).

## The Quant

1. **Walk-forward OOS is structurally empty (High).**
   - `test_months: 3` (`strategy_params.yaml`, `windows`) → about 63 trading days (252/12·3). Measured: 65–66 bars per window.
   - The OOS loop only scores a window `if len(test_bars) >= 100` (`backend/app/services/strategy_param_optimizer.py:123`), and `run_strategy_backtest` itself refuses fewer than 100 bars (`strategy_backtest.py:89-90`).
   - So every fold's test return is 0.0, `consistency` is 0, `n_trades` is 0, and every proposal is "Edge looks fake".
   - Adopt is disabled when not eligible (`frontend/app/(frame)/settings/page.tsx:2692`), so it **fails closed**. The consequence: no `active:` parameter set has ever passed walk-forward under the current exits, which `strategy_params.yaml`'s header itself says are untuned.
   - Even with longer windows, the test slice is backtested *without its warm-up history*. A 200-bar `trend_sma` can't fire inside a 3-month slice.
2. **The tuner optimizes the inverted strategy (High, latent behind §1).**
   - `direction: bullish` (lowercase, `strategy_params.yaml`) → `store.get_direction()` (`backend/app/services/strategy_param_store.py:111-113`) → `run_optimization(direction="bullish")` (`backend/app/routers/strategy_tuning.py:77`) → `train_fold` → `run_strategy_backtest(direction="bullish")`.
   - Every signal compares `== "Bullish"` and `_entry_side` treats anything else as a sell.
   - Measured: lowercase `"bullish"` results are **identical to `"Bearish"`** for every strategy and symbol (e.g. NVDA `ma_crossover`: "bullish" 4 trades / −28.47%, Bearish identical, real Bullish +21.99%).
   - Adopt then writes the winner into `active.bullish`: the frontend sends no direction (`frontend/lib/api.ts:1157-1158`) and the default is `"Bullish"` (`strategy_tuning.py:26`).
   - Fix §1 alone and the tuner starts installing bear-tuned parameters into the long strategy.
3. **Confidence is an overlapping, timeout-free, fail-open in-sample number (Medium).**
   - Every consecutive PASS day is a new sample (`signal_confidence.py:262-276`, no skip-ahead), so a 5-day setup counts as 5 "occurrences" against `min_samples: 20`.
   - Flats (timeouts) drop out of the denominator (`:155-158`), which flatters the hit rate.
   - Below `min_samples`, `status_cap` returns PASS (`:178-179`).
   - It is uncalibrated: nobody has measured whether a "70" hits 70%.
4. **The live backtest gate decides on noise (Medium).**
   - `bt_min_trades: 5` (`schemas/stock_scan.py:61`), against `_MIN_TRADES = 10` in the engine (`strategy_backtest.py:24`) and `min_trades: 20` in the optimizer.
   - The one pair that passes live, AAPL `pullback_ema` (4/6 wins): p = 0.667, SE = √(0.667·0.333/6) = 0.192, 95% CI = 0.667 ± 0.377 → **29% to 100%**. (A 95% confidence interval is the range the true win rate plausibly sits in.)
   - The gate cannot tell this strategy from a coin.
5. **Targets close to entry, and options costs absent (Medium).**
   - SPY `pullback_ema` Bullish: gross win rate 82% (9/11) with *negative* expectancy (−0.12%). Adding 0.4% round-trip cost drops the win rate to 55% (6/11), so 3 of the 9 "wins" made under 0.4% gross.
   - The prior-swing-extreme target (`strategy_params.yaml` note, `exit_swing_lookback: 20`) sits much nearer than the 1.5×ATR stop. A high win rate with a small average win is the classic setup for being run over by costs.
   - Every backtest prices the *stock* at 0.2% per leg. Options, the main instrument, are never backtested. Their cost at the allowed 20% spread is up to 10% of premium per leg, so the stock backtest says nothing about option P&L.
6. **Multiple testing with a mild penalty (Low/Medium).**
   - Grid sizes per fold: pullback_ema 3·3·3·3·4 = 324; breakout_base 3·4·3·4 = 144; mean_reversion_bb 3·3·2·3 = 54; ma_crossover 24; mean_reversion_rsi 24.
   - Selection is by **gross** in-sample Sharpe (`walk_forward.py:212` passes no commission). The complexity penalty is at most 0.05 Sharpe per numeric parameter, about 0.25 for pullback_ema (`walk_forward.py:136-176`).
   - There is no deflated-Sharpe adjustment (a correction for picking the best of many tries). Folds remain genuinely non-overlapping (`walk_forward.py:70-81`).
7. **The Monte Carlo drift is assumed from the score (Medium).** `mu = sign·(trend_score − 50)/50 · 0.40` (`backend/app/scoring/first_passage.py:384`). A trend score of 90 injects +32%/yr drift into GBM. The "probability of hitting T1/T2/T3" shown on the card is therefore partly the score restated as a probability. GBM also has no fat tails or volatility clustering. Uncalibrated.
8. **The regime model is causal (no finding).** Rolling 20-bar returns labelled Bull/Bear/Choppy, transition counts over 500 bars (`backend/app/services/regime_omm.py:1-60,169-204`). It uses no future bars. The HMM is used for intraday and display paths only.

## The Risk Manager

1. **Per-trade loss limit vs sizing (Medium).**
   - `max_loss_per_trade_pct: 0.0375` is "warning-only, never auto-clamps" (`risk_rules.yaml:19-23`).
   - The option hard cap is `max_single_position_pct: 0.05` of premium (`:12`; enforced `backend/app/services/portfolio_risk.py`, `check_position_risk`). A full-premium loss (gap, or an ignored alert) is 5% > 3.75%.
   - At the 60% premium stop it's 0.6 × 5% = 3.0%, *if* someone acts on the alert.
2. **The "daily loss" limit is an auto-trader premium budget, held in memory (Medium).**
   - It sums `premium_at_risk` from `AutoTradeState.history` (`auto_trader.py:3087-3134`), a list on a module singleton with no DB model (`:361-366`). A restart resets the day.
   - It counts auto-trader orders only, and not realized P&L. Manual Step-7 sends and stock sends never touch it.
   - At $100k: $2,000 of new premium per UTC day via the auto-trader. Unlimited via manual sends.
3. **Losing streak.**
   - At 3.75% per loser (compounded): 0.9625ⁿ ≤ 0.90 → n = ln 0.90 / ln 0.9625 = 0.1054/0.0382 = 2.76 → **3 losers to −10%**; ≤ 0.80 → 0.2231/0.0382 = 5.84 → **6 losers to −20%**.
   - At the 5% option cap, full premium: 0.1054/0.0513 = 2.05 → **3 losers to −10%** (2 = −9.75%); 0.2231/0.0513 = 4.35 → **5 losers to −20%**.
   - Nothing stops a sixth trade on day 2.
4. **Concentration (Medium).**
   - Options are capped at 25% total premium; stocks at 20% single / **100% total notional** (`risk_rules.yaml:6,17-18`). Each kind counts only its own rows (`portfolio_risk.py`, `same_kind`), so combined gross is **125%** of the account.
   - No sector or correlation cap: ten long-beta tech names count as ten bets.
   - `max_concurrent_positions: 10` does count both kinds (`len(portfolio)`).
5. **Sizing basis.** Stocks are risk-sized: 1% × a regime multiplier of 0.3–1.0 ÷ stop distance (`stock_scan.py:1085-1100,1355-1363`), so volatility enters through the stop. Options are sized by contract count against premium caps, which is not volatility-aware.
6. **Account value is hand-typed, in two copies, with two fallbacks (Medium).**
   - Every cap multiplies a client-sent `portfolioValue` from `riskStore` (localStorage, `frontend/lib/riskStore.ts:20`; sent at `frontend/components/organisms/AutoTradeArm/index.tsx:370`).
   - Server fallbacks are $50,000 (`auto_trade.py`, `ArmRequest.portfolio_value`; `backend/app/schemas/__init__.py:1019`; `backend/app/routers/risk_settings.py:153`), against the YAML's $100,000 (`risk_rules.yaml:11`, read by `stock_scan.py:2431`).
   - Nothing reads the broker balance. After a drawdown, every % cap stays sized to the old account.
7. **Execution safety (High).**
   - *No protective order anywhere.* Adapters place one entry order with no STP/bracket (grep `STP|bracket|OCO` in `backend/app/data/`: none). Stops are alerts polled every 60 s and sent via Telegram/Gmail (`backend/app/services/portfolio_alert_monitor.py:24,108-124`).
   - *Bearish stocks are short SELL/OPEN* (`stockDirectSend.ts:174-175`), up to 20% notional, sized on a 1% stop with no stop order. A 50% squeeze on a 20% short is a **10%** account loss, 10× the planned risk.
   - *The "halt" check only asks whether a quote exists.* `_market_is_open` returns True if any last/close price exists (`auto_trader.py:418-441`; `fetch_price` returns `last or close`, `backend/app/data/market.py:665`). It passes after hours, on weekends and through halts; the code's own comment admits this (`auto_trader.py:772-774`). The error text still says "Market closed or halted".
   - *The `/broker/*` endpoints are ungated.* `/broker/option-order` and `/broker/stock-order` run no exposure, loss or hours check (`broker.py:217-350`), and accept `SELL`+`OPEN` options, i.e. a naked short. The UI gates by saving the portfolio row first (`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1124-1170`; `backend/app/services/position_writer.py:443-456`). Any other client goes straight through.
   - *Done well, credited*: idempotent order claims (`broker.py`, `_claim_or_wait`); disarm-before-execute so a double fire is impossible; arm-identity `expect`; 30-minute arm expiry; fail-closed regime data on the auto-trader; "may have landed" vs "not submitted" correctly separated (`auto_trader.py:2160-2211`).
8. **Missing data, gate by gate.**

| Input missing | Behaviour | Verdict |
|---|---|---|
| Earnings date | event PASS 90 | fail-open |
| IV | vol CAUTION 50 (`stock_scorer.py:968-969`) | conservative |
| Confidence history | cap PASS | fail-open |
| Regime (scan) | gate not applied (`scan.py:728`, `regime_gate=None`) | fail-open |
| Regime (stock sizing) | floor 0.3 | conservative |
| Regime (auto-trader) | refuses | fail-closed |
| Quote at fire | refuses | fail-closed |

## Cross-parameter table

| Check | Values (file:line) | Consistent? | Severity |
|---|---|---|---|
| Per-trade loss vs daily loss | `max_loss_per_trade_pct` 0.0375 (warning) vs `auto_trade.max_daily_loss_pct` 0.02 (`risk_rules.yaml:23,59`) | No. One manual trade can be 1.9× the "daily" limit, and the daily limit doesn't see manual trades. | Medium |
| Per-trade loss vs sizing caps | option cap 5% premium (`:12`), `max_contracts_per_trade` 5 (`:26`) vs 3.75% | No. Full-premium loss is 5% > 3.75%. | Medium |
| Stock vs option caps | 25% options premium + 100% stock notional (`:6,18`), counted separately | No total bound: 125% gross | Medium |
| Backtest costs vs allowed liquidity | 0.2%/leg on stock (`strategy_params.yaml` `costs`) vs options spread ≤ 20% (`contract_rules.yaml:20`) | No. Options costs are unmodelled. | Medium |
| WFO windows vs data | train 12m / test 3m, 3y pulled (`strategy_param_optimizer.py:252`); fixtures 251 bars | Data absent here; windows fit 3y (7 folds) | Medium |
| WFO windows vs code minimums | test ≈ 65 bars vs `>= 100` guard (`strategy_param_optimizer.py:123`, `strategy_backtest.py:89`) | **No. Zero-trade folds, always.** | **High** |
| Minimum-trade gates | live 5 (`schemas/stock_scan.py:61`), engine 10 (`strategy_backtest.py:24`), optimizer 20, confidence 20 decisive (overlapping) | Inconsistent; 5 is noise | Medium |
| Stop definitions | premium stop 60% (`risk_rules.yaml:34`); structural/ATR stop 2.0×ATR (`:44`); stop-vs-premium PASS up to 70/80/60% of premium (`scoring_rules.yaml` `stop_premium`) | No. For Swing contracts where the chart stop costs 60–70% of premium, the 60% premium stop fires first and the chart stop never governs. | Low/Medium |
| DTE vs holding horizon | multiplier 2.0 (`contract_rules.yaml:14`) vs floor `hold_max+1` (`dte_window.py`, `widened_min_dte`) | No. 1 day left at max hold for Intraday/Swing/Position. | Medium |
| Config vocabulary vs code | `direction: bullish` (`strategy_params.yaml`) vs `== "Bullish"` (`strategy_engine.py`, `strategy_backtest.py:20`) | **No. Silent wrong branch.** | **High** |
| Account value basis | YAML 100,000 (`risk_rules.yaml:11`); client `riskStore` 100,000 (`frontend/lib/riskStore.ts:20`); server fallbacks 50,000 (`schemas/__init__.py:1019`, `risk_settings.py:153`, `ArmRequest`) | No, and none is live from the broker | Medium |
| Thresholds vs mirrors | stock 55/35, confidence 50/35, IV 34/55 and 44/65 vs `status.ts`, `confidenceText.ts`, `SCORING_RULES.md` | Yes | none |
| Dead or unmeasured config | `gap_threshold_pct` (dead, labelled); `auto_trade.premium_stop_pct` (NOT READ, labelled); `max_iv_rank`, `iv_rank_*`, `bearish_min_trend`, `pass_max_fraction` (UNMEASURED, all in live gates) | Labelled honestly, but four live gates run on unmeasured numbers | Medium |

## Stress test

| Scenario | What the code does | Exposure |
|---|---|---|
| Clean uptrend | Bullish trend/pullback/trigger score; long calls at 16–40 DTE (Swing) | Theta at a 1-DTE exit if held to 15 days |
| Downtrend | Bearish mirror is correct; long puts; stocks go short; spreads shown, not sent | Short stock with no stop order |
| VIX 20 → 40 | IV ceiling hard-rejects absolute IV > 70 (`contract_rules.yaml:36`); Swing vol rule REJECTs > 55; regime ramp sizes down | Open positions get no new protection; alerts only |
| Earnings inside the hold | Options: −12.75 points on a 0.15 weight; can still PASS (9 measured). Missing date → PASS. | IV crush on a full-size long option |
| Overnight gap through the stop | Alert after the next 60 s poll; no resting order | Long option: up to the full premium (≤ 5%). Short stock: unbounded within 20% notional. |
| Trading halt | `_market_is_open` passes (a last price exists); a DAY limit order is queued | Fill at the reopen gap |
| Regime flip with positions open | `regime_monitor` warns (`regime_flip_sustain_minutes: 0`); nothing closes | Unmanaged until a human acts |
| Broker API down at the order | Auto-trader: `OrderNotSubmittedError` vs "may have landed" separated, history row written. UI: save-first with a direct-send note. | Good. Except the daily-limit history dies with the process. |

## The Chair

- **The Trader and the Quant disagreed on the event rule.** The Trader calls it a broken gate. The Quant notes that a weighted penalty is a legitimate design, and that earnings 5 days out did cut PASSes from 121 to 9 on the fixtures. **The Trader is right.** The config names the window `reject_days`, Step 5 paints it REJECT, and a long-premium trade across earnings is the one trade that window exists to stop. A gate labelled REJECT that lets 9 through doesn't gate. Area 3 is REJECT.
- **The Quant and the Risk Manager disagreed on the WFO bugs.** The Risk Manager argues they cost no money, because adopt is disabled while ineligible. That fail-closed behaviour is real, and it is why these aren't execution findings. But area 2 grades *evidence*, and the walk-forward machinery the product presents as validation produces none and is aimed at the wrong side. **Area 2 is REJECT.**
- **No broker-side stop is deliberate**, written into the code: "the auto-trader places no protective order", decision A6 (`auto_trader.py:3097`). The builder answered it sensibly for the auto-trader by counting full premium. It is respected, **and still REJECT** for area 5 once live. For long options the loss is bounded by the 5% premium cap. For the bearish stock path it isn't: a short with no stop and a 20% notional cap can lose 10× its 1% risk budget on one squeeze. That meets "a loss limit a single trade can blow through with no hard stop".
- **Respected as deliberate and not counted against the system**:
  - Intraday vol skipped (`scoring_rules.yaml`, intraday `vol` nulls).
  - The `min_dte == preferred_dte_min` equality.
  - The two-sided regime ramp.
  - Demote-only gates (CAUTION is advisory by design).
  - Honest UNMEASURED and NOT READ labelling. This is unusually disciplined, and it made this review possible.

## Fix list (worst first)

| # | Severity | Area | Problem | Fix | Why it costs money |
|---|---|---|---|---|---|
| 1 | High | 2 | WFO passes `"bullish"`, every signal runs Bearish | Normalise direction at `strategy_param_store.get_direction()` (capitalise) and reject anything not in {Bullish, Bearish} in `run_strategy_backtest`; also tune `bearish` and adopt with an explicit direction | Once #2 is fixed, bear-tuned params get installed into the long strategy |
| 2 | High | 2 | OOS windows (≈65 bars) are always under the 100-bar guard | Backtest each test window with its train history prepended as warm-up, counting only trades entered inside the test dates; or set `test_months` ≥ 6 and drop the guard to the warm-up the strategy really needs | No parameter has ever been validated out of sample |
| 3 | High | 3 | Event REJECT doesn't veto long premium | In options mode, cap final status at REJECT (or at least CAUTION plus a hard block at send/arm) when `days_to_event < reject_days` inside the hold | IV crush on full-size long options |
| 4 | High | 5 | No protective order; bearish stocks are uncapped shorts | Place a broker-side stop (or a bracket) with every stock entry, short entries above all; until then, disable SELL/OPEN stocks for live | One squeeze is a 10% account loss |
| 5 | Medium | 3 | Missing earnings date = PASS 90 | Score unknown events as CAUTION in options mode, the same way missing IV already is | Unknown-date names are treated as safe |
| 6 | Medium | 3 | DTE floor `hold_max+1` | Floor at `hold_max + max(7, 0.5·hold_max)`, or keep `round(hold_min·2)` as a hard floor | Theta at exit on every Swing/Position option |
| 7 | Medium | 5 | Daily limit in memory, auto-trader only | Persist auto-trade history; count manual sends and realized P&L in the same daily budget | A restart or a manual send bypasses the breaker |
| 8 | Medium | 5 | `/broker/*` ungated; quote-only "halt" check | Run `check_position_risk` + hours (`market_session`) server-side in the order routes; block option SELL/OPEN there; use a real session/halt test in `fire()` | Any client, or a stale bundle, places unchecked orders |
| 9 | Medium | 4 | 125% combined exposure; 5% > 3.75% | Add a combined gross cap; make the per-trade max-loss a hard block or lower the option premium cap to ≤ 3.75% | Correlated full drawdown beyond the stated limits |
| 10 | Medium | 2 | Live gate n=5; overlapping confidence samples; confidence fail-open | Raise `bt_min_trades` to ≥ 20 (show the CI); de-duplicate replay fires (skip `n_days` after each fire); show "unmeasured" as CAUTION | Trades taken on noise labelled confidence |
| 11 | Medium | 3 | Spreads shown but a single leg is sent | Hide spreads, or build a multi-leg order path | The trader thinks risk is defined when it isn't |
| 12 | Medium | 4 | Account value typed by hand, 50k/100k fallbacks | Pull net liquidation from the broker; one server fallback equal to the YAML | Caps drift from the real account |
| 13 | Medium | 2 | Options never backtested; costs are stock-only | Backtest option P&L at the allowed spread, at least as a stress row on Step 6 | Stock edge ≠ option edge |
| 14 | Medium | 2 | MC drift assumed from the trend score | Use drift 0 (or measured drift) for probabilities; show the score separately | Hit probabilities overstated on strong trends |

## Not measured

- **Real multi-year performance of any strategy.** Fixtures are 1 year; the live scan wants 5. Measure by loading 5+ years for the basket into `historical_store` and re-running the backtest table and a fixed WFO.
- **Option P&L of any strategy.** No option backtest exists. Measure by repricing the chosen contract along each historical trade with recorded chains or modelled IV.
- **Confidence calibration** (does "70" hit 70%?). Measure by bucketing out-of-sample replay fires by confidence and comparing hit rates.
- **Win rate of the 9 event-REJECT PASS candidates through earnings.** Not measured; needs chain history around earnings.
- **Fill quality at mid on 20%-spread contracts.** Not measured; needs paper fill logs vs quoted mid.
- **The bearish `direction_conviction` floors and the `iv_rank_*` cut-offs.** UNMEASURED by the builder's own label; needs real bearish scans and rank-source data.
- **Regime-model accuracy.** No out-of-sample test that a "Stable Bull" label predicts anything was run.
