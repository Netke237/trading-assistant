# REGIME-SERIES-LENGTH — code audit round 4 (code stage round 2 of 3)

- **Phase:** `REGIME-SERIES-LENGTH` (#534; build units #563, #564, #565)
- **Date:** 2026-10-31
- **Reviewer:** fresh independent `gate-auditor` subagent applying `bmad-review-adversarial-general`, with no part in the build
- **Reviewed:** `git diff 87e0b56b..e7d453fe`. `87e0b56b` is `origin/main` and is already merged into the branch, so this is the whole PR diff (24 files). It was checked against `docs/superpowers/plans/2026-10-25-regime-series-length-implementation-plan.md`.
- **Gate:** a wrong number or verdict shown to the user or sent on a broker order, corrupted persisted data, or a false mechanism comment that would steer a future change into a wrong number.
- **Result:** **0 gate findings: clean.**

An earlier integrated code round was started on 2026-10-26, but no result was ever recorded. It does not count, and this round replaces it.

## What the reviewer verified

1. **Fire (auto-trader).** Commit `25fb450f` removed the 441-day provider window, Option A, guard (i) and the shared candle-cache snapshot/restore. The reviewer checked what replaced them:
   - **No forming bar:** the DB reader's end date is `last_settle_boundary(now).date()` in market time, and the query uses `date <= end`. Today's row is therefore excluded until settlement, which is stricter than Option A.
   - **No cache access:** `market._candles_cache` is never touched.
   - **Deadline:** the 25 s fetch deadline is kept.
   - **Outcomes stay distinct:** a DB error or empty history raises `RegimeDataUnavailableError`. A short or unmeasurable series returns None. A config or count fault raises `RegimeGateConfigError` and is not reclassified as missing data.
   - **Nothing else lost:** all four auto-trader hunks are regime-only. Sizing, exposure reservation and the Tradier governor are untouched. The 19 deleted tests all covered the superseded window and cache logic.
2. **Parity.** All four callers use `daily_regime_bar_count` over the full `scoring_rules.yaml`, which is the maximum across daily horizons. One async query backs both adapters, with the same end-date function. Adjustment rounding is byte-identical to `historical_store._read_bars`. Rows are keyed by the raw symbol, as the store keys them.
3. **Sync adapter.** It refuses explicitly on a running loop. Each call builds a private `NullPool` engine, runs it with `asyncio.run` on the worker thread and disposes it in `finally`. The URL is the same `DATABASE_URL` the async engine uses. There is no deadlock path.
4. **Unmeasured handling.**
   - **Options:** an unmeasurable regime gives `_regime_signal = None`. No dummy dict is substituted, and one signal feeds both scorer passes.
   - **Stocks and Analysis:** a DB error keeps the candidate as unmeasured.
   - **Config errors:** the count is computed outside the catch blocks, and the S2 check pre-validates every contributing horizon.
5. **Non-regime inputs and Intraday.** Options `bars_map`, the 441-day prefetch and the fallback candles are unchanged. So are the Stocks 5-year scorer/backtest/price/EMA/benchmark/chart bars and the 15-minute branches.
6. **Analysis.** The series is preloaded once, asynchronously, and carried in `_AnalyzeCore.daily_regime_bars` to both daily blocks. `_regime_block_for_horizon` does no I/O.
7. **Frontend.** "Regime: Unmeasured" appears only for `!s || s.insufficient_data`. A measured zero stays on the measured path.
8. **Test edits.** No numerical expectation was changed to mask a behaviour change. The `test_docc2` r8b expectation follows directly from the approved uniform count and validation rule.

## Tests the reviewer ran

These ran on Python 3.11.9:

```
py -3.11 -m pytest -q -p no:cacheprovider tests/test_daily_regime_history.py tests/test_daily_regime_integrations.py tests/test_docc2_regime_block.py tests/test_tradier_governor_sites.py tests/test_stock_scan_unmeasured_floor.py tests/test_a4_intraday_regime_bars.py tests/test_p3a_scan_sizing_signals.py tests/test_auto_trader.py tests/test_a5_analysis_mirrors_scan.py tests/test_a5c_analysis_scan_drop_flags.py
```

Result: **454 passed** in 103.69 s.

## Below the gate (logged, not fixed)

- The docstring of `backend/app/routers/stock_scan.py` `_regime_data_drop` still describes the old daily behaviour. For a daily horizon, a DB error now makes the scan abstain while Fire refuses; plan §3 approves that split. The sentence explains an exclusion the plan chose and steers no change toward a wrong number. Fix it in a later docs/hygiene pass, not in this branch (`audit_rule`: only gate findings are fixed in-branch).
