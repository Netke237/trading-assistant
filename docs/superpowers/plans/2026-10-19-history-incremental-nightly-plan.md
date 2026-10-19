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
| `SUFFIX_ONLY` | Alpaca-suffix symbol and **all** trust conditions T1–T6 hold (2.3) | 0 |
| `ADJUSTMENT_CHANGED` | T1–T4 and T6 hold, T5 fails with a **uniform** ratio (2.4) | per decision D1 (0 or 1) |
| `FULL` | any other Alpaca-suffix case: no state row, T1–T4 fail, non-uniform ratio, reference rows' raw closes changed, `force_backfill=True` | 1 (today's path, unchanged code) |
| `DEFER_ALPACA_MISSING` | a symbol with a stored Alpaca suffix whose Alpaca reply is empty tonight (outage, strict-mode omission) | 0 — nothing is written, reported, retried next night (2.5) |
| `SINGLE_PROVIDER_RECENT` | `basis_provider='tiingo'` (2.6) | 1 small request, or 0 when `SINGLE_PROVIDER_CURRENT` |
| `SINGLE_PROVIDER_CURRENT` | `basis_provider='tiingo'` and the newest stored row was fetched at or after `last_settle_boundary(now)` (no new settled bar can exist: weekend/early-Monday nights) | 0 |
| `SINGLE_PROVIDER_FULL` | `basis_provider='yfinance'`, or a Tiingo-only symbol whose recent-window checks fail (2.6) | today's path (yfinance: 0 Tiingo) |

### 2.3 Trust conditions for keeping the stored prefix (`SUFFIX_ONLY`)

Let `current` = tonight's validated Alpaca bars (`_validated(alpaca_bars, start, end)`), `seam = min(current)`, `R` = the first five dates of `current` (the same five dates `update_history` uses as `overlap_end = list(current)[4]`).

- **T1 — state matches.** A state row exists, `basis_provider IS NULL`, `state.seam_date == seam`, `state.old_source in {"tiingo","yfinance"}`, `state.seam_signature` set.
- **T2 — stored prefix is the validated one.** `history_basis.verified_boundary(stored_rows, state.verified_seam())` returns a boundary index (every row before the seam has source `old_source`, every row from the seam on is `alpaca`, all factors finite and positive, and the signature over the pair (last prefix row, seam row) matches — so neither row changed since it was last verified).
- **T3 — prefix complete.** No two consecutive stored dates in `[start, seam]` are more than `_MAX_GAP` (7 days) apart; and either `min(stored) <= start + 7 days`, or `min(stored) == state.floor_date` with `state.floor_provider` set (a provider floor observed by an earlier full fetch; `floor_requested_start <= start` always holds because `start` only moves forward).
- **T4 — every reference date is stored as Alpaca.** All five dates of `R` are stored rows with source `alpaca`, and `current` contains every stored settled Alpaca date (the existing `required <= candidate_dates` rule; if Alpaca dropped a stored date, today's code raises `HistorySeamMismatch` and that stays).
- **T5 — adjustment unchanged.** For each d in R: stored raw close == tonight's raw close at the stored 4-dp precision, and `|f_new(d) / f_stored(d) − 1| <= ADJ_TOL` with `ADJ_TOL = 1e-6`. (Smallest real event: a $0.01 dividend on a $500 stock moves the factor by 2e-5, twenty times the tolerance; repeated identical Alpaca replies give identical factors, so the tolerance only absorbs `Numeric(12,8)` rounding.)
- **T6 — prefix age within the revalidation horizon.** `now − state.floor_checked_at <= REVALIDATE_DAYS` (decision D3; `floor_checked_at` is already set to "now" by every full prefix fetch and is not touched by `SUFFIX_ONLY`, so it is exactly "when the prefix was last fetched and seam-checked"). No migration needed.

`SUFFIX_ONLY` writes tonight's `current` bars (same `_store_bars` call as today), leaves every prefix row untouched (raw, factor, `fetched_at`), recomputes `state.seam_signature` over the stored pair (last prefix row, seam row) after the write exactly as the full path does, keeps `seam_date`/`old_source`/floor fields, commits once, calls `notify_bars_changed`. All inside the existing `history_lock(symbol)` and one transaction, so a reader sees either last night's rows or tonight's, never a mix.

### 2.4 Adjustment change (`ADJUSTMENT_CHANGED`)

T5 fails, raw closes on R are unchanged, and the five ratios `f_new/f_stored` agree with each other within `ADJ_TOL` (one common r ≠ 1 — the signature of a dividend/split after 2020-07). Non-uniform ratios or changed raw closes mean Alpaca corrected its data → `FULL`.

What happens then is **decision D1** (§8):
- **D1-a re-fetch (recommended):** run today's full prefix path (`_fetch_fallback` Tiingo → yfinance, five-date seam check, write prefix + suffix, record seam/floor). One Tiingo request. If both providers fail or the Tiingo budget refuses (§4), **write nothing for the symbol tonight** (writing tonight's re-factored suffix next to the old prefix would put a 1/r step at the seam), report it as `deferred_adjustment`, and put it first in the next night's Tiingo queue.
- **D1-b rescale:** multiply every stored prefix row's `adj_factor` by r (rounded to 8 dp), set those rows' `fetched_at` to now, write the suffix, recompute the signature. Zero requests; the prefix factors become derived values rather than Tiingo's.
- **D1-c hybrid:** D1-b tonight, then a D1-a re-fetch within `REVALIDATE_DAYS` when the budget allows (set `floor_checked_at` back so T6 triggers it).

