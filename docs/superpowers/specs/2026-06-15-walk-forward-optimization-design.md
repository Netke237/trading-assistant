# Walk-Forward Parameter Optimization — Design Spec

**Date:** 2026-06-15
**Status:** Draft for review
**Author:** Kenneth + Claude (brainstorming session)

---

## 1. Purpose

Build an **offline, strategy-agnostic walk-forward optimizer** that determines robust **default parameters** for each trading strategy, then feeds those defaults into the live runtime. The engine also produces the video's honest "is this edge real or curve-fit?" verdict for each strategy.

Two outputs per strategy from every run:
1. **Proposed default parameters** — a single robust set, baked into runtime after human review.
2. **Verdict** — in-sample (curve-fit) performance vs walk-forward (blind) performance, with the return-degradation %, so a fundamentally weak strategy can be identified and dropped.

### What this is NOT
- Not per-stock optimization (statistically too few trades per stock → noise). Per-stock refinement is an explicit later phase.
- Not a runtime/in-request feature. The optimizer runs async in the background; the request path only *reads* adopted defaults.
- Not auto-adopting. Nothing changes live behavior until the user reviews and clicks **Adopt**.

---

## 2. Key decisions (locked in brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Granularity | **Pooled defaults — one robust set per strategy** across a representative basket. Per-stock refinement is a later phase. |
| 2 | Scoring objective | **Out-of-sample Sharpe + consistency** (must be positive in the majority of folds). Transaction costs always included. |
| 3 | Adoption model | **Review-then-adopt.** Job produces a *proposal* + full comparison (current vs proposed, margin, consistency, verdict). User adopts manually. |
| 4 | Cadence | **On-demand button + optional schedule toggle** (default off; weekly/monthly when on). Always async/background. |
| 5 | Basket | **Stratified sample across sectors + liquidity**, system-proposed and user-editable, stored for reproducibility. |
| 6 | Sector metadata | **Add a one-time `sector` column to `sp500.csv`** to enable sector stratification. |
| 7 | Window type | **Rolling** (default), train 12 months / test 3 months, both configurable. Anchored available as a toggle. |
| 8 | Search method | **Coarse grid search** over each strategy's config-defined ranges. |

---

## 3. Architecture

```
OFFLINE (new engine)                              RUNTIME (existing, lightly changed)
┌──────────────────────────────┐                 ┌──────────────────────────────┐
│ Optimizer job (async)        │                  │ Scan / strategy-watch / gate │
│  1. load basket (sectors)    │   writes after   │  reads tuned params from     │
│  2. pull OHLCV history        │   user ADOPTS   │  strategy_params.yaml        │
│  3. per-fold train→test       │ ───────────────►│  (instead of bare defaults)  │
│  4. consensus + OOS scoring   │                 │                              │
│  5. write PROPOSAL + verdict  │                 └──────────────────────────────┘
└──────────────────────────────┘
            │ proposal (not yet live)
            ▼
   Settings → "Strategy Tuning" tab
   review current vs proposed → ADOPT
```

### New components
| File | Responsibility |
|------|----------------|
| `backend/app/services/walk_forward.py` | Strategy-agnostic engine: fold splitting, per-fold train/test, grid search, OOS scoring. Wraps existing `run_strategy_backtest`. |
| `backend/app/services/strategy_param_optimizer.py` | Orchestrates a run: basket → per-strategy optimization → consensus → proposal + verdict. |
| `backend/app/services/strategy_param_store.py` | Loads/writes `strategy_params.yaml`. Single source of runtime params. |
| `backend/app/services/strategy_basket.py` | Builds the proposed basket (sector + liquidity strata) from `sp500.csv` + `ohlcv_daily`. |
| `backend/app/routers/strategy_tuning.py` | Endpoints: start job, poll progress, get proposal, adopt, get/save basket, get/save windows. |
| `backend/config/strategy_params.yaml` | Active defaults, per-strategy search spaces, basket definition, window + cost config. |
| Settings sub-tab (frontend) | Configure windows/costs, manage basket, run job, review + adopt. |

### Changed components
- `backend/app/data/sp500.csv` — add `sector` column.
- 3 runtime call sites read params from the store instead of bare defaults:
  - `backend/app/routers/stock_scan.py:134` (`_SIGNAL_KWARGS`)
  - `backend/app/services/strategy_backtest.py:97` (`fn(slice_bars)` → `fn(slice_bars, **params)`)
  - `backend/app/services/strategy_watch_evaluator.py` (signal call)
