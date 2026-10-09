# Stocks horizon T1: per-horizon tuning machinery — Implementation Plan (`STOCKS-HORIZON-T1`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Decision `STOCKS-PARAMS-PER-HORIZON-2026-10-05` (ADR `docs/adr/0001-stocks-parameters-per-horizon.md`,
terms in `GLOSSARY.md`), decision `STOCKS-HORIZON-T1-DESIGN-2026-10-05` (tuning gates = the replayable subset;
walk-forward windows scale with the hold), and Kenneth's answers in chat (recorded as decisions by the coordinator in
`PROJECT_STATE.json` before H1 starts):

- **T1-BASKET-SECTOR-SAMPLE-2026-10-08.** The grid search runs on a sector sample (10 symbols per sector stratum).
  Fire rates are scaled per sector to the universe. Before the report, each cell's fold winners and final parameters
  are checked again on the **full** universe: fire rate over the **fire-rate universe** (S&P 500 ∪ NDX 100 minus the
  scan-scope exclusions, what live scans see), walk-forward OOS and held-out-year trades over the **trade universe**
  (the same union minus **both** exclusion scopes, since evidence-scope bars are not trusted for tuning). The adoption
  bar uses these full-universe numbers (H10; plan round 3 finding 2, fixed by Kenneth's decision
  T1-CAP-SPLIT-H0B-2026-10-09).
- **T1-SECTORS-FILL-FIRST-2026-10-09.** 309 of 518 rows in `backend/app/data/sp500.csv` have sector `Unknown`, so
  sector strata are meaningless today. H0a fills the missing sectors from the public GICS lists before H8.
- **T1-HISTORY-BACKFILL-2026-10-09.** Stored history starts 2020-10-06, which leaves Annual 1–2 folds once every
  signal gets its full 400-bar window. Daily history back to about 2010, kept by the nightly job, is now delivered by
  its own phase **`STOCKS-HORIZON-HISTORY`** (decision T1-CAP-SPLIT-H0B-2026-10-09, below), which must ship and run
  on the mini PC before `STOCKS-HORIZON-TUNING-RUN`. T1's code reads whatever history is stored.
  Every tuned signal then starts with the full live window (exact live parity), and every horizon gets enough folds.
  This **supersedes T1-ANNUAL-TWO-FOLDS-2026-10-09** (Annual 24/12 kept; "thin" stays as a rule, no longer expected
  to trigger). The survivorship label stays: the backfill covers today's constituents only.
- **T1-MINI-PC-2026-10-09.** Every step that reads or writes stored bars (the history backfill, the bar-basis
  re-check, `tune_horizons.py`) runs on Kenneth's **mini PC**, which holds the latest price history. Planning and code can be
  done on either machine.
- **T1-LIVE-COST-UNCHANGED-2026-10-08.** The tuner charges 0.05% per leg and reports 0.2% per leg as a stress test.
  The live Step-6 per-symbol backtest gate keeps 0.2% (`costs:` untouched). T2 replaces that gate.
- **T1-ANNUAL-TWO-FOLDS-2026-10-09** (superseded by T1-HISTORY-BACKFILL-2026-10-09, kept for the record): Annual
  keeps train 24 / test 12 and is labelled **thin** when it has fewer than `min_folds_not_thin` folds.
- **T1-CAP-SPLIT-H0B-2026-10-09.** The plan stage reached its 3-round cap not clean (round 3: two gate findings).
  Kenneth chose to split: ticket H0b (history backfill + retention) leaves T1 for the new phase
  `STOCKS-HORIZON-HISTORY` (plan `docs/superpowers/plans/2026-10-09-stocks-horizon-history-plan.md`, its own plan
  rounds), carrying round 3 finding 1 (adjustment basis at the seam); round 3 finding 2 (evidence-scope symbols in
  the adoption numbers) is fixed in this plan by his decision, without a further plan round. The code audit covers it.
- **T1-H0A-SOURCES-2026-10-09.** H0a parses Wikipedia's S&P 500 table with BeautifulSoup (no new dependency),
  takes NDX-only sectors from yfinance, defines the NDX list as the app's `universe_presets.NDX100`, and leaves the
  sector heatmap and `SECTOR:` presets unchanged (logged). Decided after the H0a implementer reported the plan defect.
