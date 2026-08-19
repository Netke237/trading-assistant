# Bamendjou — Stock Scoring Rules

> **Source of truth for WS-20.** All numeric thresholds, weights, and decision boundaries are defined here.
> Values are seeded into `backend/config/scoring_rules.yaml`. Do not hardcode any of these numbers in Python.
> Last updated: 2026-08-19. If a number here and in `backend/config/scoring_rules.yaml` ever
> disagree, the YAML file is authoritative — this doc had drifted materially out of sync with
> it for several months before this update (see `TRADING_QUALITY_BENCHMARK.md`).

---

## Rule architecture

The stock scorer produces a **StockScoreCard** with five rule components. Each component returns a `Status` (PASS / CAUTION / REJECT) and a weighted score contribution. The total score (0–100) maps to a final status via the thresholds in Section 7.

All parameters are horizon-aware. Defaults below are for the **Swing** horizon (daily candles). The full horizon matrix is in Section 8.

---

## 1. Trend Rule

**Purpose:** Confirm the stock's medium-term trend supports the selected direction.

**`trend.method` selects the algorithm; `additive` is what's actually configured for all three horizons today** (`method: additive` in `backend/config/scoring_rules.yaml` for swing/intraday/position — confirmed against `stock_scorer.py::_rule_trend`'s `cfg["trend"].get("method", "additive")` dispatch). The `crossover` algorithm below still exists in code (`_trend_crossover()`) and can be selected per-horizon by setting `trend.method: crossover`, but is not active for any horizon in the live config — it's documented in its own subsection further down, not as the default.

### Additive method (default — Swing horizon shown; see Section 8 for the full per-horizon parameter matrix)

Three independently-scored components, summed and rescaled to 0–100:

| Component | Points available (Swing) | Condition for full credit |
|---|---|---|
| Price vs. MA | 40 | Close on the trade-direction side of a 20-period SMA (`ma_period`/`ma_type`) |
| MA slope | 30 | Slope of that MA over the last 10 bars (`slope_lookback`) points in the trade direction |
| ADX strength | 30 (full) / 15 (half) / 0 | ADX(14) ≥ 25 (`adx_pass`) → full; ≥ 20 (`adx_caution`) → half; below → zero |

`score = price_pts + slope_pts + adx_pts` (0–100, since the three point-maxes sum to 100 for Swing). This is a **component-level** score distinct from the overall stock score in Section 7 — it becomes one of the five weighted inputs to that total.

### Additive scoring thresholds (component-level `status_pass`/`status_caution`)
| Score | Status |
|---|---|
| ≥ 70 | PASS |
| 40–69 | CAUTION |
| < 40 | REJECT |

### Alternate: crossover method (not currently active for any horizon)

Selectable via `trend.method: crossover`, but no horizon in the live config uses it today. Kept here for reference in case it's re-enabled.

| Parameter | Value |
|---|---|
| Fast MA | 50-period EMA (daily) |
| Slow MA | 200-period EMA (daily) |
| Condition | Fast EMA above Slow EMA |
| Slow MA slope | **Required** — 200 EMA must be rising |
| Fast MA slope | **Preferred** — if flat (not declining) → CAUTION not REJECT |

| Condition | Status |
|---|---|
| 50 EMA > 200 EMA, both rising | PASS |
| 50 EMA > 200 EMA, 200 rising, 50 flat | CAUTION |
| 50 EMA > 200 EMA, 200 flat or declining | REJECT |
| 50 EMA ≤ 200 EMA | REJECT |

---

## 2. Pullback Rule

**Purpose:** Confirm price is in a valid continuation pullback, not a trend break.

### Fibonacci retracement (primary)
| Band | Retracement depth | Status |
|---|---|---|
| Shallow | 23.6%–38.2% of prior swing | CAUTION |
| Standard | 38.2%–50.0% | CAUTION |
| Golden zone | 50.0%–61.8% | **PASS** |
| Too deep | > 61.8% | REJECT |

