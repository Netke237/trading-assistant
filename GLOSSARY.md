# Glossary

Terms as they are used in this repo's code, plans, tickets and PROJECT_STATE.json.

## Stocks parameter tuning

**Horizon** — A holding-period preset chosen on Step 3: Swing 5–15d, Position 15–45d, Quarterly 45–60d, Semi-annual 90–105d, Annual 165–200d (Intraday 0–2d is Options-only for tuning). Defined in `frontend/lib/horizonPresets.ts`. Not the same as the *scoring horizon* (Intraday / Swing / Position), which is what the scorer understands.

**Cell** — One strategy × direction × horizon combination, e.g. `pullback_ema / Bullish / Swing`. The unit that gets tuned, validated and labelled.

**Horizon profile** — The tuned parameter set of every cell for one horizon. Stocks mode loads it when the horizon is picked; the user can still override values in the Step-4 panel. Avoid: "default profile", "preset" (a preset is the hold window, the profile is the parameters).

**Time exit** — Closing a stock trade when it has been held for the horizon's `holdMax` without hitting its stop or target. Applied in backtests and tuning; live it raises a `TIME_STOP` alert (no auto-close).

**Fire-rate floor** — The minimum expected number of candidates a cell must produce per scan of the tuning universe (S&P 500 + NDX 100 minus the exclusion list). A hard constraint on tuning: the tuner maximises net expectancy only among parameter sets that meet it. Never met by loosening thresholds alone.

**Held-out year** — The most recent 12 months of bars, never seen by the tuner, used once to confirm a proposal.

**Adoption bar** — What a tuned cell must clear to be adopted: walk-forward out-of-sample net expectancy with 95% CI lower bound > 0, held-out year net positive, ≥ 100 pooled OOS trades and ≥ 20 contributing symbols. Adoption is always Kenneth's click.

**Unvalidated** — Label for a cell that has not cleared the adoption bar. Visible for research and analysis; cannot reach PASS, cannot be auto-armed, cannot be sent to a broker. Applies to every bearish cell now; to bullish cells only once tuned verdicts exist (never on default-value results). A symbol with missing backtest confidence also reads Unvalidated, never PASS.

**Pooled gate** — The backtest verdict for a cell, computed from all its symbols' out-of-sample trades together. Replaces the per-symbol backtest gate; the per-symbol check survives only as an enough-data check.

**Default-value results** — Evidence measured with the untuned parameters in `strategy_params.yaml` (e.g. the 2026-10-05 Phase C reports). Kept as a baseline to compare tuned values against; never used to label, gate or hide a cell.

**Exclusion list** — One shared list of symbols (bad or unadjusted bars, delisted, ticker reused) that scans, evidence scripts and tuning all skip.