Expected volume: ~400 dividend payers × 4 ex-dates/year ≈ 6–7 symbols per trading night on average, a few dozen on peak nights.

### 2.5 Missing Alpaca reply (`DEFER_ALPACA_MISSING`)

Today an empty Alpaca reply for a symbol sends it down the full-window fallback (`current` empty → 17-year Tiingo/yfinance fetch that must contain every stored Alpaca date). On an Alpaca outage that turns the whole universe into 438 full Tiingo requests — the 11 h run plus a budget blow-out. New rule: if the symbol has at least one stored `alpaca` row and tonight's Alpaca reply for it is empty, nothing is written; the symbol is reported as `deferred_alpaca_missing` and retried next night. A symbol with no stored rows at all keeps today's full-window path (subject to the budget).

### 2.6 Tiingo-only symbols (`SINGLE_PROVIDER_RECENT`)

The 72 symbols on `basis_provider='tiingo'` have no Alpaca bars to compare against, so their change detection comes from Tiingo's own reply:

1. If `SINGLE_PROVIDER_CURRENT` holds → skip (0 requests). This alone removes two nights a week.
2. Otherwise fetch the recent window `[last_stored − 21 calendar days, end]` from Tiingo only (one request, ~15 rows instead of ~4,270).
3. Validate (`_validated`, single source `tiingo`, no gap > 7 days, raw close of each overlapping stored date within 0.5 % — the existing identity rule).
4. On the overlap dates compute `f_new/f_stored`. All within `ADJ_TOL` of 1 → upsert the window rows only; older rows untouched. Uniform r ≠ 1 → an event inside the window → per D1 (D1-a: a second, full-window request through today's `_single_provider_locked`; D1-b: rescale every stored row dated before the window by r). Non-uniform, identity failure, or validation failure → `SINGLE_PROVIDER_FULL` (today's full-window path, which keeps "any refusal leaves rows and state untouched").

The yfinance-only symbols (14) keep today's full nightly re-download: it costs no Tiingo budget and yfinance stores adjusted prices with factor 1, so the overlap-ratio test would need a different design for no time gain.

What else to do about the 72 is **decision D2** (§8).

### 2.7 Run order and priority (`ingestion_job.run_ingestion`)

Two passes instead of one alphabetical pass:

