# Design — Confidence Score (Part 1) + Stock Scanner (Part 2)

Date: 2026-06-03
Status: Draft for review
Author: Kenneth + Claude

This document covers two related pieces of work for Bamendjou:

- **Part 1 — Confidence Score (option "1a")**: backtest the existing entry signal, turn it
  into a 0–100 number, show it, and let it *demote* (never inflate) the PASS/CAUTION/REJECT
  verdict in the **existing options scanner**.
- **Part 2 — Stock Scanner (PRD)**: a second scanning mode that picks stocks, applies an
  entry/exit strategy, backtests it, sizes the position, and either recommends or paper-trades it.

Part 1 is shared infrastructure that Part 2 also reuses (its Step 4). Build order: **Part 1 first**,
then Part 2.

Data constraint (applies throughout): Tiingo provides **daily** OHLCV only. All backtesting
covers **Swing / Position** horizons. True intraday backtesting is out of scope until an intraday
data source is added.

---

# Part 1 — Confidence Score (implementation-ready spec)

## 1. Goal
Make Step 4 ranking evidence-backed. Each ranked candidate gets a confidence number derived from
how often its entry signal has worked historically. A weak history can only *demote* a candidate's
status — it can never promote one. The number is always visible with a plain-English explanation,
and its gate thresholds are user-overridable.

## 2. What "the signal" is
The entry signal already produced by `backend/app/scoring/stock_scorer.py` — the combined
trend / pullback / trigger assessment. We are scoring *that* signal's historical reliability per
symbol. We are NOT yet scoring a full trade (entry+stop+target); that is Part 2, Step 6.

## 3. How a signal counts as "worked" (decision: ATR-based)
For each historical date where the signal fired:
- Compute ATR (Average True Range) at that date.
- Look forward **N days** (N derived from horizon: Swing ≈ 10 trading days, Position ≈ 40 trading
  days; configurable).
- **Win** = price moves favorably (up for Bullish, down for Bearish) by at least **k × ATR**
  (default k = 1.5, configurable) *before* moving k × ATR against, within the N-day window.
- ATR-based so the test is fair across cheap/expensive and calm/volatile stocks.

## 4. From outcomes to a 0–100 confidence score
- Run the historical replay with **backtesting.py** over 3–5 years of Tiingo history.
- Feed outcomes to **quantstats** to compute: hit rate %, average win vs. average loss, expectancy.
- Map to a single 0–100 "signal confidence". Initial formula (tunable):
  `confidence = clamp(0..100, 100 × hit_rate × min(1, payoff_ratio))`
  where `payoff_ratio = avg_win / avg_loss`. (Exact formula tuned during implementation; stored in
  `scoring_rules.yaml` so it is auditable.)
- Confidence becomes a `RuleResult(name="confidence", status, score, detail)` so it slots into the
  existing scoring structure with no new data model.

## 5. Storage / performance
- Compute in the background on a schedule (reuse the pattern of `data/chart_cache.py` /
  `services/scan_scheduler.py`). Cache keyed by `(strategy_signal, symbol, horizon)`.
- Refresh cadence: weekly (configurable). Live scans read the cached value only — never recompute
  mid-scan.

## 6. How it enters the engine (the gate — decision: demote-only)
Defined as a new block in `backend/config/scoring_rules.yaml`:

```yaml
confidence_gate:
  cautionBelow: 50   # confidence < 50 → cap final status at CAUTION
  rejectBelow: 35    # confidence < 35 → cap final status at REJECT
  enabled: true
```

Behavior in `stock_scorer.py` after the normal status is computed:
- The gate can only **lower** the status (PASS→CAUTION→REJECT), never raise it.
- It is applied via the existing `worstStatus(...)` composition so it stays consistent with the rest
  of the scoring.
- Ordering: among equal raw scores, higher confidence ranks first.