| Parameter | Value |
|---|---|
| Swing high lookback | 40 daily bars |
| Swing high min bars ago | 5 bars (excludes micro-peaks) |
| Max time in pullback | 20 calendar days |

> **Option-specific note:** pullbacks dragging past 20 days bleed theta on long calls. Flag as CAUTION at 15 days, REJECT at 20 days.

### ATR-based fallback (used when no qualifying swing high found in lookback)
| Range | Status |
|---|---|
| < 1.0× ATR14 | REJECT (noise, not a pullback) |
| 1.0×–1.25× ATR14 | CAUTION (shallow) |
| 1.25×–2.0× ATR14 | **PASS** |
| 2.0×–2.5× ATR14 | CAUTION (deep) |
| > 2.5× ATR14 | REJECT |

| Parameter | Value |
|---|---|
| ATR period | 14 daily bars |

---

## 3. Reversal Trigger Rule

**Purpose:** Confirm the pullback is showing actionable continuation evidence — not just pausing.

### Candle patterns (ANY ONE qualifies)
| Rank | Pattern | Definition |
|---|---|---|
| 1 | Hammer | Lower wick ≥ 2× body; upper wick ≤ 10% of range; close ≥ 65th percentile of range; body ≥ 5% of range |
| 2 | Bullish Engulfing | Prior candle bearish; current candle bullish; current body fully engulfs prior body; current body ≥ 40% of range |
| 3 | Morning Star | Candle 1: bearish, body ≥ 40% range. Candle 2: body ≤ 20% range (star/doji). Candle 3: bullish, closes above midpoint of candle 1 body |

### Momentum signals (2 of 3 required for PASS)

| Signal | Parameters | Trigger |
|---|---|---|
| MACD histogram | Fast 8, Slow 21, Signal 9, source: close | Histogram sign-flip (negative → positive), rising (bar[0] > bar[-1]) |
| RSI | Period 14 | Crosses above 38 from below OR bullish divergence: price lower low + RSI higher low within 15-bar window |
| Stochastic | K=14, D=3, Smooth=3 | K crosses above D from oversold zone (≤ 31.5; oversold=30, tolerance=5%) |

### Volume (bonus — not required)
| Condition | Effect |
|---|---|
| Reversal bar volume > 1.5× 20-bar average | +10 pts added to trigger component score |

### Setup window
| Parameter | Value |
|---|---|
| All signals must occur within | 8 daily bars of each other |
| Divergence validity window | 15 bars (regular div), 15 bars (RSI pivot), 12 bars (OB/OS cross) |

### Scoring
| Condition | Status |
|---|---|
| Candle + 2 of 3 momentum signals, within 8 bars | PASS |
| Candle + 1 momentum signal | CAUTION |
| Candle only, no momentum | REJECT |
| No candle | REJECT |

---

## 4. Event Context Rule

**Purpose:** Prevent entries close to binary risk events (earnings, dividends).

### Thresholds (earnings and dividends treated identically; Swing horizon shown — see Section 8 for the full per-horizon matrix)
| Days to event | Status |
|---|---|
| > 45 days (or no event) | PASS |
| 21–45 days | CAUTION |
| < 21 days | REJECT |

---

## 5. Volatility Context Rule

**Purpose:** Ensure premium environment is appropriate for long-call buying.

### IV Rank thresholds (Swing horizon default)
| IV Rank | Status | Reasoning |
|---|---|---|
| < 5 | CAUTION | Extremely compressed — stock likely going nowhere |
| 5–34 | PASS | Cheap vol — ideal for long calls |
| 35–55 | CAUTION | Elevated premium — size down |
| > 55 | REJECT | Calls too expensive; vega risk outweighs directional edge |

---

## 6. Component weights

Weights are defined per analysis horizon and must sum to 100.

| Component | Intraday | Swing | Position |
|---|---|---|---|
| Trend rule | 35% | 30% | 30% |
| Reversal trigger | 30% | 25% | 20% |
| Pullback rule | 20% | 20% | 20% |
| Event context | 5% | 15% | 20% |
| Volatility context | 10% | 10% | 10% |
| **Total** | **100%** | **100%** | **100%** |

