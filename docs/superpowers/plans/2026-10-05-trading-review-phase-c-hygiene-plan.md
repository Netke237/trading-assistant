# Trading Review Phase C, hygiene — Implementation Plan (`TRADING-REVIEW-PHASE-C-HYGIENE`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Seven items logged against `main` by `TRADING-REVIEW-PHASE-C` (merged 2026-10-05 as `3b0348ac`, PR #55) and
recorded in `PROJECT_STATE.json` → `open_questions` ("LOGGED 2026-10-05 by TRADING-REVIEW-PHASE-C ..."). On 2026-10-05
Kenneth decided (decision `PHASE-C-DEFERRED-GRILL-2026-10-05`) to build all seven as one target, separate from
`TRADING-REVIEW-PHASE-C-RR`, with the confidence-cache test isolation first, `mean_reversion_vwap_daily` added to the
backtest map and the evidence scripts, and `setup_window_bars <= 0` read as 1 with a config-health warning.

**No live number changes on purpose, with one exception (T6).** T1-T5 and T7 change no figure the app shows today
(each says why). T6 removes a 24-hour window in which a backtest computed on pre-refresh bars can be served — both
entries cached before the refresh (eviction) and results of backtests in flight across it (generation guard).

**Independence.** Disjoint from `TRADING-REVIEW-PHASE-C-RR`'s files (`reward_risk.py`, `trade_plan.py`, `TradeCard`,
`scanStore`, `schemas/__init__.py`). Built on its own branch from `main`.

## Global constraints

- **Runtime.** Backend Python **3.11** (`cd backend && .venv/bin/python -m pytest`; Windows
  `.\.venv\Scripts\python.exe -m pytest`). Frontend `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **No threshold or parameter value changes.** No YAML value is edited by any task.
- **Numeric golden pins.** No pin may move. A moved pin is a defect: stop and report it.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Ticket graph

```
T1 (cache test isolation) ── T2 (clear_cache lock + generation)      same file: confidence_cache.py → serial
T3 (vwap_daily backtest map + evidence)                              disjoint
T4 (setup_window_bars clamp + config_health + SCORING_RULES.md)      disjoint
T5 (WfoOosMetrics type + Settings display)                           disjoint (frontend only)
T2 ── T6 (refresh_adjustments evicts _BACKTEST_CACHE + generation guard) ── T7 (commission dedupe)
                                                                     T6/T7 same file: routers/stock_scan.py → serial
