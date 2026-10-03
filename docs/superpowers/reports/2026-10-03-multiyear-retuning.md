# Multi-year retuning results

The full configured Bullish search completed successfully on 2026-10-03: five supported strategies, seven rolling folds each, and 35 completed training-fold checkpoints. **None of the five proposals is eligible.** All fall below the configured minimum of 20 average closed trades per contributing symbol. Pullback EMA and breakout base also fall below 50% positive-fold consistency. No proposed parameters were adopted; the active `min_signal_rr` floor remains 0.0.

Captured input: all 60 configured basket symbols, 753 adjusted settled daily bars per symbol (45,180 rows), 2023-10-03 through 2026-10-02. BRK.B was retrieved as Yahoo BRK-B. Symbols, aliases, input SHA256 hashes, runtime/package versions, production source hashes and grid definitions are in [the manifest](2026-10-03-retuning-manifest.json). Data came from the supported yfinance fallback with a writable cache; SPY is not part of this configured run.

The production rolling policy uses 12-month training and 3-month test windows. Seven complete OOS windows cover 2024-10-03 through 2026-07-03 (end-exclusive); the latest input quarter is not tested because the production intersection ends at the final recorded date, 2026-10-02. Every strategy has a nonempty winner for each of its seven folds. Search grids contain 324 pullback EMA, 144 breakout base, 24 MA crossover, 24 RSI and 54 Bollinger-band combinations: 570 combinations per fold across the five strategies, 239,400 training symbol/combo/window evaluations. Three configured strategies were skipped for empty unsupported grids: `mean_reversion_vwap`, `mean_reversion_vwap_daily`, and `breakout_setup`.

| Strategy | Eligible | Average closed trades per contributing symbol | Positive OOS folds | Adjusted mean OOS window return | Gross mean expectancy | Gross mean Sharpe |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| pullback_ema | No | 9 | 42.86% | 0.3659% | 0.3348% | 0.3853 |
| breakout_base | No | 4 | 14.29% | -1.4404% | -0.0690% | -0.3478 |
| ma_crossover | No | 7 | 71.43% | 1.8687% | 2.0161% | 0.4363 |
| mean_reversion_rsi | No | 2 | 71.43% | 0.4123% | 0.8503% | 0.2822 |
| mean_reversion_bb | No | 4 | 71.43% | 0.3567% | 0.5267% | 0.3633 |

The trade column is the production `n_trades`: total closed trades across OOS folds divided by the number of distinct symbols that contributed trades, rounded to an integer. It is not the basket's total trade count or a per-window average. The return is the arithmetic mean of per-fold means over symbols with closed trades; no-trade folds contribute zero. It is not a compounded or capital-weighted portfolio return. Expectancy and Sharpe are arithmetic averages of individual symbol/window backtest metrics with closed trades. Proposed consensus parameters are review candidates; these OOS metrics evaluate each fold's training winner, not a fresh test of the consensus parameters.

**Cost limitation:** production backtests use zero commission for expectancy and Sharpe. Return subtracts 0.4 percentage points per traded symbol/window using configured fee 0.001 and slippage 0.001; consistency uses those adjusted fold returns. This adjustment does not simulate costs on every trade, and the expectancy/Sharpe columns remain gross. Eligibility does not demonstrate profitability after execution costs.

Diagnostics: 357,718 training warnings and 566 OOS warnings; zero recorded training or OOS backtest errors. These warning totals count repeated grid trials, not distinct trades. Saved examples include positions still open at a window's end (excluded from closed-trade statistics), and ambiguous same-bar entry/SL/TP execution deferred to the next matching bar by backtesting.py. These model assumptions limit interpretation even though execution completed successfully.

Reproducible artifacts: [raw adjusted inputs](2026-10-03-retuning-inputs.tar.gz), [immutable strategy snapshot](2026-10-03-retuning-strategy-params.yaml), [raw proposals and diagnostics](2026-10-03-retuning-proposals.json), [completion marker](2026-10-03-retuning-completion.json), and manifest above. Extract the inputs to a local archive directory and run `backend/.venv/bin/python scripts/retune_archived_basket.py --archive <archive> --output <fresh-output> --workers 5` with Python 3.11 and the recorded production source/package versions. Copy the committed strategy snapshot to `<fresh-output>/strategy_params.snapshot.yaml` before running so the harness uses that exact configuration. The harness never adopts parameters.

Software validation: 4,809 backend tests passed, one skipped, zero failed; frontend typecheck passed. Frontend source is unchanged from the risk-fix branch's validated 183 suites/4,486 tests and production build. The harness passed independent plan/code review; the financial report's independent review is recorded separately in [the audit log](../audits/2026-10-03-multiyear-retuning.md).
