# 0001 — Stocks strategy parameters are tuned per horizon, held in the backend, and gated by evidence

- Status: accepted
- Date: 2026-10-05
- Decided by: Kenneth (grilling, rounds 1–2)

## Context

Stocks mode ran on one hand-set parameter set per strategy and direction, the same whatever horizon was picked, and its backtests had no time exit, so a "Swing" trade could be held for months. The 2026-10-05 Phase C evidence measured those untuned values; two strategies barely fired (`mean_reversion_rsi` ≈ 0.7 candidates a week across 535 symbols, `breakout_base` ≈ 2 a day) and `mean_reversion_multi` was measured through `mean_reversion_rsi` as a stand-in. Options mode already has per-horizon profiles, but as a hardcoded frontend copy of the YAML that has drifted once (event-days bug).

## Decision

1. Every **cell** (strategy × direction × horizon: Swing, Position, Quarterly, Semi-annual, Annual) gets its own tuned parameters. Intraday is out of scope (daily bars).
2. Trades get a **time exit** at the horizon's `holdMax`, counted in calendar days, exiting at the next bar's open. Backtests and tuning apply it; live stock positions and strategy watches raise a `TIME_STOP` alert. No auto-close.
3. Tuned values live in `backend/config/strategy_params.yaml` (`active.<direction>.<horizon>`). The frontend fetches them with a fallback, like `eventThresholdsStore`, never as a hardcoded copy. Picking a horizon loads its **horizon profile** into the Step-4 panel; the user can still override.
4. The tuner maximises walk-forward net expectancy at 0.05% per leg, subject to the **fire-rate floor** (candidates per scan of S&P 500 + NDX 100 minus the exclusion list: Swing ≥ 2/day, Position ≥ 1/day, Quarterly ≥ 3/week, Semi-annual ≥ 2/week, Annual ≥ 1/week), with the same gates a live scan applies. Grids are per horizon, capped at about 150 combinations per cell. Every result is also reported at 0.2% per leg.
5. A cell is adopted only if it clears the **adoption bar** (OOS net expectancy 95% CI lower bound > 0, **held-out year** net positive, ≥ 100 pooled OOS trades, ≥ 20 symbols). Adoption is Kenneth's click. Otherwise it is **Unvalidated**: visible for research, no PASS, no auto-arm, no broker send.
6. Default-value results are a baseline only. They never label, gate or hide a cell. The exception is bearish: it is blocked now, because every bearish cell lost money even before costs.
7. `mean_reversion_multi` gets a real backtest of its own rule.

## Consequences

- The C4 round 2 verdicts, the two-pass retune on the old grids and the robustness-matrix alternative are dropped. C4 Q3/Q4/Q6 and confidence de-overlap remain as error fixes.
- The final report must state how many cells passed against how many would pass by chance.
- The 2020-10..2026-10 sample is mostly a bull market and survivorship-biased; results carry that label until longer history is ingested (logged, not scheduled).
