# Stocks horizon T1: per-horizon tuning machinery — Implementation Plan (`STOCKS-HORIZON-T1`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Decision `STOCKS-PARAMS-PER-HORIZON-2026-10-05` (ADR `docs/adr/0001-stocks-parameters-per-horizon.md`,
terms in `GLOSSARY.md`), decision `STOCKS-HORIZON-T1-DESIGN-2026-10-05` (tuning gates = the replayable subset;
walk-forward windows scale with the hold), and Kenneth's answers in chat (recorded as decisions by the coordinator in
`PROJECT_STATE.json` before H1 starts):

- **T1-BASKET-SECTOR-SAMPLE-2026-10-08.** The grid search runs on a sector sample (10 symbols per sector stratum).
  Fire rates are scaled per sector to the universe. Before the report, each cell's final parameters are checked
  again on the **full** universe (S&P 500 ∪ NDX 100 minus the exclusion list).
- **T1-LIVE-COST-UNCHANGED-2026-10-08.** The tuner charges 0.05% per leg and reports 0.2% per leg as a stress test.
  The live Step-6 per-symbol backtest gate keeps 0.2% (`costs:` untouched). T2 replaces that gate.
- **T1-ANNUAL-TWO-FOLDS-2026-10-09.** Annual keeps train 24 / test 12. With warm-up and the held-out year it gets
  about 2 folds (not the ~3 the T1-DESIGN decision estimated); its results are labelled **thin**.
- **T1-CUSTOM-NEAREST-HOLD-2026-10-09.** A Custom hold uses the parameters of the tuned horizon whose hold max is
  nearest to the Custom hold max; the card names it ("Custom: using Annual settings").
- **T1-PROFILES-NO-FALLBACK-2026-10-09.** The frontend has no hardcoded copy of the profiles and no fallback: a
  failed fetch shows "profile unavailable" and the backend applies the profile itself. This supersedes ADR 0001
  decision 3's "with a fallback" and follows `DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29`.

**Hard dependency.** T1 depends on `STOCKS-HORIZON-P0`. P0B is built and its code round came back clean
(2026-10-09, `codex/stocks-horizon-p0b` @ `cb16238e`) but is not merged. **No ticket is built until P0B is merged to
the base branch.** H2 reads P0B's `StockScanRequest.hold_max_days` and `DEFAULT_HOLD_MAX`; H6 edits the stock sends
P0B B7 changed. If P0B's merged names differ, the coordinator updates this plan before H2 starts.

**Not in T1** (other tasks): running the tuner on Kenneth's data (`STOCKS-HORIZON-TUNING-RUN`); the Adopt action,
Unvalidated labels from tuned verdicts, the pooled per-cell gate (`T2`); scorer re-tune and its 120-bar window
(`T3`); Pre-Breakout (`T4`); Intraday and `mean_reversion_vwap` (no daily bars, ADR decision 1).

**Live behaviour that changes, on purpose.**

- **H1 (error fix): one 400-bar signal window.** Live single-strategy scans, `mean_reversion_multi`, Analysis,
  strategy watches and composite watches give a strategy the last 400 bars, as the backtest will. Today they get 120
  (composite watches: `bars[i-119:i+1]`), so `mean_reversion_rsi` (needs 219 bars at defaults), `mean_reversion_bb`
  (225), and `pullback_ema` with `trend_ema >= 111` **never fire live** while Step 6 shows trades. After H1 they fire.
  Also, because `_ema` is seeded from the window's first values and `_rsi` smooths from the window start, **every
  live `pullback_ema` signal and every RSI reading moves** (entries, stops and tolerance hits), for every symbol.
  The scorer's `bars[-120:]` is not changed.
- **H2: time exit.** Every daily-bar backtest closes a trade still open `hold_max_days` calendar days after entry, at
  the next bar's open. Step-6 win rates and expectancies move, **and so do `passes_gate` and the scan's
  backtest-gate keep/drop verdicts** — the candidate list changes. Intraday horizon and intraday strategies get no
  time exit.
- **H3:** `mean_reversion_multi` backtests its own vote and combined levels, not the `mean_reversion_rsi` stand-in.
  Its Step-6 numbers and gate verdicts change.