- **T1-CUSTOM-NEAREST-HOLD-2026-10-09.** A Custom hold uses the parameters of the tuned horizon whose hold max is
  nearest to the Custom hold max; the card names it ("Custom: using Annual settings").
- **T1-PROFILES-NO-FALLBACK-2026-10-09.** The frontend has no hardcoded copy of the profiles and no fallback: a
  failed fetch shows "profile unavailable" and the backend applies the profile itself. This supersedes ADR 0001
  decision 3's "with a fallback" and follows `DOCC-3-THRESHOLD-STORES-REFUSE-2026-09-29`.

**Hard dependency.** T1 depends on `STOCKS-HORIZON-P0`. P0A and P0B are merged to `main` (P0B via PR #91 at
`aaa7102c`, 2026-10-09), and `main` is merged into this branch. H2 reads P0B's `StockScanRequest.hold_max_days`
(`app/schemas/stock_scan.py`) and `DEFAULT_HOLD_MAX` (`app/scoring/stock_scorer.py`; keys `Intraday`, `Swing`,
`Position` only); H6 edits the stock sends P0B B7 changed. Both names exist on `main` as written here.

**Plan audit status.** Round 1 (2026-10-08: 4 critical, 13 major, 10 minor) and round 2 (2026-10-09: 23 findings,
8 gate-level) are fixed in this text. Round 3 (2026-10-09, the stage's last) found 2 gate findings: the plan stage
ended **at the cap, not clean**. Kenneth's decision T1-CAP-SPLIT-H0B-2026-10-09 moved H0b and finding 1 out and fixed
finding 2 here; tickets are cut from this text.

**Not in T1** (other tasks): running the tuner on the mini PC's data (`STOCKS-HORIZON-TUNING-RUN`); the Adopt action,
Unvalidated labels from tuned verdicts, the pooled per-cell gate (`T2`); scorer re-tune and its 120-bar window
(`T3`); Pre-Breakout (`T4`); Intraday and `mean_reversion_vwap` (no daily bars, ADR decision 1).

**Live behaviour that changes, on purpose.**

- **H1 (error fix): one 400-bar signal window.** Live single-strategy scans, `mean_reversion_multi`, Analysis,
  strategy watches and composite watches give a strategy the last 400 bars, as the backtest will. Today they get 120
  (composite watches: `bars[i-119:i+1]`), so `mean_reversion_rsi` (needs 219 bars at defaults), `mean_reversion_bb`
  (225), and `pullback_ema` with `trend_ema >= 111` **never fire live** while Step 6 shows trades. After H1 they fire.
  Also, because `_ema` is seeded from the window's first values and `_rsi` smooths from the window start, **every
  live `pullback_ema` signal and every RSI reading moves** (entries, stops and tolerance hits), for every symbol.
  The backtest window also grows from 350 to 400 bars, so Step-6 results and `passes_gate` for `pullback_ema` and the
  RSI strategies move in H1 too, as do the legacy Settings tuner's results. Composite watches on the **intraday**
  path (`mean_reversion_vwap` on 15-min bars) keep their 120-bar window, so their anchored VWAP is unchanged. The
  scorer's `bars[-120:]` is not changed.
- **H0a:** sectors are filled for about 300 S&P names that read `Unknown` today (and the NDX-only names), so
  `sector_for_symbol`'s callers see them: the stock scan's sector context (`stock_scan._sector_context`) and the
  tuner's strata (H8). The sector heatmap (`routers/sectors.py`) and the `SECTOR:` universe presets
  (`universe_presets._load_sp500_by_sector`) read `sp500.csv` directly and are **unchanged** (T1-H0A-SOURCES-2026-10-09,
  logged against main).
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
  defect today: the adopted YAML value never reached a live scan. Saved search profiles (localStorage, H5) and
  saved scan schedules / the continuous-scan request (server-side `resolved_request`, H4) lose their frozen strategy
  values and follow the profile.
- **H6/H7:** a stock position or a strategy watch with a hold raises `TIME_STOP` once held `hold_max_days`. No
  automatic close (ADR decision 2).

## Global constraints

- **Runtime.** Backend Python **3.11** (Windows `.\.venv\Scripts\python.exe -m pytest`). Frontend
  `cd frontend && npm run typecheck && npm run test`. The worktree has no `.venv`; the coordinator creates one from
  `backend/requirements.txt` before H0a. `backtesting` must be the pinned **0.6.6** (Kenneth's main-PC checkout has
  0.6.5 installed); H8's parity test asserts `backtesting.__version__ == "0.6.6"`, and the Verification section
  upgrades the venv that serves the live app on the mini PC to the pin.
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
  **Owner:** H2 creates `horizon_profiles.py` (`TUNED_HORIZONS`, `HOLD_MAX_DAYS`, `tuned_params_horizon`,
  `hold_for_backtest`) and the cross-file hold test; H5 creates the frontend `tunedParamsHorizon`.
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
  **daily-bar** strategy signal function passes at most the last 400 bars ending at the evaluated bar: live scan
  (single + multi), Analysis, strategy watch (entry and reversal), composite watch (daily keys only), the backtest's
  per-bar slice, the tuner. Intraday paths keep their windows (scan `intraday_bars[-300:]`, composite intraday 120).
  Pre-Breakout's `breakout_setup_signal` and `fibonacci_pullback_signal` are T4 and untouched.
- **Bars needed.** `bars_needed(strategy, params) -> int` in `strategy_engine.py`: the smallest bar count at which
  **every** length guard of the signal function can pass, read from the code (e.g. `ma_crossover` = `slow +
  max(5, lookback)`, from `len(bars) < slow + 5` and `len(slow_ma) < lookback + 1` — the implementer derives each
  exactly and the both-ways test is the judge). `mean_reversion_multi` = max over its variants with their merged
  params. Tested both ways (H1).
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
  by `merge_multi_params(base, override)` (H3): `variant_params[v]` = `get_exit(v)` ∪ the variant's **direction
  baseline** `get_active(v, direction)` ∪ the multi profile's `variant_params[v]` ∪ request overrides. The variant
  base is **always** the direction baseline, never the standalone strategy's tuned horizon profile (a T2 adopt of a
  `mean_reversion_rsi` Quarterly profile must not change multi); a test pins this. Grid keys address it with
  dots: `min_confirmations`, `mean_reversion_rsi.rsi_oversold`, `mean_reversion_bb.bb_std`,
  `mean_reversion_vwap_daily.vwap_lookback`, ….

