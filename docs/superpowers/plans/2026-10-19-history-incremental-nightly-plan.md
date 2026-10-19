# HISTORY-INCREMENTAL-NIGHTLY — incremental nightly daily-bar ingestion

**Tracking issue:** #413 · **Phase id:** `HISTORY-INCREMENTAL-NIGHTLY` · **Status:** plan only (no code in this phase until Kenneth answers §8)
**Depends on:** STOCKS-HORIZON-HISTORY, HISTORY-SINGLE-PROVIDER-REBUILD (both on main); **open PR #390** (`HISTORY-INGEST-GAPS`) must be merged before the build starts (§9).
**Unchanged by this phase:** `scheduling.history_years` = 17 (decision T1-HISTORY-BACKFILL-2026-10-09), the seam tolerance (0.5 % on five shared dates), the single-provider rebuild path and its "never deletes" rule, the 17-year prune, `rebuild=true` / `force_backfill=true` manual runs (they stay full re-fetches).

## 1. Problem, measured from the code

| Item | Where | Today |
|---|---|---|
| Nightly job | `ingestion_scheduler._run_nightly` → `ingestion_job.run_ingestion(universe, years=17)` | runs every calendar day (cron hour/minute only), weekends and holidays included |
| Alpaca step | `fetch_daily_bars_batch(chunk, fetch_start, fetch_end, strict_adjustments=True)`, chunks of 100 | requests the 17-year window; Alpaca answers from 2020-07-27; raw + `adjustment=all` → `adj_factor` per row. Fast; **not** the problem |
| Alpaca-suffix symbols (`basis_provider` NULL, ~438) | `history_backfill.update_history` | `older_required` (stored dates before the seam) is non-empty, so **every night** `_fetch_fallback(symbol, start, overlap_end)` downloads the whole Tiingo prefix (~2009-10 → 2020-08, ~2,700 rows) to re-check the seam and rewrite every prefix row |
| Tiingo-only symbols (`basis_provider='tiingo'`, 72 incl. SPY) | `update_history` → `_single_provider_locked(..., (state.basis_provider,))` | re-downloads the **whole 17-year window** (~4,270 rows) every night |
| yfinance-only symbols (`basis_provider='yfinance'`, 14) | same | full yfinance re-download; no Tiingo cost; out of scope (§2.6) |
| Tiingo pacing | `governor.build_default_governor`: `rate=1/72` per s, `capacity=2`, `SymbolBudget(max_symbols=50, window=3600)` | ~510 Tiingo requests × 72 s ≈ **10.2 h** per night, plus the Alpaca step and writes ≈ 11 h |
| Tiingo limits enforced | governor (in memory, reset by every restart) | only requests/hour (token bucket) and distinct symbols/hour. **Requests/day, distinct symbols/month and bandwidth/month are not tracked anywhere** |

Published Tiingo limits (tiingo.com/about/pricing, read 2026-10-19): Starter (free) 50 requests/hour, 1,000 requests/day, 500 unique symbols/month, 1 GB/month; Power ($30/month) 10,000/hour, 100,000/day, 110,328 symbols/month, 40 GB/month. The page does not say whether "per month" is a calendar month or rolling.

**Finding for Kenneth (Q0, §8):** today's nightly touches ~510 distinct Tiingo symbols every night and downloads roughly 0.5 GB (≈ 1 MB per 17-year reply × 72 + ≈ 0.6 MB per prefix × 438). On the free tier that exceeds the monthly symbol cap (500) on the first night and the monthly bandwidth (1 GB) on the second. Either the account is on a paid tier, or Tiingo is already refusing part of the run and `_fetch_fallback` is quietly filling prefixes from yfinance (it catches every Tiingo exception and tries yfinance). The live logs / Tiingo account page on the mini PC answer this; the plan does not depend on which, because every limit becomes a configured number (§4).

## 2. Design

### 2.1 Why the prefix may be kept (the invariant)

A stored row holds the raw OHLC and `adj_factor` = provider adjClose / close *as of the fetch date* (`OhlcvDailyModel`, `_read_bars` returns raw × `adj_factor`). A new dividend or split with ex-date E multiplies the factor of **every** row dated before E by one common ratio r. The stored prefix (all dated ≤ 2020-07) is therefore still correct tonight if and only if no adjustment event happened since it was fetched — or, equivalently for the seam, if the Alpaca factors on the seam's reference dates (also dated 2020-07) are unchanged.

The seam check already proved, when the prefix was last fetched, that `Tiingo close × factor` equals `Alpaca close × factor` within 0.5 % on the five overlap dates. If tonight's Alpaca raw close **and** factor on those same reference dates equal the stored Alpaca values, and the stored prefix rows are byte-identical to what was validated (the seam signature still verifies), then the validated relationship still holds exactly, and re-downloading the prefix would write the same numbers again. That is the condition under which the plan skips the Tiingo request.

### 2.2 Per-symbol nightly classification (pure function)

New module `backend/app/services/history_incremental.py`, pure (no I/O):