- **H4/H5:** a live scan's strategy parameters come from the backend profile for direction × params horizon unless
  the user overrode a field. Until T2 adopts tuned values every profile **is** today's direction baseline, so values
  change only where the request used to carry a frontend/schema default instead of the YAML value (e.g. pullback
  tolerance 8% → the YAML's 4%; breakout volume 1.1 (frontend) / 1.5 (schema) → YAML 1.5). That difference is a
  defect today: the adopted YAML value never reached a live scan. Saved search profiles and scheduled scans lose
  their frozen strategy values (migration, H5).
- **H6/H7:** a stock position or a strategy watch with a hold raises `TIME_STOP` once held `hold_max_days`. No
  automatic close (ADR decision 2).

## Global constraints

- **Runtime.** Backend Python **3.11** (Windows `.\.venv\Scripts\python.exe -m pytest`). Frontend
  `cd frontend && npm run typecheck && npm run test`. The worktree has no `.venv`; the coordinator creates one from
  `backend/requirements.txt` before H1. `backtesting` must be the pinned **0.6.6** (Kenneth's main checkout has
  0.6.5 installed); H8's parity test asserts `backtesting.__version__ == "0.6.6"`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **Numeric golden pins.** H1, H2, H3 and H4 move signal, backtest and scan pins on purpose. The implementer lists
  every moved pin with its cause (window, time exit, multi rule, profile value). Any other moved pin is a defect:
  stop and report it.
- **No value changes outside this plan:** `costs:` (0.1% + 0.1%), `scoring_rules.yaml`, `min_samples`, confidence
  thresholds and every existing `active:` value stay as they are.
- **YAML comments.** `strategy_param_store.adopt()` rewrites `strategy_params.yaml` with `yaml.safe_dump`, which
  drops comments. Rationale for new blocks lives in docstrings and this plan.
- **Persisted stores.** Any persisted-shape change bumps `version` with a `migrate()` branch (CLAUDE.md).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Shared definitions (used by several tickets)

- **Tuned horizons.** `Swing`, `Position`, `Quarterly`, `SemiAnnual`, `Annual` — the frontend `HorizonKey` spelling
  (`frontend/lib/horizonPresets.ts`). Backend `TUNED_HORIZONS` in new `app/services/horizon_profiles.py`, same order.
- **Hold max per tuned horizon** (calendar days): Swing 15, Position 45, Quarterly 60, SemiAnnual 105, Annual 200.
  Backend `HOLD_MAX_DAYS` in `horizon_profiles.py`, with a comment naming `horizonPresets.ts`; a test reads both
  files and fails if they differ.
- **Params horizon** — which tuned horizon's parameters a scan or watch reads. Frontend
  `tunedParamsHorizon(hz, holdMax): TunedHorizon | null` in `horizonPresets.ts` (new; `resolveParamsHorizon` is
  left alone — it feeds the options table): a tuned preset → itself; `Intraday` → `null`; `Custom` → `null` if
  `scoringHorizonForHold(holdMax) === 'Intraday'`, else the tuned horizon minimising `|holdMax − HOLD_MAX|` (tie →
  the shorter horizon). Backend `tuned_params_horizon(hold_max_days)` in `horizon_profiles.py`, same rule, used when
  a request carries a hold but no `params_horizon`. Examples pinned in both test suites: Custom 60–185 → Annual;
  Custom 5–30 → Swing (|30−15|=15 = |30−45|=15, tie → Swing); Custom 0–3 → `null`.
- **Signal window.** `SIGNAL_WINDOW_BARS = 400` in `app/services/strategy_engine.py`. Every caller of a strategy
  signal function passes at most the last 400 bars ending at the evaluated bar: live scan (single + multi),
  Analysis, strategy watch (entry and reversal), composite watch, the backtest's per-bar slice, the tuner.
- **Bars needed.** `bars_needed(strategy, params) -> int` in `strategy_engine.py`: the smallest bar count at which
  **every** length guard of the signal function can pass, read from the code (e.g. `ma_crossover` is `slow +
  max(5, lookback + 1)`-shaped because of both `len(bars) < slow + 5` and `len(slow_ma) < lookback + 1` — the
  implementer derives each exactly). `mean_reversion_multi` = max over its variants with their merged params.
  Tested both ways (H1).
- **Time exit.** Trade filled on bar `e` (date `d_e`). At the close of bar `t`, if `(d_t − d_e).days >=
  hold_max_days`, the trade is closed with a market order. `backtesting.py` inserts a close order at the front of the
  queue (`Trade.close()`), so it fills at bar `t+1`'s **open before** stop and target are checked: stop and target
  cannot fire on `t+1`. Exit reason `"time"`. `hold_max_days=None` = no time exit. The live alert uses the same rule at
  end of day (days held `>= hold_max_days`).
- **Hold for a backtest.** `hold_for_backtest(horizon, strategy, hold_max_days) -> int | None`: `None` when the
  scoring horizon is `Intraday` or the strategy is intraday (`mean_reversion_vwap`); else `hold_max_days` if given,
  else `DEFAULT_HOLD_MAX[horizon]` (P0B).
- **Cell.** strategy × direction × tuned horizon. Tuned strategies: `pullback_ema`, `breakout_base`, `ma_crossover`,
  `mean_reversion_rsi`, `mean_reversion_bb`, `mean_reversion_multi` (6 × 2 × 5 = 60 cells).
- **Net trade return** = a trade's `Trade.pl_pct` (×100) with the per-leg cost as `backtesting.py`'s `commission`.
  **Net expectancy** = the mean net trade return over pooled trades (trade-weighted).
- **Multi params shape.** One nested object, used by the live loop, the backtest, the profile and the tuner:
  `{"variants": [...], "min_confirmations": n, "variant_params": {"<variant>": {...}}}`. Its effective form is built
  by `merge_multi_params(base, override)` (H3): `variant_params[v]` = `get_exit(v)` ∪ the variant's baseline
  `get_active(v, direction)` ∪ the multi profile's `variant_params[v]` ∪ request overrides. Grid keys address it with
  dots: `min_confirmations`, `mean_reversion_rsi.rsi_oversold`, `mean_reversion_bb.bb_std`,
  `mean_reversion_vwap_daily.vwap_lookback`, ….

## Ticket graph

```
H1 (signal window) ── H2 (time exit) ── H3 (multi backtest + shape) ── H4 (profiles, Optional request fields)
H4 ── H5 (frontend profiles + migrations)
H4 ── H6 (position TIME_STOP) ── H7 (watch horizon + TIME_STOP)
H4 ── H8 (signal/gate cache, simulator, gate mask) ── H9 (walk-forward per cell) ── H10 (report, CLI, re-check)
```

Sequential build: H1 … H10. H1–H4 and H8 edit `strategy_backtest.py` / `strategy_engine.py` / `stock_scan.py`;
serial order avoids conflicts.

---

## H1 — One signal window everywhere a signal is computed

**Mechanism today.** `routers/stock_scan.py::_process_stock` calls the signal function on `bars[-120:]`;
`_multi_signal` and `_analyze_core` likewise. `strategy_backtest.run_strategy_backtest` slices the last 350 bars per
bar. `strategy_watch_evaluator._eval_strategy_watch` passes the full `get_bars` result (entry and reversal paths).
`composite_trigger_evaluator.py` (~L472) slices `bars[max(0, i - 119): i + 1]`. Length guards return `None` on short
windows.

**Semantics.**

- Add `SIGNAL_WINDOW_BARS` and `bars_needed` (shared definitions).
- Replace every slice above with `[-SIGNAL_WINDOW_BARS:]` (composite: `bars[max(0, i - SIGNAL_WINDOW_BARS + 1): i +
  1]`); the scan's intraday branch keeps `intraday_bars[-300:]`; the backtest's `start = max(0, n - 350)` becomes
  `n - SIGNAL_WINDOW_BARS` (update its comment). Check that the watch's and the composite evaluator's `get_bars`
  ranges reach 400 trading bars; widen them if not. `_MIN_STRATEGY_BARS` in the composite evaluator is left as is.
- Grep for any other caller of a `*_signal` function (`grep -rn "_signal(" backend/app`) and apply the same rule;
  list them in the ticket report.

**Test first.** (1) A synthetic 600-bar series built so `mean_reversion_rsi` at defaults fires on the last bar:
`_process_stock` (mocked bars/quotes as existing scan tests do) returns a card. Today: the no-setup rejection.
(2) Same for `mean_reversion_bb`. (3) The composite evaluator matches a `mean_reversion_rsi` setup on that series.
(4) `bars_needed` both ways, per strategy, on synthetic series built to fire: with exactly `bars_needed` bars the
signal is not `None`; with `bars_needed − 1` it is `None`. (5) Every combination in the current `search:` blocks has
`bars_needed <= 400` (H4 extends this to its grids). (6) Watch entry and reversal calls receive ≤ 400 bars.

**Commit:** `fix(stocks): one 400-bar signal window for scan, Analysis, watches and backtest (STOCKS-HORIZON-T1)`

---

## H2 — Time exit in the backtest; the live scan passes the hold

**Mechanism today.** `run_strategy_backtest` holds a trade until stop or target. `next()` returns early on `n <
60` and on warm-up bars before `entry_start`.

**Semantics.**

- `run_strategy_backtest(..., hold_max_days: int | None = None, entry_end: date | None = None)`. In `next()`,
  the order is: cancel stale entry orders; `n < 60` return; **then the time-exit loop over open trades** (shared
  definitions); then the `entry_start` warm-up return; then `entry_end` (no new entry on a bar dated `>= entry_end`,
  return); then entry logic. So a trade open at `entry_start`/`entry_end` boundaries still time-exits.
- New `run_strategy_backtest_trades(...)` (same arguments) → `(BacktestResult, list[TradeRecord])`.
  `TradeRecord` (frozen dataclass, `strategy_backtest.py`): `entry_date: date, exit_date: date, entry_price: float,
  exit_price: float, net_return_pct: float, exit_reason: Literal["stop", "target", "time"]`. `run_strategy_backtest`
  calls it and drops the list (return type and API payloads unchanged). Exit reason: `"time"` if the strategy closed
  it (record the trade in a set when calling `close()`); else by side and inequality — Bullish: exit price `<= sl` →
  stop, `>= tp` → target; Bearish mirrored (works for gap fills at the open).
- `BacktestResult` gains `n_time_exits: int = 0` (last field, defaulted).
- Stock scan: `_process_stock` and `_analyze_core` pass `hold_for_backtest(req.horizon, bt_strategy,
  req.hold_max_days)`. `_backtest_key` includes it.
- The legacy Settings → Strategy Tuning WFO (`strategy_param_optimizer.py`) is unchanged (no hold); H10's report
  says so.

**Test first.** (1) A long entry that never touches stop or target, `hold_max_days=15`: exits at the open of the
first bar after the first bar dated `>= entry + 15` calendar days; a case crossing a weekend and a holiday.
(2) `hold_max_days=None` → identical trades to today (pin). (3) Stop hit before the limit → `"stop"`, no time exit.
(4) On the time-exit bar's next bar the open is beyond the stop: the exit is `"time"` at the open (close fills
first). (5) A gap-through-stop fill classifies `"stop"`. (6) A trade open on the `entry_end` bar still time-exits
later; no entry on or after `entry_end`. (7) Scan: Swing request without `hold_max_days` → 15 in the key; Intraday
→ `None`; `mean_reversion_vwap` → `None`.