## Ticket graph

```
H0a (sector fill)  ──────────────────────────────────────────────────────────────┐
H1 (signal window) ── H2 (time exit) ── H3 (multi backtest + shape) ── H4 (profiles, Optional request fields)
H4 ── H5 (frontend profiles + migrations)
H4 ── H6 (position TIME_STOP) ── H7 (watch horizon + TIME_STOP)
H4 ── H8 (signal/gate cache, simulator, gate mask) ── H9 (walk-forward per cell) ── H10 (report, CLI, re-check)
```

Sequential build: H0a, H1 … H10. H0a touches no file the others touch and does not depend on P0B; the coordinator
builds it first. (H0b moved to `STOCKS-HORIZON-HISTORY`; the id is not reused.) H1–H4 and H8 edit `strategy_backtest.py` / `strategy_engine.py` /
`stock_scan.py`; serial order avoids conflicts.

---

## H0a — Fill the missing sectors

**Mechanism today.** `backend/app/data/sp500.csv` (`symbol,sector,liquidity`) has 309 of 518 rows at `Unknown`.
`sector_map.sector_for_symbol` reads only that file. `scripts/update_sp500_liquidity.py` tries yfinance `.info` for
`Unknown` rows and writes `Unknown` on any failure. `sp500_update_service` (daily `sp500_scheduler`) rewrites the file.
NDX-only names have no sector anywhere.

**Semantics.**

Sources and parser per decision **T1-H0A-SOURCES-2026-10-09** (Kenneth, after the H0a implementer found that
`pandas.read_html` needs `lxml`/`html5lib`, which `backend/requirements.txt` does not carry, and that the Wikipedia
"Nasdaq-100" page has no constituents table with GICS sectors):

- **Universe** = the S&P 500 rows of `sp500.csv` ∪ the app's own `universe_presets.NDX100` list (the list scans and
  the tuner use), not a live Nasdaq-100 page.