- `strategy_engine.py` signal functions already accept keyword params — **no change required**.

### Strategy-agnostic contract
The engine never hard-codes strategy names. Each strategy is described in `strategy_params.yaml` by:
- its tunable parameter names + default values,
- a search range (list of candidate values) per parameter.

Adding a new strategy = adding a config block + registering its signal fn in the existing `_SIGNAL_FNS` map. No engine edits.

---

## 4. The optimizer engine (`walk_forward.py`)

### 4.1 Fold construction (rolling)
Given the full date range and `train_months` / `test_months`:
- Fold = (train window, immediately-following test window).
- Step forward by `test_months`; repeat until history is exhausted.
- ~19 folds for 2018→present at 12/3 months (matches the video).
- Anchored mode: train window start fixed; train window grows each fold.

### 4.2 Per-fold train → test (per strategy)
For each fold:
1. **Train (in-sample):** run a grid search over the strategy's candidate parameter combos. Each combo is backtested **across every basket symbol**, restricted to the train window, and trades are **pooled**. Pick the combo with the best in-sample Sharpe → the fold's "winning params."
2. **Test (blind):** lock the winning params, run them across every basket symbol on the **test window only**. Record the pooled out-of-sample trades and the fold's chosen param values.

### 4.3 Collapse to one default (consensus)
After all folds:
- **Consensus default** = per-parameter aggregation of the fold winners: median for numeric params, mode for categorical (e.g. `ma_type`, `require_reversal`).
- Validate the single consensus set by running it across all fold **test** windows (blind) and stitching those OOS trades.

### 4.4 Scoring & eligibility
Computed on the **stitched out-of-sample** trades of the consensus set (after costs):
- Annualized **Sharpe** (primary metric — used for in-sample combo selection in §4.2 and for the proposed-vs-current comparison in §8).
- Expectancy, win rate, total return, max drawdown.
- **Consistency** = fraction of fold test-windows with positive OOS return.

Eligibility for adoption-recommendation:
- pooled OOS trade count ≥ `min_trades`,
- consistency ≥ 0.5 (positive in the majority of folds).

