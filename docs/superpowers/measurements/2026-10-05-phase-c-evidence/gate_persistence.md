# Gate persistence (H3)

- Git commit: `b1b627080347a7a776ef9cc5c6910f3a5903ee99`
- Generated (UTC): 2026-10-05T09:23:07Z
- Symbols (535): A, AAL, AAPL, ABBV, ABNB, ABT, ACGL, ACN, ADBE, ADI, ADM, ADP, ADSK, AEE, AEP, AES, AFL, AIG, AIZ, AJG, AKAM, ALB, ALGN, ALL, ALLE, ALV, AMAT, AMCR, AMD, AME, ... (505 more)
- Date range requested: 1990-01-01 .. 2026-10-05
- Date range loaded: 2020-10-06 .. 2026-10-02
- BARS_BASIS_VERSION: `b2`
- Cost model: net: per-leg commission 0.2000% (fee_pct 0.001 + slippage_pct 0.001, strategy_params.yaml `costs`, as WFO), charged on entry and exit; DAY entry limits
- Split: each symbol's loaded bars at their midpoint (by bar count)
- Warm-up: 260 bars before the second half (WFO slice_with_warmup)
- Min trades per half: 5
- Params: adopted `active` block per direction over the `exit` block

## Spearman rho of per-symbol expectancy, first half vs second half

| Strategy | Direction | Symbols run | n (both halves) | rho | Noise band | Verdict |
|---|---|---:|---:|---:|---|---|
| pullback_ema | Bullish | 535 | 484 | -0.036 | +/-0.089 | within noise |
| pullback_ema | Bearish | 535 | 406 | +0.066 | +/-0.097 | within noise |
| breakout_base | Bullish | 535 | 19 | +0.395 | +/-0.462 | within noise |
| breakout_base | Bearish | 535 | 42 | -0.114 | +/-0.306 | within noise |
| ma_crossover | Bullish | 535 | 522 | -0.027 | +/-0.086 | within noise |
| ma_crossover | Bearish | 535 | 518 | +0.006 | +/-0.086 | within noise |
| mean_reversion_rsi | Bullish | 535 | 0 | - | - | - |
| mean_reversion_rsi | Bearish | 535 | 0 | - | - | - |
| mean_reversion_bb | Bullish | 535 | 408 | +0.035 | +/-0.097 | within noise |
| mean_reversion_bb | Bearish | 535 | 252 | +0.087 | +/-0.124 | within noise |

Noise band: +/-1.96/sqrt(n-1). A rho inside it cannot be told apart from zero persistence.