## 7. Overrides (decision: both default + per-scan)
- **Persistent default**: Settings → "Score weights & parameters" gains a "Confidence gate" control
  (cautionBelow / rejectBelow / enabled). Persisted like other settings.
- **Per-scan override**: a small control on the screener (Step 4 area) to tighten/loosen the two
  thresholds for the current scan only; resets to the persisted default next scan.
- Precedence: per-scan override > persisted default > YAML default.

## 8. Display (decision: always visible + interpretation text)
- **Step 4 ranking table**: new "Conf %" column beside Δrank / Δscore.
- **Score component cards** (Step 4 right panel): a "Confidence" card, same visual language as the
  trend/pullback/trigger cards.
- **Interpretation text** (plain English, always shown on the card / tooltip), templated, e.g.:
  - High (≥70): "Strong history — this setup worked 72% of the time on AAPL over 4 years, with wins
    bigger than losses."
  - Medium (50–69): "Mixed history — worked 58% of the time; treat with normal caution."
  - Low (<50): "Weak history — only 41% reliable on this stock. Capped at CAUTION."
- **Badge reason**: when the gate demotes, the status badge tooltip states the reason
  ("Demoted: signal only 41% reliable historically"), mirroring how Step 3 explains its REJECT.

## 9. Repos used (Part 1)
| Repo | Role |
|---|---|
| kernc/backtesting.py | Replays the signal over history |
| ranaroussi/quantstats | Hit rate / expectancy metrics |
| (existing) stock_scorer.py, indicator_compute.py, chart_cache.py, scan_scheduler.py | Signal, indicators, cache, scheduling |
| (existing) Tiingo source | Longer history window (no new source) |

## 10. Out of scope (Part 1)
- Full trade (stop/target) backtesting — that's Part 2 Step 6.
- Intraday horizon.
- Any change to trading/orders.

---

# Part 2 — Stock Scanner (PRD)

## 1. Overview
A second scanning **mode** in the existing screener that finds stocks, applies a chosen entry/exit
strategy, backtests it, sizes the position by risk, and then either **recommends** the trade or
sends it to **IBKR paper trading**. It reuses Steps 1–4 of the options screener and swaps the back
half.

## 2. Goals
- Reuse as much existing structure as possible (universe, direction, regime, ranking, alerts).
- Give a defined, testable entry/exit rule per candidate.
- Never let an unproven rule reach a trade — backtest is a gate.
- Risk-aware sizing from a manually-entered account size.
- Safe-by-default execution: recommendation or paper; live deferred.

## 3. Non-goals (v1)
- Live broker orders (separate, safety-reviewed project later).
- Intraday strategies.
- Options (handled by the existing scanner).
- Auto-close of positions (exits are monitor + alert; the human acts).

## 4. Users
Kenneth — single operator, swing/position horizon.

## 5. Placement (decision: mode toggle, shared steps)
One screener with a **Stocks / Options** mode switch. Steps 1–4 are shared; the back half branches
by mode. `scanStore` carries the active mode.

## 6. Workflow (7 steps)
| Step | Reuse | What happens |
|---|---|---|
| 1 — Universe | reuse | Pick stock pool (`universe_presets.py`, `sp500.csv`) |
| 2 — Direction | reuse | Long/short + horizon |
| 3 — Regime | reuse | Market-safe gate (`regime_hmm.py`) |
| 4 — Ranking | reuse + Part 1 | Score & sort, **with Conf % column** |
| 5 — Strategy / Entry-Exit | new (replaces Contracts) | Pick strategy; set trigger, stop, target |
| 6 — Backtest gate | new | Backtest the full rule on this stock; show win rate, return, drawdown; gate before trading |
| 7 — Position card + execution | new (replaces Trade Card) | Sizing + Recommend / Paper |

## 7. Strategies (decision: all four in v1)
Each strategy has configurable parameters (defaults below), editable in Settings (extend the
existing "Custom params" tab).