If no consensus set is eligible → verdict flags the strategy as **weak/curve-fit** (recommend dropping, per the video's core lesson).

### 4.5 The verdict (curve-fit detector)
- **In-sample illusion:** best single param set optimized on the *entire* history, its full-history return.
- **Walk-forward reality:** the stitched OOS return of the consensus set.
- **Return degradation %** = 1 − (walk-forward ÷ in-sample). High degradation = the edge was mostly curve-fitting.

### 4.6 Transaction costs
Per round-trip trade: `fee_pct + slippage_pct` applied to entry and exit. Default **0.1% per leg** (config). Costs are applied in both train and test so the optimizer never selects a cost-fragile edge.

---

## 5. Parameter search spaces (starting points — editable in config)

| Strategy | Parameter | Candidate values |
|----------|-----------|------------------|
| `pullback_ema` | `ema_period` | 20, 50 |
| | `trend_ema` | 100, 150, 200 |
| | `atr_stop_mult` | 1.0, 1.5, 2.0 |
| | `rr_target_mult` | 1.5, 2.0, 2.5, 3.0 |
| | `tolerance` | 0.05, 0.08, 0.10 |
| `breakout_base` | `base_lookback` | 15, 20, 30 |
| | `atr_tight_max` | 1.0, 1.5, 2.0 |
| | `volume_mult` | 1.1, 1.3, 1.5 |
| | `rr_target_mult` | 1.5, 2.0, 2.5, 3.0 |
| `ma_crossover` | `fast` | 10, 20 |
| | `slow` | 50, 100 |
| | `lookback` | 5, 10 |
| `mean_reversion_rsi` | `rsi_period` | 7, 14 |
| | `rsi_oversold` | 25, 30, 35 |
| | `trend_sma` | 100, 200 |

Grid sizes are deliberately small to bound compute and overfitting. All ranges live in `strategy_params.yaml` and can be widened/narrowed without code changes.

---

## 6. Storage formats

### `strategy_params.yaml`
```yaml
windows:
  type: rolling          # rolling | anchored
  train_months: 12
  test_months: 3
costs:
  fee_pct: 0.001
  slippage_pct: 0.001
basket:
  per_sector: 5          # top-N liquid names per sector
  symbols: [AAPL, MSFT, ...]   # frozen, reproducible
strategies:
  pullback_ema:
    active:              # adopted defaults consumed at runtime
      ema_period: 50
      trend_ema: 100
      atr_stop_mult: 1.5
      rr_target_mult: 2.0
      tolerance: 0.08
    search:              # grid ranges
      ema_period: [20, 50]
      ...
```
`active` is what runtime reads. `search` is what the optimizer explores. Initial `active` = the current hard-coded defaults, so behavior is unchanged until the first adoption.

### Job results
A run record (small DB table or JSON file keyed by job id) holding: status, progress, per-strategy proposal (consensus params), OOS metrics, per-fold winners, verdict numbers, and the equity-curve points for the retail-vs-walk-forward chart.

---

## 7. Jobs & async orchestration

- **On-demand:** `POST /api/strategy-tuning/run` enqueues a background job (reuse the existing `asyncio.create_task` + thread-pool pattern already used for backtests and schedulers). Returns a `job_id`.
- **Progress:** `GET /api/strategy-tuning/jobs/{job_id}` returns status, % complete, and per-strategy/per-fold progress (the video shows fold-by-fold progress).
- **Schedule:** optional toggle in `strategy_params.yaml` (mirrors `strategy_watches.yaml`'s `schedule` block); reuses the existing scheduler. Default off; cadence weekly or monthly. A scheduled run produces a proposal, never auto-adopts.
- **Concurrency:** one optimizer run at a time; new requests are rejected while a run is active.

### Performance note
Cost ≈ folds × grid combos × basket symbols × strategies single-symbol backtests. Mitigations: small grids, basket sampling (~50–80 names), thread-pool parallelism, per-(symbol, fold, combo) caching, and infrequent scheduling. Runtime is expected in minutes-to-tens-of-minutes for a sampled basket; the full-S&P "deep re-tune" is an explicit heavier opt-in.

---

## 8. Adoption flow (review-then-adopt)

Settings → **Strategy Tuning** tab shows, per strategy:
- **Current defaults** vs **Proposed defaults** (parameter values).
- OOS Sharpe / expectancy / return for each, and the **margin** of improvement.
- **Consistency** (positive folds / total folds).
- **Verdict:** in-sample vs walk-forward return + degradation %, with the blue (retail) vs orange (walk-forward) equity curves.
- **Per-fold table:** chosen params + OOS result per fold.
- **Recommendation badge:** "Proposed beats current — safe to adopt" / "Marginal — your call" / "Edge looks fake — consider dropping."

**Adopt** writes the proposed set to `active` in `strategy_params.yaml`. The previous `active` is archived (so adoption is reversible). Adoption is per-strategy — you can adopt one strategy's params and reject another's.

---

## 9. Runtime consumption

`strategy_param_store.get_active(strategy) -> dict` returns the adopted params. The 3 call sites pass them into the signal fn, merged with any per-request override (request override wins, preserving the existing `_SIGNAL_KWARGS` and `params_override` behavior). If `strategy_params.yaml` is missing or a strategy has no `active` block, the signal fn's own defaults apply — so the system degrades gracefully to today's behavior.

---

## 10. Testing

- **Unit:** fold construction (rolling + anchored, edge counts), consensus aggregation (median/mode), cost application, eligibility/consistency logic, degradation math.
- **Engine:** synthetic OHLCV with a known edge → optimizer recovers the planted params; synthetic noise → optimizer reports high degradation / ineligible.
- **Store:** YAML round-trip, missing-file fallback to signal-fn defaults, archive-on-adopt.
- **Runtime:** each call site honors adopted params and per-request overrides; missing config → unchanged behavior (regression guard).
- **Router:** job lifecycle (start → progress → proposal → adopt), single-run concurrency guard.
- **Basket:** stratification picks top-N liquid per sector; reproducible from frozen symbol list.

---

## 11. Out of scope (future phases)

- **Phase 2a — Per-stock refinement** (idea 5): for a small active watchlist, refine the global default per stock, adopting only if it beats the global out-of-sample. Guards against per-stock overfitting.
- **Phase 2b — Regime-conditioned defaults** (idea 7): per-(strategy × regime) defaults using the existing `/api/regime` signal, at the strategy level (not per stock) to keep enough trades per cell.
- **Phase 2c — Confirmation gate upgrade** (idea 4): make `passes_gate` judge stitched OOS performance of the adopted params at scan time.
- **Bayesian / random search** if grids become too large.
- **Sector-index or S&P-index baseline runs** (ideas 2/3) as cheaper fallbacks / sanity benchmarks.

---

## 12. Open questions

None blocking. Window defaults, cost defaults, search ranges, and basket size are all config-editable and can be tuned after the first real run.
