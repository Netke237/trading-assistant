# HISTORY-INGEST-GAPS — three ingestion gaps found by the D3 recovery run (#114)

Target id: `HISTORY-INGEST-GAPS`. Follow-up to `HISTORY-SINGLE-PROVIDER-REBUILD` (PR #341).
Evidence: #114 comments of 2026-10-15/16, PR #347,
`docs/superpowers/measurements/2026-10-15-d3-history-recovery/`.
Backend only, one layer, three small pieces built test-first in one branch and one PR.
No migration, no frontend change, no config change.

## Gate reminder

A finding blocks only if it can put a wrong number in front of a user or on a broker
order, or corrupt persisted data. For this target that means: bars of the wrong
instrument stored under a symbol, bars stored under the wrong symbol, or a refresh that
silently skips or mis-stores the staleness reference.

## 1. Class-share tickers reach Tiingo and yfinance in their own spelling

**Defect.** `BF.B` and `BRK.B` are stored with a dot (the SP500 CSV, Alpaca and the
`ohlcv_daily.symbol` column all use the dot). Tiingo and yfinance spell class shares with
a dash (`BRK-B`, `BF-B`) and return nothing for the dotted form, so both
`_single_provider_locked` (rebuild and nightly single-provider update) and
`_fetch_fallback` (seam fallback) see "no settled bars in the window", and the on-demand
`historical_store._fetch_chain` Tiingo/yfinance legs also come back empty.

**Where symbols reach the providers.** Every history path goes through exactly two
adapter functions:

- `app/data/tiingo.py::fetch_historical_candles` — called by `history_backfill._fetch_fallback`,
  `history_backfill._single_provider_locked` and `historical_store._fetch_chain`.
- `app/services/historical_store.py::_yfinance_fetch` — called by the same three.

**Fix.** Translate at the adapter boundary, not in the callers:

- New `app/data/provider_symbols.py` with one pure function
  `dash_class_ticker(symbol: str) -> str` returning `symbol.strip().upper().replace(".", "-")`.
  (A US equity ticker uses `.` only as a share-class separator; index tickers such as
  `^GSPC` are untouched because they contain no dot.)
- `fetch_historical_candles` builds its URL path from `dash_class_ticker(symbol)` and keys
  the governor call on the same provider ticker (the Tiingo budget counts what Tiingo is
  asked for; a dotted and dashed request are one symbol either way).
- `_yfinance_fetch` passes `dash_class_ticker(symbol)` to `yf.download`.
- Neither adapter returns a symbol in its bar dicts, and every caller stores the bars
  under the symbol *it* was given (`hs._store_bars(symbol, …)`), so the stored symbol,
  the `ohlcv_history_state` key and the `notify_bars_changed` key stay `BRK.B`.
- Alpaca is not touched (it accepts and returns the dotted form). `app/data/market.py`'s
  chart/quote yfinance paths are out of scope (not history ingestion); logged as a
  possible follow-up only if they show the same symptom.

**Safety net already in place.** `_single_provider_locked` compares the last five shared
dates against stored rows from another provider (0.5 % tolerance) before writing, and
`update_history`'s seam fallback checks five overlap dates against Alpaca — so a wrong
instrument could not be written silently even if the mapping were wrong.

**Tests (written first, must fail before the fix):**

- `fetch_historical_candles("BRK.B", …)` with `httpx.get` patched: the requested URL path
  is `/tiingo/daily/BRK-B/prices`; `"AAPL"` is unchanged; the governor sees `BRK-B`.
- `_yfinance_fetch("BF.B", …)` with `yfinance.download` patched: called with `"BF-B"`.
- End to end through `history_backfill.rebuild_single_provider("BRK.B", …)` on the
  in-memory SQLite fixture, with only the HTTP / `yf.download` layer faked (answering
  only for `BRK-B`): rebuild succeeds, every stored row and the state row are keyed
  `BRK.B`, and no row exists under `BRK-B`.

## 2. Single-provider failure reasons in the ingest status, and in the log

**Defect.** `ingestion_job.run_ingestion` appends
`"{sym}: single-provider update refused — {exc}"` to the local `errors` list only. The
list is returned in `IngestionResult`, which `start_ingestion_task`'s fire-and-forget task
discards; `GET /api/data/ingest/status` returns `_state`, which has only
`single_provider_failed_symbols`, and the job itself logs nothing for this branch. On
2026-10-16 `O` failed and the reason was unrecoverable.

**Fix.**

- `_state` gains `single_provider_errors: {}` (initial dict and per-run reset, next to
  `rebuild_errors`).
- The `SingleProviderRefused` branch records `_state["single_provider_errors"][sym] = str(exc)`
  and logs `logger.warning("ingestion: single-provider update refused for %s — %s", sym, exc)`.
- `IngestionResult` gains `single_provider_errors: dict[str, str]` (copy of the state dict),
  matching how `rebuild_errors` is returned.
- `GET /api/data/ingest/status` already spreads `get_ingestion_state()`, so the new key is
  exposed without router changes. The router test pins it.

**Tests (first):** a nightly run where a single-provider symbol's provider refuses —
`/api/data/ingest/status` shows `single_provider_errors == {sym: <reason containing the
provider refusal>}` alongside `single_provider_failed_symbols == [sym]`; the warning is in
`caplog`; a following successful run resets the dict to `{}`.

## 3. The nightly run keeps the startup staleness reference fresh

**Defect.** `main.py`'s lifespan decides "DB is stale" from `SPY`'s last stored date, but
neither the nightly universe (`ingestion_scheduler._run_nightly`) nor the startup catch-up
universe (also in `main.py`) contains `SPY` — both expand only SP500 + NDX100 + DOW30
(SPY is an ETF in none of them). `SPY` is refreshed only on demand when the app reads it.
If the app is idle for a few days, `SPY` goes stale; the next restart then runs a full
catch-up — which also does not include `SPY`, so every restart repeats it until something
reads `SPY`.

**Fix (one definition for both places).** In `app/services/ingestion_job.py`:

- `STALENESS_REFERENCE = "SPY"`.
- `ingestion_universe() -> list[str]`: `[STALENESS_REFERENCE]` followed by the deduplicated
  SP500 + NDX100 + DOW30 expansion; if the expansion raises, `[STALENESS_REFERENCE]`
  (today's fallback was already `["SPY"]`). The reference goes first so it is refreshed
  before the Tiingo hourly symbol budget is spent by other single-provider symbols.
- `async def startup_catch_up() -> bool`: reads `_last_stored_date(STALENESS_REFERENCE)`;
  if `_should_ingest(last)` it calls `start_ingestion_task(ingestion_universe(), years=6)`
  (unchanged `years`; `effective_years` already takes the max with the configured horizon)
  and logs the same info line; returns whether a run was started.
- `ingestion_scheduler._run_nightly` calls `start_ingestion_task(ingestion_universe(),
  years=history_years())`.
- `main.py`'s lifespan replaces its inline block with `await startup_catch_up()` inside the
  existing try/except.

Rejected alternatives: adding SPY to a preset (would put an ETF into the SP500 scan
universe); a second nightly job just for SPY (two runs racing for the history lock and the
Tiingo budget, and a second "running" state); changing the reference to an SP500 member
(SPY is also the regime/benchmark series that must stay fresh).

**Tests (first):**

- `_run_nightly` starts ingestion with `["SPY", …preset symbols…]`, SPY first, deduplicated
  (existing `test_nightly_uses_same_retention` updated from `["TEST"]` to `["SPY", "TEST"]` —
  intended behavior change).
- `ingestion_universe()` falls back to `["SPY"]` when expansion raises, and does not
  duplicate SPY if a preset ever contains it.
- `startup_catch_up()` with a stale SPY row starts a run whose universe contains SPY; with a
  fresh SPY row starts nothing.
- End to end on the single-provider ingestion fixture: a nightly-shaped run over
  `ingestion_universe()` (presets faked to one symbol) with `SPY` on `basis_provider="tiingo"`
  and a stale last row brings `SPY`'s last stored date to the latest settled day, after
  which `_should_ingest(last SPY date)` is False.

## Done when

- Tests for each piece fail before and pass after their fix.
- Full backend suite: only the known Windows baseline failures (compared against a
  baseline run of `main` in this worktree before the change).
- Plan audit clean (fresh gate-auditor), then code audit clean (fresh gate-auditor per
  round, cap 3 per stage).
- PR opened referencing #114; not merged.