1. **Pass 1 — no Tiingo.** Alpaca batch (unchanged), then every symbol whose action needs no Tiingo request (`SUFFIX_ONLY`, D1-b/D1-c rescale, `SINGLE_PROVIDER_CURRENT`, yfinance-only, `DEFER_ALPACA_MISSING`). Minutes.
2. **Pass 2 — Tiingo queue, in priority order:** (1) SPY (the staleness reference from #390); (2) last night's `deferred_adjustment` symbols; (3) the other `SINGLE_PROVIDER_RECENT` symbols; (4) `ADJUSTMENT_CHANGED` under D1-a; (5) `FULL`; (6) T6-only revalidations (prefix older than `REVALIDATE_DAYS`, everything else trusted), at most `REVALIDATE_PER_NIGHT` per night and only while the nightly budget share (§4) has room. A budget refusal stops pass 2 for that limit; every symbol not reached keeps last night's rows and is reported `deferred_budget` with the limit's name.

The classification is computed once per symbol at the start of its own write, inside its lock; the queue order only decides *when* each symbol is processed. A symbol whose classification changes between the queue build and its turn (e.g. a manual run in between) is simply classified again.

`force_backfill=True` → every Alpaca-suffix symbol is `FULL`; `rebuild=True` → today's rebuild path. Both unchanged.

### 2.8 What this does to the numbers (the gate)

- `SUFFIX_ONLY` produces exactly the rows the full path would produce when Tiingo returns the same prefix it returned at the last fetch (T2 proves the stored prefix is that reply; T5 proves the seam partner is unchanged). Test 2 in T4 pins this as an equivalence: same provider replies → identical `_read_bars` output from both paths.
- `stale_reasons` stays consistent: prefix rows keep one `fetched_at` batch; the seam step is exempted only through `verified_boundary`, whose signature is recomputed after every write; Alpaca rows carry `div_cash = 0`, so `pre_action_fetch` cannot fire on a kept prefix; a missed event (Tiingo row with `div_cash` after an older row's fetch date) **still** flags the symbol for `refresh_adjustments`, which remains the manual backstop.
- Undetectable residual (stated, not fixed): a Tiingo-side correction of pre-2020 history with no Alpaca-visible change is picked up only at the next T6 revalidation or next adjustment event.

## 3. Expected run time

| Night | Tiingo requests (D1-a) | Tiingo time at 72 s | With D1-b/c |
|---|---:|---:|---:|
| Weekend / early-Monday nights | ~0 | ~0 | ~0 |
| Typical trading night | 72 + ~6 adjusted + revalidations | ~1.6 h | ~1.4 h |
| Peak ex-dividend night | 72 + ~30–40 | ~2.1–2.3 h | ~1.4 h |
| Alpaca outage | 72 (+ deferrals) | ~1.4 h | same |

Pass 1 (Alpaca batch + ~438 suffix upserts) is the same work the current run already does minus the prefix rows; it must be measured on the mini PC (§7). D2's options change the "72".

Monthly distinct Tiingo symbols: 72 + distinct dividend payers re-fetched that month (~130–250 under D1-a) + revalidations — inside 500 with the reserve in §4, which is why T6's revalidation is budget-gated rather than a fixed every-30-days sweep (438 + 72 = 510 would not fit).

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
- **Visible:** `GET /api/data/ingest/status` gains `tiingo_usage` (each limit: `used`, `limit`, `nightly_stop_at`, `window`) and per-run counters `suffix_only`, `adjustment_changed`, `prefix_refetched`, `prefix_rescaled`, `single_provider_recent`, `single_provider_skipped_current`, `revalidated`, `deferred` (`{symbol: reason}`), `tiingo_requests`, `tiingo_bytes`; the data-sources panel shows Tiingo `degraded` with the exhausted limit in its detail; the job logs one summary line. Stage C adds the four meters and last-run summary to Settings → Data (decision D5).
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

### Stage B — incremental writer (backend, ~400 lines + tests)
**B1** `services/history_incremental.py`: `classify_nightly_symbol` and the ratio helpers, pure. Tests: one per row of the 2.2 table and per trust condition T1–T6 failing on its own; uniform vs non-uniform ratio; raw-close change → `FULL`; `ADJ_TOL` boundary (1e-6 passes, 2e-5 fails); seam date moved → `FULL`.
**B2** `services/history_backfill.py`: `update_history` gains the `SUFFIX_ONLY`, `ADJUSTMENT_CHANGED` (per D1) and `DEFER_ALPACA_MISSING` branches before today's code; `_single_provider_locked` gains the recent-window variant (2.6). Tests:
1. `SUFFIX_ONLY`: Tiingo/yfinance mocks never awaited; prefix rows byte-identical (raw, factor, `fetched_at`); suffix rewritten; signature recomputed and `verified_boundary` passes; `stale_reasons` returns None.
2. **Equivalence:** same scenario run through the full path (Tiingo mock returns exactly the stored prefix) and the incremental path on two copies of the DB → identical `_read_bars` output over the whole window.
3. Dividend after 2020-07 (Alpaca factors on R scaled by 0.995, raw unchanged): D1-a → one Tiingo call, seam re-checked, prefix factors equal the new Tiingo reply; D1-b → no call, prefix factors × 0.995, adjusted series continuous across the seam within the seam tolerance.
4. Split (r = 0.25) same as 3.
5. D1-a with Tiingo refused by the budget **and** yfinance failing → no row or state change, `deferred_adjustment`.
6. Alpaca reply empty for a stored symbol → no write, `deferred_alpaca_missing`; for an unstored symbol → today's full-window path.
7. Each T-condition failure → today's full path is taken (spy on `_fetch_fallback`).
8. Tiingo-only: current → no request; recent window, no event → one request with `startDate = last − 21 d`, only window rows rewritten; event inside the window → per D1; identity failure → full-window path; refusal leaves rows and state untouched (snapshot compare).
9. `force_backfill=True` → full path even when trusted.
10. Locking: a concurrent `get_bars` for the same symbol waits for the incremental write (existing `history_lock` test pattern).
**B3** `services/ingestion_job.py`: two passes, priority queue, deferral carry-over (in-memory list + recomputed each night from the classification, so a restart loses only the ordering hint, never data), run counters, summary log line. Tests: pass order (no Tiingo call before pass 1 finishes); SPY first in pass 2; budget refusal stops pass 2 and marks the rest `deferred_budget`; counters; a second run after a dividend night picks the deferred symbol first; existing `test_history_floor_and_job.py` / `test_history_single_provider_ingestion.py` stay green (fixtures patched only where the new branches would reach the network — recorded as a test-only amendment if needed).

### Stage C — Settings → Data line (frontend, ~150 lines + tests) — per D5
**C1** `frontend/lib/api.ts` type for `tiingo_usage` + run counters; a small `TiingoBudget` molecule under the existing Data section (four meters `used / limit`, last run: duration, Tiingo requests, deferred count with reasons). Jest tests for rendering, missing fields (older backend) and the degraded state; `npm run typecheck`.

### Stage D — coordinator: verify, audit, PR (per stage)
Python 3.11 full backend suite, frontend typecheck + jest for C; `git merge origin/main` before each code round 1; code audit per stage (cap 3 each); PR per stage, `Refs #413`.

## 6. Acceptance

1. On a night with no adjustment events, no Alpaca-suffix symbol issues a Tiingo request, and every symbol's adjusted series is identical to what the full path would have stored (B2 test 2; live spot check §7).
2. A dividend or split after 2020-07 is detected from Alpaca's factors with zero extra requests and handled per D1; the seam is never left with a basis step (B2 tests 3–5).
3. Tiingo-only symbols make at most one small request per trading night (two on their own ex-date under D1-a) and none when no new bar can exist.
4. All four Tiingo limits are enforced from the persisted ledger across restarts, with a nightly reserve, and are visible on the status endpoint (and in Settings → Data under D5).
5. `history_years` stays 17; manual `rebuild` / `force_backfill` unchanged; no row is ever deleted except by the existing 17-year prune.

## 7. Operational run (mini PC, live backend, Kenneth's go-ahead; not part of the build)

1. Before deploy, SELECT-only: Tiingo request count, distinct symbols and duration of the last three nightly runs (log lines `ingestion complete`, `history: tiingo window rejected`), and how many prefixes are currently `source='yfinance'` (answers Q0's "quiet fallback" question). Tiingo account page: plan tier and month-to-date usage → `data_providers.tiingo` values.
2. Deploy, `alembic upgrade head` (one new table, no data change), restart.
3. Observe the first trading night: duration, `tiingo_requests`, `suffix_only` ≈ 438 minus adjusted/deferred, `deferred` reasons; first weekend night: ~0 Tiingo requests.
4. Spot check: for five symbols with an ex-date that week, compare `_read_bars` before vs after a manual `force_backfill` run (ratio within 1e-6 on every date) — proves the incremental path left nothing a full run would change.
5. Bar-basis check script (as in the D3 measurement) shows no new `batch_step` / `pre_action_fetch` flags. Record under `docs/superpowers/measurements/`.

## 8. Decisions for Kenneth

- **Q0 — Tiingo plan.** Which Tiingo plan is the account on (free Starter or paid)? Today's nightly usage exceeds the free monthly symbol and bandwidth caps (§1). The answer sets the limits in `data_providers.tiingo`; the build defaults to free-tier numbers.
- **D1 — how to handle a detected dividend/split** (2.4): (a) re-fetch the prefix from Tiingo, re-run the seam check — **recommended**: numbers stay provider values, seam re-validated; costs one request per adjusted symbol (~6/night, tens on peak nights). (b) rescale the stored factors by Alpaca's ratio — zero requests, flat ~1.4 h, but the prefix becomes derived values and Tiingo/Alpaca methodology differences are never re-checked. (c) hybrid — rescale tonight, re-fetch within the revalidation window when budget allows; most code.
- **D2 — the 72 Tiingo-only symbols** (they cost ~1.4 h a trading night on their own):
  - (a) **keep them on Tiingo, one small recent-window request per trading night** (2.6) — in the plan as the baseline; ~1.4 h typical, ~1.6 h when several are ex-dividend under D1-a; zero on weekend nights.
  - (b) (a) plus an **automatic "re-seam" back to the Alpaca-suffix basis** for symbols whose stored Tiingo rows now pass the five-date seam check against Alpaca. This needs **no Tiingo request** (the Tiingo overlap rows are already stored, freshly factored by that night's update), and most of the 72 were rebuilt on request because their stored history started 2020-10-12 (a missing prefix), not because a seam check measured a mismatch, so a large share may qualify. It reverses the "a rebuilt symbol stays on its provider" rule of HISTORY-SINGLE-PROVIDER-REBUILD, so it is your call; it would be a separate follow-up phase, measured first (a SELECT + Alpaca-only script can count how many would pass without touching any data).
  - (c) **Tiingo Power plan** ($30/month per the pricing page): 10,000 requests/hour removes the pacing problem for everything; combinable with (a)/(b).
  - (d) append Alpaca's recent bars onto the Tiingo series — **not recommended**: mixes two providers inside a series the rebuild deliberately made single-provider.
  - (e) update them less often than nightly — **not recommended**: stale bars in scans.
- **D3 — revalidation horizon** (T6): re-fetch a trusted prefix anyway after N days, at most K per night, only within the nightly budget. Recommended N = 90, K = 10. "Never" is possible (rely on adjustment events and the manual `refresh_adjustments`); N = 30 for every symbol does not fit the 500-symbol month.
- **D4 — nightly reserve** (§4): recommended 100 requests/day, 25 symbols/month, 100 MB/month held back for daytime scans.
- **D5 — Stage C UI line** now (recommended: Kenneth reads the app, not the API) or later.

## 9. Overlap with PR #390 and other work

PR #390 (HISTORY-INGEST-GAPS, open) edits `ingestion_job.py` (state keys, `ingestion_universe`, `startup_catch_up`), `ingestion_scheduler.py`, `tiingo.py` (dash class tickers inside `fetch_historical_candles`) and `historical_store.py` (yfinance dash). Stage A edits `tiingo.py`'s `request()` and Stage B edits `ingestion_job.run_ingestion` — the same functions. The build starts from a `main` that contains #390; if #390 is still open when Kenneth approves, Stage A/B wait for it (no rebasing onto an unmerged branch). This plan relies on #390's SPY-first universe for pass 2's priority (1).

No other open claim touches `history_backfill.py`, `ingestion_job.py`, `tiingo.py` or `governor.py` (claims ledger read 2026-10-19).

## 10. Completion milestones for this phase (task-ratings.md)

10 % plan drafted · 20 % plan independently approved · 50 % stage A+B implemented · 70 % regression + local checks pass · 85 % each stage's code audit clean · 95 % PR heads green · 100 % merged and the §7 live run recorded. Stage C counts only if D5 = now.
