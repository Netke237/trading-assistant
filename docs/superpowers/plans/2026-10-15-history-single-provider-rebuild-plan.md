# HISTORY-SINGLE-PROVIDER-REBUILD — implementation plan

Board item / tracking issue: #324 · Branch: `board/history-single-provider-rebuild-570085af` · Decision: Kenneth, chat 2026-10-15, "rebuild each from one provider" (rejected: accept 6 years; loosen the 0.5 % seam tolerance).
Context: #114 (D3 backfill recovery), #230 (MEAS isolation, closed).

## 1. Problem (from the code, not only the issue)

`history_backfill.update_history` is the only nightly writer of `ohlcv_daily`. For every symbol it validates an Alpaca **suffix** (`current`) and, whenever older rows exist or the prefix is missing, a Tiingo→yfinance **prefix** (`_fetch_fallback`). The prefix is accepted only if, on the first five shared Alpaca dates, `fallback close × adj_factor ÷ alpaca close × adj_factor` is within 0.5 % (`accept`, lines 123–134). Otherwise it raises `HistorySeamMismatch` **before any write**, so:

- the symbol's prefix is never restored (76 symbols start 2020-10-12, SPY 2021-07-21), and
- the Alpaca suffix is not written either, so the symbol stops getting new bars (45 traded symbols stuck at 2026-10-09, SPY among them; `main.py` startup uses SPY's last date as the staleness reference, so each restart starts a full ~11 h catch-up).

The mismatches are adjustment-basis differences between providers (0.5–6 %) and real corporate-action treatment differences (CTRA 5.175, CTVA 0.150, …). Inside one provider the series is coherent; the defect is only in **joining** two providers.

## 2. Design

### 2.1 Single-provider basis, recorded per symbol

`ohlcv_history_state` gets two nullable columns:

| column | meaning |
|---|---|
| `basis_provider` String(20) | `NULL` = normal path (Alpaca suffix + optional fallback prefix, unchanged). `'tiingo'` or `'yfinance'` = the symbol's whole retained series comes from that one provider. |
| `basis_rebuilt_at` DateTime(tz) | when the series was last rebuilt/replaced from that provider. |

A symbol with `basis_provider` set **never goes through the seam path again**: `update_history` routes it to the single-provider replace (2.3) with that provider only. This is what keeps a rebuilt symbol current without re-introducing the seam (issue scope "ongoing updates").

### 2.2 The single-provider replace (one function, two callers)

`history_backfill._single_provider_locked(db, symbol, start, end, providers) -> RebuildResult`, called with the symbol's `history_lock` held and an open session. For each provider in `providers`, in order, it:

1. **Fetches the full window** `[start, end]` from that provider only:
   - `tiingo`: `fetch_historical_candles(symbol, start, end + 1 day, strict_adjustments=True)` (goes through the Tiingo governor, so pacing, the symbol budget and 429 retries are respected exactly as today's prefix fetch);
   - `yfinance`: `asyncio.to_thread(hs._yfinance_fetch, symbol, start, end + 1 day)`.
2. **Validates** with the existing `_validated(bars, start, end)` (settled dates only, inside the window, finite positive OHLC and `adj_factor`, no duplicate date, one known source), then additionally:
   - every bar's `source` equals the provider asked (never mixes providers);
   - non-empty;
   - **no internal gap**: no two consecutive dates more than `_MAX_GAP = timedelta(days=7)` calendar days apart (the longest normal market closure since 2009 is 5 days, Hurricane Sandy). This is "covers the window it claims": from its first to its last date.
3. **Identity check** against the existing rows of the symbol in `[start, end]` whose `source` differs from the provider (rows already from this provider are skipped: their identity was checked when they were first written). On the newest `_IDENTITY_DATES = 5` such shared dates:
   - both raw-basis (provider `tiingo` and existing source `alpaca` or `tiingo`): compare **raw** `close` (dividend/split adjustment does not enter, so the 0.5–6 % basis differences that cause the seam refusals cannot cause this one);
   - otherwise (provider `yfinance`, or existing source `yfinance` / `tiingo_legacy` / `NULL`): compare adjusted closes `close × (adj_factor or 1)`;
   - `abs(ratio − 1) > Decimal("0.005")` → reject (wrong security / wrong ticker history). No shared foreign-source dates → nothing to compare, pass.
4. **Never loses a stored date**: every existing **settled** date in `[start, end]` must be in the candidate, else reject (same rule as the existing `required <= candidate` guards). Because the candidate is a superset and is upserted, every existing row in the window is replaced; no `DELETE` is issued.
5. **Writes atomically**: `hs._store_bars(symbol, candidate, db)` (chunked upsert, no commit) must return exactly the candidate's dates; then the state row (created if missing) is set — `basis_provider = provider`, `basis_rebuilt_at = now`, `seam_date = old_source = seam_signature = None`, `floor_requested_start = start`, `floor_date = min(candidate)`, `floor_provider = provider`, `floor_checked_at = now` — and **one** `db.commit()`. Then `notify_bars_changed(symbol)`.
6. On any exception for a provider (fetch error, `RateLimited`, `ProviderUnavailable`, validation, identity, superset), nothing has been written for it (all checks precede `_store_bars`; an exception inside `_store_bars` aborts the uncommitted transaction — call `await db.rollback()` before trying the next provider), the reason is recorded as `"<provider>: <exc>"`, and the next provider is tried. All providers failed → raise `SingleProviderRefused("; ".join(reasons))`. **Refusal leaves the existing rows and state untouched.**

`SingleProviderRefused(ValueError)` is a new exception that deliberately does **not** subclass `HistorySeamMismatch`, so ingestion can tell "seam refused → try a rebuild" from "rebuild/single-provider update refused → report".

`RebuildResult` (frozen dataclass): `provider`, `rows_before` (existing rows in window), `rows_after` (= len(candidate)), `first_date_before` (`date | None`), `first_date_after`, `last_date_after`, `backfilled` (`first_date_before is not None and first_date_after < first_date_before`, or no rows before), `floor_reached` (`first_date_after > start + 7 days`).

Rows older than `start` (outside the window) are not touched here; `run_ingestion` prunes everything older than the same cutoff at the end of the same run (`_prune_old_rows`, unchanged), and every rebuild runs inside `run_ingestion` (2.4).

Callers:

- `rebuild_single_provider(symbol, start, end)` (public): takes `history_lock(symbol)`, opens a session, calls `_single_provider_locked(..., providers=("tiingo", "yfinance"))` — Tiingo first, yfinance only if Tiingo fails (issue scope).
- `update_history` (existing): right after it reads `state` (inside its lock and session, before the Alpaca fetch), if `state is not None and state.basis_provider in {"tiingo", "yfinance"}`: `r = await _single_provider_locked(db, symbol, start, end, (state.basis_provider,))` and return `HistoryUpdateResult(stored=r.rows_after, backfilled=r.backfilled, floor_reached=r.floor_reached, provider=r.provider)`. No Alpaca fetch, no seam, `alpaca_bars` and `force_backfill` ignored. The recorded provider only: a nightly failure does not switch the basis (that would flip a whole series between providers night to night); it raises `SingleProviderRefused`, the rows stay as they are, and an explicit rebuild (2.4) re-chooses Tiingo → yfinance. `HistoryUpdateResult` gains `provider: str | None = None` (`None` on the normal path).

Because `refresh_adjustments` (production branch) calls `update_history(..., force_backfill=True)`, a stale-flagged single-provider symbol is refreshed from its own provider too, with no change to `refresh_adjustments`.

### 2.3 On-demand reads keep the basis

`historical_store._get_bars_locked` (scan-time delta fetch) currently walks Alpaca → Tiingo → yfinance and stores the first non-empty reply. For a single-provider symbol that would append Alpaca rows to a Tiingo series between nightly runs (mixed basis read by scans). Change: `_fetch_chain` gains `providers: tuple[str, ...] = ("alpaca", "tiingo", "yfinance")` and only tries those, in that order; `_get_bars_locked` reads `OhlcvHistoryStateModel` for the symbol and, when `basis_provider` is `tiingo`/`yfinance`, passes `providers=(basis_provider,)`. Normal symbols: unchanged behaviour (same default order).

### 2.4 Triggers and reporting

- **Automatic after a seam refusal** (chosen trigger): in `run_ingestion`, when `update_history` raises `HistorySeamMismatch`, the refusal is still counted exactly as today (`seam_mismatch`, `seam_mismatch_symbols`, `seam_ratios`), then `rebuild_single_provider(sym, fetch_start, fetch_end)` runs once for that symbol in the same pass. Success → recorded as rebuilt with `trigger: "seam_refusal"` and **not** counted in `failed`; refusal → `failed += 1`, an error line `"{sym}: seam mismatch — {seam}; rebuild refused — {reasons}"`, recorded under `rebuild_refused`. Rationale: a refused symbol today gets *no* bars at all; a coherent one-provider series is strictly better, and the next night keeps it current via 2.2's routing. This also fixes future refusals without a manual step.
- **Explicit request flag**: `POST /api/data/ingest` gets `rebuild: bool = False`; `run_ingestion(..., rebuild=True)` calls `rebuild_single_provider` for **every** requested symbol instead of `update_history` (`trigger: "request"`). Used for the internal-gap symbols that are not seam-refused (PSX, CSCO, CTAS, TSCO, LNC) and to move a single-provider symbol back to Tiingo after a yfinance fallback.
- A single-provider symbol whose nightly update is refused (`SingleProviderRefused` from `update_history`) → `failed += 1`, error line `"{sym}: single-provider update refused — …"`, listed in `single_provider_failed_symbols`; never retried as a rebuild in the same pass.
- `alpaca_count` counts only normal-path symbols that had Alpaca bars; `gapfill_count` normal-path symbols without; single-provider updates count in `single_provider_updated`.

New keys in the `_state` reset dict, `get_ingestion_state()` and `IngestionResult`:

| key | value |
|---|---|
| `rebuilt` / `rebuilt_symbols` | count / list |
| `rebuild_details` | `{sym: {"provider", "trigger", "rows_before", "rows_after", "first_date_before", "first_date_after", "last_date_after"}}` (dates ISO strings or `null`) |
| `rebuild_refused` / `rebuild_refused_symbols` / `rebuild_errors` | count / list / `{sym: reasons}` |
| `single_provider_updated` | count |
| `single_provider_failed_symbols` | list |

`GET /api/data/ingest/status` additionally returns `single_provider_symbols`: `{sym: {"provider", "rebuilt_at", "floor_date"}}` read from `ohlcv_history_state` where `basis_provider IS NOT NULL` (via `ingestion_job.single_provider_symbols()`; a DB error yields `{}` and is logged, never a 500). This survives restarts, unlike the in-memory run state.

### 2.5 SPY and the startup catch-up

No change to `main.py`. Once SPY is rebuilt and kept current by 2.2, `_should_ingest(last SPY date)` is false and a restart does not start the full catch-up (acceptance 4). Pinned by a test (T3).

## 3. Tickets (build units; the phase is the audit target)

Python 3.11 only (`backend/.venv` of the main checkout or the prepared venv). `DATABASE_URL` must be **unset** when running tests (conftest then uses its temp SQLite file); tests never touch the live DB. Frontend is not touched; `npm run typecheck` is still run before each commit.

### T1 — history state columns + migration
Files: `backend/app/models/ohlcv_daily.py`, `backend/migrations/versions/<new>_history_basis_provider.py` (revises `a93b8d24f760`, the single head on 2026-10-15), `backend/tests/test_history_basis_migration.py` (new).
- Tests first: (a) on a disposable SQLite file: create `ohlcv_history_state` (the c15d709a26b1 shape) with a row, `stamp a93b8d24f760`, `upgrade <new>` → both columns exist, the old row is intact with `NULL`s; `downgrade a93b8d24f760` → columns gone, row and its other values intact. (b) `alembic heads` shows exactly one head, the new revision.
- Model: `basis_provider = Column(String(20), nullable=True)`, `basis_rebuilt_at = Column(DateTime(timezone=True), nullable=True)`; docstring line saying `basis_provider` set = single-provider series, routed away from the seam path.
- Migration: `op.add_column` ×2; downgrade via `op.batch_alter_table("ohlcv_history_state")` dropping both.
- Commit: `feat(history): record single-provider basis per symbol (HISTORY-SINGLE-PROVIDER-REBUILD T1)`.

### T2 — single-provider replace + routing in `update_history`
Files: `backend/app/services/history_backfill.py`, `backend/tests/test_history_single_provider.py` (new). Blocked by T1.
Tests first (in-memory SQLite factory exactly as `tests/test_history_coherent_backfill.py`; providers patched at `app.data.tiingo.fetch_historical_candles` and `historical_store._yfinance_fetch` — the new code imports `fetch_historical_candles` inside the function, as `_fetch_fallback` does, so that patch target works — `_utcnow` pinned):
1. Seam-refused shape (Alpaca rows from a late start, Tiingo full window with factor 0.9 so the seam would refuse): `rebuild_single_provider` stores the whole Tiingo window, every row `source == "tiingo"`, state `basis_provider == "tiingo"`, seam fields `None`, `floor_date == first Tiingo date`, result counts/dates correct.
2. Tiingo raises / returns `[]` / fails validation → yfinance used, `basis_provider == "yfinance"`.
3. Refusals leave rows and state byte-identical (snapshot before/after): candidate omits an existing settled date; internal gap > 7 days; identity mismatch (Tiingo raw close 2 % off Alpaca raw close on the newest shared dates); mixed source in reply; both providers fail → `SingleProviderRefused` (not a `HistorySeamMismatch`).
4. Identity uses raw closes for Tiingo vs Alpaca: a 5 % `adj_factor` difference with equal raw closes passes.
5. Atomicity: `_store_bars` raising on the second chunk (patch to fail on call 2 with a >500-row window) → no row or state change, and the next provider is tried on a clean session.
6. Routing: after a rebuild, `update_history(sym, start, end, alpaca_bars=<seam-refusing Alpaca bars>)` does **not** raise, does not call `_fetch_fallback` or the Alpaca client, stores the new Tiingo date, returns `provider == "tiingo"`; with `basis_provider == "tiingo"` and Tiingo failing, it raises `SingleProviderRefused` and never calls yfinance.
7. Normal-path regression: a symbol with no `basis_provider` behaves exactly as before (existing `test_history_coherent_backfill.py` and `test_history_floor_and_job.py` stay green unchanged).
8. Locking: `rebuild_single_provider` holds `history_lock(symbol)` (a concurrent `update_history` for the same symbol waits — assert ordering with an `asyncio.Event` in the patched fetch).
- Commit: `feat(history): rebuild a seam-refused symbol from one provider (HISTORY-SINGLE-PROVIDER-REBUILD T2)`.

### T3 — ingestion trigger, request flag, status
Files: `backend/app/services/ingestion_job.py`, `backend/app/routers/ingestion.py`, `backend/tests/test_history_single_provider_ingestion.py` (new). Blocked by T2.
Tests first (same in-memory factory; Alpaca batch patched at `app.services.ingestion_job.fetch_daily_bars_batch` / `get_alpaca_client`; `_prune_old_rows` left real on the in-memory DB):
1. A seam-refusing symbol in `run_ingestion` is counted in `seam_mismatch` **and** rebuilt (`rebuilt_symbols`, `rebuild_details[sym]` with provider/trigger/rows/dates), not in `failed`.
2. **Next normal ingestion** (second `run_ingestion`, new settled day available from Tiingo and Alpaca, Alpaca still seam-incompatible): no `seam_mismatch`, `single_provider_updated == 1`, the new date is stored with `source == "tiingo"` (acceptance 2).
3. Rebuild refused after a seam refusal → `failed == 1`, `rebuild_refused_symbols == [sym]`, rows untouched, error line contains both reasons.
4. `rebuild=True` rebuilds a symbol that is **not** seam-refused (trigger `"request"`).
5. SPY: after (1) with SPY as the symbol and Tiingo serving through the last settled day, `_should_ingest(_last_stored_date("SPY"))` is `False` (acceptance 4).
6. Router: `POST /api/data/ingest {"symbols": ["SPY"], "rebuild": true}` passes `rebuild=True` to `start_ingestion_task`; default is `False`. `GET /api/data/ingest/status` includes `single_provider_symbols` and still returns 200 when that query raises.
- Commit: `feat(ingestion): rebuild seam-refused symbols and report it (HISTORY-SINGLE-PROVIDER-REBUILD T3)`.

### T4 — on-demand reads keep a single-provider basis
Files: `backend/app/services/historical_store.py`, `backend/tests/test_history_single_provider_reads.py` (new). Blocked by T1 (disjoint from T2/T3 files; run after T3 to keep the build sequential).
Tests first:
1. `basis_provider == "tiingo"`, stale DB: `get_bars` calls only Tiingo (Alpaca and yfinance mocks never awaited), stores the delta as `source == "tiingo"`.
2. Tiingo empty for that symbol → no Alpaca fallback, returns stored rows only.
3. No state row / `basis_provider NULL` → order Alpaca → Tiingo → yfinance unchanged (existing `test_historical_store*.py` green).
- Commit: `fix(history): keep a single-provider series on its provider in get_bars (HISTORY-SINGLE-PROVIDER-REBUILD T4)`.

### T5 — coordinator: verify, code audit, PR
Full backend suite (Python 3.11) + frontend typecheck + frontend tests; `git merge origin/main` before code round 1; code audit on `origin/main..HEAD` (cap 3); PR `Closes #324` only for the code — operational acceptance (items 3–4) stays open as below.

## 4. Operational run (NOT in this session — mini PC, live backend only, Kenneth's go-ahead)

1. Deploy the merged code; `alembic upgrade head` (adds two nullable columns; no data change).
2. Restart the live backend. SPY is stale, so the startup catch-up ingests the universe; every seam refusal is now rebuilt automatically (watch `GET /api/data/ingest/status`: `rebuilt`, `rebuild_refused`, `rebuild_errors`).
3. Explicit pass for the remaining list and the gap symbols, after (2) finishes: `POST /api/data/ingest` with `{"symbols": [<77 refused + PSX CSCO CTAS TSCO LNC>], "rebuild": true}`.
4. Record counts, refusals with reasons (delisted symbols → floors), first dates, remaining gaps (SELECT-only) under `docs/superpowers/measurements/`, link from #114 and #324; confirm SPY current and that a further restart logs no catch-up; observe one nightly run with `single_provider_updated > 0` and no seam refusal for rebuilt symbols.

## 5. Risks / residuals (not fixed here)

- A rebuilt symbol stays on its provider; there is no path back to the Alpaca-suffix basis (not needed: the series is coherent). A yfinance-basis symbol stays on yfinance until an explicit `rebuild: true`.
- The nightly single-provider update re-fetches the full window (one Tiingo request per symbol, the same count the prefix fetch already uses).
- Bars after delisting dates (SGEN, ANSS) are not fixed; if the provider lacks dates the store has, the rebuild is refused and reported (by design, never deletes).