| Strategy | When | Entry | Stop | Exit | Source ref |
|---|---|---|---|---|---|
| Pullback to 20-EMA | steady trends | uptrend (px>rising 50-SMA) + dip to 20-EMA + reversal candle | below recent swing low | prior high / trail under higher lows | ai-trader; existing stock_scorer "pullback" |
| Breakout from tight base | momentum | break above N-day high after quiet range + volume spike | below the base | measured move / trail | ai-trader |
| MA crossover (20/50) | simple trend | 20-MA crosses above 50-MA | below 50-MA | cross back down | je-suis-tm/quant-trading |
| Mean reversion (RSI) | range / oversold-in-uptrend | RSI<30 while above 200-MA | below recent low | RSI to mid / target | je-suis-tm/quant-trading |

Ship-first recommendation: Pullback-to-20-EMA (closest to existing code), then the rest.

## 8. Backtest gate (Step 6)
- Engine: **backtesting.py**; report: **quantstats**.
- Per-symbol backtest of the *full* rule (entry + stop + target) over 3–5 years of cached Tiingo
  daily data.
- Surfaced metrics: win rate, total/annualized return, max drawdown, expectancy, # trades.
- Gate: a configurable minimum (e.g., min trades, min expectancy) before the candidate can proceed
  to Step 7. Thresholds live in config + Settings (same pattern as Part 1's gate).

## 9. Position sizing (decision: % risk AND fixed dollar, user picks)
- **Account size**: manual input in Settings (persisted).
- **Method selector** per trade:
  - **Fixed % risk**: shares = (account × risk%) / (entry − stop). Default risk% = 1%.
  - **Fixed dollar**: shares = fixed$ / entry.
- Show resulting shares, dollar exposure, and dollar risk on the position card.

## 10. Execution modes (decision: recommendation + paper in v1)
Step 7 mode switch, default safe:
| Mode | Behavior | Needs |
|---|---|---|
| Recommendation only (default) | shows entry/stop/target/size; places nothing | nothing (IBKR stays read-only) |
| Paper | sends simulated orders to IBKR **paper** account; tracks hypothetical P&L | IBKR paper login + paper order endpoints |
| Live (deferred) | real orders | out of scope v1 — separate project |

Note: the current IBKR adapter (`data/ibkr.py`) is explicitly read-only. Paper mode requires a new,
clearly-separated paper-order path; it must not enable live order endpoints.

## 11. Exit handling (decision: monitor + alert)
Reuse the existing alert system (`services/alert_*`, `services/portfolio_alert_monitor.py`,
notifications). When price hits stop or target, notify; the human acts. No auto-close in v1.

## 12. Reuse map (existing → stock scanner)
| Existing | Reused for |
|---|---|
| `universe_presets.py`, `sp500.csv` | Step 1 |
| `scanStore` | mode + scan context |
| `regime_hmm.py` | Step 3 |
| `stock_scorer.py` + Part 1 confidence | Step 4 |
| `indicator_compute.py` | strategy indicators |
| alert system + notifications | Step 7 exits |
| Settings "Custom params" tab | strategy params, sizing, gates |
| StepNavBar, screener layout, primitives/atoms/molecules | UI shell |

## 13. New dependencies (repos)
backtesting.py, quantstats (shared with Part 1); strategy logic referenced from whchien/ai-trader
and je-suis-tm/quant-trading; smart-money-concepts optional for structure-based stops.

## 14. Risks / open items
- Tiingo rate limits when caching multi-year history for many symbols — fetch-and-store, throttle.
- Synthetic-free: stock backtest uses real prices (good); no options modeling needed here.
- Paper-order path must be firewalled from live endpoints.
- Strategy parameter sprawl — keep defaults sane; expose in Custom tab only.

## 15. Success criteria
- A candidate can flow Universe → … → backtest gate → sized recommendation, end to end, for the
  Pullback strategy, with the backtest gate blocking unproven rules.
- Confidence column visible and demote-gate working in the existing options scanner.
- Paper order round-trips against IBKR paper account for at least one symbol.