---

## 7. Score-to-status thresholds

Applied after weighted sum is computed. Horizon-neutral.

| Score | Status |
|---|---|
| ≥ 55 | PASS — strong setup, proceed to contract evaluation |
| 35–54 | CAUTION — proceed with awareness, consider smaller size |
| < 35 | REJECT — skip |

---

## 8. Horizon parameter matrix

All parameters that differ by horizon. The YAML config file contains one section per horizon.

| Parameter | Intraday (4H) | Swing (Daily) | Position (Weekly) |
|---|---|---|---|
| **Trend** (additive method — see Section 1) | | | |
| MA | 9-period EMA | 20-period SMA | 50-period SMA |
| ADX PASS / CAUTION floor | 20 / 15 | 25 / 20 | 25 / 15 |
| **Pullback** | | | |
| Swing high lookback (bars) | 20 | 40 | 75 |
| Max time in pullback | 3 days | 20 days | 60 days |
| **Reversal trigger** | | | |
| MACD periods (fast/slow/signal) | 5 / 13 / 3 | 8 / 21 / 5 | 12 / 26 / 9 |
| RSI floor | 40 | 38 | 37 |
| Stochastic (K/D/Smooth) | 14 / 3 / 3 | 14 / 3 / 3 | 14 / 3 / 3 |
| Setup window (bars) | 10 | 8 | 5 |
| RSI divergence window (bars) | 10 | 15 | 20 |
| Momentum signals for PASS | 1 of 3 | 2 of 3 | 2 of 3 |
| **Event context** | | | |
| Earnings/dividend REJECT | < 1 day | < 21 days | < 30 days |
| Earnings/dividend CAUTION | 1–3 days | 21–45 days | 30–60 days |
| **Volatility context** | | | |
| IV Rank PASS ceiling | (not scored) | 34 | 44 |
| IV Rank CAUTION ceiling | (not scored) | 55 | 65 |
| IV Rank REJECT above | (not scored) | 55 | 65 |

---

## 9. Regime scoring model

Used by Step 3 (market regime validator), not by the stock scorer. Stored in `backend/config/regime_rules.yaml`.

Sourced from validated Dual-Engine Confluence strategy (prior system).

| Condition | Points |
|---|---|
| SPY Daily close > 200-period SMA | +2.0 |
| QQQ Daily close > 200-period SMA | +2.0 |
| SPY 4H close > 50-period SMA | +1.0 |
| QQQ 4H close > 50-period SMA | +1.0 |
| VIX < 20 | +1.5 |
| VIX < 15 (bonus tier) | +0.5 |
| **Maximum score** | **8.0** |

| Score | Status | Behaviour |
|---|---|---|
| ≥ 6.0 | PASS | Full green — trade normally |
| 4.0–5.9 | CAUTION | Reduced size — 1 contract max |
| < 4.0 | REJECT | No scan — block Step 4 |

---

## 10. YAML seed

Seed values for `backend/config/scoring_rules.yaml`. The stock scorer reads from this file; no numeric values appear in Python code.