- New committed file `backend/app/data/sector_overrides.csv` (`symbol,sector,source,as_of`), canonical sector names
  (`sector_names.NORMALIZE`). New script `backend/scripts/fill_sectors.py` builds it:
  - **S&P 500 names:** the GICS Sector column of the Wikipedia page "List of S&P 500 companies" (table
    `id="constituents"`), parsed with **BeautifulSoup and the standard `html.parser`** (`beautifulsoup4` is already
    installed; no new dependency, not `pandas.read_html`). `source` = `wikipedia-gics`. "Information Technology" maps
    to the canonical `Technology` (add it to `NORMALIZE`).
  - **NDX-only names** (in `NDX100`, not in the S&P table): the yfinance `.info` `sector`, the source
    `update_sp500_liquidity.py` already uses, mapped through `NORMALIZE`. `source` = `yfinance`.
  - A sector name that maps to nothing canonical is an error naming it (no silent `Unknown`). Ticker spellings
    (`BRK.B` vs `BRK-B`) are normalised the way `update_sp500_liquidity._yf_key` / the CSV already do. A symbol
    neither source can resolve is listed in the script output as unmatched, never written as `Unknown`.
- `sector_for_symbol`: the `sp500.csv` sector when it is not `Unknown`, else `sector_overrides.csv`, else
  `(None, None)`. The overrides are read inside the existing cached `_symbol_to_raw_sector` (no second `lru_cache`:
  `tests/test_docc4_config_health.py` allowlists exactly that one). The daily updater keeps writing `sp500.csv` as
  today; nothing it writes can erase an override. The only caller, `stock_scan._sector_context`, already shows a
  `None` name as "Unknown".
- The implementer runs the script once (needs internet; either PC — no bar data involved) and commits the CSV; the
  coordinator reviews its diff. Re-running later is a manual refresh. The heatmap and the `SECTOR:` presets are not
  changed (logged against main).

**Test first.** `sector_for_symbol` prefers a known `sp500.csv` sector, falls back to the override, returns `None`
for neither. The script's Wikipedia parser on a saved HTML fixture (a few rows incl. a `BRK.B`-style ticker and an
unknown GICS name → error); the NDX-only path with yfinance mocked (a mapped sector; a failure → unmatched). After the
real run: a test asserts `Unknown` covers 0 of the S&P 500 rows of `sp500.csv` ∪ `universe_presets.NDX100` (minus
any the script listed as unmatched, which the ticket report names).

**Commit:** `feat(data): fill missing sectors from the public GICS lists (STOCKS-HORIZON-T1)`

---

## H0b — moved to `STOCKS-HORIZON-HISTORY`

Not built in T1 (decision T1-CAP-SPLIT-H0B-2026-10-09). See `docs/superpowers/plans/2026-10-09-stocks-horizon-history-plan.md`.

---

## H1 — One signal window everywhere a signal is computed

**Mechanism today.** `routers/stock_scan.py::_process_stock` calls the signal function on `bars[-120:]` (via
`signal_fn(`, ~L1339); `_multi_signal` (`fn(`, ~L419) and `_analyze_core` (~L866) likewise.
`strategy_backtest.run_strategy_backtest` slices `max(0, n - 350)` per bar. `strategy_watch_evaluator` passes the full
`get_bars` result at entry (`fn(`, ~L390) and reversal (~L485). `composite_trigger_evaluator.py` (~L476) slices
`bars[max(0, i - 119): i + 1]` for every key, daily and intraday. Length guards return `None` on short windows.

**Semantics.**

- Add `SIGNAL_WINDOW_BARS` and `bars_needed` (shared definitions).
- Change exactly these call sites: `_process_stock` daily branch (`bars[-120:]` → `bars[-SIGNAL_WINDOW_BARS:]`; the
  intraday branch keeps `intraday_bars[-300:]`), `_multi_signal`, `_analyze_core`'s signal call, the backtest
  (`start = max(0, n - SIGNAL_WINDOW_BARS)` — keep the `max(0, …)`; update its comment), the watch evaluator's entry
  and reversal calls (`fn(bars[-SIGNAL_WINDOW_BARS:], …)`), and the composite evaluator's slice for **daily** keys
  only (`bars[max(0, i - SIGNAL_WINDOW_BARS + 1): i + 1]`; the intraday `mean_reversion_vwap` path keeps
  `i - 119`). Check that the watch's and the composite evaluator's `get_bars` ranges reach 400 trading bars; widen
  them if not. `_MIN_STRATEGY_BARS` is left as is. Pre-Breakout callers (`breakout_setup_signal`,
  `fibonacci_pullback_signal`) are not touched (T4). The implementer greps for further callers of the six daily
  signal functions (direct and through `_SIGNAL_FNS`) and lists any extra one in the ticket report before changing it.