`classify_nightly_symbol(state, stored_rows, alpaca_bars, start, now) -> NightlyAction`

`stored_rows` = the symbol's stored rows in `[start, end]` as `(date, close, adj_factor, split_factor, div_cash, source, fetched_at)` (the `stale_reasons` tuple shape), read inside the symbol's `history_lock` and the writer's transaction, **before** anything is written.

| Action | When | Tiingo requests |
|---|---|---|
| `SUFFIX_ONLY` | Alpaca-suffix symbol, **all** trust conditions T1–T5 hold (2.3), no pending adjustment (2.4) | 0 |
| `ADJUSTMENT_CHANGED` | T1–T4 hold, T5 fails with a **uniform** ratio (2.4) | 1 under D1-a (0 if it falls back to the interim rescale); 0 under D1-b |
| `PREFIX_RECHECK` | T1–T5 hold but the state carries a pending adjustment (2.4, D1-a only) | 1 |
| `REVALIDATE` | `SUFFIX_ONLY` would apply, but the prefix is older than `REVALIDATE_DAYS` (2.3) and this symbol is among tonight's `REVALIDATE_PER_NIGHT` oldest with Tiingo budget room; every other such symbol stays `SUFFIX_ONLY` tonight | 1 |
| `FULL` | any other Alpaca-suffix case: no state row, T1–T4 fail, non-uniform ratio, reference raw closes changed, **empty Alpaca reply** (2.5), `force_backfill=True` | 1 (today's path, unchanged code) |
| `SINGLE_PROVIDER_CURRENT` | `basis_provider='tiingo'` and `state.window_verified_at >= last_settle_boundary(now)` — a nightly single-provider write already ran after the latest boundary at which a new settled bar could exist (weekend/early-Monday nights) | 0 |
| `SINGLE_PROVIDER_RECENT` | `basis_provider='tiingo'`, not current, and the window anchor is usable (2.6) | 1 small request |
| `SINGLE_PROVIDER_FULL` | `basis_provider='yfinance'`, or a Tiingo-only symbol whose anchor is missing/too old or whose recent-window checks fail (2.6) | today's path (yfinance: 0 Tiingo) |

### 2.3 Trust conditions for keeping the stored prefix (`SUFFIX_ONLY`)

Let `current` = tonight's validated Alpaca bars (`_validated(alpaca_bars, start, end)`), `seam = min(current)`, `R` = the first five dates of `current` (the same five dates `update_history` uses as `overlap_end = list(current)[4]`).

- **T1 — state matches.** A state row exists, `basis_provider IS NULL`, `state.seam_date == seam`, `state.old_source in {"tiingo","yfinance"}`, `state.seam_signature` set.
- **T2 — stored prefix is the validated one.** `history_basis.verified_boundary(stored_rows, state.verified_seam())` returns a boundary index (every row before the seam has source `old_source`, every row from the seam on is `alpaca`, all factors finite and positive, and the signature over the pair (last prefix row, seam row) — including both rows' `fetched_at` — matches, so neither row changed since it was last verified).
- **T3 — prefix complete.** No two consecutive stored dates in `[start, seam]` are more than `_MAX_GAP` (7 days) apart; and either `min(stored) <= start + 7 days`, or `min(stored) == state.floor_date` with `state.floor_provider` set (a provider floor observed by an earlier full fetch; `floor_requested_start <= start` always holds because `start` only moves forward).
- **T4 — every reference date is stored as Alpaca.** All five dates of `R` are stored rows with source `alpaca`, and `current` contains every stored settled Alpaca date (the existing `required <= candidate_dates` rule; if Alpaca dropped a stored date, today's code raises `HistorySeamMismatch` and that stays).
- **T5 — adjustment unchanged.** For each d in R: stored raw close == tonight's raw close at the stored 4-dp precision, and `|f_new(d) / f_stored(d) − 1| <= ADJ_TOL` with `ADJ_TOL = 1e-6`. (Smallest real event: a $0.01 dividend on a $500 stock moves the factor by 2e-5, twenty times the tolerance; repeated identical Alpaca replies give identical factors, so the tolerance only absorbs `Numeric(12,8)` rounding.) The reference rows are rewritten only by `update_history` writes: on-demand `get_bars` appends only after the last stored date and heals only legacy provisional rows, and `refresh_adjustments` goes through `force_backfill` (→ `FULL`). So "R unchanged since the last nightly write" is what T5 tests.

**Revalidation (not a trust condition).** `state.floor_checked_at` is set to "now" by every full prefix fetch (`history_backfill.update_history`, the `observed` branch) and by the single-provider writer, and is not touched by `SUFFIX_ONLY`, so it is "when the prefix was last fetched and seam-checked". A symbol whose `floor_checked_at` is older than `REVALIDATE_DAYS` (decision D3) is still trusted and written `SUFFIX_ONLY`; additionally up to `REVALIDATE_PER_NIGHT` of the oldest such symbols are re-fetched (`REVALIDATE`, today's full path) when the Tiingo budget has room. No symbol is ever left without its nightly write because of revalidation.

`SUFFIX_ONLY` writes tonight's `current` bars (same `_store_bars` call as today), leaves every prefix row untouched (raw, factor, `fetched_at`), recomputes `state.seam_signature` over the stored pair (last prefix row, seam row) after the write exactly as the full path does, keeps `seam_date`/`old_source`/floor fields, commits once, calls `notify_bars_changed`. All inside the existing `history_lock(symbol)` and one transaction, so a reader sees either last night's rows or tonight's, never a mix.

### 2.4 Adjustment change (`ADJUSTMENT_CHANGED`, `PREFIX_RECHECK`)

T5 fails, raw closes on R are unchanged, and the five ratios `f_new/f_stored` agree with each other within `ADJ_TOL` (one common `r_A ≠ 1` — the signature of a dividend/split after 2020-07, as Alpaca applied it). Non-uniform ratios or changed raw closes mean Alpaca corrected its data → `FULL`.

Two building blocks:

- **Rescale** (zero requests): multiply every stored prefix row's `adj_factor` by `r_A` (rounded to 8 dp), set those rows' `fetched_at` to now (they are now "factored as of tonight", which keeps `stale_reasons`' `pre_action_fetch`/`batch_step` meanings true), write tonight's suffix, recompute the seam signature; one transaction. Valid for every prefix date because the event's ex-date is after 2020-07, so every prefix row is scaled by the same ratio; for a yfinance prefix (factor 1, adjusted prices) the factor becomes `r_A` and `_read_bars` returns adjusted × `r_A`, which is again correct.
- **Verified re-fetch** (one request): today's full prefix path (`_fetch_fallback` Tiingo → yfinance, five-date seam check, write prefix + suffix, record seam/floor), plus one **new acceptance check** before anything is written: on the last five stored prefix dates, the re-fetched adjusted close (`close × adj_factor`, so a Tiingo↔yfinance switch compares correctly) divided by the stored adjusted close must equal the expected ratio within `EVENT_TOL = max(2e-6, 0.1 × |1 − r_expected|)`, where `r_expected = r_A` for `ADJUSTMENT_CHANGED` and `1` for `PREFIX_RECHECK` (the stored prefix already carries the interim rescale). This rejects a provider that has not yet applied the event (its reply would sit inside the 0.5 % seam tolerance but leave a step). A Tiingo budget refusal keeps today's fallback: `_fetch_fallback` moves to yfinance, which goes through the same seam check and the same acceptance check.

What happens on `ADJUSTMENT_CHANGED` is **decision D1** (§8):
- **D1-a re-fetch first (recommended):** verified re-fetch. If it is refused — both providers fail, the acceptance check rejects the reply (provider lag), or the seam check fails — apply the **rescale as an interim** in the same night (never write tonight's re-factored suffix next to an old prefix, never leave the symbol unwritten), and record `state.pending_adjustment_ratio = r_A`, `pending_adjustment_since = now`, `pending_adjustment_attempts = 0`. A symbol with a pending adjustment is `PREFIX_RECHECK` on later nights (pass 2 priority 2): a verified re-fetch with `r_expected = 1`; success clears the three fields; refusal leaves the rescaled rows (continuous with Alpaca) and increments the attempts. After 5 refused attempts it is reported `adjustment_unconfirmed` and no longer retried until the next event or its revalidation. A seam-check failure on a recheck follows today's rule (seam refusal → single-provider rebuild).
- **D1-b rescale only:** rescale, no request, no pending state. The prefix factors become derived values; Tiingo/Alpaca methodology differences are re-checked only at revalidation.

Expected volume: ~400 dividend payers × 4 ex-dates/year ≈ 6–7 symbols per trading night on average, a few dozen on peak nights.

### 2.5 Missing Alpaca reply

No new deferral: an empty Alpaca reply for a symbol (client unconfigured, batch failure, strict-mode omission) keeps today's behaviour exactly — the full-window fallback, which rewrites every row with current factors (`update_history`, the `else` branch when `current` is empty). The only change is ordering: such symbols are `FULL` and run in pass 2, where the Tiingo budget and its yfinance fallback apply. An Alpaca outage therefore costs Tiingo budget and time as it does today, but never freezes a symbol's factors.

### 2.6 Tiingo-only symbols (`SINGLE_PROVIDER_*`)

The 72 symbols on `basis_provider='tiingo'` have no Alpaca bars to compare against, so their change detection comes from Tiingo's own reply. On-demand `get_bars` asks only Tiingo for them and appends rows after the last stored date with the factors of *its* fetch moment, so the stored rows' `fetched_at` or `max(date)` say nothing about what the nightly verified. Two new state fields, written **only** by the nightly single-provider writer (recent-window or full) and by `rebuild_single_provider`, carry that instead:

- `window_verified_through` (date): the newest date the last nightly write fetched and verified together with the rows before it;
- `window_verified_at` (timestamp): when that write committed.

Steps:

1. `SINGLE_PROVIDER_CURRENT` if `window_verified_at >= last_settle_boundary(now)` → skip (0 requests). Removes two nights a week. An on-demand append cannot satisfy this.
2. `SINGLE_PROVIDER_FULL` if `window_verified_through` is NULL (first night after deploy, or a symbol never written by the new code) or older than 45 calendar days.
3. Otherwise fetch the window `[window_verified_through − 21 calendar days, end]` from Tiingo only (one request, ~20–40 rows instead of ~4,270). The **anchor rows** are the stored rows dated in `[window_verified_through − 21 d, window_verified_through]`: they were written by a nightly in the same verified batch as the rows before them, so they share the older rows' basis. Rows after the anchor (on-demand appends) are inside the window and are all rewritten.
4. Validate (`_validated`, single source `tiingo`, no gap > 7 days, the reply contains every stored settled date in the window, raw close of each anchor row within 0.5 % of the stored raw close).
5. On the anchor rows compute `f_new/f_stored`. All within `ADJ_TOL` of 1 → upsert the window rows only; rows before the window untouched; set `window_verified_through = max(window)`, `window_verified_at = now`. Uniform `r ≠ 1` (an event after the anchor) → under D1-a a second, full-window request through today's `_single_provider_locked` (refused → rescale every row dated before the window by r, rows' `fetched_at` = now, plus the window upsert, as the interim; no pending state needed because the next night's anchor check re-verifies against Tiingo's own reply); under D1-b the rescale. Non-uniform ratios, an identity failure or a validation failure → `SINGLE_PROVIDER_FULL` (today's full-window path, which keeps "any refusal leaves rows and state untouched").

A Tiingo refusal (budget or provider) on any single-provider path behaves as today: `SingleProviderRefused`, rows and state untouched. `get_bars` for these symbols is refused too, so no post-event row can be appended next to unrefreshed ones while Tiingo is unavailable.

The yfinance-only symbols (14) keep today's full nightly re-download: it costs no Tiingo budget and yfinance stores adjusted prices with factor 1, so the overlap-ratio test would need a different design for no time gain.

What else to do about the 72 is **decision D2** (§8).

### 2.7 Run order and priority (`ingestion_job.run_ingestion`)

Two passes instead of one alphabetical pass:

1. **Pass 1 — no Tiingo.** Alpaca batch (unchanged), then every symbol whose action needs no Tiingo request (`SUFFIX_ONLY`, `ADJUSTMENT_CHANGED` under D1-b, `SINGLE_PROVIDER_CURRENT`, yfinance-only). Minutes.
2. **Pass 2 — Tiingo queue, in priority order:** (1) SPY (the staleness reference from #390); (2) `PREFIX_RECHECK`; (3) the other `SINGLE_PROVIDER_RECENT` / `SINGLE_PROVIDER_FULL` symbols; (4) `ADJUSTMENT_CHANGED` under D1-a; (5) `FULL`; (6) `REVALIDATE`, only while the nightly budget share (§4) has room. A Tiingo budget refusal does **not** stop pass 2: each symbol still runs its path, whose fallbacks are today's (prefix paths → yfinance, seam-checked; ADJUSTMENT_CHANGED → interim rescale; single-provider → refused, untouched). Only `REVALIDATE` is skipped when the budget has no room (those symbols were already written `SUFFIX_ONLY`, see 2.3).

The classification is computed once per symbol at the start of its own write, inside its lock; the queue order only decides *when* each symbol is processed. A symbol whose classification changes between the queue build and its turn (e.g. a manual run in between) is simply classified again. All persistent carry-over between nights lives in `ohlcv_history_state` (pending adjustment, window anchor, `floor_checked_at`), so a restart loses nothing.

`force_backfill=True` → every Alpaca-suffix symbol is `FULL`; `rebuild=True` → today's rebuild path (which also sets the window anchor). Both otherwise unchanged.

### 2.8 What this does to the numbers (the gate)

- `SUFFIX_ONLY` produces exactly the rows the full path would produce when Tiingo returns the same prefix it returned at the last fetch (T2 proves the stored prefix is that reply; T5 proves the seam partner is unchanged). B2 test 2 pins this as an equivalence: same provider replies → identical `_read_bars` output from both paths.
- `stale_reasons` stays consistent: prefix rows keep one `fetched_at` batch; the seam step is exempted only through `verified_boundary`, whose signature is recomputed after every write; Alpaca rows carry `div_cash = 0`, so `pre_action_fetch` cannot fire on a kept prefix; a missed event (Tiingo row with `div_cash` after an older row's fetch date) **still** flags the symbol for `refresh_adjustments`, which remains the manual backstop.
- Between nights, on-demand `get_bars` may append rows with post-event factors next to rows that still carry pre-event factors — today's documented residual ("about one dividend", the stale-factor comment in `historical_store.py`). Every nightly path above rewrites those rows: the Alpaca suffix is rewritten whole, and a Tiingo-only window always covers everything after the nightly-verified anchor. No nightly path keys a skip or an overlap on a row an on-demand fetch can write.
- A provider that applies an event later than Alpaca cannot freeze a seam step: the verified re-fetch's acceptance check (2.4) refuses its reply, and the interim rescale plus `PREFIX_RECHECK` keep the series continuous until the provider catches up.
- Undetectable residual (stated, not fixed): a Tiingo-side correction of pre-2020 history with no Alpaca-visible change is picked up only at the next revalidation or next adjustment event.

## 3. Expected run time

| Night | Tiingo requests (D1-a) | Tiingo time at 72 s | With D1-b |
|---|---:|---:|---:|
| Weekend / early-Monday nights | ~0 | ~0 | ~0 |
| Typical trading night | 72 + ~6 adjusted + revalidations | ~1.6 h | ~1.4 h |
| Peak ex-dividend night | 72 + ~30–40 | ~2.1–2.3 h | ~1.4 h |
| Alpaca outage | 72 + up to 438 `FULL` (today's path; the budget then sends the rest to yfinance) | as today, bounded by the budget | same |

Pass 1 (Alpaca batch + ~438 suffix upserts) is the same work the current run already does minus the prefix rows; it must be measured on the mini PC (§7). D2's options change the "72".

Monthly distinct Tiingo symbols: 72 + distinct dividend payers re-fetched that month (~130–250 under D1-a) + revalidations — inside 500 with the reserve in §4, which is why revalidation is budget-gated rather than a fixed every-30-days sweep (438 + 72 = 510 would not fit).

## 4. Tiingo budget: all four limits enforced and visible

New persisted ledger, enforced at the one place every Tiingo history request goes through (`tiingo.fetch_historical_candles` → `get_governor().call("tiingo", request, symbol=...)`).

- **Table** `provider_request_log` (new model in `app/models/provider_usage.py`, new Alembic revision in `backend/migrations/versions/` on top of the then-current head): `id`, `provider`, `requested_at` (tz-aware), `symbol` (nullable), `response_bytes` (body length, uncompressed — at least the transferred size), `status_code`, `caller` (`nightly` / `on_demand` / `probe`). Index on `(provider, requested_at)`.
- **Recorded** inside `request()` — i.e. per HTTP attempt, so the governor's 429 retries are counted — after the response arrives (also for 4xx/5xx). The `/api/test` health probe in `routers/data_sources.py` records too (it is cached; a handful a day).
- **Checked** before each attempt, in one `asyncio.Lock` (single backend process — the deployment runs one uvicorn worker; stated as an assumption) so check-and-record cannot interleave between the nightly and an on-demand scan:
  - requests in the last 60 min `< requests_per_hour`;
  - requests in the last 24 h `< requests_per_day` (rolling — conservative whatever Tiingo's reset hour is);
  - a symbol **not yet seen** in the last 31 days is admitted only if distinct symbols in the last 31 days `< symbols_per_month` (31-day rolling ⊇ any calendar month and any 30-day window — conservative for both readings of "per month");
  - bytes in the last 31 days `< bytes_per_month`.
  - The nightly (`caller="nightly"`) stops at limit − reserve, leaving the reserve for daytime scans; on-demand callers may use the full limit.
- **Refusal** raises the existing `ProviderUnavailable("tiingo <limit> budget exhausted (used/limit)")`, which every caller already handles (`_fetch_fallback` moves to yfinance; `_single_provider_locked` refuses with rows untouched; `get_bars` moves down its chain). The governor's in-memory hourly bucket and symbol budget stay as the pacing layer.
- **Config** in `settings.yaml` (example in `settings.example.yaml`), validated at load with free-tier defaults until Kenneth answers Q0:
  ```yaml
  data_providers:
    tiingo:
      requests_per_hour: 50
      requests_per_day: 1000
      symbols_per_month: 500
      bytes_per_month: 1000000000
      nightly_reserve: {requests_per_day: 100, symbols_per_month: 25, bytes_per_month: 100000000}
  ```
- **Retention:** rows older than 40 days are deleted by the nightly maintenance (`_run_nightly_maintenance`).
- **Visible:** `GET /api/data/ingest/status` gains `tiingo_usage` (each limit: `used`, `limit`, `nightly_stop_at`, `window`) and per-run counters `suffix_only`, `adjustment_changed`, `prefix_refetched`, `prefix_rescaled` (interim or D1-b), `prefix_rechecked`, `adjustment_pending` (`{symbol: since, attempts}`), `adjustment_unconfirmed`, `single_provider_recent`, `single_provider_skipped_current`, `revalidated`, `revalidation_skipped_budget`, `tiingo_requests`, `tiingo_bytes`; the data-sources panel shows Tiingo `degraded` with the exhausted limit in its detail; the job logs one summary line. Stage C adds the four meters and last-run summary to Settings → Data (decision D5).
- **First-month caveat:** the ledger starts empty at deploy and cannot see requests made before it; Tiingo's own account page stays authoritative, and a 429 is still honoured by the governor.

## 5. Build stages and tickets

Each stage is one layer and one PR with its own code audit (audit_rule: one layer or ~500 lines per audit target). Stage B depends on A; C on A (and B for the run counters).

### Stage A — Tiingo usage ledger (backend, ~250 lines + tests)
**A1** `models/provider_usage.py`, migration, `data/tiingo_budget.py` (ledger check/record, config load + validation), `data/tiingo.py` (call it inside `request()`), `routers/data_sources.py` (probe records; degraded detail), `services/ingestion_scheduler.py` (40-day prune), `config/settings.example.yaml`. Tests first (in-memory SQLite, `_utcnow`/clock pinned):
1. Each limit refuses at exactly its limit (hour, rolling 24 h, 31-day distinct with a repeat symbol admitted, 31-day bytes); a refused call sends no HTTP request.
2. Nightly stops at limit − reserve; on-demand continues to the limit.
3. A 429 retry is recorded as two requests; a 4xx is recorded.
4. Concurrent nightly + on-demand calls at limit − 1: exactly one admitted.
5. Refusal surfaces as `ProviderUnavailable` and `_fetch_fallback` falls to yfinance (existing behaviour) — no exception escapes.
6. Invalid config (negative, missing, reserve ≥ limit) → load error names the key; absent block → free-tier defaults.
7. Prune deletes only rows older than 40 days.
**A2** status endpoint `tiingo_usage` + router test (200 even when the ledger query fails, as `single_provider_symbols` does).

### Stage B — incremental writer (backend, ~450 lines + tests)
**B0** `models/ohlcv_daily.py` `OhlcvHistoryStateModel` + one Alembic revision: nullable `window_verified_through` (Date), `window_verified_at` (DateTime tz), `pending_adjustment_ratio` (Numeric(16,12)), `pending_adjustment_since` (DateTime tz), `pending_adjustment_attempts` (Integer). No data change; NULL means "no anchor / nothing pending" and routes to today's full paths. `rebuild_single_provider` and the full single-provider path set the anchor fields.
**B1** `services/history_incremental.py`: `classify_nightly_symbol` and the ratio helpers (`uniform_ratio`, `event_accepted`), pure. Tests: one per row of the 2.2 table and per trust condition T1–T5 failing on its own; pending adjustment → `PREFIX_RECHECK`; revalidation selection (oldest first, capped, never removes the `SUFFIX_ONLY` write); uniform vs non-uniform ratio; raw-close change → `FULL`; empty Alpaca reply → `FULL`; `ADJ_TOL` boundary (1e-6 passes, 2e-5 fails); `EVENT_TOL` boundary; seam date moved → `FULL`; single-provider anchor NULL / older than 45 days → `SINGLE_PROVIDER_FULL`.
**B2** `services/history_backfill.py`: `update_history` gains the `SUFFIX_ONLY`, `ADJUSTMENT_CHANGED` (per D1, with the acceptance check and interim rescale) and `PREFIX_RECHECK` branches before today's code; `_single_provider_locked` gains the anchored recent-window variant (2.6). Tests:
1. `SUFFIX_ONLY`: Tiingo/yfinance mocks never awaited; prefix rows byte-identical (raw, factor, `fetched_at`); suffix rewritten; signature recomputed and `verified_boundary` passes; `stale_reasons` returns None.
2. **Equivalence:** same scenario run through the full path (Tiingo mock returns exactly the stored prefix) and the incremental path on two copies of the DB → identical `_read_bars` output over the whole window.
3. Dividend after 2020-07 (Alpaca factors on R scaled by 0.995, raw unchanged): D1-a → one Tiingo call, seam re-checked, prefix factors equal the new Tiingo reply; D1-b → no call, prefix factors × 0.995, adjusted series continuous across the seam within the seam tolerance.
4. Split (r = 0.25) same as 3.
5. D1-a fallbacks: (i) Tiingo refused by the budget, yfinance passes seam + acceptance → written from yfinance; (ii) both refused → interim rescale written (prefix × r_A, `fetched_at` = now), pending fields set, adjusted series continuous across the seam; (iii) **provider lag**: Tiingo reply has not applied the event (adjusted prefix 0.4 % off Alpaca, inside the 0.5 % seam tolerance) → acceptance check refuses it, interim rescale written; next night with Tiingo caught up → `PREFIX_RECHECK` accepts, pending cleared, prefix = Tiingo reply; Tiingo still lagging 5 nights → `adjustment_unconfirmed`, rows stay the continuous rescaled series.
6. Alpaca reply empty for a stored symbol (and a whole-batch failure) → today's full-window path, every row rewritten with current factors.
7. Each T-condition failure → today's full path is taken (spy on `_fetch_fallback`).
8. Tiingo-only: anchor current → no request; **an on-demand `get_bars` append after the settle boundary** (post-event factor, `fetched_at` after the boundary) → the nightly still fetches the window and, the event being after the anchor, refreshes every older row; **an on-demand 30-day chunk after a 21+ day gap with an event inside it** → the window starts at the anchor, the anchor rows show the ratio, every older row is refreshed (no step at the chunk start); recent window, no event → one request with `startDate = window_verified_through − 21 d`, only window rows rewritten, anchor advanced; anchor NULL / older than 45 days → full-window path; identity failure → full-window path; refusal leaves rows and state untouched (snapshot compare).
9. `force_backfill=True` → full path even when trusted.
10. Locking: a concurrent `get_bars` for the same symbol waits for the incremental write (existing `history_lock` test pattern).
**B3** `services/ingestion_job.py`: two passes, priority queue (all carry-over read from `ohlcv_history_state`), run counters, summary log line. Tests: pass order (no Tiingo call before pass 1 finishes); SPY first in pass 2; a budget refusal mid-pass-2 does not stop the pass — later `FULL` symbols are still written via yfinance and only `REVALIDATE` is skipped; counters; after a restart a pending adjustment is still rechecked first; existing `test_history_floor_and_job.py` / `test_history_single_provider_ingestion.py` stay green (fixtures patched only where the new branches would reach the network — recorded as a test-only amendment if needed).

### Stage C — Settings → Data line (frontend, ~150 lines + tests) — per D5
**C1** `frontend/lib/api.ts` type for `tiingo_usage` + run counters; a small `TiingoBudget` molecule under the existing Data section (four meters `used / limit`, last run: duration, Tiingo requests, pending/unconfirmed adjustments). Jest tests for rendering, missing fields (older backend) and the degraded state; `npm run typecheck`.

### Stage D — coordinator: verify, audit, PR (per stage)
Python 3.11 full backend suite, frontend typecheck + jest for C; `git merge origin/main` before each code round 1; code audit per stage (cap 3 each); PR per stage, `Refs #413`.

## 6. Acceptance

1. On a night with no adjustment events, no Alpaca-suffix symbol issues a Tiingo request, and every symbol's adjusted series is identical to what the full path would have stored (B2 test 2; live spot check §7).
2. A dividend or split after 2020-07 is detected from Alpaca's factors with zero extra requests and handled per D1; neither a provider lag nor a refusal leaves a basis step at the seam or a symbol unwritten (B2 tests 3–5).
2a. No nightly skip or overlap decision is keyed on rows an on-demand `get_bars` can write (B2 test 8).
3. Tiingo-only symbols make at most one small request per trading night (two on their own ex-date under D1-a) and none when no new bar can exist.
4. All four Tiingo limits are enforced from the persisted ledger across restarts, with a nightly reserve, and are visible on the status endpoint (and in Settings → Data under D5).
5. `history_years` stays 17; manual `rebuild` / `force_backfill` unchanged; no row is ever deleted except by the existing 17-year prune.

## 7. Operational run (mini PC, live backend, Kenneth's go-ahead; not part of the build)

1. Before deploy, SELECT-only: Tiingo request count, distinct symbols and duration of the last three nightly runs (log lines `ingestion complete`, `history: tiingo window rejected`), and how many prefixes are currently `source='yfinance'` (answers Q0's "quiet fallback" question). Tiingo account page: plan tier and month-to-date usage → `data_providers.tiingo` values.
2. Deploy, `alembic upgrade head` (one new table and five nullable state columns, no data change), restart. The first trading night takes the full single-provider path for the 72 Tiingo-only symbols (no anchor yet) — one night at today's cost for those.
3. Observe the first trading night: duration, `tiingo_requests`, `suffix_only` ≈ 438 minus adjusted, `adjustment_pending` / `adjustment_unconfirmed`; first weekend night: ~0 Tiingo requests.
4. Spot check: for five symbols with an ex-date that week, compare `_read_bars` before vs after a manual `force_backfill` run (ratio within 1e-6 on every date) — proves the incremental path left nothing a full run would change.
5. Bar-basis check script (as in the D3 measurement) shows no new `batch_step` / `pre_action_fetch` flags. Record under `docs/superpowers/measurements/`.

## 8. Decisions for Kenneth

- **Q0 — Tiingo plan.** Which Tiingo plan is the account on (free Starter or paid)? Today's nightly usage exceeds the free monthly symbol and bandwidth caps (§1). The answer sets the limits in `data_providers.tiingo`; the build defaults to free-tier numbers.
- **D1 — how to handle a detected dividend/split** (2.4): (a) **re-fetch first — recommended**: re-download the prefix, re-run the seam check and check that the provider applied the same event; if it can't (budget, outage, provider not caught up yet), rescale the stored factors by Alpaca's ratio for that night and re-check on later nights. Numbers end as provider values; one request per adjusted symbol (~6/night, tens on peak nights). (b) **rescale only**: zero requests, flat ~1.4 h, but the prefix becomes derived values and Tiingo/Alpaca differences are re-checked only at revalidation. (Round 1 of the audit folded the earlier "hybrid" option into (a): its fallback is the hybrid.)
- **D2 — the 72 Tiingo-only symbols** (they cost ~1.4 h a trading night on their own):
  - (a) **keep them on Tiingo, one small recent-window request per trading night** (2.6) — in the plan as the baseline; ~1.4 h typical, ~1.6 h when several are ex-dividend under D1-a; zero on weekend nights.
  - (b) (a) plus an **automatic "re-seam" back to the Alpaca-suffix basis** for symbols whose stored Tiingo rows now pass the five-date seam check against Alpaca. This needs **no Tiingo request** (the Tiingo overlap rows are already stored and verified current by that night's update), and most of the 72 were rebuilt on request because their stored history started 2020-10-12 (a missing prefix), not because a seam check measured a mismatch, so a large share may qualify. It reverses the "a rebuilt symbol stays on its provider" rule of HISTORY-SINGLE-PROVIDER-REBUILD, so it is your call; it would be a separate follow-up phase, measured first (a SELECT + Alpaca-only script can count how many would pass without touching any data).
  - (c) **Tiingo Power plan** ($30/month per the pricing page): 10,000 requests/hour removes the pacing problem for everything; combinable with (a)/(b).
  - (d) append Alpaca's recent bars onto the Tiingo series — **not recommended**: mixes two providers inside a series the rebuild deliberately made single-provider.
  - (e) update them less often than nightly — **not recommended**: stale bars in scans.
- **D3 — revalidation horizon** (2.3): re-fetch a trusted prefix anyway after N days, at most K per night, only within the nightly budget. Recommended N = 90, K = 10. "Never" is possible (rely on adjustment events and the manual `refresh_adjustments`); N = 30 for every symbol does not fit the 500-symbol month.
- **D4 — nightly reserve** (§4): recommended 100 requests/day, 25 symbols/month, 100 MB/month held back for daytime scans.
- **D5 — Stage C UI line** now (recommended: Kenneth reads the app, not the API) or later.

## 9. Overlap with PR #390 and other work

PR #390 (HISTORY-INGEST-GAPS, open) edits `ingestion_job.py` (state keys, `ingestion_universe`, `startup_catch_up`), `ingestion_scheduler.py`, `tiingo.py` (dash class tickers inside `fetch_historical_candles`) and `historical_store.py` (yfinance dash). Stage A edits `tiingo.py`'s `request()` and Stage B edits `ingestion_job.run_ingestion` — the same functions. The build starts from a `main` that contains #390; if #390 is still open when Kenneth approves, Stage A/B wait for it (no rebasing onto an unmerged branch). This plan relies on #390's SPY-first universe for pass 2's priority (1).

No other open claim touches `history_backfill.py`, `ingestion_job.py`, `tiingo.py` or `governor.py` (claims ledger read 2026-10-19).

## 10. Completion milestones for this phase (task-ratings.md)

10 % plan drafted · 20 % plan independently approved · 50 % stage A+B implemented · 70 % regression + local checks pass · 85 % each stage's code audit clean · 95 % PR heads green · 100 % merged and the §7 live run recorded. Stage C counts only if D5 = now.

## 11. Plan audit log

| Round | Reviewer | Target | Gate findings | Result |
|---|---|---|---:|---|
| 1 (plan 1) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | whole plan at bb0b0ebb vs the code and PR #390's diff | 5 | all fixed in this revision |

Round 1 findings (common root: on-demand `get_bars` writes rows between nights):
- **R1-F1** `SINGLE_PROVIDER_CURRENT` keyed on the newest row's `fetched_at` could be satisfied by an on-demand append after an ex-date → a basis step survives. Fixed: keyed on the new nightly-only `window_verified_at` (2.6 step 1); B2 test 8.
- **R1-F2** Tiingo-only overlap anchored at `last_stored` could sit entirely inside an on-demand chunk → step at the chunk start never repaired. Fixed: overlap anchored at the nightly-only `window_verified_through`, full path when missing or older than 45 days (2.6 steps 2–5); B2 test 8.
- **R1-F3** unbounded `DEFER_ALPACA_MISSING` froze factors under a persistent Alpaca gap. Fixed: removed; an empty Alpaca reply keeps today's full-window path (2.5); B2 test 6.
- **R1-F4** a D1-a re-fetch could accept a Tiingo prefix that has not yet applied the event (inside the 0.5 % seam tolerance) and then freeze it. Fixed: acceptance check against `r_A` with `EVENT_TOL`, interim rescale plus `PREFIX_RECHECK` (2.4); B2 test 5(iii).
- **R1-F5** D1-a "budget refused → write nothing" dropped today's yfinance fallback and could freeze adjusted symbols for weeks. Fixed: the yfinance fallback stays; both refused → interim rescale, never unwritten; a budget refusal no longer stops pass 2 (2.4, 2.7); B2 test 5(i)(ii), B3.

Logged below the gate (not fixed): `REVALIDATE` capacity (now moot: over-cap symbols are written `SUFFIX_ONLY`); 2.6's identity check is a new check, not the existing same-source rule (the plan defines it explicitly); D1-b on Tiingo-only rows now sets `fetched_at` (folded in); coarse Alpaca rounding could hide a sub-0.01 % dividend under `ADJ_TOL` (negligible).