```yaml
# Abbreviated illustration of backend/config/scoring_rules.yaml's shape —
# NOT a complete copy (the real file additionally nests trend scoring under
# method: additive/crossover/relative_strength, and has rsi_ceiling /
# stoch_overbought fields for bearish signals not shown here). See that file
# for the authoritative, complete structure. Numbers below last synced 2026-08-19.

stock_score_thresholds:
  pass: 55
  caution: 35

horizons:
  swing:
    weights:
      trend: 0.30
      pullback: 0.20
      trigger: 0.25
      event: 0.15
      vol: 0.10
    trend:
      fast_ema: 50
      slow_ema: 200
      slow_slope_required: true
      fast_slope_required: false      # CAUTION if flat, not REJECT
    pullback:
      fib_shallow_min: 0.236
      fib_shallow_max: 0.382
      fib_standard_min: 0.382
      fib_standard_max: 0.500
      fib_golden_min: 0.500
      fib_golden_max: 0.618
      swing_high_lookback_bars: 40
      swing_high_min_bars_ago: 5
      max_days_in_pullback: 20
      theta_caution_days: 15
      atr_period: 14
      atr_pass_min: 1.0
      atr_pass_max: 2.0
      atr_caution_max: 2.5
    trigger:
      macd_fast: 8
      macd_slow: 21
      macd_signal: 5
      macd_histogram_rising: true
      rsi_period: 14
      rsi_floor: 38
      rsi_div_window_bars: 15
      stoch_k: 14
      stoch_d: 3
      stoch_smooth: 3
      stoch_oversold: 30
      stoch_tolerance_pct: 5
      setup_window_bars: 8
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.50
      volume_bonus_pts: 10
    event:
      reject_days: 21
      caution_days: 45
    vol:
      iv_rank_compressed_caution: 5
      iv_rank_pass_max: 34
      iv_rank_caution_max: 55

  intraday:
    weights:
      trend: 0.35
      pullback: 0.20
      trigger: 0.30
      event: 0.05
      vol: 0.10
    trend:
      fast_ema: 20
      slow_ema: 50
      slow_slope_required: true
      fast_slope_required: false
    pullback:
      fib_shallow_min: 0.236
      fib_shallow_max: 0.382
      fib_standard_min: 0.382
      fib_standard_max: 0.500
      fib_golden_min: 0.500
      fib_golden_max: 0.618
      swing_high_lookback_bars: 20
      swing_high_min_bars_ago: 5
      max_days_in_pullback: 3
      theta_caution_days: 2
      atr_period: 14
      atr_pass_min: 1.0
      atr_pass_max: 2.0
      atr_caution_max: 2.5
    trigger:
      macd_fast: 5
      macd_slow: 13
      macd_signal: 3
      macd_histogram_rising: true
      rsi_period: 14
      rsi_floor: 40
      rsi_div_window_bars: 10
      stoch_k: 14
      stoch_d: 3
      stoch_smooth: 3
      stoch_oversold: 30
      stoch_tolerance_pct: 5
      setup_window_bars: 10
      momentum_signals_for_pass: 1
      volume_lookback_bars: 20
      volume_multiplier: 1.20
      volume_bonus_pts: 10
    event:
      reject_days: 1
      caution_days: 3
    vol:
      iv_rank_compressed_caution: null   # not scored for intraday
      iv_rank_pass_max: null
      iv_rank_caution_max: null

  position:
    weights:
      trend: 0.30
      pullback: 0.20
      trigger: 0.20
      event: 0.20
      vol: 0.10
    trend:
      fast_ema: 50
      slow_ema: 200
      slow_slope_required: true
      fast_slope_required: true          # both required on weekly
    pullback:
      fib_shallow_min: 0.236
      fib_shallow_max: 0.382
      fib_standard_min: 0.382
      fib_standard_max: 0.500
      fib_golden_min: 0.500
      fib_golden_max: 0.618
      swing_high_lookback_bars: 75
      swing_high_min_bars_ago: 3
      max_days_in_pullback: 60
      theta_caution_days: 45
      atr_period: 14
      atr_pass_min: 1.0
      atr_pass_max: 2.0
      atr_caution_max: 2.5
    trigger:
      macd_fast: 12
      macd_slow: 26
      macd_signal: 9
      macd_histogram_rising: true
      rsi_period: 14
      rsi_floor: 37
      rsi_div_window_bars: 20
      stoch_k: 14
      stoch_d: 3
      stoch_smooth: 3
      stoch_oversold: 30
      stoch_tolerance_pct: 5
      setup_window_bars: 5
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.50
      volume_bonus_pts: 10
    event:
      reject_days: 30
      caution_days: 60
    vol:
      iv_rank_compressed_caution: 5
      iv_rank_pass_max: 44
      iv_rank_caution_max: 65
```
