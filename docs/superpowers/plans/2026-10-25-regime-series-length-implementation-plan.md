# REGIME-SERIES-LENGTH — approved implementation

Tracking/claim: #534, `REGIME-SERIES-LENGTH`. Decision: [Kenneth's untagged approval](https://github.com/Netke237/trading-assistant/issues/534#issuecomment-6393270194) of both recommendations in the [numbered questions](https://github.com/Netke237/trading-assistant/issues/534#issuecomment-6383936133): option 1, uniform daily regime history from the database (800 bars for current configuration), and explicit unmeasured disclosure/logging. Evidence PR #540 is merged. This is the implementation following that evidence, not another measurement run.

Current application baseline: `f777fa2885e84ce14da5ec765541030817b31afc`. Preserve the measurement plan/code reviews and counters. The next reviews use existing **plan round 2** and **code round 2**, with at most round 3 available in either stage; do not reset counters or open an unapproved extra stage. Review the whole new implementation plan/diff, not the unchanged merged measurement code.

## 1. Contract and scope

For a fixed symbol, horizon, direction, scoring configuration, observation time and database contents, Options, Stocks and auto-trade must hand `compute_omm` the identical ordered adjusted daily-close series. Analysis's per-symbol daily regime summaries must follow the same rule. A daily regime that cannot be measured remains explicitly unmeasured, with no fabricated zero-conviction payload. Existing behavior for a measured regime, gate thresholds, sizing rules and data-unavailable/config-error refusals remains authoritative.

Scope: a new `backend/app/services/daily_regime_history.py`; its isolated database tests; daily regime call sites in `backend/app/routers/scan.py`, `backend/app/routers/stock_scan.py` and `backend/app/services/auto_trader.py`; relevant regression tests; the shared `MarketSentiment` molecule and tests. Coordinator owns this plan/state/audit records and issue metadata.

Do not edit `historical_store.py`, provider adapters, ingestion, schemas, persistence shapes, scoring configuration, `regime_omm.py`, intraday processing, broker submission or shared candle caches. #535 owns history-writer work; #536 owns the Options provider fallback's forming daily bar. Neither file set is needed here. Historical-store imports may reuse existing pure settlement utilities; do not change them.

## 2. Shared read protocol

Implement public async and synchronous read adapters over **one** query/row-conversion implementation. Both accept a validated effective daily bar count, symbol and optional aware observation time. Default observation time is aware UTC; derive the inclusive database end date from `historical_store.last_settle_boundary(now).date()` in the boundary's market timezone. The store's settled daily rows, including its two-hour settlement delay, are the common source. This avoids introducing a provider-specific current-bar rule. Preserve this cutoff explicitly in tests around close/settlement, weekends and DST. A holiday adds no row; no new holiday calendar is needed.

Count policy: at least **800 bars**, increasing to `window + lookback` if an effective daily horizon needs more. Current Swing (500+20) and Position (750+50) both read 800. Use positive integer validation, excluding bool/nonfinite/float inputs, and the existing regime configuration validator. If a shared uniform count is derived from both daily horizon blocks, validate all contributing blocks before reading; a malformed contributing configuration must surface as a configuration error, not get caught as missing market data. No silent config defaults and no reduced statistical windows.

Query `OhlcvDailyModel` by symbol and `date <= end`, descending date, SQL `LIMIT count`; reverse the results for ascending chronological order. A stale/sparse database still returns its latest available rows, never a fabricated calendar-length history. No provider fetch, heal, write, commit or candle-cache change in these readers. Empty history and database errors remain distinguishable to callers.

Apply exactly the existing store's adjustment contract to all OHLC values: `float(raw)` when `adj_factor is None`; otherwise `round(float(raw) * float(adj_factor), 6)`. Raw volume remains integer and `time` is the ISO date. Test with independently specified raw/adjusted values, null factors and historical split/dividend factors. Do not round closes differently between adapters or regenerate numerical golden pins.

Async scans use request-loop sessions (`AsyncSessionLocal`, resolved at call time, with injection possible in tests). The synchronous Fire adapter runs in its existing worker thread and must **not** use that application's pooled async engine from a fresh `asyncio.run` loop. Create a private async engine/session factory with `NullPool` for the same configured database URL; run the shared read on the worker's own event loop and dispose its private engine in `finally`. No global engine disposal, persistent extra thread, schema creation or mutation. An invocation already on an event-loop thread must fail explicitly rather than deadlock it. Test multiple independent synchronous invocations against an isolated file SQLite database and engine cleanup on failure; verify the private-engine/NullPool construction. PostgreSQL credentials are never read or printed by tests.

## 3. Call-site integration

### Options

Keep existing `bars_map`, 441-calendar-day candle fetch, fallback candle calls, prices, scorer input and confidence-cache generation unchanged. Only the daily `_regime_bars` branch in `_process_symbol` gets the shared database reader. Run the read under the existing per-symbol semaphore and never recursively acquire that semaphore. The `15min` branch and its completed-bar/refusal protocol stay unchanged.

Validate contributing configuration before the data-fetch/computation catch block. Database failure, empty/short history and `compute_omm` returning None each leave `_regime_signal = None`; emit an explicit warning with symbol/horizon and cause (without credentials or database URL). Both pre-screen and post-chain scorer calls continue using that single signal. A measured signal retains its current payload and HMM processing over the same selected regime bars. An unmeasured signal is not replaced with a truthy dummy dictionary (which would accidentally apply a gate to invented zeroes).

### Stocks and Analysis