```

Sequential build in the order T1, T2, T3, T4, T5, T6, T7. T6 also needs T2 (`_clear_generation` and the helper).

**Plan round 1 (2026-10-05):** HYG-P1-F1 (T4 wrote wrong per-horizon numbers into SCORING_RULES.md) and HYG-P1-F2
(T6 left an in-flight backtest able to re-insert a pre-refresh result) fixed in this text. Also corrected from the
same audit's checks: T4's function is `_rule_trigger`; `clear_cache` has no production caller (T2).

---

## T1 — Confidence-cache tests never touch the real cache file (item 5)

**Mechanism today.** `backend/app/data/confidence_cache.py` sets `_DB_PATH` at import to the real
`backend/data/confidence_cache.db` and runs `_warm_load()` at import, which reads that file and **deletes its expired
rows**. `backend/tests/test_confidence_cache.py` calls `clear_cache()` and `set_cached()` without redirecting
`_DB_PATH`, so a test run wipes every real cached confidence and leaves
`MSFT|bullish|swing|default:default|options|b2 = {"confidence": 50, "sample_size": 30}` (written at
`test_confidence_cache.py:125`), which `_warm_load` then serves after a backend restart. Confirmed in Kenneth's file on
2026-10-05 (the row was deleted by hand that day). `tests/test_adjustment_refresh.py:245` already monkeypatches
`_DB_PATH` per test; the other tests do not.

**Semantics.**

- `confidence_cache._DB_PATH` = `os.environ.get("BAMENDJOU_CONFIDENCE_CACHE_DB")` when set and non-empty, else today's
  default path. Read once at import, before `_warm_load()`.
- `backend/tests/conftest.py` sets that variable to a file inside the session temp dir it already creates
  (`_TEST_DB_DIR`), with `os.environ.setdefault`, in the "safety pin" block **before any app import** — the same
  pattern as the `DATABASE_URL` and credential-store pins already there, with a comment in the same style.
- Production behaviour is unchanged (the variable is unset there).

**Test first.** `backend/tests/test_confidence_cache_isolation.py`:

1. Under pytest, `confidence_cache._DB_PATH` is not the default path (compute the default the same way the module does
   and compare resolved paths) and lies under the conftest temp dir.
2. A subprocess (`sys.executable -c ...`, env var set to a `tmp_path` file) imports `app.data.confidence_cache` and
   prints `_DB_PATH`; it equals the env value. With the variable empty, it equals the default path.

**Code.** The env lookup in `confidence_cache.py`; the conftest pin. Remove nothing from the existing tests (the
per-test monkeypatch in `test_adjustment_refresh.py` stays).

**Why no live number changes:** only test runs read the variable.

**Commit:** `test(cache): pin the confidence cache to a temp file under pytest (Phase C hygiene)`

---

## T2 — `clear_cache()` takes `_db_lock` and invalidates in-flight writes (item 4)

**Mechanism today.** `clear_cache()` (`confidence_cache.py`) clears `_store` under `_lock` and runs
`DELETE FROM confidence_cache` **without** `_db_lock` and **without** bumping any generation. It has **no production
caller** today (`routers/credentials.py:33-34` calls `tastytrade_session.clear_cache`, a different function); tests
call it. A `set_cached(..., bars_generation=g)` already past its memory
write when `clear_cache` runs can re-insert its row into SQLite after the DELETE (it holds `_db_lock`, the DELETE does
not wait for it), and a value computed before the clear is still accepted into `_store` afterwards because no
generation moved. `invalidate_symbol` (same file) already does this correctly for one symbol (R2-F1 of Phase C).

**Semantics.**

- A module-level `_clear_generation = 0`.
- `clear_cache()`: under `_lock`, `_generation += 1`, `_clear_generation = _generation`, `_store.clear()`; then, under
  `_db_lock` (lock order `_db_lock` then `_lock` is never inverted: `_lock` is released first, exactly as in
  `invalidate_symbol`), the DELETE.
- The two generation checks (`set_cached` under `_lock`, `_write_db_guarded` under `_db_lock` + `_lock`) compare
  `bars_generation` against `max(_symbol_generation.get(sym, 0), _clear_generation)`. Extract one helper
  `_invalidated_after(key, bars_generation) -> bool` used by both, so they cannot drift.
- `bars_generation=None` keeps the unconditional write (unchanged).

**Test first.** Extend `backend/tests/test_adjustment_refresh.py` next to the existing generation tests (they already
use a tmp `_DB_PATH`):

1. `g = generation()`; `clear_cache()`; `await set_cached(k, v, bars_generation=g)` → `get_cached(k)` is None and the
   SQLite file has no row for `k`.
2. `bars_generation=None` after a clear still writes (unchanged behaviour).
3. The interleaving test: patch `_write_db` so that, inside the guarded write, it signals and waits; run
   `clear_cache()` on another thread while it waits; after both finish, no row for `k` remains in SQLite. Mirror the
   existing R2-F1 interleaving test's structure.

**Why no live number changes:** no production path calls `clear_cache`. T2 makes it safe for any future caller and
provides the clear generation T6 relies on.

**Commit:** `fix(cache): clear_cache takes _db_lock and invalidates in-flight writes (Phase C hygiene)`

---

## T3 — `mean_reversion_vwap_daily` in the backtest map and the evidence scripts (item 1)

**Mechanism today.** `run_strategy_backtest` (`services/strategy_backtest.py:101-108`) maps six strategy names to signal
functions; `mean_reversion_vwap_daily` is missing, so a backtest of it returns `_empty_result(..., "Unknown strategy
...")`. In the live app it is reachable only as a `mean_reversion_multi` variant (`routers/stock_scan.py:400-428`),
and the multi path backtests through `_MULTI_BT_STRATEGY = "mean_reversion_rsi"` (`stock_scan.py:244`), so **no live
scan number depends on the missing entry**. The evidence harness cannot measure it: `DAILY_STRATEGIES`
(`scripts/evidence/gate_persistence.py:45-47`, imported by `strategy_matrix.py:43`) omits it.

**Semantics.**

- Add `"mean_reversion_vwap_daily": mean_reversion_vwap_daily_signal` to the map (import it with the others). Its
  signature (`strategy_engine.py:1105-1114`) takes `direction` and `current_price` and defaults `vwap_lookback` /
  `vwap_deviation_pct`, so the backtest's `fn(slice_bars, direction=direction, **effective_params)` call works with the
  `exit:` block in `strategy_params.yaml:207-212` merged by `get_exit`.
- Add `"mean_reversion_vwap_daily"` to the `Strategy` Literal in `strategy_backtest.py:13`.
- Append it to `DAILY_STRATEGIES` in `gate_persistence.py`.
- Do **not** add it to `schemas/stock_scan.py`'s top-level `Strategy` Literal, to `_MULTI_BT_STRATEGY`, or to
  `strategy_watch_evaluator._SIGNAL_FNS`. Those would change live behaviour; out of scope.

**Test first.** `backend/tests/test_strategy_backtest_vwap_daily.py`:

1. `run_strategy_backtest(bars, strategy="mean_reversion_vwap_daily", direction="Bullish")` on a fixture with ≥ 100
   daily bars (use an existing OHLCV fixture from `backend/tests/fixtures/`) does **not** return the
   "Unknown strategy" summary.
2. `"mean_reversion_vwap_daily" in gate_persistence.DAILY_STRATEGIES` (import the module the way the existing
   evidence tests do; find them with `grep -rln "evidence" backend/tests`).

**Why no live number changes:** stated above; the multi path's proxy is untouched.

**Commit:** `fix(backtest): run mean_reversion_vwap_daily in the backtest and the evidence harness (Phase C hygiene)`

---

## T4 — `setup_window_bars <= 0` reads as 1 and warns (item 2)

**Mechanism today.** `_rule_trigger` (`scoring/stock_scorer.py:754`) reads `window = int(tc.get("setup_window_bars",
1))`. A value `<= 0` makes `_event_within(n, window, ...)` find no bar, so MACD, the RSI cross and the stochastic event
can never pass: the trigger rule silently loses its momentum events. `config_health` only checks that the key is known
(`HORIZON_KEYS["trigger"]`, `config_health.py:130-134`), not its value. `SCORING_RULES.md:134` says "All signals must
occur within 8 daily bars of each other" and `:142` "within 8 bars"; the code windows each event against the **last**
bar (`:137` already says so) and the window is per horizon (8 / 10 / 5 in `scoring_rules.yaml:105,264,375`).

**Semantics.**

- `window = max(1, int(tc.get("setup_window_bars", 1)))`. Non-integer values keep today's behaviour (out of scope).
- `config_health`: for each horizon in `_HORIZONS` whose `trigger.setup_window_bars` is an `int`/`float` `< 1`, append a
  **warning** (`r.warnings`, via `_warning(path, message)`) at path `horizons.<h>.trigger.setup_window_bars` with message
  `"setup_window_bars must be >= 1; read as 1 (last bar only)"`. Add it as one small `_check_setup_window(doc, r)`
  called where `_check_horizons` is called. Warnings, not errors: the reader always has a usable value (DOCC pattern).
- `SCORING_RULES.md`: line 134 becomes "Each momentum event must occur within | the last `setup_window_bars` bars
  (per horizon — see the Section 8 matrix's "Setup window (bars)" row), and its state must still hold on the last
  bar"; line 142 "within 8 bars" becomes "within `setup_window_bars`". Do not write per-horizon numbers into these two
  lines (the shipped values are Intraday 10, Swing 8, Position 5: `scoring_rules.yaml:264,105,375`, already stated at
  `SCORING_RULES.md:219`). Change nothing else in the file.

**Test first.**

1. `backend/tests/test_stock_scorer_setup_window.py` (or extend the existing T7 test file — find it with
   `grep -rln setup_window_bars backend/tests`): a config with `setup_window_bars: 0` scores the trigger rule exactly
   as `setup_window_bars: 1` on the same bars (a fixture where a MACD cross happens on the last bar).
2. `config_health` test (extend the existing config-health tests): a scoring_rules document with
   `horizons.swing.trigger.setup_window_bars: 0` yields exactly one warning at that path and no error; the shipped file
   yields none.

**Why no live number changes:** the shipped values are 8 / 10 / 5.

**Commit:** `fix(scoring): setup_window_bars below 1 reads as 1 and warns in config health (Phase C hygiene)`

---

## T5 — `WfoOosMetrics` carries the pooled-evidence fields (item 3)

**Mechanism today.** Since Phase C T5, the backend's `oos_metrics` (`services/strategy_param_optimizer.py:203-216`)
holds `n_trades` (pooled across the basket — the figure `min_trades` gates), `n_trades_per_symbol` and `n_symbols`
(the `min_symbols` floor). `frontend/lib/api.ts:1113-1120` `WfoOosMetrics` lacks the last two, and the Settings
Strategy Tuning card (`app/(frame)/settings/page.tsx:2746-2750`) shows "OOS trades" = `n_trades` with no symbol count,
so a user cannot see the second half of the eligibility floor.

**Semantics.**

- `WfoOosMetrics` gains `n_trades_per_symbol?: number; n_symbols?: number;` — optional, because proposals persisted
  before Phase C T5 lack them.
- The "OOS trades" value renders `{n_trades}` followed, only when `n_symbols` is a number, by
  ` · {n_symbols} symbols` in the same element. Nothing else on the card changes.

**Test first.** Extend the existing Settings Strategy Tuning test (find it with
`grep -rln "OOS trades" frontend --include=*.test.tsx`; if none exists, add
`frontend/app/(frame)/settings/__tests__/wfoOosTrades.test.tsx` rendering the proposal card the way neighbouring
settings tests do): a proposal with `n_trades: 42, n_symbols: 5` shows "42 · 5 symbols"; one without `n_symbols` shows
"42".

**Why no live number changes:** `n_trades` is shown as today; the symbol count is added beside it.

**Commit:** `feat(settings): show the WFO proposal's contributing symbol count (Phase C hygiene)`

---

## T6 — `refresh_adjustments` evicts the refreshed symbols' cached backtests (item 6)

**Mechanism today.** `_BACKTEST_CACHE` (`routers/stock_scan.py:545`) holds `BacktestResult`s for 24 h
(`_BACKTEST_TTL`) under `_backtest_key` (`:626-644`), whose bar component hashes only the **last 20** `(time, close)`
pairs. `refresh_adjustments` (`services/historical_store.py:503-567`) rewrites a stale symbol's adj factors and calls
`confidence_cache.invalidate_symbol(symbol)` (`:560`) but never touches `_BACKTEST_CACHE`. When the refresh changes only
bars older than the last 20 (a split or dividend adjustment further back), the key is unchanged and the scan and the
Analysis page serve the pre-refresh backtest — win rate, expectancy, `passes_gate` — for up to 24 h. That is a wrong
number in front of the user.

**Semantics.**

- `routers/stock_scan.py` gains `evict_backtest_cache(symbols: Iterable[str]) -> int`: removes every
  `_BACKTEST_CACHE` key whose prefix is `f"{SYMBOL.upper()}|"` (exact prefix with the `|` delimiter, so `AAPL` never
  evicts `AAPLX`); returns the count.
- **In-flight guard (plan round 1, HYG-P1-F2).** Eviction alone does not close the window: a scan or Analysis request
  that read the bars before the refresh and is awaiting `run_strategy_backtest` in `_BACKTEST_POOL` stores its
  pre-refresh result at `stock_scan.py:857` / `:1312` **after** the eviction, under the same key, for 24 h. Both
  writers already capture `_bars_gen = conf_generation()` before reading the bars (`stock_scan.py:697`, `:1135`), and
  `refresh_adjustments` calls `invalidate_symbol(symbol)` (which bumps that symbol's generation) before the callback.
  So:
  - `confidence_cache` gains public `invalidated_since(symbol: str, bars_generation: int) -> bool` = the T2 helper's
    test (`max(_symbol_generation.get(SYMBOL, 0), _clear_generation) > bars_generation`) under `_lock`. T2's
    `_invalidated_after(key, ...)` calls it with the key's symbol prefix, so the rule lives in one place.
  - At both `_BACKTEST_CACHE[_bt_key] = ...` stores: skip the store when
    `invalidated_since(symbol, _bars_gen)`; the computed `bt_result` is still used for this request (it is what this
    request's bars give, as today).
  - The eviction stays: it removes entries stored before the refresh started.
- The service must not import the router. `refresh_adjustments` gains an optional parameter
  `on_refreshed: Callable[[str], None] | None = None`, called once per refreshed symbol right after
  `invalidate_symbol(symbol)`. The endpoint (`routers/historical_data.py:78-85`) passes
  `lambda s: evict_backtest_cache([s])`. Every other caller of `refresh_adjustments` (check with
  `grep -rn "refresh_adjustments(" backend/app`; today the endpoint is the only one) is listed in the ticket report.

**Test first.** `backend/tests/test_adjustment_refresh.py`:

1. Seed `_BACKTEST_CACHE` with keys for `AAPL` and `AAPLX`; `evict_backtest_cache(["aapl"])` removes only `AAPL`'s and
   returns 1.
2. `refresh_adjustments([...], fetch=<stub>, on_refreshed=spy)` calls `spy` once per refreshed symbol and never for a
   failed or non-stale one (reuse the file's existing stale-symbol fixtures).
3. Endpoint test: posting to `/api/historical-data/refresh-adjustments` with a stubbed refresh that reports `AAPL`
   refreshed leaves no `AAPL|` key in `_BACKTEST_CACHE`.
4. `invalidated_since`: `g = generation()`; `invalidate_symbol("AAPL")` → `invalidated_since("AAPL", g)` is True,
   `invalidated_since("MSFT", g)` is False; after `clear_cache()` both are True for the pre-clear `g`.
5. Interleaving (HYG-P1-F2): drive one of the two scan paths with `get_historical_bars` and `run_strategy_backtest`
   stubbed so that `invalidate_symbol(symbol)` + `evict_backtest_cache([symbol])` run while the backtest is in flight
   (e.g. the stubbed backtest triggers them before returning). After the request finishes, `_BACKTEST_CACHE` has no
   entry for that symbol, and the request's own result still carries the computed backtest. Repeat for the other
   path (`:1312` and `:857`), or parametrize.

**Commit:** `fix(backtest): a refresh evicts cached backtests and drops in-flight pre-refresh results (Phase C hygiene)`

---

## T7 — One per-leg commission rule (item 7)

**Mechanism today.** `routers/stock_scan.py:204-210` `_backtest_commission()` computes
`costs.get("fee_pct", 0.001) + costs.get("slippage_pct", 0.001)` itself; `services/walk_forward.py:110-117`
`commission_for(costs)` computes the same expression. The two can drift.

**Semantics.** `_backtest_commission()` returns `commission_for(get_costs())`; keep its docstring's first sentence and
add "Same rule as walk_forward.commission_for (Phase C T4)."

**Test first.** A test that patches `get_costs` to `{"fee_pct": 0.002, "slippage_pct": 0.003}` and asserts
`_backtest_commission() == commission_for(that) == 0.005`, plus one with `{}` asserting `0.002`.

**Why no live number changes:** the expressions are identical today.

**Commit:** `refactor(backtest): stock scan uses walk_forward.commission_for (Phase C hygiene)`

---

## Out of scope

- Any YAML value, threshold, strategy parameter, or the C4 decisions.
- Adding `mean_reversion_vwap_daily` as a top-level Stocks strategy or to strategy watches.
- Non-integer `setup_window_bars` handling.
- The other `open_questions` entries.