**Test first.** (1) A synthetic 600-bar series built so `mean_reversion_rsi` at defaults fires on the last bar:
`_process_stock` (mocked bars/quotes, backtest mocked to pass, as existing scan tests do) returns a card — or, with
the real backtest, a rejection that is **not** the no-setup reason. Today: the no-setup rejection. (2) Same for
`mean_reversion_bb`. (3) The composite evaluator matches a daily `mean_reversion_rsi` setup on that series; an
intraday `mean_reversion_vwap` composite result is unchanged (pin before/after). (4) Backtest on a 150-bar series
gives the same trades as before for bars < 350 (no negative index).
(5) `bars_needed` both ways, per strategy, on synthetic series built to fire: with exactly `bars_needed` bars the
signal is not `None`; with `bars_needed − 1` it is `None`. (6) Every combination in the current `search:` blocks has
`bars_needed <= 400` (H4 extends this to its grids). (7) Watch entry and reversal calls receive ≤ 400 bars.

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
- Create `app/services/horizon_profiles.py` (`TUNED_HORIZONS`, `HOLD_MAX_DAYS`, `tuned_params_horizon`,
  `hold_for_backtest`) and its cross-file test against `horizonPresets.ts` (shared definitions).
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
  auto-trade) and make each read `None`-safe; list them in the ticket report. Two known readers break on `None`
  and move: the model validator `check_min_confirmations` (`schemas/stock_scan.py`) and the
  `"mean_reversion_vwap" in req.mean_reversion_variants` check (`_reject_unsupported_multi_variants`,
  `stock_scan.py` ~L462). Both become checks on the **merged** multi shape after `merge_multi_params`: 422 when
  `min_confirmations > len(variants)` or when `mean_reversion_vwap` is in the effective variants (so a request with 2
  variants against a profile `min_confirmations: 3` is refused, not silently dead).
