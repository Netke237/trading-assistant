# Score calibration

- Git commit: `7f377ab5505278c562f0ae2b2564a8a4ecea79bd`
- Generated (UTC): 2026-10-06T04:03:32Z
- Symbols (18): AAPL, MSFT, NVDA, AMZN, GOOGL, META, JPM, V, XOM, UNH, HD, PG, COST, ABBV, BAC, CRM, AMD, DIS
- Excluded (universe_exclusions.yaml): 2 — CTVA (scan), AVB (scan)
- Date range requested: 1990-01-01 .. 2026-10-06
- Date range loaded: 2020-10-06 .. 2026-10-02
- BARS_BASIS_VERSION: `b3`
- Cost model: gross: barrier R from evaluate_fire; no fees or slippage
- Scoring mode: options
- Replay: as compute_confidence: warm-up 60, horizon history_years window
- Bootstrap: 2000 resamples, seed 7

## Swing / Bullish

Barriers: target 3 ATR, stop 1.5 ATR, window 10 bars; win = +2.000 R, loss = -1 R.

| Bucket | n (distinct) | Wins | Losses | Flats | Mean R | 95% CI |
|---|---:|---:|---:|---:|---:|---|
| PASS | 1122 | 229 | 496 | 397 | +0.151 | [+0.077, +0.223] |
| CAUTION | 1150 | 231 | 491 | 428 | +0.167 | [+0.099, +0.238] |
| REJECT | 610 | 131 | 257 | 222 | +0.191 | [+0.092, +0.291] |
| ALL (base rate) | 1710 | 352 | 721 | 637 | +0.196 | [+0.139, +0.255] |

### Confidence replay sample size vs min_samples (20)

- Symbols: 18
- Meeting min_samples, overlapping (today): 18
- Meeting min_samples, non-overlapping: 18
- Median decisive fires: overlapping 254.0, non-overlapping 39.5

| Symbol | Overlapping | Non-overlapping | min_samples |
|---|---:|---:|---:|
| AAPL | 255 | 39 | 20 |
| ABBV | 255 | 37 | 20 |
| AMD | 269 | 42 | 20 |
| AMZN | 249 | 36 | 20 |
| BAC | 245 | 39 | 20 |
| COST | 272 | 42 | 20 |
| CRM | 266 | 43 | 20 |
| DIS | 213 | 40 | 20 |
| GOOGL | 262 | 43 | 20 |
| HD | 253 | 37 | 20 |
| JPM | 251 | 39 | 20 |
| META | 285 | 46 | 20 |
| MSFT | 239 | 36 | 20 |
| NVDA | 325 | 47 | 20 |
| PG | 196 | 36 | 20 |
| UNH | 222 | 37 | 20 |
| V | 249 | 40 | 20 |
| XOM | 261 | 46 | 20 |