Preserve `_HISTORY_YEARS = 5` and all original `bars` arrays for backtests, signals, price, EMA, benchmark, charts and scorer inputs. Replace only the daily regime branches in `_process_stock` and `_analyze_core`. Use the shared reader under their existing concurrency structure; catch data errors locally and log unmeasured explicitly instead of dropping an otherwise usable candidate on an unguarded query exception. Keep config errors outside that abstention handler.

`_regime_block_for_horizon` is synchronous and currently reuses Analysis's full daily history. Do not block its event loop with database I/O. Preload the shared daily regime series once in `_analyze_core`, carry it separately from `daily_bars` in the internal `_AnalyzeCore` handoff, and pass it explicitly to the daily horizon blocks. Both supported daily horizons use the common count sufficient for all blocks being rendered. Leave Intraday's separately loaded bars alone. Any additional per-symbol daily `compute_omm` call found in this router must use the same source; no raw five-year regime escape path. Market-wide regime/monitor calculations are outside this symbol-specific scope.

### Auto-trade

Retain `_fetch_scan_window_bars(symbol)` as the patchable entry point but replace its old provider/cache/441-day implementation with the synchronous shared DB reader and a concise accurate contract. Use a count sufficient for all configured daily horizons; configuration failures must become `RegimeGateConfigError` and existing configuration refusal handling, rather than a data abstention. `_measure_trade_regime` retains its existing fetch deadline, thread execution, symbol/direction/horizon, computation, gate and sizing policy. No bars/database failure still follow its existing `RegimeDataUnavailableError` path; a nonempty history too short or statistically unmeasurable still returns None with a warning. No new broker order or real notification is executed during verification.

Update the obsolete mechanism comments describing 441-day/provider parity in the affected helper and `_measure_trade_regime`; these would otherwise instruct future changes using the superseded rule. Retain unrelated historical audit records unchanged. Intraday continues using `_fetch_intraday_regime_bars`.

## 4. Visible unmeasured result

The existing `MarketSentiment` molecule is shared by TradeCard and StockPositionCard; TradeCard shows it by default. For absent sentiment or `insufficient_data`, render a visible caution notice **“Regime: Unmeasured”**, with a reason that covers insufficient history/unavailable data. Suppress stale conviction/state/probability values as today. Keep measured output unchanged; measured zero conviction is valid and must still show as zero. No schema additions, store migrations, qualification-status changes or policy changes.

Tests cover undefined/null/insufficient sentiment, stale numbers behind insufficient-data, measured zero, normal measured data, compact/default display, candidate changes and actual card integration. Preserve explicit `showMarketSentiment` presentation controls rather than changing their meaning. Log warnings at every daily scan abstention and retain the existing Fire warnings.

## 5. Build units (fresh implementer each; only after clean plan review)

1. **Shared reader and policy** — new service, `backend/tests/test_daily_regime_history.py`. Write tests first: literal 800-of-1000 expected dates; count growth/config errors; SQL limit/symbol/end isolation; exact adjustment examples; stale/empty history; settlement/weekend/DST boundaries; async/sync byte/value parity; private-engine cleanup and repeated worker loops; explicit query failure; no write or provider call. Use isolated test databases only. Full frontend typecheck/Jest and Python 3.11 backend suite per implementer contract. Estimated S, complexity 4.
2. **All reader integrations** — the three caller files and relevant existing/new backend tests. Test actual scan, analysis and Fire entry points with deterministic isolated DB rows, spies at their real `compute_omm` calls and literal independently expected input arrays. Prove identical input series and direct independently derived `compute_omm` result for both directions and daily horizons; prove original non-regime scorer/backtest history lengths are preserved. Pin both Options scorer passes, Analysis per-horizon summaries, DB-error/unmeasured/config-error outcomes and Intraday's unchanged fetch path. Replace obsolete date-window tests with tests for the approved DB-source/count contract while retaining deadline, cache-isolation and refusal invariants; explain any changed expectation. Full frontend/backend checks. Estimated M, complexity 4.
3. **Disclosure and evidence** — `frontend/components/molecules/MarketSentiment/{index.tsx,MarketSentiment.test.tsx}`, necessary existing card test files, and a scoped implementation verification note under `docs/superpowers/measurements/2026-10-24-regime-series-length/`. Meaningful UI RED→GREEN before implementation; actual card unmeasured notice and measured-zero distinction. Document deterministic DB/reader parity evidence, exact runtime, tests and remaining live-mini-PC limits. Full frontend/backend checks. Estimated XS, complexity 2.

No implementer edits phase state or GitHub. No unrelated fixes. Report any scope conflict before editing another owner's files.

## 6. Independent reviews and completion

Plan review applies the numeric/persistence gate against real code before tickets. Preserve existing plan1/code1 evidence reviews, use remaining plan/code rounds without resets. After all units, merge current `origin/main`, resolve state conflicts only within this phase, rerun required checks, then independently audit the whole new application diff plus interactions against this plan. Review both wrong-number/order/persistence defects and mechanism comments that would cause a wrong change. A nonclean third stage round stops work.

Backend interpreter is `/workspace/.venv311/bin/python` (3.11.16); verify its version before every backend execution. Backend test fixtures pin local isolated databases and credential/state files. No real DB, broker, notification, calibration or ingestion jobs are run. Frontend typecheck, complete Jest, complete backend suite, focused parity tests and production frontend build form local acceptance; missing/failed checks are not passed by assertion. Record any unchanged-main failures separately with reproduction.

Milestones for this implementation: 10% plan draft; 20% exact plan independently clean; 50% all three build units implemented; 70% required checks/DB parity/disclosure pass; 85% independent code audit clean; 95% exact PR head meets merge requirements; 100% verified merge and integrated retests. Historical measurement completion stays recorded separately. Self-merge follows `docs/agents/board.md` step 7 only.
