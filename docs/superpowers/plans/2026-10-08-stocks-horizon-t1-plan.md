# Stocks horizon T1: per-horizon tuning machinery — Implementation Plan (`STOCKS-HORIZON-T1`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Decision `STOCKS-PARAMS-PER-HORIZON-2026-10-05` (ADR `docs/adr/0001-stocks-parameters-per-horizon.md`,
terms in `GLOSSARY.md`), decision `STOCKS-HORIZON-T1-DESIGN-2026-10-05` (tuning gates = the replayable subset;
walk-forward windows scale with the hold), and Kenneth's answers of 2026-10-08 (in chat):

- **T1-BASKET-SECTOR-SAMPLE-2026-10-08.** The grid search runs on a sector sample (about 10 symbols per sector, about
  110 symbols). Fire rates are scaled from the sample to the universe. Before the report, each cell's winning
  parameters are checked again on the **full** universe (S&P 500 + NDX 100, minus the exclusion list).
- **T1-LIVE-COST-UNCHANGED-2026-10-08.** The tuner charges 0.05% per leg and reports 0.2% per leg as a stress test.
  The live Step-6 per-symbol backtest gate keeps its 0.2% (`costs:` block untouched). T2 replaces that gate.

**Hard dependency.** T1 depends on `STOCKS-HORIZON-P0` (P0A built; P0B in progress on `codex/stocks-horizon-p0b`).
This plan may be written and audited now. **No ticket is built until P0B is merged to the base branch and its audit
is clean.** H2 reads P0B's `StockScanRequest.hold_max_days` and `DEFAULT_HOLD_MAX`; H6 runs after P0B's stock-send
guards. If P0B changes either name, the coordinator updates this plan before H2 starts.

**What T1 does NOT do** (other tasks): run the tuner on Kenneth's data (`STOCKS-HORIZON-TUNING-RUN`); the Adopt
action, Unvalidated labels from tuned verdicts and the pooled per-cell gate (`T2`); scorer re-tune (`T3`);
Pre-Breakout (`T4`); Intraday and `mean_reversion_vwap` (no daily bars, ADR decision 1).

**Live behaviour that changes, on purpose.**

- **H1 (error fix):** single-strategy live scans, Analysis and `mean_reversion_multi` now give a strategy the same
  400-bar window as the backtest. Today they get the last 120 bars, so `mean_reversion_rsi` (needs `trend_sma +
  rsi_period + 5` = 219 bars), `mean_reversion_bb` (needs 225), and `pullback_ema` with `trend_ema >= 111` can
  **never fire** in a live scan, while the Step-6 backtest of the same symbol shows trades. After H1 they fire live.
  The scorer's own `bars[-120:]` window is **not** changed (T3).
- **H2:** every backtest closes a trade still open `hold_max_days` calendar days after entry, at the next bar's open.
  Step-6 win rates and expectancies move, most for long-hold strategies on short horizons.
- **H3:** `mean_reversion_multi` gets a backtest of its own rule (the variant vote and the combined levels), no longer
  the `mean_reversion_rsi` stand-in. Its Step-6 numbers change.
- **H4/H5:** the Stocks Step-4 strategy panel loads the profile for the chosen direction × horizon from the backend.
  Until Kenneth adopts tuned values (T2), every profile **is** today's direction block, so the values shown change
  only where the frontend's own hardcoded defaults differed from the YAML (e.g. pullback tolerance 8% in the frontend,
  4% in `active.bullish`). That difference is a defect today: the YAML's adopted value never reached a live scan.
- **H6/H7:** a stock position or a strategy watch that has a hold raises `TIME_STOP` once it has been held
  `hold_max_days`. No automatic close (ADR decision 2).

## Global constraints

