# HISTORY-INCREMENTAL-NIGHTLY — incremental nightly daily-bar ingestion

**Tracking issue:** #413 · **Phase id:** `HISTORY-INCREMENTAL-NIGHTLY` · **Status:** plan APPROVED (plan round 5 clean, 2026-10-19); no code yet. Kenneth's decisions recorded (§8); build waits for PR #390
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
| `RESCALE` | T1–T4 and T6 hold, T5 fails with a **uniform** ratio that is explained by **new** Alpaca events, each with `F < P(E)` (2.4) | 0 |
| `CONFIRM` | D1-a only: T1–T5 hold, and an Alpaca-visible event E has `F < P(E)` and `today >= E + L` — the prefix was rescaled for E and the provider's lag window is over (2.4) | 1 |
| `REVALIDATE` | `SUFFIX_ONLY` would apply, but the prefix is older than `REVALIDATE_DAYS` (2.3) and this symbol is among tonight's `REVALIDATE_PER_NIGHT` oldest with Tiingo budget room; every other such symbol stays `SUFFIX_ONLY` tonight | 1 |
| `FULL` | any other Alpaca-suffix case: no state row, T1–T4 fail, T6 fails (prefix written inside a lag window), non-uniform ratio, a T5 change not explained by new events fetched-before (2.4), reference raw closes changed, **empty Alpaca reply** (2.5), `force_backfill=True` | 1 (today's path, unchanged code) |
| `SINGLE_PROVIDER_CURRENT` | `basis_provider='tiingo'` and `state.window_verified_at >= last_settle_boundary(now)` — a nightly single-provider write already ran after the latest boundary at which a new settled bar could exist (weekend/early-Monday nights) | 0 |
| `SINGLE_PROVIDER_RECENT` | `basis_provider='tiingo'`, not current, and the window anchor is usable (2.6) | 1 small request |
| `SINGLE_PROVIDER_FULL` | `basis_provider='yfinance'`, or a Tiingo-only symbol whose anchor is missing/too old or whose recent-window checks fail (2.6) | today's path (yfinance: 0 Tiingo) |

### 2.3 Trust conditions for keeping the stored prefix (`SUFFIX_ONLY`)

Let `current` = tonight's validated Alpaca bars (`_validated(alpaca_bars, start, end)`), `seam = min(current)`, `R` = the first five dates of `current` (the same five dates `update_history` uses as `overlap_end = list(current)[4]`). Let `F` = the ET date of `state.floor_checked_at`: every full prefix fetch sets it to "now" (`history_backfill.update_history`, the `observed` branch; the single-provider writer too) and `SUFFIX_ONLY` / `RESCALE` never touch it, so `F` is "the day the stored prefix was last fetched from a provider and seam-checked". Let `E_set` = the **Alpaca-visible event dates**: every date d of `current` whose factor differs from the previous `current` row's by more than `ADJ_TOL` (a dividend/split ex-date after the seam, as Alpaca applies it; rows before an ex-date carry the extra factor), and for each E its step ratio `s(E) = f(row before E) / f(E)`. `P(E)` = the `current` date immediately before E. `L` = `PROVIDER_LAG_DAYS` trading days (weekdays), default 5.

**Why the window opens at `P(E)`, not E (R3-F1).** The nightly runs at 02:00 Europe/Berlin ≈ 20:00 ET of the *previous* ET day, after that day's bar settles (18:00 ET), and Alpaca can apply an ex-date-X adjustment to every row before any bar dated X exists. A prefix fetched that evening has `F = X − 1 = P(X)` and may already sit next to Alpaca factors that carry X while the other provider does not yet. A missing IEX bar on E moves the visible step to a later row E′, but `P(E′)` is still before the true ex-date. So every comparison below uses `P(E)`.

- **T1 — state matches.** A state row exists, `basis_provider IS NULL`, `state.seam_date == seam`, `state.old_source in {"tiingo","yfinance"}`, `state.seam_signature` set.
- **T2 — stored prefix is the validated one.** `history_basis.verified_boundary(stored_rows, state.verified_seam())` returns a boundary index (every row before the seam has source `old_source`, every row from the seam on is `alpaca`, all factors finite and positive, and the signature over the pair (last prefix row, seam row) — including both rows' `fetched_at` — matches, so neither row changed since it was last verified).
- **T3 — prefix complete.** No two consecutive stored dates in `[start, seam]` are more than `_MAX_GAP` (7 days) apart; and either `min(stored) <= start + 7 days`, or `min(stored) == state.floor_date` with `state.floor_provider` set (a provider floor observed by an earlier full fetch; `floor_requested_start <= start` always holds because `start` only moves forward).
- **T4 — every reference date is stored as Alpaca.** All five dates of `R` are stored rows with source `alpaca`, and `current` contains every stored settled Alpaca date (the existing `required <= candidate_dates` rule; if Alpaca dropped a stored date, today's code raises `HistorySeamMismatch` and that stays).
- **T5 — adjustment unchanged.** For each d in R: stored raw close == tonight's raw close at the stored 4-dp precision, and `|f_new(d) / f_stored(d) − 1| <= ADJ_TOL` with `ADJ_TOL = 1e-6`. (Smallest real event: a $0.01 dividend on a $500 stock moves the factor by 2e-5, twenty times the tolerance; repeated identical Alpaca replies give identical factors, so the tolerance only absorbs `Numeric(12,8)` rounding.) The reference rows are rewritten only by `update_history` writes: on-demand `get_bars` appends only after the last stored date and heals only legacy provisional rows, and `refresh_adjustments` goes through `force_backfill` (→ `FULL`). So "R unchanged since the last nightly write" is what T5 tests.
- **T6 — prefix not fetched inside a provider-lag window.** No E in `E_set` has `P(E) <= F < E + L`. A prefix fetched on or after the evening before an ex-date (`P(E)`), but before L trading days after the ex-date have passed, may come from a provider that has not yet applied that event — its adjusted prefix can sit up to 0.5 % off Alpaca and still pass the seam check. Such a prefix is never trusted: the symbol stays `FULL` (today's nightly re-fetch, which is today's repair for exactly this case) every night until a fetch lands at `F >= E + L`. B1 pins the boundaries: `F = P(E) − 1` trading day → trusted; `F = P(E)` (the 20:00-ET fetch the evening before the ex-date) → `FULL`; `F = E + L − 1` → `FULL`; `F = E + L` → trusted; a missing bar on E → the window opens at `P(E′)`. This applies to every path that fetches a prefix — `FULL` for any reason, `REVALIDATE`, `force_backfill`, the empty-Alpaca full window, `CONFIRM`, and the prefix today's code stored the night before deploy.

**Revalidation (not a trust condition).** A symbol whose `floor_checked_at` is older than `REVALIDATE_DAYS` (decision D3) is still trusted and written `SUFFIX_ONLY`; additionally up to `REVALIDATE_PER_NIGHT` of the oldest such symbols are re-fetched (`REVALIDATE`, today's full path) when the Tiingo budget has room. No symbol is ever left without its nightly write because of revalidation.

`SUFFIX_ONLY` writes tonight's `current` bars (same `_store_bars` call as today), leaves every prefix row untouched (raw, factor, `fetched_at`), recomputes `state.seam_signature` over the stored pair (last prefix row, seam row) after the write exactly as the full path does, keeps `seam_date`/`old_source`/floor fields, commits once, calls `notify_bars_changed`. All inside the existing `history_lock(symbol)` and one transaction, so a reader sees either last night's rows or tonight's, never a mix.

### 2.4 Adjustment change (`RESCALE`, `CONFIRM`)

T5 fails, raw closes on R are unchanged, and the five ratios `f_new/f_stored` agree with each other within `ADJ_TOL` (one common `r_A ≠ 1` — a dividend/split after the seam, as Alpaca applied it). Non-uniform ratios or changed raw closes mean Alpaca corrected its data → `FULL`.

**Which events are new.** The stored Alpaca suffix rows were all written by one nightly write, so their factor steps give last night's event set with its step ratios. The **new events** N are the dates in tonight's `E_set` that are absent from the stored steps, or whose step ratio changed by more than `ADJ_TOL`. `RESCALE` is allowed only when (i) N is non-empty, (ii) the product of the new events' step ratios (for a changed step, new over old) equals `r_A` within `ADJ_TOL`, and (iii) **every** new event has `F < P(E)` — the prefix was fetched before the evening on which any provider could have applied it, so it certainly does not contain it. Any other T5 change → `FULL`. Condition (iii) closes the case where the other provider applied an event *before* Alpaca: the stored prefix then already carries it, and a rescale would apply it twice; the re-fetch instead seam-checks the prefix against Alpaca's now-adjusted rows.

**`RESCALE`** (both D1 options, zero requests, the event night): multiply every stored prefix row's `adj_factor` by `r_A` (rounded to 8 dp), set those rows' `fetched_at` to now (they are now "factored as of tonight", which keeps `stale_reasons`' `pre_action_fetch`/`batch_step` meanings true), write tonight's suffix, recompute the seam signature; one transaction; `floor_checked_at` (F) is **not** changed — no provider was asked. Valid for every prefix date because the ex-date is after the seam, so every prefix row is scaled by the same ratio; for a yfinance prefix (factor 1, adjusted prices) the factor becomes `r_A` and `_read_bars` returns adjusted × `r_A`, again correct. Because the rescale uses Alpaca's own ratio on a prefix fetched before the event's window, the prefix stays continuous with the Alpaca suffix whatever any other provider's timing — no lag exposure. Several events before a confirmation compose (each night's `r_A` is relative to the stored rows).

**`CONFIRM`** (D1-a only, one request, L trading days later): when an event E has `F < P(E)` (the prefix predates E's window, so it was rescaled for it) and `today >= E + L`, run today's full prefix path (`_fetch_fallback` Tiingo → yfinance, five-date seam check, write prefix + suffix, record seam/floor, F = today ≥ E + L). The provider's own factors then replace the derived ones after its lag window. If the providers return no usable reply (`_fetch_fallback` returns `[]` — budget refusal on both, outage), `CONFIRM` degrades to `SUFFIX_ONLY` for the night (the rescaled prefix is still trusted by T1–T6) and is tried again the next night; a seam mismatch on a real reply follows today's rule (seam refusal → single-provider rebuild). The same "no usable reply → `SUFFIX_ONLY`" rule applies to `REVALIDATE`. A Tiingo budget refusal alone keeps today's fallback to yfinance.

What differs between the D1 options (§8) is only `CONFIRM`: **D1-a** rescale on the event night, then one provider re-fetch L trading days later (provider values in the end; one request per event); **D1-b** rescale only (derived factors until revalidation). T6 applies under both.

Expected volume: ~400 dividend payers × 4 ex-dates/year ≈ 6–7 events per trading night on average, a few dozen on peak nights — each one `RESCALE` that night and, under D1-a, one `CONFIRM` L trading days later.

### 2.5 Missing Alpaca reply

No new deferral: an empty Alpaca reply for a symbol (client unconfigured, batch failure, strict-mode omission) keeps today's behaviour exactly — the full-window fallback, which rewrites every row with current factors (`update_history`, the `else` branch when `current` is empty). The only change is ordering: such symbols are `FULL` and run in pass 2, where the Tiingo budget and its yfinance fallback apply. An Alpaca outage therefore costs Tiingo budget and time as it does today, but never freezes a symbol's factors. (Such a write clears the seam, so the next night with an Alpaca reply fails T1 and is `FULL` again; T6 then governs when the prefix becomes trusted.)

### 2.6 Tiingo-only symbols (`SINGLE_PROVIDER_*`)

The 72 symbols on `basis_provider='tiingo'` have no Alpaca bars to compare against, so their change detection comes from Tiingo's own reply. On-demand `get_bars` asks only Tiingo for them and appends rows after the last stored date with the factors of *its* fetch moment, so the stored rows' `fetched_at` or `max(date)` say nothing about what the nightly verified. Two new state fields, written **only** by the nightly single-provider writer (recent-window or full) and by `rebuild_single_provider`, carry that instead:

- `window_verified_through` (date): the newest date the last nightly write fetched and verified together with the rows before it;
- `window_verified_at` (timestamp): when that write committed.

Steps:

1. `SINGLE_PROVIDER_CURRENT` if `window_verified_at >= last_settle_boundary(now)` → skip (0 requests). Removes two nights a week. An on-demand append cannot satisfy this.
2. `SINGLE_PROVIDER_FULL` if `window_verified_through` is NULL (first night after deploy, or a symbol never written by the new code) or older than 45 calendar days.
3. Otherwise fetch the window `[window_verified_through − 21 calendar days, end]` from Tiingo only (one request, ~20–40 rows instead of ~4,270). The **anchor rows** are the stored rows dated in `[window_verified_through − 21 d, window_verified_through]`: they were written by a nightly in the same verified batch as the rows before them, so they share the older rows' basis. Rows after the anchor (on-demand appends) are inside the window and are all rewritten.
4. Validate (`_validated`, single source `tiingo`, no gap > 7 days, the reply contains every stored settled date in the window, raw close of each anchor row within 0.5 % of the stored raw close).
5. On the anchor rows compute `f_new/f_stored`. All within `ADJ_TOL` of 1 → upsert the window rows only; rows before the window untouched; set `window_verified_through = max(window)`, `window_verified_at = now`. Uniform `r ≠ 1` (an event after the anchor, as Tiingo itself applied it — one provider, so no cross-provider lag) → under D1-a a second, full-window request through today's `_single_provider_locked` (refused → rescale every row dated before the window by r, those rows' `fetched_at` = now, plus the window upsert and anchor advance, as the fallback; the series is then Tiingo's own reply plus Tiingo's own ratio); under D1-b the rescale. Non-uniform ratios, an identity failure or a validation failure → `SINGLE_PROVIDER_FULL` (today's full-window path, which keeps "any refusal leaves rows and state untouched").

A Tiingo refusal (budget or provider) on a single-provider fetch otherwise behaves as today: `SingleProviderRefused`, rows and state untouched. On-demand rows appended meanwhile (the daytime reserve may still admit `get_bars`) are inside the next successful nightly window and are rewritten then — the same one-dividend residual as today.

The yfinance-only symbols (14) keep today's full nightly re-download: it costs no Tiingo budget and yfinance stores adjusted prices with factor 1, so the overlap-ratio test would need a different design for no time gain.

What else to do about the 72 is **decision D2** (§8).

### 2.7 Run order and priority (`ingestion_job.run_ingestion`)

Two passes instead of one alphabetical pass:

1. **Pass 1 — no Tiingo.** Alpaca batch (unchanged), then every symbol whose action needs no Tiingo request (`SUFFIX_ONLY`, `RESCALE`, `SINGLE_PROVIDER_CURRENT`, yfinance-only). Minutes.
2. **Pass 2 — Tiingo queue, in priority order:** (1) SPY (the staleness reference from #390); (2) the other `SINGLE_PROVIDER_RECENT` / `SINGLE_PROVIDER_FULL` symbols; (3) `FULL`; (4) `CONFIRM`; (5) `REVALIDATE`, only while the nightly budget share (§4) has room. A Tiingo budget refusal does **not** stop pass 2: each symbol still runs its path, whose fallbacks are today's (prefix paths → yfinance, seam-checked; `CONFIRM`/`REVALIDATE` with no usable reply → `SUFFIX_ONLY`; single-provider → refused, untouched). Only `REVALIDATE` is skipped when the budget has no room (those symbols were already written `SUFFIX_ONLY`, see 2.3).

The classification is computed once per symbol at the start of its own write, inside its lock; the queue order only decides *when* each symbol is processed. A symbol whose classification changes between the queue build and its turn (e.g. a manual run in between) is simply classified again. All carry-over between nights is derived from stored rows and `ohlcv_history_state` (`floor_checked_at`, the window anchor) plus tonight's Alpaca reply, so a restart loses nothing.

`force_backfill=True` → every Alpaca-suffix symbol is `FULL`; `rebuild=True` → today's rebuild path (which also sets the window anchor). Both otherwise unchanged.

### 2.8 What this does to the numbers (the gate)

- `SUFFIX_ONLY` produces exactly the rows the full path would produce when Tiingo returns the same prefix it returned at the last fetch (T2 proves the stored prefix is that reply; T5 proves the seam partner is unchanged). B2 test 2 pins this as an equivalence: same provider replies → identical `_read_bars` output from both paths.
- `stale_reasons` stays consistent: prefix rows keep one `fetched_at` batch (a rescale moves the whole prefix to one new batch); the seam step is exempted only through `verified_boundary`, whose signature is recomputed after every write; Alpaca rows carry `div_cash = 0`, so `pre_action_fetch` cannot fire on a kept prefix; a missed event (Tiingo row with `div_cash` after an older row's fetch date) **still** flags the symbol for `refresh_adjustments`, which remains the manual backstop.
- Between nights, on-demand `get_bars` may append rows with post-event factors next to rows that still carry pre-event factors — today's documented residual ("about one dividend", the stale-factor comment in `historical_store.py`). Every nightly path above rewrites those rows: the Alpaca suffix is rewritten whole, and a Tiingo-only window always covers everything after the nightly-verified anchor. No nightly path keys a skip or an overlap on a row an on-demand fetch can write.
- Provider lag: a prefix fetched inside an Alpaca-visible event's lag window is never trusted (T6), so it is re-fetched every night exactly as today until the window has passed; a prefix that predates the event follows Alpaca's own ratio (`RESCALE`) and is replaced by the provider's reply only after the window (`CONFIRM`). **Accepted residual** (decision `HISTORY-INCREMENTAL-LAG-RESIDUAL-2026-10-19`, Kenneth): a provider whose lag exceeds L trading days, re-fetched at `E + L` (by `CONFIRM`, T6's last `FULL`, or a revalidation), can still store a prefix up to 0.5 % off — the seam tolerance today's code accepts too — and it then stays until the next event, revalidation or manual refresh. This is **worse than today** for that case (today's nightly re-fetch repairs it the night the provider catches up); Kenneth accepted it as the price of not re-downloading every night. The same applies, symmetrically, to Alpaca applying an event more than L trading days after the other provider. `PROVIDER_LAG_DAYS` is configurable; raising it costs no extra requests under D1-a (one `CONFIRM` per event), only more `FULL` nights for prefixes fetched inside a window.
- Undetectable residual (stated, not fixed): a Tiingo-side correction of pre-2020 history with no Alpaca-visible change is picked up only at the next revalidation or next adjustment event.

## 3. Expected run time

| Night | Tiingo requests (D1-a) | Tiingo time at 72 s | With D1-b |
|---|---:|---:|---:|
| Weekend / early-Monday nights | ~0 | ~0 | ~0 |
| Typical trading night | 72 + ~6 `CONFIRM` + revalidations | ~1.6 h | ~1.4 h |
| Peak ex-dividend night | 72 + ~30–40 | ~2.1–2.3 h | ~1.4 h |
| Alpaca outage | 72 + up to 438 `FULL` (today's path; the budget then sends the rest to yfinance) | as today, bounded by the budget | same |

Pass 1 (Alpaca batch + ~438 suffix upserts) is the same work the current run already does minus the prefix rows; it must be measured on the mini PC (§7). D2's options change the "72".

Monthly distinct Tiingo symbols: 72 + distinct dividend payers confirmed that month (~130–250 under D1-a) + revalidations — inside 500 with the reserve in §4, which is why revalidation is budget-gated rather than a fixed every-30-days sweep (438 + 72 = 510 would not fit).

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
- **Visible:** `GET /api/data/ingest/status` gains `tiingo_usage` (each limit: `used`, `limit`, `nightly_stop_at`, `window`) and per-run counters `suffix_only`, `adjustment_changed`, `prefix_refetched`, `prefix_rescaled`, `prefix_confirmed`, `confirm_retry` (no usable reply, written `SUFFIX_ONLY`), `lag_window_full` (T6), `single_provider_recent`, `single_provider_skipped_current`, `revalidated`, `revalidation_skipped_budget`, `tiingo_requests`, `tiingo_bytes`; the data-sources panel shows Tiingo `degraded` with the exhausted limit in its detail; the job logs one summary line. Stage C adds the four meters and last-run summary to Settings → Data (decision D5).
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
**B0** `models/ohlcv_daily.py` `OhlcvHistoryStateModel` + one Alembic revision: nullable `window_verified_through` (Date), `window_verified_at` (DateTime tz). No data change; NULL means "no anchor" and routes to today's full path. `rebuild_single_provider` and the full single-provider path set them; the test-only `refresh_adjustments(fetch=...)` branch clears them with the other state fields.
**B1** `services/history_incremental.py`: `classify_nightly_symbol` and the helpers (`uniform_ratio`, `alpaca_event_dates`, `lag_exposed`), pure. Tests: one per row of the 2.2 table and per trust condition T1–T6 failing on its own; T6 at `F = P(E) − 1` (trusted), `P(E)` at 20:00 ET (lag-exposed), `E`, `E + L − 1`, `E + L` (trading days, weekend in between), and with the bar on E missing; new-event detection against the stored suffix steps (new step, changed step, unchanged steps ignored); `RESCALE` refused → `FULL` when a new event has `F >= P(E)` (the other provider led Alpaca) or the step-ratio product disagrees with `r_A`; **condition (iii) isolated (R4-F1)** — fixtures that keep T1–T6 true so that only (iii) can refuse, and that fail if (iii) is removed: (a) Alpaca's step at X first appears on a night with `F = X + L + 1` (Alpaca applied the dividend late; the prefix, fetched by a `REVALIDATE` after the other provider applied it, already carries it) → `FULL`, not `RESCALE`, and no prefix factor is multiplied; (b) Alpaca changes the ratio of an old step E with `F >> E + L` → `FULL`; `CONFIRM` only under D1-a, only for `F < P(E)` and only once `today >= E + L`; two events before a confirmation; revalidation selection (oldest first, capped, never removes the `SUFFIX_ONLY` write); uniform vs non-uniform ratio; raw-close change → `FULL`; empty Alpaca reply → `FULL`; `ADJ_TOL` boundary (1e-6 passes, 2e-5 fails); seam date moved → `FULL`; single-provider anchor NULL / older than 45 days → `SINGLE_PROVIDER_FULL`.
**B2** `services/history_backfill.py`: `update_history` gains the `SUFFIX_ONLY`, `RESCALE` and `CONFIRM`/`REVALIDATE` (no usable reply → `SUFFIX_ONLY`) branches before today's code; `_single_provider_locked` gains the anchored recent-window variant (2.6). Tests:
1. `SUFFIX_ONLY`: Tiingo/yfinance mocks never awaited; prefix rows byte-identical (raw, factor, `fetched_at`); suffix rewritten; signature recomputed and `verified_boundary` passes; `stale_reasons` returns None.
2. **Equivalence:** same scenario run through the full path (Tiingo mock returns exactly the stored prefix) and the incremental path on two copies of the DB → identical `_read_bars` output over the whole window.
3. Dividend after 2020-07 (Alpaca factors on R scaled by 0.995, raw unchanged): event night → no provider call, prefix factors × 0.995 and `fetched_at` = now, F unchanged, adjusted series continuous across the seam; under D1-a, L trading days later → one `CONFIRM` call, prefix = the provider reply, F = that day; under D1-b → no call ever.
4. Split (r = 0.25) same as 3; a yfinance prefix (factor 1) same as 3.
5. **Provider lag (R1-F4, R2-F1):** (i) a `FULL` night (T1 failure, and separately an empty-Alpaca night) inside an event's lag window stores a lagging Tiingo prefix 0.4 % off (passes the 0.5 % seam) → every following night is `FULL` (T6) until `F >= E + L`; with Tiingo caught up on night E + 2, the stored prefix equals the caught-up reply from that night on, and on night E + L it becomes `SUFFIX_ONLY` with no step; (ii) the prefix stored by today's code the night before deploy, inside a lag window → same; (iii) `CONFIRM` with Tiingo budget-refused and yfinance passing → written from yfinance; with both returning nothing → `SUFFIX_ONLY` that night, rescaled prefix kept, `CONFIRM` again the next night; with a seam mismatch on a real reply → today's seam-refusal rule.
6. Alpaca reply empty for a stored symbol (and a whole-batch failure) → today's full-window path, every row rewritten with current factors; the next night with an Alpaca reply is `FULL` (seam cleared) and T6 then applies.
7. Each T-condition failure → today's full path is taken (spy on `_fetch_fallback`).
8. Tiingo-only: anchor current → no request; **an on-demand `get_bars` append after the settle boundary** (post-event factor, `fetched_at` after the boundary) → the nightly still fetches the window and, the event being after the anchor, refreshes every older row; **an on-demand 30-day chunk after a 21+ day gap with an event inside it** → the window starts at the anchor, the anchor rows show the ratio, every older row is refreshed (no step at the chunk start); recent window, no event → one request with `startDate = window_verified_through − 21 d`, only window rows rewritten, anchor advanced; anchor NULL / older than 45 days → full-window path; identity failure → full-window path; refusal leaves rows and state untouched (snapshot compare).
9. `force_backfill=True` → full path even when trusted.
10. Locking: a concurrent `get_bars` for the same symbol waits for the incremental write (existing `history_lock` test pattern).
**B3** `services/ingestion_job.py`: two passes, priority queue (all carry-over read from `ohlcv_history_state`), run counters, summary log line. Tests: pass order (no Tiingo call before pass 1 finishes); SPY first in pass 2; a budget refusal mid-pass-2 does not stop the pass — later `FULL` symbols are still written via yfinance, `CONFIRM` falls back to `SUFFIX_ONLY`, and only `REVALIDATE` is skipped; counters; after a restart a due `CONFIRM` is still found (derived from F and tonight's Alpaca factors); existing `test_history_floor_and_job.py` / `test_history_single_provider_ingestion.py` stay green (fixtures patched only where the new branches would reach the network — recorded as a test-only amendment if needed).

### Stage C — Settings → Data line (frontend, ~150 lines + tests) — per D5
**C1** `frontend/lib/api.ts` type for `tiingo_usage` + run counters; a small `TiingoBudget` molecule under the existing Data section (four meters `used / limit`, last run: duration, Tiingo requests, rescaled / confirmed / lag-window counts). Jest tests for rendering, missing fields (older backend) and the degraded state; `npm run typecheck`.

### Stage D — coordinator: verify, audit, PR (per stage)
Python 3.11 full backend suite, frontend typecheck + jest for C; `git merge origin/main` before each code round 1; code audit per stage (cap 3 each); PR per stage, `Refs #413`.

## 6. Acceptance

1. On a night with no adjustment events, no Alpaca-suffix symbol issues a Tiingo request, and every symbol's adjusted series is identical to what the full path would have stored (B2 test 2; live spot check §7).
2. A dividend or split after 2020-07 is detected from Alpaca's factors with zero extra requests and rescaled the same night; a prefix fetched inside a provider-lag window is re-fetched nightly as today until the window has passed; no refusal leaves a symbol unwritten (B2 tests 3–5).
2a. No nightly skip or overlap decision is keyed on rows an on-demand `get_bars` can write (B2 test 8).
3. Tiingo-only symbols make at most one small request per trading night (two on their own ex-date under D1-a) and none when no new bar can exist.
4. All four Tiingo limits are enforced from the persisted ledger across restarts, with a nightly reserve, and are visible on the status endpoint (and in Settings → Data under D5).
5. `history_years` stays 17; manual `rebuild` / `force_backfill` unchanged; no row is ever deleted except by the existing 17-year prune.

## 7. Operational run (mini PC, live backend, Kenneth's go-ahead; not part of the build)

1. Before deploy, SELECT-only: Tiingo request count, distinct symbols and duration of the last three nightly runs (log lines `ingestion complete`, `history: tiingo window rejected`), and how many prefixes are currently `source='yfinance'` (answers Q0's "quiet fallback" question). Tiingo account page: plan tier and month-to-date usage → `data_providers.tiingo` values.
2. Deploy, `alembic upgrade head` (one new table and two nullable state columns, no data change), restart. The first trading night takes the full single-provider path for the 72 Tiingo-only symbols (no anchor yet) — one night at today's cost for those.
3. Observe the first trading night: duration, `tiingo_requests`, `suffix_only` ≈ 438 minus rescaled/confirmed/`lag_window_full`; first weekend night: ~0 Tiingo requests.
4. Spot check: for five symbols with an ex-date that week, compare `_read_bars` before vs after a manual `force_backfill` run (ratio within 1e-6 on every date) — proves the incremental path left nothing a full run would change.
5. Bar-basis check script (as in the D3 measurement) shows no new `batch_step` / `pre_action_fetch` flags. Record under `docs/superpowers/measurements/`.

## 8. Decisions for Kenneth — DECIDED 2026-10-19

Kenneth, in chat, 2026-10-19: accepted the provider-lag residual (2.8; decision `HISTORY-INCREMENTAL-LAG-RESIDUAL-2026-10-19`), authorized one additional plan stage (rounds 4–6) to fix R3-F1, and accepted the proposals below (decision `HISTORY-INCREMENTAL-DECISIONS-2026-10-19`).

- **Q0 — Tiingo plan:** check the Tiingo account page (plan tier, month-to-date usage) before the build is deployed (§7 step 1). Stay on the free plan if it fits; the build ships free-tier defaults (50/h, 1,000/day, 500 symbols/month, 1 GB/month) as settings, so a plan change is a config edit.
- **D1 — dividends/splits:** (a) rescale on the event night, then one `CONFIRM` re-fetch `PROVIDER_LAG_DAYS` = 5 trading days later.
- **D2 — the 72 Tiingo-only symbols:** (a) one small recent-window request per trading night now (2.6). Follow-up phase, measured first: move symbols whose stored Tiingo rows pass the five-date seam check back to the Alpaca-suffix basis (no Tiingo request). Not (d) mixing providers, not (e) updating less often. (c) Tiingo Power only if Kenneth later wants the 72 in minutes.
- **D3 — revalidation:** `REVALIDATE_DAYS` = 90, `REVALIDATE_PER_NIGHT` = 10, only within the nightly budget share.
- **D4 — nightly reserve:** 100 requests/day, 25 symbols/month, 100 MB/month held back for daytime scans.
- **D5 — UI:** Stage C (Settings → Data line) is built in this phase.

## 9. Overlap with PR #390 and other work

PR #390 (HISTORY-INGEST-GAPS, open) edits `ingestion_job.py` (state keys, `ingestion_universe`, `startup_catch_up`), `ingestion_scheduler.py`, `tiingo.py` (dash class tickers inside `fetch_historical_candles`) and `historical_store.py` (yfinance dash). Stage A edits `tiingo.py`'s `request()` and Stage B edits `ingestion_job.run_ingestion` — the same functions. The build starts from a `main` that contains #390; if #390 is still open when Kenneth approves, Stage A/B wait for it (no rebasing onto an unmerged branch). This plan relies on #390's SPY-first universe for pass 2's priority (1).

No other open claim touches `history_backfill.py`, `ingestion_job.py`, `tiingo.py` or `governor.py` (claims ledger read 2026-10-19).

## 10. Completion milestones for this phase (task-ratings.md)

10 % plan drafted · 20 % plan independently approved · 50 % stage A+B implemented · 70 % regression + local checks pass · 85 % each stage's code audit clean · 95 % PR heads green · 100 % merged and the §7 live run recorded. Stage C counts only if D5 = now.

## 11. Plan audit log

| Round | Reviewer | Target | Gate findings | Result |
|---|---|---|---:|---|
| 1 (plan 1) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | whole plan at bb0b0ebb vs the code and PR #390's diff | 5 | all fixed at 61530009 |
| 2 (plan 2) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | `git diff bb0b0ebb 61530009` (the round-1 fixes) + interactions | 1 | fixed at 69950537 |
| 3 (plan 3) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | `git diff 61530009 69950537` (the round-2 fix) + interactions | 2 | **NOT FIXED — plan-stage cap of three rounds reached; audit stopped, plan NOT clean** |
| 4 (plan stage 2, round 1) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | `git diff 85feb24e 9833e279` (R3-F1 fix + section-8 decisions) + interactions | 1 | fixed at 828c907d |
| 5 (plan stage 2, round 2) | fresh `gate-auditor` subagent, bmad-review-adversarial-general | `git diff 9833e279 828c907d` (the R4-F1 fix) + interactions | 0 | **CLEAN — plan approved** |

Round 1 findings (common root: on-demand `get_bars` writes rows between nights):
- **R1-F1** `SINGLE_PROVIDER_CURRENT` keyed on the newest row's `fetched_at` could be satisfied by an on-demand append after an ex-date → a basis step survives. Fixed: keyed on the new nightly-only `window_verified_at` (2.6 step 1); B2 test 8.
- **R1-F2** Tiingo-only overlap anchored at `last_stored` could sit entirely inside an on-demand chunk → step at the chunk start never repaired. Fixed: overlap anchored at the nightly-only `window_verified_through`, full path when missing or older than 45 days (2.6 steps 2–5); B2 test 8.
- **R1-F3** unbounded `DEFER_ALPACA_MISSING` froze factors under a persistent Alpaca gap. Fixed: removed; an empty Alpaca reply keeps today's full-window path (2.5); B2 test 6.
- **R1-F4** a D1-a re-fetch could accept a Tiingo prefix that has not yet applied the event (inside the 0.5 % seam tolerance) and then freeze it. Fixed at 61530009 by an acceptance check + interim rescale + recheck; **superseded in round 2** (see R2-F1) by T6 + `RESCALE`/`CONFIRM` (2.3, 2.4).
- **R1-F5** D1-a "budget refused → write nothing" dropped today's yfinance fallback and could freeze adjusted symbols for weeks. Fixed: the yfinance fallback stays on every prefix path; a budget refusal no longer stops pass 2; `CONFIRM`/`REVALIDATE` with no usable reply write `SUFFIX_ONLY` (2.4, 2.7); B2 test 5(iii), B3.

Logged below the gate (not fixed): `REVALIDATE` capacity (now moot: over-cap symbols are written `SUFFIX_ONLY`); 2.6's identity check is a new check, not the existing same-source rule (the plan defines it explicitly); D1-b on Tiingo-only rows now sets `fetched_at` (folded in); coarse Alpaca rounding could hide a sub-0.01 % dividend under `ADJ_TOL` (negligible).

Round 2 finding:
- **R2-F1** the round-1 acceptance check guarded only the adjustment paths; a prefix written by `FULL` (T-failure, empty Alpaca reply, `REVALIDATE`, `force_backfill`, or today's code the night before deploy) inside a provider-lag window passed only the 0.5 % seam check, became trusted by `SUFFIX_ONLY`, and the acceptance check then refused the later correct reply. Fixed by replacing the whole adjustment mechanism: **T6** — a prefix fetched within `PROVIDER_LAG_DAYS` trading days after an Alpaca-visible ex-date is never trusted, so the symbol is re-fetched nightly exactly as today until the window has passed; adjustments are applied by `RESCALE` with Alpaca's own ratio on the event night (lag-immune), and under D1-a confirmed by one provider re-fetch after the lag window (`CONFIRM`). The pending-adjustment columns, `EVENT_TOL` and `PREFIX_RECHECK` are gone; Stage B adds only the two window-anchor columns. Residual stated in 2.8 (provider lag longer than L). B1 T6 boundary tests, B2 test 5.

Logged below the gate in round 2 (not fixed): `PREFIX_RECHECK` tolerance (moot, removed); refused-recheck suffix write (moot; `CONFIRM`/`REVALIDATE` now fall back to `SUFFIX_ONLY`); budget-refused seam refusal moving a symbol to a yfinance single-provider basis (today's rule, coherent series); 2.6's "get_bars refused too" claim (corrected: the daytime reserve may admit it, the next nightly window rewrites those rows); attempts cap semantics (moot); test-only `refresh_adjustments(fetch=...)` not clearing the anchor (folded into B0).

### Round 3 — cap reached, findings OPEN (not fixed, by audit_rule)

The plan stage has run its three rounds. Per `audit_rule` the audit stops here, `audit_clean` stays false, and nothing below is fixed in this plan until Kenneth decides how to proceed. The proposed fixes are the auditor's, recorded so they are not lost; they are **unaudited**.

- **R3-F1 (High) — T6 opens the lag window one ET day too late.** The nightly runs at 02:00 Europe/Berlin ≈ 20:00 ET of the *previous* ET day, and Alpaca can apply an ex-date-X adjustment to every row before any bar dated X exists. A `FULL` prefix fetched that evening (deploy night, `REVALIDATE`, a T1–T4 failure, an empty Alpaca reply) has `F = X − 1`; the next night `E = X` appears, `X <= X − 1` is false, T6 holds and the possibly-lagging prefix (up to 0.5 % off) is trusted `SUFFIX_ONLY` — under D1-a until `CONFIRM`, under D1-b until revalidation. A missing IEX bar on E shifts the step later and widens the hole. The planned B1 test "T6 at F = E − 1 → trusted" pins the defect. *Proposed fix:* open the window at `P(E)`, the `current` date before E (`P(E) <= F < E + L` → `FULL`); test F = P(E) at 20:00 ET → lag-exposed.
- **R3-F2 (Medium) — a provider lag longer than L is worse than today, not equal.** Under D1-a, `CONFIRM` at E + L would overwrite a *correct* rescaled prefix with a provider prefix that still lags (inside the 0.5 % seam), and T6's last `FULL` at E + L would trust such a prefix under both D1 options; today's nightly re-fetch repairs it the night the provider catches up. 2.8 states this residual but calls it today's behaviour, which it is not. *Proposed fix:* accept a `CONFIRM` reply only if its adjusted prefix agrees with the stored rescaled prefix within a tight tolerance (e.g. 1e-4), otherwise keep the rescaled prefix and retry nightly; trust a lag-exposed `FULL` prefix only once a later nightly reply agrees with it; B2 test with a lag of L + 2 days.

Diagnosis (for Kenneth, per the cap corollary): all three rounds converge on one question, not on batch size — **how long may a kept prefix trust a provider that applies dividends later than Alpaca?** Any incremental design that stops re-downloading the prefix every night must either detect "the provider has caught up" (rounds 2–3 show each detector has an edge) or accept a stated, bounded residual: a pre-2020 adjusted price up to 0.5 % off (inside today's seam tolerance) until the next revalidation or event, only when a provider lags Alpaca by more than L trading days. The Tiingo ledger (Stage A) is unaffected by these findings.

### Plan stage 2 (rounds 4–6), authorized by Kenneth 2026-10-19

Opened by decision `HISTORY-INCREMENTAL-STAGE2-2026-10-19` to fix R3-F1 only; R3-F2 is closed as the accepted residual (decision `HISTORY-INCREMENTAL-LAG-RESIDUAL-2026-10-19`, restated in 2.8). Change: the lag window and every event comparison now use `P(E)` (the `current` date before the ex-date) instead of E (2.3, 2.4); `RESCALE` additionally requires the T5 change to be explained by new Alpaca events whose window starts after F (2.4, "Which events are new") — found while applying the fix: with the window at `P(E)`, a prefix fetched after the other provider applied an event that Alpaca applied later would otherwise be rescaled twice. B1 boundary tests updated.

Round 4 (stage 2, round 1): the P(E) change closes R3-F1 for every operator timezone/cron hour, weekends, holidays and a missing IEX bar; condition (iii) is correct. One finding:
- **R4-F1 (Medium)** no planned test isolates `RESCALE` condition (iii): the listed fixture sits inside the T6 window, where T6 alone already forces `FULL`, so an implementation without (iii) passes every planned test while double-applying an event Alpaca applies more than L days late (or an Alpaca correction of an old step). Fixed: B1 now has two fixtures that keep T1–T6 true so only (iii) can refuse.

Logged below the gate in round 4 (not fixed): 2.4's "all written by one nightly write" ignores on-demand Alpaca appends (they only cause `FULL` or a stricter check); coarse Alpaca rounding could create spurious steps (efficiency only); Alpaca applying an event more than one evening before P(E) (no evidence either way); acceptance 6.2 / B2 test 3 wording omits the visible-step and `F < P(E)` requirements; B2 test 5(i) trusts from E+L+1, not E+L; 2.8's "symmetric" Alpaca-lag residual is overstated, since (iii) sends that case to `FULL`; F's commit time may cross midnight ET (hours at the window end); `REVALIDATE` may fire while a `CONFIRM` is due (today-equivalent).

Round 5 (stage 2, round 2): **zero gate-level findings — plan stage clean.** The auditor confirmed both R4-F1 fixtures are constructible under 2.2–2.4, keep T1–T6 true, fail if (iii) is removed and assert `FULL`; code claims re-checked at 828c907d. Below the gate (for the implementer, not fixed here): count "X + L + 1" in **trading** days (a calendar-day reading can land inside the T6 window); assert "no prefix factor multiplied" in a B2 test (B1 is a pure classifier); fixture (a) needs a dividend under 0.5 %; fixture (b) needs E after the fifth reference date.
