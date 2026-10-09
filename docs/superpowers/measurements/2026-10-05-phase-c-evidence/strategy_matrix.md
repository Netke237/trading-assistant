# Strategy matrix (M5, M6)

- Git commit: `b1b627080347a7a776ef9cc5c6910f3a5903ee99`
- Generated (UTC): 2026-10-05T13:16:58Z
- Symbols (535): A, AAL, AAPL, ABBV, ABNB, ABT, ACGL, ACN, ADBE, ADI, ADM, ADP, ADSK, AEE, AEP, AES, AFL, AIG, AIZ, AJG, AKAM, ALB, ALGN, ALL, ALLE, ALV, AMAT, AMCR, AMD, AME, ... (505 more)
- Date range requested: 1990-01-01 .. 2026-10-05
- Date range loaded: 2020-10-06 .. 2026-10-02
- BARS_BASIS_VERSION: `b2`
- Cost model: net: per-leg commission 0.2000% (fee_pct 0.001 + slippage_pct 0.001, strategy_params.yaml `costs`, as WFO), charged on entry and exit; DAY entry limits
- History: each symbol's full loaded history, no warm-up exclusion beyond the backtest's own 60 bars
- Min trades (gate): 10 (strategy_backtest._MIN_TRADES)
- Bootstrap: 2000 resamples over symbols, seed 7
- Params: adopted `active` block per direction over the `exit` block

## Pooled net trade return per strategy and direction

| Strategy | Direction | Symbols | Traded | Trades | Mean trade return % | 95% CI | Symbols >= min trades |
|---|---|---:|---:|---:|---:|---|---:|
| pullback_ema | Bullish | 535 | 534 | 13769 | -0.343 | [-0.428, -0.253] | 96.3% |
| pullback_ema | Bearish | 535 | 534 | 9999 | -0.990 | [-1.108, -0.859] | 91.8% |
| breakout_base | Bullish | 535 | 531 | 3135 | -0.168 | [-0.327, -0.006] | 9.0% |
| breakout_base | Bearish | 535 | 535 | 3543 | -0.768 | [-0.911, -0.624] | 15.3% |
| ma_crossover | Bullish | 535 | 534 | 11324 | +0.167 | [+0.025, +0.306] | 98.9% |
| ma_crossover | Bearish | 535 | 535 | 11231 | -1.314 | [-1.468, -1.152] | 99.1% |
| mean_reversion_rsi | Bullish | 535 | 159 | 214 | -0.029 | [-0.703, +0.666] | 0.0% |
| mean_reversion_rsi | Bearish | 535 | 149 | 205 | -0.525 | [-1.276, +0.262] | 0.0% |
| mean_reversion_bb | Bullish | 535 | 534 | 10818 | -0.364 | [-0.437, -0.292] | 94.2% |
| mean_reversion_bb | Bearish | 535 | 533 | 7578 | -0.606 | [-0.695, -0.518] | 73.8% |

Mean trade return is net of costs and trade-weighted across symbols (each symbol's expectancy times its trade count).