**Commit:** `feat(backtest): time exit at hold_max_days, next-bar open; scan passes the hold (STOCKS-HORIZON-T1)`

---

## H3 — `mean_reversion_multi`: one params shape, a real backtest

**Mechanism today.** `stock_scan._multi_signal` loops variants, merging each with `_merge_strategy_params(variant,
…)` and reading `min_confirmations`, `vwap_lookback`, `vwap_deviation_pct` from the request; the backtest uses
`_MULTI_BT_STRATEGY = "mean_reversion_rsi"`. `strategy_params.yaml` has no `mean_reversion_multi` block.

**Semantics.**

- `strategy_engine.multi_signal(bars, *, direction, params) -> StrategySignal | None` over the **multi params shape**
  (already merged): runs each variant with `variant_params[v]`, returns `resolve_multi_signal(fired)` when at least
  `min_confirmations` fire. `mean_reversion_vwap` in `variants` → `ValueError` (the scan keeps its 422).
- `merge_multi_params(direction, profile, request_overrides) -> dict` builds the effective shape (shared
  definitions). H3 calls it with `profile = get_active("mean_reversion_multi", direction)`; H4 swaps in
  `get_profile`.
- `strategy_params.yaml` gains `strategies.mean_reversion_multi.active.{bullish,bearish}` = `{variants:
  [mean_reversion_rsi, mean_reversion_bb, mean_reversion_vwap_daily], min_confirmations: 2, variant_params:
  {mean_reversion_vwap_daily: {vwap_lookback: 20, vwap_deviation_pct: 0.02}}}` (today's frontend values, so live
  behaviour is unchanged by the move) and an empty `exit: {}`.
- `_multi_signal` builds the shape once (request overrides: `mean_reversion_variants`,
  `mean_reversion_min_confirmations`, `vwap_lookback`, `vwap_deviation_pct`, the variant-specific request fields
  from `_SIGNAL_KWARGS`) and calls `multi_signal`; its rejection reasons stay word-for-word (funnel guard regex).
- `strategy_backtest` registers `"mean_reversion_multi"`: per bar `multi_signal(window, direction=…,
  params=effective_params)`; `effective_params` = the shape passed in (no `get_exit` merge for multi). `Strategy`
  literal gains it.
- Scan: `_bt_strategy = "mean_reversion_multi"`, `_bt_params` = **the same shape object** the live call used;
  `_backtest_key` hashes it (canonical JSON, sorted keys). Delete `_MULTI_BT_STRATEGY` and `_multi_bt_params`.
  `resolve_multi_signal`'s docstring: limitation closed.