- **Runtime.** Backend Python **3.11** (Windows `.\.venv\Scripts\python.exe -m pytest`). Frontend
  `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **Numeric golden pins.** H1, H2 and H3 move backtest and signal pins on purpose. The implementer lists every moved
  pin with the reason (window, time exit, multi rule). Any other moved pin is a defect: stop and report it.
- **No value changes outside this plan:** `costs:` (0.1% + 0.1%), `scoring_rules.yaml`, `min_samples`, confidence
  thresholds and every existing `active:` value stay as they are.
- **YAML comments.** `strategy_param_store.adopt()` rewrites `strategy_params.yaml` with `yaml.safe_dump`, which
  drops comments. Rationale for new blocks goes in docstrings and in this plan, not only in YAML comments.
- **Persisted stores.** Any persisted-shape change bumps `version` with a `migrate()` branch (CLAUDE.md). New stores
  that do not need persistence have no `persist()`.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Shared definitions (used by several tickets)

- **Horizon keys.** The frontend `HorizonKey` spelling: `Swing`, `Position`, `Quarterly`, `SemiAnnual`, `Annual`
  (`frontend/lib/horizonPresets.ts`). Backend constant `TUNED_HORIZONS` in new module
  `app/services/horizon_profiles.py`, same spelling, same order. `Intraday` and `Custom` are not tuned horizons.
- **Params horizon.** The tuned horizon a scan or watch reads parameters for: the preset key when it is one of
  `TUNED_HORIZONS`; for `Custom`, `resolveParamsHorizon(...)` (Swing or Position by `holdMax`, as today); for
  `Intraday`, none (direction baseline).
- **Hold max per tuned horizon** (calendar days, from `HORIZON_PRESETS`): Swing 15, Position 45, Quarterly 60,
  SemiAnnual 105, Annual 200. Backend constant `HOLD_MAX_DAYS` in `horizon_profiles.py`, with a comment naming
  `horizonPresets.ts` as the source it mirrors. A test reads both files and fails if they differ (same idea as the
  existing YAML/TS sync tests; follow the nearest one).
- **Signal window.** `SIGNAL_WINDOW_BARS = 400` in `app/services/strategy_engine.py`. Every caller of a strategy
  signal function passes `bars[-SIGNAL_WINDOW_BARS:]`: live scan (single + multi), Analysis, strategy watch, the
  backtest's per-bar slice, and the tuner. The scorer keeps `bars[-120:]`.
- **Bars needed.** `bars_needed(strategy, params) -> int` in `strategy_engine.py`: the smallest bar count for which
  the signal function's own length guard can pass (e.g. `mean_reversion_rsi`: `trend_sma + rsi_period + 5`;
  `mean_reversion_bb`: `trend_sma + bb_period + 5`; `ma_crossover`: `slow + 5`; `pullback_ema`: `trend_ema + 10`;
  read each guard from the code, do not copy these from here). A test calls every signal function with
  `bars_needed - 1` bars → `None` (guard holds) and checks that every grid combination in H4's `search_by_horizon`
  has `bars_needed <= SIGNAL_WINDOW_BARS` (no grid point can be silently dead).
- **Time exit.** Trade entered on bar `e` (date `d_e`). At the close of bar `t`, if `(d_t - d_e).days >=
  hold_max_days`, the trade is closed at bar `t+1`'s open. Stop and target stay active on bar `t+1` exactly as
  `backtesting.py` orders them against a market close. The exit reason is `"time"`. `hold_max_days=None` means no
  time exit (today's behaviour). The live alert uses the same rule at end of day: days held `>= hold_max_days`.
- **Cell.** strategy × direction × tuned horizon. Tuned strategies: `pullback_ema`, `breakout_base`, `ma_crossover`,
  `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_multi` (6 × 2 × 5 = 60 cells).
- **Net trade return.** A trade's percent return after charging the per-leg cost on entry and exit, the way
  `backtesting.py` charges `commission` (`Trade.pl_pct`). **Net expectancy** = mean net trade return over the
  pooled trades.

## Ticket graph

```
H1 (signal window) ── H2 (time exit) ── H3 (multi backtest) ──┐
H4 (profiles in YAML + read path + API) ── H5 (frontend profiles)
H6 (position TIME_STOP) ── H7 (watch horizon + TIME_STOP)      │
H8 (signal cache + simulator + gate mask) ◄────────────────────┘ (needs H1-H4)
H9 (walk-forward per cell) ── H10 (report + CLI + full-universe re-check)
```

Sequential build: H1, H2, H3, H4, H5, H6, H7, H8, H9, H10. H1–H3 and H8 edit `strategy_backtest.py` /
`strategy_engine.py`; H1, H2, H4 edit `routers/stock_scan.py`; serial order avoids conflicts.

---

## H1 — One signal window for scan, Analysis, watch and backtest

**Mechanism today.** `routers/stock_scan.py::_process_stock` calls the signal function on `bars[-120:]` (and
`_multi_signal` on `bars[-120:]`); `_analyze_core` does the same. `strategy_backtest.run_strategy_backtest` slices the
last 350 bars per bar. `strategy_watch_evaluator._eval_strategy_watch` passes whatever `get_bars(start, end)`
returned. Length guards in `strategy_engine` return `None` when the window is too short, so a live scan with
`rsi_trend_sma: 200` never produces a `mean_reversion_rsi` signal.

**Semantics.**

- Add `SIGNAL_WINDOW_BARS = 400` and `bars_needed(strategy, params)` (shared definitions) to `strategy_engine.py`.
- Replace the signal-call slices: `_process_stock` single path (`bars[-120:]` → `bars[-SIGNAL_WINDOW_BARS:]`; the
  intraday branch keeps `intraday_bars[-300:]`), `_multi_signal`, `_analyze_core`'s signal call, the backtest's
  `start = max(0, n - 350)` → `n - SIGNAL_WINDOW_BARS` (update its comment), and the watch evaluator's `fn(bars, ...)`
  → `fn(bars[-SIGNAL_WINDOW_BARS:], ...)`. Check that the watch's `get_bars` range covers 400 trading bars; if not,
  widen it.
- The scan's history fetch is 5 years (`_HISTORY_YEARS`), enough. The scorer call keeps `bars[-120:]`.

**Test first.** (1) A synthetic 600-bar series built so `mean_reversion_rsi` (defaults, `trend_sma` 200) fires on
the last bar: `_process_stock` (mocked bars/quotes as the existing scan tests do) returns a card, not
`no setup`. Today it returns the no-setup rejection. (2) Same for `mean_reversion_bb`. (3) `bars_needed` guard test
from shared definitions (the grid half runs once H4 lands; until then it checks the current `search:` blocks).
(4) Watch evaluator receives at most 400 bars.

**Commit:** `fix(stocks): one 400-bar signal window for scan, Analysis, watch and backtest (STOCKS-HORIZON-T1)`

---

## H2 — Time exit in the backtest; the live scan passes the hold

**Mechanism today.** `run_strategy_backtest` holds a trade until stop or target. Nothing knows the hold.

**Semantics.**

- `run_strategy_backtest(..., hold_max_days: int | None = None, entry_end: date | None = None)`. Inside `next()`,
  before the entry logic: for each open trade apply the shared **time exit** (`trade.close()` is a market order,
  filled at the next bar's open). `entry_end`: no new entry on a bar dated `>= entry_end` (tuner use; mirrors
  `entry_start`).
- New `run_strategy_backtest_trades(...)` with the same arguments, returning `(BacktestResult, list[TradeRecord])`.
  `TradeRecord` (frozen dataclass in `strategy_backtest.py`): `entry_date: date, exit_date: date, entry_price: float,
  exit_price: float, net_return_pct: float, exit_reason: Literal["stop", "target", "time", "end"]`. `run_strategy_backtest`
  calls it and drops the list, so its return type and API payloads are unchanged. Exit reason: compare the exit price
  with the trade's `sl`/`tp`; `"time"` comes from a set of trades the strategy closed itself; `"end"` is not expected
  (open trades at the end are excluded, `finalize_trades=False`) and is only defined for completeness.
- `BacktestResult` gains `n_time_exits: int = 0` (append at the end, default keeps constructors valid).
- Stock scan: `_process_stock` and `_analyze_core` pass `hold_max_days = req.hold_max_days if not None else
  DEFAULT_HOLD_MAX[req.horizon]` (both from P0B). `_backtest_key` includes it, so cached results without a time exit
  are not served.
- The Settings → Strategy Tuning WFO (`strategy_param_optimizer.py`) is left as it is (no hold). Logged in H10's
  report as "legacy tuner, no time exit".

**Test first.** (1) A synthetic series where a long entry never touches stop or target: with `hold_max_days=15`
the trade exits on the open of the first bar after the bar dated `>= entry + 15` calendar days; across a weekend
the exit is the Monday open. (2) `hold_max_days=None` → identical trades to today (pin). (3) Stop hit before the
time limit → `exit_reason "stop"`, no time exit. (4) `entry_end`: no entry on or after it. (5) Scan: the backtest key
differs for hold 15 vs 45; a request without `hold_max_days` on Swing uses 15.

**Commit:** `feat(backtest): time exit at hold_max_days, next-bar open; scan passes the hold (STOCKS-HORIZON-T1)`

---

## H3 — A real `mean_reversion_multi` backtest

**Mechanism today.** `stock_scan._multi_signal` runs the variant loop and `resolve_multi_signal`; the backtest uses
`_MULTI_BT_STRATEGY = "mean_reversion_rsi"` as a stand-in. `resolve_multi_signal`'s docstring records this as a
known limitation.

**Semantics.**

- Move the loop into `strategy_engine.multi_signal(bars, *, direction, variants, min_confirmations,
  variant_params: dict[str, dict]) -> StrategySignal | None`, returning `resolve_multi_signal(fired)` when at least
  `min_confirmations` variants fire. `variant_params` is the fully merged kwargs per variant (the caller merges).
  `mean_reversion_vwap` in `variants` raises `ValueError` (the scan keeps its 422).
- `_multi_signal` calls it; its rejection reasons stay word-for-word (the funnel guard regex reads them).
- **Flat grid keys for the tuner and profiles** (`MULTI_PARAM_ROUTES` in `strategy_engine.py`):
  `rsi_oversold`, `rsi_period`, `trend_sma` → `mean_reversion_rsi`; `bb_std`, `bb_period` → `mean_reversion_bb`;
  `vwap_lookback`, `vwap_deviation_pct` → `mean_reversion_vwap_daily`; `min_confirmations`, `variants` → the vote.
  `split_multi_params(params) -> (variants, min_confirmations, variant_params)` applies the routes over each
  variant's merged exit + baseline.
- `strategy_backtest` registers `"mean_reversion_multi"`: its per-bar function is `multi_signal` with
  `split_multi_params(effective_params)`. `Strategy` literal gains it.
- Scan: `_bt_strategy = "mean_reversion_multi"`, `_bt_params` = the same merged params the live loop used, so the
  backtest replays exactly the rule the card shows. Delete `_MULTI_BT_STRATEGY` and `_multi_bt_params`. Update
  `resolve_multi_signal`'s docstring: the limitation is closed.

**Test first.** (1) On a synthetic series, `run_strategy_backtest(strategy="mean_reversion_multi", params={...,
"min_confirmations": 2})` places trades only on bars where two variants fire, at the combined levels (assert the
first trade's stop/target equal `resolve_multi_signal` on that bar). (2) `min_confirmations: 3` with only two
variants able to fire → zero trades. (3) The scan's multi backtest key names `mean_reversion_multi`.
(4) Live loop and backtest agree: the scan's signal on the last bar equals `multi_signal` on the same window.

**Commit:** `feat(backtest): mean_reversion_multi backtests its own vote and levels (STOCKS-HORIZON-T1)`

---

## H4 — Horizon profiles: YAML, read path, API, scan and watch use them

**Mechanism today.** `strategy_params.yaml` holds `strategies.<s>.active.<direction>` (one set per direction),
`search:` (one grid) and `exit:`. `_merge_strategy_params(strategy, direction, request_kwargs)` merges exit < active
< request. The stock scan request carries only the scoring horizon (`Swing` / `Position` / `Intraday`).

**Semantics.**

- **YAML shape** (ADR decision 3, `active.<direction>.<horizon>`): inside `active.<direction>`, a key named in
  `TUNED_HORIZONS` holds a dict = that horizon's profile; every other key is the **direction baseline** (today's
  values, unchanged). T1 writes no profile; T2's Adopt writes them. Example after a future adopt:
  ```yaml
  active:
    bullish:
      ema_period: 50        # baseline
      ...
      Swing: {ema_period: 20, trend_ema: 50, atr_stop_mult: 1.5, exit_swing_lookback: 10, tolerance: 0.04}
  ```
- `strategy_param_store`: `get_active(strategy, direction)` returns the baseline **only** (horizon keys removed), so
  every existing caller is unchanged. New `get_profile(strategy, direction, horizon) -> tuple[dict, Literal["tuned",
  "baseline"]]` = `{**baseline, **profile}` and `"tuned"` when the profile exists, else `(baseline, "baseline")`.
  `horizon=None` → baseline. New `get_search_by_horizon(strategy, horizon) -> dict`.
  `adopt(strategy, params, direction, horizon=None)`: `horizon=None` keeps today's behaviour **and preserves any
  horizon sub-dicts** in that direction block (today it replaces the block wholesale, which would delete them);
  with a horizon it writes only `active[direction][horizon]`. T2 wires the button; T1 only makes it correct.
- **Grids** (ADR decision 4: per horizon, ≤ 150 combinations per cell): new `search_by_horizon:` under each tuned
  strategy, values below. The old `search:` stays for the Settings WFO. A load-time check (H8's tuner and a unit
  test) refuses a grid with more than 150 combinations or a combination whose `bars_needed > SIGNAL_WINDOW_BARS`.
  Combinations with `fast >= slow` (ma_crossover) or `ema_period >= trend_ema` (pullback_ema) are skipped by the
  tuner and counted in the report, not errors.

  | Strategy | Horizon | Grid | n |
  |---|---|---|---:|
  | pullback_ema | Swing | ema_period [10,20,35] · trend_ema [50,100] · atr_stop_mult [1.0,1.5,2.0] · exit_swing_lookback [10,20] · tolerance [0.02,0.04] | 72 |
  | pullback_ema | Position | ema_period [20,35,50] · trend_ema [100,150,200] · atr_stop_mult [1.5,2.0,2.5] · exit_swing_lookback [20,30] · tolerance [0.03,0.06] | 108 |
  | pullback_ema | Quarterly | ema_period [35,50,100] · trend_ema [150,200] · atr_stop_mult [2.0,2.5,3.0] · exit_swing_lookback [30,50] · tolerance [0.04,0.08] | 72 |
  | pullback_ema | SemiAnnual | ema_period [50,100] · trend_ema [150,200] · atr_stop_mult [2.5,3.0,4.0] · exit_swing_lookback [50,100] · tolerance [0.04,0.08] | 48 |
  | pullback_ema | Annual | ema_period [50,100,150] · trend_ema [200] · atr_stop_mult [3.0,4.0,5.0] · exit_swing_lookback [100,150] · tolerance [0.06,0.10] | 36 |
  | breakout_base | Swing | base_lookback [10,15,20] · atr_tight_max [3.0,3.5,4.0,4.5] · volume_mult [1.1,1.3,1.5] · measured_move_mult [0.5,0.75,1.0] | 108 |
  | breakout_base | Position | base_lookback [15,20,30] · atr_tight_max [3.0,3.5,4.0,4.5] · volume_mult [1.1,1.3,1.5] · measured_move_mult [0.75,1.0,1.5] | 108 |
  | breakout_base | Quarterly | base_lookback [20,30,40] · atr_tight_max [3.5,4.0,4.5,5.0] · volume_mult [1.1,1.3,1.5] · measured_move_mult [1.0,1.5,2.0] | 108 |
  | breakout_base | SemiAnnual | base_lookback [30,40,60] · atr_tight_max [4.0,4.5,5.0] · volume_mult [1.1,1.3] · measured_move_mult [1.5,2.0,3.0] | 54 |
  | breakout_base | Annual | base_lookback [40,60,90] · atr_tight_max [4.0,5.0,6.0] · volume_mult [1.1,1.3] · measured_move_mult [2.0,3.0,4.0] | 54 |
  | ma_crossover | Swing | fast [5,10,20] · slow [30,50] · lookback [3,5,10] · atr_target_mult [1.5,2.0,3.0] | 54 |
  | ma_crossover | Position | fast [10,20,30] · slow [50,100,150] · lookback [5,10] · atr_target_mult [2.0,3.0,4.0] | 54 |
  | ma_crossover | Quarterly | fast [20,30,50] · slow [100,150,200] · lookback [5,10,20] · atr_target_mult [3.0,4.0,5.0] | 81 |
  | ma_crossover | SemiAnnual | fast [30,50] · slow [150,200] · lookback [10,20] · atr_target_mult [4.0,6.0,8.0] | 24 |
  | ma_crossover | Annual | fast [50,100] · slow [200,300] · lookback [10,20] · atr_target_mult [6.0,8.0,10.0] | 24 |
  | mean_reversion_rsi | Swing | rsi_period [2,7,14] · rsi_oversold [10,20,30,35] · trend_sma [50,100,200] · exit_sma_period [5,10,20] | 108 |
  | mean_reversion_rsi | Position | rsi_period [7,14,21] · rsi_oversold [25,30,35,40] · trend_sma [100,200] · exit_sma_period [10,20,50] | 72 |
  | mean_reversion_rsi | Quarterly | rsi_period [14,21] · rsi_oversold [30,35,40] · trend_sma [100,200] · exit_sma_period [20,50] | 24 |
  | mean_reversion_rsi | SemiAnnual | rsi_period [14,21,28] · rsi_oversold [30,35,40] · trend_sma [200] · exit_sma_period [50,100] | 18 |
  | mean_reversion_rsi | Annual | rsi_period [14,21,28] · rsi_oversold [30,35,40] · trend_sma [200] · exit_sma_period [100,150] | 18 |
  | mean_reversion_bb | Swing | bb_period [10,15,20] · bb_std [1.5,2.0,2.5] · trend_sma [50,100,200] · stop_atr_mult [0.5,1.0] | 54 |
  | mean_reversion_bb | Position | bb_period [20,30] · bb_std [1.5,2.0,2.5] · trend_sma [100,200] · stop_atr_mult [0.5,1.0,1.5] | 36 |
  | mean_reversion_bb | Quarterly | bb_period [30,50] · bb_std [2.0,2.5] · trend_sma [100,200] · stop_atr_mult [1.0,1.5,2.0] | 24 |
  | mean_reversion_bb | SemiAnnual | bb_period [50,100] · bb_std [2.0,2.5] · trend_sma [200] · stop_atr_mult [1.5,2.0,3.0] | 12 |
  | mean_reversion_bb | Annual | bb_period [100,150] · bb_std [2.0,2.5] · trend_sma [200] · stop_atr_mult [2.0,3.0,4.0] | 12 |
  | mean_reversion_multi | Swing | min_confirmations [2,3] · vwap_lookback [10,20] · vwap_deviation_pct [0.01,0.02,0.03] · rsi_oversold [25,30,35] · bb_std [1.5,2.0,2.5] | 108 |
  | mean_reversion_multi | Position | min_confirmations [2,3] · vwap_lookback [20,50] · vwap_deviation_pct [0.02,0.03,0.05] · rsi_oversold [30,35] · bb_std [2.0,2.5] | 48 |
  | mean_reversion_multi | Quarterly, SemiAnnual, Annual (each) | min_confirmations [2,3] · vwap_lookback [50,100] · vwap_deviation_pct [0.03,0.05,0.08] · rsi_oversold [30,35,40] · bb_std [2.0,2.5] | 72 |

  **Grid rationale** (lives here, YAML comments do not survive `adopt()`): look-backs, stops and targets lengthen
  with the hold, because a time exit now caps the trade and a target that cannot be reached inside the hold only
  turns into a time exit. Each grid brackets the current baseline where it is sensible for that hold. Parameters
  that do not move rung 1 stay out of the grid (same reason as the existing `search:` comments). The parameter
  **names** above must match each signal function's keyword names; the implementer checks every one against
  `strategy_engine.py` and stops on a mismatch.
- **API.** `GET /api/config/strategy-profiles` in `routers/config.py`: `{ "<strategy>": { "Bullish"|"Bearish": {
  "<horizon>": {"params": {...}, "source": "tuned"|"baseline"} } } }` for the six tuned strategies and the five tuned
  horizons, plus `"baseline"` per direction. Read fresh on each call (the store's 60 s cache applies).
- **Scan.** `StockScanRequest` gains `params_horizon: Optional[Literal["Swing","Position","Quarterly","SemiAnnual",
  "Annual"]] = None`. `_merge_strategy_params(strategy, direction, request_kwargs, params_horizon=None)`: exit <
  `get_profile(...)` < request. Every caller in `stock_scan.py` passes `req.params_horizon` (including the multi
  variants via H3's merge). The card gains `params_source: Literal["tuned","baseline"]` for display (H5).
- **Watch.** The evaluator merges `get_profile(key, wdir, w.get("params_horizon"))` instead of `get_active` (H7
  adds the field; until then it is absent → baseline, unchanged).

**Test first.** (1) `get_active` on a block with a `Swing:` sub-dict returns the baseline without it. (2)
`get_profile` tuned / baseline / `None`. (3) `adopt(..., horizon=None)` keeps an existing `Swing:` sub-dict;
`adopt(..., horizon="Swing")` writes only it. (4) Grid check: every `search_by_horizon` grid ≤ 150 and every combo
`bars_needed <= 400`; the table above is the YAML (a test reads the YAML and compares counts per cell to this
plan's n column). (5) Endpoint shape. (6) Scan with `params_horizon="Quarterly"` and a tuned `Quarterly` profile in a
temp YAML uses the profile; without one uses the baseline; a request value still wins.

**Commit:** `feat(stocks): per-horizon parameter profiles in strategy_params.yaml, read by scan and watch (STOCKS-HORIZON-T1)`

---

## H5 — Frontend: the Step-4 panel loads the horizon profile

**Mechanism today.** `scanParamsStore` (persisted, `'bamendjou:scan-params'`) holds hardcoded `DEFAULTS` for the
strategy fields; Step 4 Stocks (`app/(frame)/screener/step-4-stocks/page.tsx`) copies them into local `useState`
for `StrategyParamsPanel`; `resolveStockScanRequest.ts` **always** sends every field, so the YAML `active:` value of
a field the panel shows never reaches a live scan.

**Semantics.**

- **No hardcoded copy** (ADR decision 3), and **no hardcoded fallback** (decision
  `DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29`, which the later threshold stores follow: a failed fetch shows no
  verdict). This supersedes the ADR's "with a fallback": the backend already applies the profile when the request
  omits a field, so a failed fetch loses nothing.
- New `lib/strategyProfilesStore.ts` (no `persist()`), modelled on `eventThresholdsStore.ts`: `profiles | null`,
  `status`, `error`, `fetch()`, a `seq` guard and a strict `parseStrategyProfiles(raw)` that throws naming the path.
- **Override model.** `scanParamsStore` keeps the user's edits only: each strategy field becomes `T | null`, where
  `null` = follow the profile. Bump `version`; the `migrate()` branch sets every strategy field to `null` (the old
  persisted values were the hardcoded defaults or edits made against them; Kenneth re-enters any edit he wants
  kept — the coordinator tells him in the ticket report). Non-strategy fields (`btMinTrades`, `eventFilter`,
  `stockShortlistMax`, multi variants list) keep their values.
- The panel shows, per field: the override if set, else the profile value for (direction, params horizon), with a
  small `tuned` / `baseline` tag per strategy section and a per-field "reset to profile". If the store failed, the
  panel says "Profile unavailable — the scan uses the backend's values" and shows the overrides only.
- `resolveStockScanRequest.ts` sends `params_horizon` (shared definitions) and only the **overridden** strategy
  fields; a `null` field is omitted, so the backend applies the profile.
- Changing horizon or direction never erases overrides.

**Test first.** Parser tests (good payload; each malformed path named). Store: failed fetch → `profiles null`,
status `failed`. Request builder: no overrides → no strategy fields, `params_horizon: "Quarterly"` for a Quarterly
context and `"Position"` for Custom 60–185; one override → only that field. Migration: a v-old persisted state →
all strategy fields `null`, other fields kept. Panel: shows the profile value, then the override after an edit.

**Commit:** `feat(ui): Step-4 strategy panel follows the backend horizon profile; edits are overrides (STOCKS-HORIZON-T1)`

---

## H6 — Stock positions raise TIME_STOP at the hold

**Mechanism today.** `TIME_STOP` exists for options only (`alert_generator.py` ~L375 and `frontend/lib/alertEngine.ts`
~L334, both `<= 3` DTE). `PortfolioPosition` (`models/portfolio.py`) has `entry_date` but no hold.

**Semantics.**

- `portfolio_positions` gains nullable `hold_max_days INTEGER` (Alembic migration; existing rows `NULL`). The
  portfolio schemas and `frontend/types/domain.ts` `PortfolioPosition` gain `holdMaxDays: number | null`.
- The stock sends (Step 7 position card, `StockSendDialog`, `StockPositionCard` paths — the same places P0B B7
  touches) write `hold_max_days` = the scan's hold (`sanitizeHoldDays` over `ScanContext`'s hold). Options rows stay
  `NULL`.
- Backend `alert_generator`: for a stock position (`parse_expiry_from_contract` → `None`) with `hold_max_days` set,
  `days_held = (today - date(entry_date)).days`; if `days_held >= hold_max_days` and not muted → `TIME_STOP` with
  `reference_value = days_held`, reason `Time stop — {symbol} held {days_held}d (hold {hold_max_days}d)`. Same
  dedup/log path as the options branch. Frontend `alertEngine.ts` mirrors it, replacing the `!isStock` exclusion with
  the stock rule. Alerts page label: `Time stop (≤3 DTE / hold reached)`. `EditDrawer.tsx`'s stock case shows
  `held ≥ N days` when set.
- `NULL` hold → no stock time stop (today's behaviour).

**Test first.** Backend: stock row entered 15 days ago, hold 15 → one `TIME_STOP`; 14 days → none; `NULL` → none;
options row unchanged. Frontend: same three cases in `alertEngine`; the stock send body carries `hold_max_days`
(Custom 60–185 → 185).

**Commit:** `feat(alerts): stock positions raise TIME_STOP when held hold_max_days (STOCKS-HORIZON-T1)`

---

## H7 — Strategy watches carry a horizon and raise a time exit

**Mechanism today.** A strategy watch (`strategy_watches.yaml`, `routers/strategy_watch.py::AddWatch`) has symbol,
strategy, direction, `params_override`; the evaluator moves `idle → armed` on a signal and back on stop / target /
reversal. No hold.

**Semantics.**

- `AddWatch` and `BulkAdd` gain `params_horizon: Optional[TunedHorizon] = None`. The watch stores it plus
  `hold_max_days` (= `HOLD_MAX_DAYS[params_horizon]`, or `None`). Existing watches: absent → `None`.
- Evaluator, `armed` phase, before the stop/target checks: if `hold_max_days` is set and `(today -
  date(last_event_at)).days >= hold_max_days` where `last_event` is `entry` or `reversal` → event `exit_time`
  (`reason: "{symbol}: {label} time exit — held {n}d (hold {hold}d)"`), state → idle. Add `exit_time` wherever
  `exit_stop`/`exit_target` are enumerated (formatter, notification text, frontend types and labels).
- The strategy-watch page's add form offers the horizon (the five tuned horizons plus "none"); the list shows it.

**Test first.** Armed 15 days with hold 15 → `exit_time`, idle; 14 days → no event; no horizon → never; an
`exit_time` formats and dispatches like `exit_stop`. Frontend: the add request carries `params_horizon`.

**Commit:** `feat(watch): strategy watches carry a horizon; time exit at its hold (STOCKS-HORIZON-T1)`

---

## H8 — Tuner core: signal cache, trade simulator, replayable gate mask

**Why a simulator.** One `backtesting.py` run calls the signal function on every bar. Up to 150 combinations × 60
cells × ~110 symbols × each fold is far too slow. Signals do not depend on the horizon or on the cost; trades do.
So H8 computes each (symbol, strategy, direction, combination) **signal series once**, caches it on disk, and
simulates trades cheaply per horizon and per cost. A parity test ties the simulator to `run_strategy_backtest`.

**Semantics.** New package `app/services/horizon_tuning/`:

- `signals.py`: `signal_series(bars, strategy, direction, params) -> list[SignalPoint | None]`, one entry per bar,
  computed exactly as `run_strategy_backtest`'s `next()` would (same `n < 60` skip, `bars[-SIGNAL_WINDOW_BARS:]`
  window, same `effective_params` merge with `get_exit`, the multi path from H3). `SignalPoint(entry, stop,
  target)`. Disk cache under `backend/data/tuning_cache/` (gitignored), key = symbol, strategy, direction, sorted
  params, `SIGNAL_WINDOW_BARS`, last bar date, and a `SIGNAL_CACHE_VERSION` constant bumped whenever a signal
  function changes.
- `simulate.py`: `simulate_trades(bars, signals, *, direction, commission, hold_max_days, entry_start, entry_end,
  allowed: list[bool] | None) -> list[TradeRecord]`. Rules = `run_strategy_backtest`'s: DAY limit entry valid for one
  bar, `_entry_side` check, one position at a time, stop/target via `backtesting.py`'s fill rules, H2's time exit,
  commission per leg, no entry where `allowed[t]` is False. The implementer reads `backtesting.py` 0.6.x's order
  processing (`_Broker._process_orders`) and copies its fill rules (limit fill price, same-bar SL/TP ordering, gap
  handling) — the parity test is the judge.
- **Parity test (gate for this ticket).** Synthetic deterministic series (seeded random walks, 1,500 bars, trending
  and choppy, plus the four 251-bar fixtures), every tuned strategy × both directions × `hold_max_days` in {None,
  15, 200} × commission in {0, 0.0005, 0.002}: `simulate_trades` equals `run_strategy_backtest_trades`' list
  (dates equal, prices and returns within 1e-9). One combination per strategy from H4's grids plus the baseline.
- `gates.py`: `gate_mask(bars, direction, scoring_horizon, *, min_price, max_price, benchmark) -> list[bool]`: per
  bar `t`, the replayable live gates on bars up to `t`, in the scan's order: price within `[min_price, max_price]`
  (close of `t`; `None` = no bound); `score_stock(bars[t-119..t], direction, scoring_horizon, scoring_mode="stock",
  regime_signal=None, fundamentals=None, earnings/dividend None, overrides=None, benchmark aligned as the scan
  does)` status `!= "REJECT"`; `_direction_conviction_drop(...)` returns `None` (import the scan's helper — do not
  copy it). Scoring horizon = `Swing` for Swing, `Position` for the four longer horizons (as the scan sends today).
  Cached on disk like signals.
- **Not applied, and named in every report** (decision `STOCKS-HORIZON-T1-DESIGN-2026-10-05`): regime gate, regime
  filter, fundamentals, IV, earnings dates, the confidence replay, `min_stock_score`, the per-symbol backtest gate.
- `basket.py`: tuning sample = `build_basket(rows, per_sector=tuning.basket.per_sector)` (existing
  `strategy_basket.py`) over S&P 500 ∪ NDX 100 rows minus `universe_exclusions.yaml` (both scopes — the evidence
  scope is exactly "skipped by tuning"); NDX names not in `sp500.csv` join with their sector if known, else
  `"Unknown"`. Universe = the same union minus exclusions (for the fire-rate scale and H10's re-check).
- `strategy_params.yaml` gains a `tuning:` block (read by `strategy_param_store.get_tuning_config()`):
  ```yaml
  tuning:
    cost_per_leg: 0.0005          # ADR decision 4
    stress_cost_per_leg: 0.002
    held_out_months: 12
    windows:                      # decision STOCKS-HORIZON-T1-DESIGN-2026-10-05: test >= 2 x holdMax, train = 2 x test
      Swing:      {train_months: 12, test_months: 3}
      Position:   {train_months: 12, test_months: 3}
      Quarterly:  {train_months: 12, test_months: 4}
      SemiAnnual: {train_months: 16, test_months: 8}
      Annual:     {train_months: 24, test_months: 12}
    fire_rate_floor_per_day:      # candidates per scan day across the universe (ADR decision 4)
      Swing: 2.0
      Position: 1.0
      Quarterly: 0.6              # 3 / week
      SemiAnnual: 0.4             # 2 / week
      Annual: 0.2                 # 1 / week
    adoption: {ci_level: 0.95, min_oos_trades: 100, min_symbols: 20, bootstrap_resamples: 2000, seed: 7}
    min_train_trades: 30
    basket: {per_sector: 10}
    gates: {min_price: null, max_price: null}
  ```
  A week is 5 scan days. Loader validates every key and refuses unknown or missing ones (fail loudly).
- **Runtime probe.** `scripts/tune_horizons.py --probe` (the CLI lands in H10; H8 ships this flag) times the signal
  function per strategy on 3 symbols and prints ms per call and a projected total for the configured basket and
  grids at `--workers N`. The implementer runs it on the fixtures and records the numbers in the ticket report.

**Test first.** Parity test above (first). Gate mask: a bar whose scorer status is REJECT is `False`; a bar below
`min_price` is `False`; the conviction-floor case matches `_direction_conviction_drop`. Cache: second call reads from
disk (mock the compute, assert not called); a `SIGNAL_CACHE_VERSION` bump recomputes. Config loader refuses an
unknown key.

**Commit:** `feat(tuning): signal cache, parity-tested trade simulator and replayable gate mask (STOCKS-HORIZON-T1)`

---

## H9 — Walk-forward per cell

**Semantics.** `app/services/horizon_tuning/walk_forward_cell.py::tune_cell(cell, data) -> CellResult`.

- **Data range.** All stored daily bars per symbol (`historical_store.get_bars` from 1990-01-01; Phase C loaded
  2020-10-06 .. 2026-10-02). `data_end` = latest bar date common to ≥ 90% of the sample. **Held-out year** =
  `[data_end - held_out_months, data_end]`; `heldout_start` is its first day.
- **Folds.** `build_folds(data_start, heldout_start, train_months, test_months)` with the horizon's windows. Entries
  in a test window: `[test_start, min(test_end, heldout_start - hold_max_days - 7 days))`. A trade may run past its
  test window (it is closed by the time exit, at most `hold_max_days` + a few days later) but never into the held-out
  year. Train entries likewise stop `hold_max_days + 7` days before `train_end`. Folds whose entry window is empty
  are dropped. A cell with fewer than 4 folds is labelled **thin** (Annual: about 3).
- **Selection (per fold).** For each grid combination (skipping the invalid ones, counted): simulate the train
  window at `cost_per_leg` with the gate mask. Eligible if pooled train trades ≥ `min_train_trades` **and** the
  train fire rate ≥ the horizon's floor, where fire rate = (gate-passing signal bars in the sample over the train
  window ÷ scan days in it) × (universe size ÷ sample size). Winner = highest pooled train **net expectancy**; tie →
  more trades, then grid order. No eligible combination → fold has no winner (counted).
- **Out-of-sample.** Each fold's winner trades its test window (same simulator, `cost_per_leg` and
  `stress_cost_per_leg`). The pooled OOS trades across folds are the walk-forward evidence.
- **Final parameters.** The combination that won the most folds; tie → highest net expectancy over the union of all
  train windows. Always a grid point (no median of values — `consensus()` could produce off-grid values).
- **Held-out year.** The final parameters trade the held-out year once, both costs.
- `CellResult`: cell, final params, fold winners, per-fold OOS stats, pooled OOS trades (at both costs, as
  `TradeRecord` lists with symbol), held-out stats, fire rate (sample-scaled), counts (combos tried / invalid /
  ineligible), `thin`.
- Parallelism: signal series are computed in a `ProcessPoolExecutor` (`--workers`), one work unit per (symbol,
  strategy, direction, combination batch); simulation runs in-process.

**Test first.** On a small synthetic universe with a planted edge (one combination clearly profitable after costs,
others not) the planted combination wins every fold and is final. Fold construction: Annual on 2020-10-06 ..
2026-10-02 gives the expected folds and entry cut-offs (pin the dates); no OOS trade's exit date ≥ `heldout_start`.
Fire-rate scaling formula pinned on a hand-counted case. A combination below the floor never wins.

**Commit:** `feat(tuning): per-cell walk-forward with hold-scaled windows and a held-out year (STOCKS-HORIZON-T1)`

---

## H10 — Report, CLI and the full-universe re-check

**Semantics.**

- **CLI** `backend/scripts/tune_horizons.py`: `--cells` (filter, default all 60), `--directions` (default both),
  `--workers` (default `os.cpu_count() - 1`), `--probe`, `--resume` (skips cells whose result JSON exists for the
  same config hash), `--out DIR` (default `docs/superpowers/measurements/<today>-horizon-tuning/`). Prints the
  projected runtime before starting. Runs on Kenneth's machine (bars are only in his Postgres).
- **Full-universe re-check** (T1-BASKET-SECTOR-SAMPLE-2026-10-08): for each cell's final parameters, compute the
  signal series and gate mask on the **whole universe** and report the measured fire rate over the walk-forward
  span. The floor verdict uses this number, not the scaled one (both are shown).
- **Adoption bar** per cell (ADR decision 5), computed at `cost_per_leg`:
  1. OOS net expectancy 95% CI lower bound > 0 — cluster bootstrap over symbols (resample symbols with
     replacement, 2000 resamples, seed 7, trade-weighted mean), as the Phase C evidence harness does.
  2. Held-out year net expectancy > 0.
  3. Pooled OOS trades ≥ 100.
  4. OOS symbols with ≥ 1 trade ≥ 20.
  5. Full-universe fire rate ≥ the horizon floor.
  Verdict `passes_bar` true only if all five hold. Bearish cells are computed and shown, marked **blocked
  (P0B)** whatever the verdict. Nothing is written to `active:` (T2).
- **Chance count.** The report states `cells passed` and `expected by chance = n_cells_evaluated × 0.025 × 0.5`
  (one-sided 2.5% CI miss × an independent held-out coin flip under no edge), with that formula written out and
  labelled an approximation.
- **Report files.** `tuning_report.json` (every `CellResult` field, the config, the git commit, data range, sample and
  universe sizes, runtimes) and `tuning_report.md`: one row per cell (final params, OOS trades / symbols / net
  expectancy and CI at 0.05%, the same at 0.2%, held-out at both costs, fire rate scaled and full, folds, thin,
  verdict, failed criteria). Header lists: the gates **not applied** (H8 list), "legacy Settings tuner has no time
  exit", the survivorship / bull-market label (ADR consequences), the cost model.

**Test first.** Bootstrap CI on a fixed trade list pinned (seed 7). Adoption bar: each of the five criteria failing
alone flips the verdict and is named. Chance-count formula. `--resume` skips a finished cell. A tiny end-to-end run
on two synthetic symbols writes both files with every documented column.

**Commit:** `feat(tuning): tune_horizons CLI, adoption-bar report and full-universe fire-rate re-check (STOCKS-HORIZON-T1)`

---

## Verification (coordinator, after H10)

- Backend full suite on Python 3.11; frontend typecheck + Jest.
- `tune_horizons.py --probe` on Kenneth's machine: the projected runtime is reported to him before the real run
  (`STOCKS-HORIZON-TUNING-RUN`). If it is over 24 h at his core count, the coordinator raises it with him (options:
  smaller `per_sector`, fewer cells per night with `--resume`).
- Live checks on Kenneth's machine: a live `mean_reversion_rsi` scan returns setups (H1); a Swing stock scan's
  Step-6 shows time exits (H2); the Step-4 panel shows `baseline` profiles (H5); a stock position entered with hold 15
  raises `TIME_STOP` on day 15 (H6).

## Out of scope (logged, not built)

- The Adopt button, Unvalidated labels from verdicts, the pooled gate replacing the per-symbol backtest gate (T2).
- Switching the live Step-6 gate to 0.05% per leg (decision T1-LIVE-COST-UNCHANGED-2026-10-08; T2).
- The legacy Settings → Strategy Tuning WFO: no time exit, 3-year window, Sharpe ranking. Left running as is;
  candidates for removal once T2 ships.
- Longer history and delisted names (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05, logged, not scheduled).
- The scorer's 120-bar window (T3).