- **Saved server-side requests.** Scan schedules store a full `resolved_request` (`schemas/scan_schedule.py`,
  fired as-is by `scan_schedule_scheduler.py`), and the continuous scan persists its `last_request`. A one-off
  migration on load (versioned, idempotent, with a backup like `adopt()`'s) strips the strategy fields above from
  every stocks request in both, and sets `params_horizon` from the request's `hold_max_days` via
  `tuned_params_horizon` when the scoring horizon is not Intraday. Without it, old schedules would keep sending the
  frozen defaults (0.08, 1.1, …) and override the profile forever.
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
`params_horizon` → Annual. (7) Watch reversal uses the profile. (8) Multi: a request with 2 variants and a profile
`min_confirmations: 3` → 422; `mean_reversion_vwap` in the effective variants → 422; a request without multi fields
validates. (9) Migration: a stored schedule request carrying `pullback_tolerance_pct: 0.08` and `hold_max_days: 60`
loses the field and gains `params_horizon: "Quarterly"`; running the migration twice changes nothing.

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
  `maCrossoverLookback`, `breakoutVolumeMult`, `rsiPeriod`, `rsiOversold`, **`rsiOverbought` (new; sent as
  `rsi_overbought`, the one RSI threshold the bearish rule reads)**, `rsiTrendSma`, `requireChoppyRegime`,
  `meanReversionVariants`, `meanReversionMinConfirm`, `vwapLookback`, `vwapDeviationPct`. Unchanged:
  `btMinTrades`, `btMinWinRate`, `eventFilter`, `stockShortlistMax`. `rsiOversold` / `rsiOverbought` /
  `rsiPeriod` / `rsiTrendSma` overrides apply to the standalone RSI strategy **and** to multi's RSI variant, as
  today's request already does (`_SIGNAL_KWARGS`); the panel says so under the RSI section.
- `scanParamsStore`: bump `version`; `migrate()` sets every override field to `null`. `searchProfilesStore`
  (`'bamendjou:search-profiles'`): bump `version`; `migrate()` sets each saved profile's override fields to `null`
  (other saved fields kept). Snapshot save stores only non-`null` overrides; `loadParams` restores them as overrides.
  The coordinator tells Kenneth in the ticket report that saved strategy values were reset to "follow profile".
- New `lib/strategyProfilesStore.ts` (no `persist()`), modelled on `eventThresholdsStore.ts`: `profiles | null`,
  `status`, `error`, `fetch()`, `seq` guard, strict `parseStrategyProfiles(raw)` naming the failing path. No
  fallback (T1-PROFILES-NO-FALLBACK-2026-10-09).
- Panel: per field, the override if set, else the profile value for (direction, `tunedParamsHorizon`); a `tuned` /
  `baseline` tag per strategy section; per-field "reset to profile"; for Custom, "Custom: using <horizon> settings".
  Fetch failed → "Profile unavailable — the scan uses the backend's values", overrides only.
- **Settings page** (`app/(frame)/settings/page.tsx` ~L2350+) edits the same store with no horizon or direction in
  view, so an edit there masks every profile. Its fields show an empty input with the placeholder "follows horizon
  profile" when `null`, a "clear" button when set, and one line of help: "A value here overrides the tuned setting
  for every horizon and direction."
- Create `tunedParamsHorizon` in `horizonPresets.ts` (shared definitions) with the pinned examples.
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
  `strategy_watch_store.add_watch` and `add_watches_bulk` gain the `params_horizon` keyword (default `None`) and
  write both fields.
- Composite watches get no `TIME_STOP`: they have no entry/armed position to age. Intended; stated in the ticket
  report.
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
  benchmark series hash (if any), price bounds, and source hashes of `stock_scorer.py`, of
  `routers/stock_scan.py::_direction_conviction_drop` and of `services/config_loader.py`
  (`load_direction_conviction_min_trend`, which resolves the floor).
- `simulate.py`: `simulate_trades(bars, signals, *, direction, commission, hold_max_days, entry_start, entry_end,
  allowed: list[bool] | None) -> list[TradeRecord]` with `run_strategy_backtest`'s rules (DAY limit entry valid for
  one bar, `_entry_side`, one position at a time, H2's `next()` order and time exit, commission per leg, no entry
  where `allowed[t]` is False, **an empty result for fewer than 100 bars** (as `run_strategy_backtest`), and **trades
  still open at the end of the series are dropped** (`finalize_trades=False`); the simulator returns those dropped
  trades' count so callers can report it). The implementer copies the fill rules from `backtesting.py` 0.6.6
  (`_Broker._process_orders`: limit fill price, gaps, same-bar SL/TP order, close-order priority). The parity test
  is the judge.
- **Parity test (gate for this ticket).** Two layers so it stays runnable. **Fast (default suite, budget ≤ 3 min):**
  a pairwise-covering matrix over strategy × direction × `hold_max_days` {None, 15, 200} × commission {0, 0.0005,
  0.002} × `entry_start`/`entry_end` {unset, mid-series} × series {trending, choppy, gappy-with-holidays, one
  fixture}, plus two edge series: one ending with a trade open, one of 99 bars. **Full (`@pytest.mark.slow`, run by
  the coordinator before closing H8):** the full product, 1,500-bar series. Both: `simulate_trades` equals
  `run_strategy_backtest_trades` (dates equal, prices/returns within 1e-9, same exit reasons, same dropped-open
  count). Asserts `backtesting.__version__ == "0.6.6"`.
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
- `basket.py`: **strata** = `sector_for_symbol` after H0a (the 11 GICS sectors; a symbol still without a sector is
  listed and left out of the sample). **Liquidity** for ranking = mean daily dollar volume (close × volume) from
  stored bars over the walk-forward span before `heldout_start`, the same measure for every symbol (S&P and NDX-only
  alike; the CSV `liquidity` column is not used). Sample = `build_basket(rows, per_sector=tuning.basket.per_sector)`
  (existing `strategy_basket.py`, top-N per stratum) over S&P 500 ∪ NDX 100 minus `universe_exclusions.yaml` **both
  scopes** (the evidence scope means "skipped by tuning"). **Fire-rate universe** = the same union minus the
  **scan-scope** exclusions only (live scans still scan evidence-scope names); it is used **only** to count fires.
  **Trade universe** = the union minus **both** scopes, as the sample; every simulated trade (sample and H10's
  full-universe re-check) comes from it, so no trade is ever taken on evidence-scope bars. The report labels the sample
  "liquidity-selected (dollar volume), equal count per sector".
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
    windows:                      # STOCKS-HORIZON-T1-DESIGN-2026-10-05 values (train is 2-4 x test)
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
- **Ordering note.** H8 uses H0a's sectors and reads whatever history is stored; the real run needs
  `STOCKS-HORIZON-HISTORY` shipped and its backfill done on the mini PC. Tests use synthetic data and need neither.
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
- **Warm-up.** `warm_start` = the calendar date at index `SIGNAL_WINDOW_BARS` (the same for every cell and horizon),
  so every tuned signal is computed on a full 400-bar window, exactly as live after H1 (`_ema` / `_rsi` depend on the
  window start). Per symbol, no entry is allowed before that symbol's own 400th bar (`allowed[t]` is False there);
  symbols listed later simply start later. With `STOCKS-HORIZON-HISTORY`'s history (~2009–2010 start) this costs about 1.6 years and leaves
  every horizon several folds.
- **Folds.** `build_folds(warm_start, heldout_start, train_months, test_months)` — the existing rule: a fold exists
  only if its whole test window ends `<= heldout_start`. **Entry cut-offs** (calendar days, `buffer =
  exit_buffer_days`): train entries in `[train_start, train_end − hold − buffer)`; test entries in `[test_start,
  min(test_end, heldout_start − hold − buffer))`; held-out entries in `[heldout_start, data_end − hold − buffer)`.
  Worst case from a signal on day `s`: fill ≤ s+4 (holiday weekend), time-exit trigger ≤ fill + hold + 3, exit open
  ≤ +4, so exit ≤ s + hold + 11 < s + hold + 14 on an exchange calendar. A symbol with missing bars (halt, ingestion
  hole) can still push an exit further, so as a hard guard any trade whose `exit_date` reaches its window's
  restriction (`train_end` for train, `heldout_start` for test, after `data_end` for held-out) is **dropped and
  counted**, never kept. Folds with an empty entry window are dropped. Fewer than `min_folds_not_thin` folds →
  **thin**. Fold dates are pinned in the test on a synthetic exchange calendar 2009-10-01 .. 2026-10-02 (the
  expected span after `STOCKS-HORIZON-HISTORY`), per horizon; the report prints each cell's real fold dates from the mini PC's data.
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
  `thin`, effective entry spans, boundary-dropped and end-dropped trade counts.
- Parallelism: signal series and gate masks are computed in a `ProcessPoolExecutor` (`--workers`), one work unit per
  (symbol, strategy, direction); simulation runs in-process.

**Test first.** Planted edge on a small synthetic universe: the planted combination wins every fold and is final.
Fold dates per horizon pinned on the synthetic 2009-10-01 .. 2026-10-02 calendar. On a calendar with holidays, every
OOS and train trade's exit date is before its window's restriction and before `heldout_start`; no held-out trade is
open at `data_end`; a symbol with a 10-day bar hole produces a crossing trade that is dropped and counted. A
combination below the floor never wins. A 355-bar-lookback combination is eligible from fold 0 (warm-up), and no
entry happens before a symbol's 400th bar.

**Commit:** `feat(tuning): per-cell walk-forward with hold-scaled windows and a held-out year (STOCKS-HORIZON-T1)`

---

## H10 — Report, CLI and the full-universe re-check

**Semantics.**

- **CLI** `backend/scripts/tune_horizons.py`: `--cells` (filter; default all 60), `--directions` (default both),
  `--workers` (default `os.cpu_count() - 1`), `--probe`, `--resume` (skips cells whose result exists for the same
  config + data hash), `--out` (summaries; default `docs/superpowers/measurements/<today>-horizon-tuning/`), `--data`
  (trade lists and per-cell JSON; default `backend/data/tuning_runs/<today>/`, gitignored). Prints the projected
  runtime before starting. Runs on the mini PC (T1-MINI-PC-2026-10-09: the latest bars are only in its Postgres).
- **Full-universe re-check** (T1-BASKET-SECTOR-SAMPLE-2026-10-08). Selection stays on the sample; evaluation is
  repeated on the full universe (H8's two universes): each fold's **winner** trades that fold's test entries on every
  **trade-universe** symbol (still out-of-sample — winners were chosen on sample train windows), and the **final**
  parameters trade the held-out year on every trade-universe symbol, both costs. The **fire-rate universe** gives the
  measured fire rate over the walk-forward span and the held-out year; its evidence-scope symbols add fires, never
  trades. Cost is small: per cell, one signal series per distinct fold winner per
  universe symbol. The report shows sample and universe numbers side by side.
- **Adoption bar** per cell (ADR decision 5) at `cost_per_leg`, on the **full-universe** OOS and held-out numbers
(criteria 1–4 from the trade universe, criterion 5 from the fire-rate universe):
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
- **Chance count.** Over the **bullish** cells only (bearish cells are blocked and cannot be adopted; they are
  reported in their own table): `bullish cells passed` and `expected by chance ≈ n_bullish_cells_evaluated × 0.025 ×
  0.5` (one-sided CI miss × an independent held-out coin flip under no edge), formula written out and labelled an
  approximation.
- **Report files.** `--out`: `tuning_report.md` (one row per cell: final params; OOS trades / symbols / net
  expectancy / CI at 0.05% and at 0.2%; held-out at both costs and its entry span; fire rate scaled, full
  walk-forward, full held-out; folds; thin; verdict; failed criteria) and `tuning_summary.json` (same, no trade
  lists). `--data`: per-cell JSON with trade lists. Header: gates not applied (H8 list), `current_price` gap, "legacy
  Settings tuner has no time exit", sample selection, survivorship / bull-market label (ADR consequences), cost model,
  git commit, data range, sample and universe sizes, runtimes, the Annual window note.

**Test first.** Cluster bootstrap pinned on a fixed trade list (seed 7), and shown wider than a per-trade bootstrap
on data where one symbol's trades are correlated. Each adoption criterion failing alone flips the verdict and is
named. Chance-count formula. An evidence-scope symbol contributes fires to criterion 5 but no trade to criteria 1–4 (sample
and full-universe re-check). `--resume` skips a finished cell. A tiny end-to-end run on two synthetic symbols writes
all files with every documented column.

**Commit:** `feat(tuning): tune_horizons CLI, adoption-bar report, full-universe re-check (STOCKS-HORIZON-T1)`

---

## Verification (coordinator, after H10)

- Backend full suite on Python 3.11; frontend typecheck + Jest.
- On the mini PC, in order: upgrade the live app's venv to `backtesting==0.6.6` (`pip install -r
  backend/requirements.txt`); confirm `STOCKS-HORIZON-HISTORY` is shipped and its first backfill and bar-basis
  re-check are done (that phase's Verification); then `tune_horizons.py --probe`. The projected runtime goes to Kenneth before the
  real run (`STOCKS-HORIZON-TUNING-RUN`). Over 24 h at its core count → raise it (smaller `per_sector`, fewer cells
  per night with `--resume`).
- Live checks on the mini PC: a live `mean_reversion_rsi` scan returns setups (H1); a Swing stock scan's
  Step 6 shows time exits (H2); the Step-4 panel shows `baseline` profiles and a Custom 60–185 scan says "using Annual
  settings" (H5); a stock position entered with hold 15 raises `TIME_STOP` on day 15 (H6).

## Out of scope (logged, not built)

- The Adopt button, Unvalidated labels from verdicts, the pooled gate replacing the per-symbol backtest gate (T2).
- Switching the live Step-6 gate to 0.05% per leg (T1-LIVE-COST-UNCHANGED-2026-10-08; T2).
- The legacy Settings → Strategy Tuning WFO (no time exit, 3-year window, Sharpe ranking): left as is.
- `TIME_STOP_APPROACHING` for stocks.
- Delisted names (logged by STOCKS-PARAMS-PER-HORIZON-2026-10-05, not scheduled). Longer history for today's
  constituents: phase `STOCKS-HORIZON-HISTORY`.
- The scorer's 120-bar window (T3). The live `current_price` vs close difference for `pullback_ema` (reported).