**Test first.** (1) Backtest places trades only on bars where ≥ `min_confirmations` variants fire, at the combined
levels (first trade's stop/target = `resolve_multi_signal` on that bar). (2) `min_confirmations: 3` with a variant
unable to fire → zero trades. (3) Parity: the scan card's entry/stop/target on the last bar equal `multi_signal` on
the same window with the same shape, and the backtest key changes when any nested value changes. (4) The YAML
baseline reproduces today's live result on a fixture (pin before/after).

**Commit:** `feat(backtest): mean_reversion_multi backtests its own vote and levels (STOCKS-HORIZON-T1)`

---

## H4 — Horizon profiles: YAML, read path, API, Optional request fields

**Mechanism today.** `strategies.<s>.active.<direction>` holds one set; `_merge_strategy_params` drops only `None`
request values, and **every strategy field of `StockScanRequest` has a non-`None` default** (`schemas/stock_scan.py`
~L16–29, ~L95–97), so the YAML `active:` value of any field the request carries never applies.

**Semantics.**

- **Request fields become Optional.** Every strategy field of `StockScanRequest` (and of the Analysis request if it
  is a separate model) becomes `Optional[...] = None`, same bounds: `pullback_tolerance_pct`, `pullback_ema_period`,
  `pullback_trend_ema`, `pullback_ma_type`, `ma_crossover_fast/slow/lookback`, `breakout_volume_mult`,
  `rsi_period`, `rsi_oversold`, `rsi_overbought`, `rsi_trend_sma`, `require_choppy_regime`,
  `mean_reversion_variants`, `mean_reversion_min_confirmations`, `vwap_lookback`, `vwap_deviation_pct`.
  `pullback_require_reversal` stays as is (UI toggle, not tuned). Before changing, grep every request builder and
  backend reader of these fields (Pre-Breakout ad-hoc scans, schedule resolver, `_SIGNAL_KWARGS`, Analysis,
  auto-trade) and make each read `None`-safe; list them in the ticket report.
- **YAML shape** (ADR decision 3, `active.<direction>.<horizon>`): inside `active.<direction>`, a key in
  `TUNED_HORIZONS` holds that horizon's profile dict; every other key is the **direction baseline** (unchanged
  values). T1 writes no profile.
- `strategy_param_store`: `get_active(strategy, direction)` returns the baseline only (horizon keys removed), so
  existing callers are unchanged. `get_profile(strategy, direction, horizon) -> tuple[dict, Literal["tuned",
  "baseline"]]` = `({**baseline, **profile}, "tuned")` when the profile exists, else `(baseline, "baseline")`;
  `horizon=None` → baseline. For `mean_reversion_multi` the merge is nested (`variant_params` per variant).
  `get_search_by_horizon(strategy, direction, horizon) -> dict`. `adopt(strategy, params, direction,
  horizon=None)`: `None` keeps today's behaviour **but preserves horizon sub-dicts** (today it replaces the block
  wholesale); with a horizon it writes only `active[direction][horizon]`. T2 wires the button.
- **Grids** (ADR decision 4, ≤ 150 per cell): `search_by_horizon: {bullish: {<horizon>: grid}, bearish: {…}}`
  under each tuned strategy. Bullish grids = the table below. **Bearish grids are the same except**:
  `mean_reversion_rsi` tunes `rsi_overbought` with the mirrored values (100 − each `rsi_oversold` value) instead of
  `rsi_oversold` (the bearish branch reads only `rsi_overbought`, `strategy_engine.py` ~L851), and the multi grid's
  `mean_reversion_rsi.rsi_oversold` becomes `mean_reversion_rsi.rsi_overbought` likewise. The implementer checks
  every other strategy for a direction-only parameter the same way and reports it. The old `search:` stays for the
  legacy WFO. A load-time check (unit test + H8's loader) refuses a grid with > 150 combinations or a combination with
  `bars_needed > SIGNAL_WINDOW_BARS`. Combinations with `fast >= slow` (ma_crossover) or `ema_period >= trend_ema`
  (pullback_ema) are skipped by the tuner and counted.

  | Strategy | Horizon | Bullish grid | n |
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
  | mean_reversion_multi | Swing | min_confirmations [2,3] · vwap_daily.vwap_lookback [10,20] · vwap_daily.vwap_deviation_pct [0.01,0.02,0.03] · rsi.rsi_oversold [25,30,35] · bb.bb_std [1.5,2.0,2.5] | 108 |
  | mean_reversion_multi | Position | min_confirmations [2,3] · vwap_daily.vwap_lookback [20,50] · vwap_daily.vwap_deviation_pct [0.02,0.03,0.05] · rsi.rsi_oversold [30,35] · bb.bb_std [2.0,2.5] | 48 |
  | mean_reversion_multi | Quarterly, SemiAnnual, Annual (each) | min_confirmations [2,3] · vwap_daily.vwap_lookback [50,100] · vwap_daily.vwap_deviation_pct [0.03,0.05,0.08] · rsi.rsi_oversold [30,35,40] · bb.bb_std [2.0,2.5] | 72 |

  (`rsi.` / `bb.` / `vwap_daily.` abbreviate `mean_reversion_rsi.` / `mean_reversion_bb.` /
  `mean_reversion_vwap_daily.`; the YAML uses the full names.)

  **Grid rationale:** look-backs, stops and targets lengthen with the hold, because the time exit now caps the trade
  and a target that cannot be reached within the hold only becomes a time exit. Parameters that do not move rung 1
  stay out (as the existing `search:` comments explain). The implementer checks every parameter name against the
  signal function's keywords and stops on a mismatch.
- **API.** `GET /api/config/strategy-profiles` (`routers/config.py`):
  `{"<strategy>": {"Bullish"|"Bearish": {"baseline": {...}, "horizons": {"<TunedHorizon>": {"params": {...},
  "source": "tuned"|"baseline"}}}}}` for the six tuned strategies. Read fresh each call (store cache applies).
- **Scan.** `StockScanRequest` gains `params_horizon: Optional[TunedHorizon] = None`. If it is `None` and
  `hold_max_days` is set and the scoring horizon is not Intraday, the backend uses `tuned_params_horizon(
  hold_max_days)`. `_merge_strategy_params(strategy, direction, request_kwargs, params_horizon=None)`: exit <
  `get_profile(...)` < request (non-`None`). Every caller in `stock_scan.py` passes it, including H3's
  `merge_multi_params`. The card gains `params_horizon: str | None` and `params_source: "tuned" | "baseline"`.
- **Watch.** Entry **and reversal** (`strategy_watch_evaluator.py` ~L484) read `get_profile(key, dir,
  w.get("params_horizon"))` instead of `get_active`. Absent field → baseline (unchanged until H7).

**Test first.** (1) `get_active` hides a `Swing:` sub-dict. (2) `get_profile` tuned / baseline / `None`, flat and
multi (nested). (3) `adopt(horizon=None)` keeps sub-dicts; `adopt(horizon="Swing")` writes only it. (4) Grid check:
counts per cell equal this table's n (test reads the YAML), every combination `bars_needed <= 400`, bearish rsi grids
contain `rsi_overbought` and no `rsi_oversold`. (5) Endpoint shape. (6) Scan: a request **without** strategy fields
uses the YAML baseline (`pullback_tolerance_pct` 0.04, not 0.08); with a tuned `Quarterly` profile in a temp YAML and
`params_horizon="Quarterly"` uses the profile; an explicit request value still wins; `hold_max_days=185` without
`params_horizon` → Annual. (7) Watch reversal uses the profile.

**Commit:** `feat(stocks): per-horizon parameter profiles; request fields default to the profile (STOCKS-HORIZON-T1)`

---

## H5 — Frontend: the panel follows the horizon profile; edits are overrides

**Mechanism today.** `scanParamsStore` (persisted `'bamendjou:scan-params'`) holds hardcoded `DEFAULTS`; Step 4
Stocks copies them into local state for `StrategyParamsPanel`; `resolveStockScanRequest.ts` always sends every
field. `searchProfileSnapshot.ts` saves a full `strategyParams` snapshot and `loadParams` it back (~L47–66, L101);
`scanScheduleResolve.ts` (~L124) sends `profile.strategyParams` for scheduled scans; Settings
(`app/(frame)/settings/page.tsx` ~L2350+) edits some of the same fields.

**Semantics.**

- **Override fields** (each becomes `T | null`, `null` = follow the profile): `pullbackTolerancePct`,
  `pullbackEmaPeriod`, `pullbackTrendEma`, `pullbackMaType`, `maCrossoverFast`, `maCrossoverSlow`,
  `maCrossoverLookback`, `breakoutVolumeMult`, `rsiPeriod`, `rsiOversold`, `rsiTrendSma`, `requireChoppyRegime`,
  `meanReversionVariants`, `meanReversionMinConfirm`, `vwapLookback`, `vwapDeviationPct`. Unchanged:
  `btMinTrades`, `btMinWinRate`, `eventFilter`, `stockShortlistMax`.
- `scanParamsStore`: bump `version`; `migrate()` sets every override field to `null`. `searchProfilesStore`
  (`'bamendjou:search-profiles'`): bump `version`; `migrate()` sets each saved profile's override fields to `null`
  (other saved fields kept). Snapshot save stores only non-`null` overrides; `loadParams` restores them as overrides.
  The coordinator tells Kenneth in the ticket report that saved strategy values were reset to "follow profile".
- New `lib/strategyProfilesStore.ts` (no `persist()`), modelled on `eventThresholdsStore.ts`: `profiles | null`,
  `status`, `error`, `fetch()`, `seq` guard, strict `parseStrategyProfiles(raw)` naming the failing path. No
  fallback (T1-PROFILES-NO-FALLBACK-2026-10-09).
- Panel: per field, the override if set, else the profile value for (direction, `tunedParamsHorizon`); a `tuned` /
  `baseline` tag per strategy section; per-field "reset to profile"; for Custom, "Custom: using <horizon> settings".
  Fetch failed → "Profile unavailable — the scan uses the backend's values", overrides only. Settings page fields
  that edit the same store follow the same null-override model.
- `ResolvedStockScanContext` gains `paramsHorizon`; all its builders (`stockScan.ts`, `scanScheduleResolve.ts`,
  `analysisStore.ts`, and any other found by grep) set it from `tunedParamsHorizon` over the context's preset and
  hold. `buildStockScanRequestBody` sends `params_horizon` and only non-`null` overrides.
- Changing horizon or direction never erases overrides.

**Test first.** Parser (good payload; each malformed path named). Store failure → `profiles null`, `failed`. Request
builder: no overrides → no strategy fields and `params_horizon` = `"Quarterly"` for Quarterly, `"Annual"` for
Custom 60–185, absent for Intraday; one override → only that field. Both migrations. Saved-profile round trip keeps
an override and nothing else. Scheduled scan body carries `params_horizon` and only overrides. Panel shows the
profile value, then the override after an edit, then the profile after reset.

**Commit:** `feat(ui): strategy panel follows the backend horizon profile; edits are overrides (STOCKS-HORIZON-T1)`

---

## H6 — Stock positions raise TIME_STOP at the hold

**Mechanism today.** `TIME_STOP` is options-only (`alert_generator.py` ~L375, `frontend/lib/alertEngine.ts` ~L334,
`<= 3` DTE). `portfolio_positions` has `entry_date`, no hold. `portfolioStore` is persisted
(`'bamendjou-portfolio-v1'`, version 6, `migratePortfolioPersist`).

**Semantics.**

- Nullable `hold_max_days INTEGER` on `portfolio_positions` (Alembic migration; existing rows `NULL`); schemas and
  `PortfolioPosition` (`types/domain.ts`) gain `holdMaxDays: number | null`. `portfolioStore` version 6 → 7 with a
  `migratePortfolioPersist` branch setting `holdMaxDays: null` on stored rows.
- The stock sends (the same places P0B B7 touched: Step 7 position card, `StockSendDialog`, `StockPositionCard`)
  write `hold_max_days` = the scan's hold (`sanitizeHoldDays` over `ScanContext`). Options rows stay `NULL`.
- Backend `alert_generator`: a stock position (`parse_expiry_from_contract` → `None`) with `hold_max_days` set:
  `days_held = (today − date(entry_date)).days` (both in the server's local date, as `days_to_expiry` uses today);
  `days_held >= hold_max_days` and not muted → `TIME_STOP`, `reference_value = days_held`, reason `Time stop —
  {symbol} held {days_held}d (hold {hold_max_days}d)`, same log/dedup path as the options branch. Frontend
  `alertEngine.ts` mirrors it (replacing the `!isStock` exclusion with the stock rule). Alerts page label `Time stop
  (≤3 DTE / hold reached)`; `EditDrawer.tsx`'s stock case shows `held ≥ N days` when set.
- `TIME_STOP_APPROACHING` stays options-only (out of scope, logged).

**Test first.** Backend: entered 15 days ago, hold 15 → one `TIME_STOP`; 14 → none; `NULL` → none; options row
unchanged. Frontend: same cases; migration v6 → v7; stock send body carries `hold_max_days` (Custom 60–185 → 185).

**Commit:** `feat(alerts): stock positions raise TIME_STOP when held hold_max_days (STOCKS-HORIZON-T1)`

---

## H7 — Strategy watches carry a horizon and raise TIME_STOP

**Mechanism today.** A strategy watch (`strategy_watches.yaml`, `routers/strategy_watch.py::AddWatch`/`BulkAdd`)
has symbol, strategy, direction, `params_override`; the evaluator moves `idle → armed` on a signal and back on stop /
target / reversal. No hold.

**Semantics.**

- `AddWatch` and `BulkAdd` gain `params_horizon: Optional[TunedHorizon] = None`; the watch stores it plus
  `hold_max_days` (`HOLD_MAX_DAYS[params_horizon]` or `None`). Existing watches: absent → `None`.
- Evaluator, `armed` phase, before stop/target: if `hold_max_days` is set and `(today_utc − date_utc(last_event_at)).
  days >= hold_max_days` with `last_event` in {`entry`, `reversal`} → event type **`time_stop`** (ADR decision 2's
  `TIME_STOP`), reason `"{symbol}: {label} time stop — held {n}d (hold {hold}d)"`, state → idle. Both dates are UTC
  calendar dates (`last_event_at` is UTC ISO). Add `time_stop` wherever `exit_stop` / `exit_target` are enumerated
  (formatter, notification text, frontend types and labels).
- The strategy-watch page's add form offers the five tuned horizons plus "none"; the list shows it.

**Test first.** Armed 15 days, hold 15 → `time_stop`, idle; 14 → none; no horizon → never; formats and dispatches
like `exit_stop`; UTC boundary case (entry 23:30 UTC). Frontend: the add request carries `params_horizon`.

**Commit:** `feat(watch): strategy watches carry a horizon; TIME_STOP at its hold (STOCKS-HORIZON-T1)`

---

## H8 — Tuner core: caches, trade simulator, replayable gate mask

**Why a simulator.** One `backtesting.py` run calls the signal function on every bar; up to 150 combinations × 60
cells × ~110 symbols × folds is far too slow. Signals do not depend on the horizon or the cost; trades do. So H8
computes each (symbol, strategy, direction, combination) **signal series once**, caches it on disk, and simulates
trades per horizon and cost. A parity test ties the simulator to `run_strategy_backtest`.

**Semantics.** New package `app/services/horizon_tuning/`:

- `signals.py`: `signal_series(bars, strategy, direction, params) -> list[SignalPoint | None]`, one per bar, exactly
  as `run_strategy_backtest`'s `next()` computes it (same `n < 60` skip, `SIGNAL_WINDOW_BARS` window, the
  `get_exit` merge — or H3's shape for multi). `SignalPoint(entry, stop, target)`.
- `cache.py`: disk cache under `backend/data/tuning_cache/` (gitignored). **Signal key** = sha256 of: symbol,
  strategy, direction, the **effective** params (after the exit merge / multi merge, canonical JSON),
  `SIGNAL_WINDOW_BARS`, `BARS_BASIS_VERSION`, a hash of the full OHLCV series used (`time, open, high, low, close,
  volume` of every bar), and `SIGNAL_CACHE_VERSION` (a constant bumped whenever a signal function changes; a test
  pins a hash of `strategy_engine.py`'s source and fails with "bump SIGNAL_CACHE_VERSION" when it changes). **Gate
  key** = symbol, direction, scoring horizon, OHLCV hash, `BARS_BASIS_VERSION`, sha256 of `scoring_rules.yaml`, the
  benchmark series hash (if any), price bounds, and a source hash of `stock_scorer.py`.
- `simulate.py`: `simulate_trades(bars, signals, *, direction, commission, hold_max_days, entry_start, entry_end,
  allowed: list[bool] | None) -> list[TradeRecord]` with `run_strategy_backtest`'s rules (DAY limit entry valid for
  one bar, `_entry_side`, one position at a time, H2's `next()` order and time exit, commission per leg, no entry
  where `allowed[t]` is False). The implementer copies the fill rules from `backtesting.py` 0.6.6
  (`_Broker._process_orders`: limit fill price, gaps, same-bar SL/TP order, close-order priority). The parity test
  is the judge.
- **Parity test (gate for this ticket).** Seeded synthetic series (1,500 bars, trending, choppy, gappy with
  holidays) plus the four 251-bar fixtures; every tuned strategy × both directions × `hold_max_days` {None, 15, 200} ×
  commission {0, 0.0005, 0.002} × `entry_start`/`entry_end` {unset, mid-series}; one grid combination per strategy
  plus the baseline: `simulate_trades` equals `run_strategy_backtest_trades` (dates equal, prices/returns within
  1e-9, same exit reasons). Asserts `backtesting.__version__ == "0.6.6"`.
- `gates.py`: `gate_mask(bars, direction, scoring_horizon, *, min_price, max_price, benchmark) -> list[bool]`: per
  bar `t`, the replayable live gates on bars up to `t`, in the scan's order: close of `t` within `[min_price,
  max_price]` (`None` = no bound); `score_stock(bars[t-119..t], direction, scoring_horizon, scoring_mode="stock",
  regime_signal=None, fundamentals=None, no earnings/dividend, overrides=None, benchmark aligned as the scan does)`
  status `!= "REJECT"`; `_direction_conviction_drop(...)` is `None` (import the scan's helper, do not copy it).
  Scoring horizon: `Swing` for Swing, `Position` for the four longer horizons.
- **Not applied, named in every report** (decision `STOCKS-HORIZON-T1-DESIGN-2026-10-05`): regime gate, regime filter,
  fundamentals, IV, earnings dates, confidence replay, `min_stock_score`, the per-symbol backtest gate. Also named:
  the live scan passes the live quote as `current_price` to `pullback_ema` (`stock_scan.py` ~L1338); the tuner uses
  the close.
- `basket.py`: **strata** = the `sector` column of `backend/app/data/sp500.csv`; NDX 100 names not in it form one
  stratum `"NDX-only"`. Sample = `build_basket(rows, per_sector=tuning.basket.per_sector)` (existing
  `strategy_basket.py`, top-N by liquidity per stratum) over the union minus `universe_exclusions.yaml` (both scopes —
  the evidence scope means "skipped by tuning"). Universe = the same union minus exclusions. The report labels the
  sample "liquidity-selected, equal count per stratum".
- **Fire rate (sample-scaled), per sector:** `rate = Σ_s (fires_s ÷ scan_days) × (N_universe_s ÷ N_sample_s)`, where
  `fires_s` = gate-passing signal bars in stratum `s` over the window and `scan_days` = trading days in it. A week is
  5 scan days.
- `strategy_params.yaml` gains a `tuning:` block (`strategy_param_store.get_tuning_config()`, validated; unknown or
  missing keys are refused):
  ```yaml
  tuning:
    cost_per_leg: 0.0005          # ADR decision 4
    stress_cost_per_leg: 0.002
    held_out_months: 12
    exit_buffer_days: 14          # calendar days added to the hold when cutting entries (H9)
    windows:                      # STOCKS-HORIZON-T1-DESIGN-2026-10-05: test >= 2 x holdMax, train = 2 x test
      Swing:      {train_months: 12, test_months: 3}
      Position:   {train_months: 12, test_months: 3}
      Quarterly:  {train_months: 12, test_months: 4}
      SemiAnnual: {train_months: 16, test_months: 8}
      Annual:     {train_months: 24, test_months: 12}   # 12 < 2 x 200d (13.2 mo): as decided; noted in the report
    fire_rate_floor_per_day:      # candidates per scan day across the universe (ADR decision 4)
      Swing: 2.0
      Position: 1.0
      Quarterly: 0.6              # 3 / week
      SemiAnnual: 0.4             # 2 / week
      Annual: 0.2                 # 1 / week
    adoption: {ci_level: 0.95, min_oos_trades: 100, min_symbols: 20, bootstrap_resamples: 2000, seed: 7}
    min_train_trades: 30
    min_folds_not_thin: 4
    basket: {per_sector: 10}
    gates: {min_price: null, max_price: null}
  ```
- **Runtime probe.** `backend/scripts/tune_horizons.py --probe` (the CLI's other flags land in H10) times the signal
  function per strategy on 3 symbols and prints ms per call and the projected total for the configured basket and
  grids at `--workers N`. The implementer runs it on the fixtures and records the numbers in the ticket report.

**Test first.** Parity test (first). Gate mask: a scorer-REJECT bar → `False`; below `min_price` → `False`; the
conviction case matches `_direction_conviction_drop`. Cache: second call reads from disk; changing one old bar's
close (same last date) recomputes; changing an `exit:` value recomputes; editing `scoring_rules.yaml` recomputes the
gate mask. Sector scaling formula on a hand-counted case. Config loader refuses an unknown key.

**Commit:** `feat(tuning): signal/gate caches, parity-tested trade simulator, replayable gate mask (STOCKS-HORIZON-T1)`

---

## H9 — Walk-forward per cell

**Semantics.** `app/services/horizon_tuning/walk_forward_cell.py::tune_cell(cell, data) -> CellResult`.

- **Calendar.** The trading calendar = the sorted union of bar dates over the sample. `data_end` = the latest date
  on which ≥ 90% of sample symbols have a bar. **Held-out year** = `[heldout_start, data_end]`, `heldout_start` =
  `data_end − held_out_months`.
- **Warm-up.** `warm_start` = the calendar date at index `max(bars_needed over the cell's grid)` (so every
  combination of the cell can fire from the first fold on). Symbols that start later simply have fewer signals.
- **Folds.** `build_folds(warm_start, heldout_start, train_months, test_months)` — the existing rule: a fold exists
  only if its whole test window ends `<= heldout_start`. **Entry cut-offs** (calendar days, `buffer =
  exit_buffer_days`): train entries in `[train_start, train_end − hold − buffer)`; test entries in `[test_start,
  min(test_end, heldout_start − hold − buffer))`; held-out entries in `[heldout_start, data_end − hold − buffer)`.
  Worst case from a signal on day `s`: fill ≤ s+4 (holiday weekend), time-exit trigger ≤ fill + hold + 3, exit open
  ≤ +4, so exit ≤ s + hold + 11 < s + hold + 14. Folds with an empty entry window are dropped. Fewer than
  `min_folds_not_thin` folds → **thin**. Expected (pinned in the test for data 2020-10-06 .. 2026-10-02): Annual 2
  folds (T1-ANNUAL-TWO-FOLDS-2026-10-09); the test pins every horizon's actual fold dates.
- **Selection (per fold).** For each grid combination (invalid ones skipped and counted): simulate the train entries
  at `cost_per_leg` with the gate mask. Eligible if pooled train trades ≥ `min_train_trades` **and** the
  sector-scaled train fire rate ≥ the horizon floor. Winner = highest pooled train net expectancy; tie → more
  trades, then grid order. No eligible combination → no winner (counted).
- **Out-of-sample.** Each fold's winner trades its test entries at both costs. The pooled OOS trades across folds are
  the walk-forward evidence.
- **Final parameters** = the combination that won the most folds; tie → highest net expectancy over the union of
  all train entry windows. Always a grid point (`consensus()`'s median could leave the grid).
- **Held-out year.** The final parameters trade the held-out entries once, both costs. Trades still open at
  `data_end` cannot occur by construction; the report states the effective held-out entry span (Annual: about
  `12 months − 214 days`).
- `CellResult`: cell, final params, fold dates and winners, per-fold OOS stats, pooled OOS `TradeRecord`s with
  symbol (both costs), held-out stats, scaled fire rate, counts (tried / invalid / ineligible / no-winner folds),
  `thin`, effective entry spans.
- Parallelism: signal series and gate masks are computed in a `ProcessPoolExecutor` (`--workers`), one work unit per
  (symbol, strategy, direction); simulation runs in-process.

**Test first.** Planted edge on a small synthetic universe: the planted combination wins every fold and is final.
Fold dates per horizon pinned for 2020-10-06 .. 2026-10-02 (Annual = 2). On a calendar with holidays, every OOS and
train trade's exit date is before the next window's restriction and before `heldout_start`; no held-out trade is
open at `data_end`. A combination below the floor never wins. Long-lookback combinations are eligible from fold 0
(warm-up).

**Commit:** `feat(tuning): per-cell walk-forward with hold-scaled windows and a held-out year (STOCKS-HORIZON-T1)`

---

## H10 — Report, CLI and the full-universe re-check

**Semantics.**

- **CLI** `backend/scripts/tune_horizons.py`: `--cells` (filter; default all 60), `--directions` (default both),
  `--workers` (default `os.cpu_count() - 1`), `--probe`, `--resume` (skips cells whose result exists for the same
  config + data hash), `--out` (summaries; default `docs/superpowers/measurements/<today>-horizon-tuning/`), `--data`
  (trade lists and per-cell JSON; default `backend/data/tuning_runs/<today>/`, gitignored). Prints the projected
  runtime before starting. Runs on Kenneth's machine (bars only in his Postgres).
- **Full-universe re-check** (T1-BASKET-SECTOR-SAMPLE-2026-10-08): each cell's final parameters get signal series
  and gate masks on the whole universe; the report shows the measured fire rate over the walk-forward span and over
  the held-out year beside the scaled one. The floor verdict uses the measured walk-forward rate.
- **Adoption bar** per cell (ADR decision 5) at `cost_per_leg`:
  1. OOS net expectancy CI lower bound > 0, **cluster bootstrap over symbols**: group pooled OOS trades by symbol;
     each resample draws `S` symbols with replacement (`S` = symbols with ≥ 1 OOS trade), concatenates all their
     trades, takes the trade-weighted mean; 2000 resamples, `numpy.random.default_rng(7)`; the lower bound is the
     2.5th percentile.
  2. Held-out year net expectancy > 0.
  3. Pooled OOS trades ≥ 100.
  4. Symbols with ≥ 1 OOS trade ≥ 20.
  5. Measured full-universe fire rate ≥ the horizon floor.
  `passes_bar` only if all five hold; failed criteria are named. Bearish cells are computed and shown, marked
  **blocked (P0B)** whatever the verdict. Nothing is written to `active:` (T2).
- **Chance count.** `cells passed` and `expected by chance ≈ n_cells_evaluated × 0.025 × 0.5` (one-sided CI miss ×
  an independent held-out coin flip under no edge), formula written out and labelled an approximation.
- **Report files.** `--out`: `tuning_report.md` (one row per cell: final params; OOS trades / symbols / net
  expectancy / CI at 0.05% and at 0.2%; held-out at both costs and its entry span; fire rate scaled, full
  walk-forward, full held-out; folds; thin; verdict; failed criteria) and `tuning_summary.json` (same, no trade
  lists). `--data`: per-cell JSON with trade lists. Header: gates not applied (H8 list), `current_price` gap, "legacy
  Settings tuner has no time exit", sample selection, survivorship / bull-market label (ADR consequences), cost model,
  git commit, data range, sample and universe sizes, runtimes, the Annual window note.

**Test first.** Cluster bootstrap pinned on a fixed trade list (seed 7), and shown wider than a per-trade bootstrap
on data where one symbol's trades are correlated. Each adoption criterion failing alone flips the verdict and is
named. Chance-count formula. `--resume` skips a finished cell. A tiny end-to-end run on two synthetic symbols writes
all files with every documented column.

**Commit:** `feat(tuning): tune_horizons CLI, adoption-bar report, full-universe re-check (STOCKS-HORIZON-T1)`

---

## Verification (coordinator, after H10)

- Backend full suite on Python 3.11; frontend typecheck + Jest.
- `tune_horizons.py --probe` on Kenneth's machine; the projected runtime goes to him before the real run
  (`STOCKS-HORIZON-TUNING-RUN`). Over 24 h at his core count → raise it (smaller `per_sector`, fewer cells per night
  with `--resume`).
- Live checks on Kenneth's machine: a live `mean_reversion_rsi` scan returns setups (H1); a Swing stock scan's
  Step 6 shows time exits (H2); the Step-4 panel shows `baseline` profiles and a Custom 60–185 scan says "using Annual
  settings" (H5); a stock position entered with hold 15 raises `TIME_STOP` on day 15 (H6).

## Out of scope (logged, not built)

- The Adopt button, Unvalidated labels from verdicts, the pooled gate replacing the per-symbol backtest gate (T2).
- Switching the live Step-6 gate to 0.05% per leg (T1-LIVE-COST-UNCHANGED-2026-10-08; T2).
- The legacy Settings → Strategy Tuning WFO (no time exit, 3-year window, Sharpe ranking): left as is.
- `TIME_STOP_APPROACHING` for stocks.
- Longer history and delisted names (logged by STOCKS-PARAMS-PER-HORIZON-2026-10-05, not scheduled).
- The scorer's 120-bar window (T3). The live `current_price` vs close difference for `pullback_ema` (reported).
