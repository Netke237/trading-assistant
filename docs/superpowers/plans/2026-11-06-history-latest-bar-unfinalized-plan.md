# HISTORY-LATEST-BAR-UNFINALIZED — plan

Board item: #574 · Branch: `board/history-latest-bar-unfinalized-30123325` · Follow-up to #413 (Stages A/B merged)

## 1. Problem and evidence

The 2026-11-06 01:00 UTC nightly (`GET /api/data/ingest/status`) ran in 71 min. 148 of its 514 symbols failed:

- 85 yfinance-basis (single-provider) symbols, among them SPY, ABBV, IBM, MRK, PFE and T, failed with `yfinance: invalid open on 2026-11-05`.
- 61 seam-refused symbols needed a rebuild and failed with `tiingo: requests_per_hour budget exhausted (50/50); yfinance: invalid open on 2026-11-05`, so `rebuild_refused=61` and `rebuilt=0`.

All the evidence below was gathered read-only:

1. **The error comes from `_validated` (`backend/app/services/history_backfill.py:87-104`).** It runs over every settled bar in the window. One bar with a non-finite or ≤ 0 `open/high/low/close/adj_factor` raises `HistorySeamMismatch` and rejects the whole reply.
2. **The bar was settled by the code's definition.** The nightly runs at 01:00 UTC, which is 20:00 ET on 2026-11-05. `hs.is_settled(d, now)` is `now >= 16:00 ET(d) + 2 h`, so 2026-11-05 was settled from 18:00 ET. It was also the latest settled weekday: `hs.last_settle_boundary(now)` → 2026-11-05 18:00 ET.
3. **The bad bar is transient, and only the latest day is affected.** I ran a real yfinance fetch through the app's `hs._yfinance_fetch` at 06:58 UTC the same morning, 5 h 58 min after the nightly. It returned a complete 2026-11-05 bar for SPY, ABBV, IBM, MRK, PFE, T, TJX and UNH. The app's own `_validated` accepted the full 6-year and 17-year windows for all eight. No bar on any date had a price ≤ 0 or NaN.
4. **It is the same failure every night.** In Postgres, SPY (yfinance basis since its rebuild on 2026-11-03 at 14:32 UTC) has its latest bar on 2026-11-02. The nightlies of 2026-11-04, 11-05 and 11-06 wrote nothing for it. Other yfinance-basis symbols reached 2026-11-04 only through daytime on-demand writes (`fetched_at` around 15:00 UTC), which happen after Yahoo has finalised the bar. SPY is not in a scan universe, so it got no daytime writes and fell 3 trading days behind.
5. **The provider reply had a NaN or 0 open, not a NaN volume.** A NaN volume would make `int(row["Volume"])` raise inside `_yfinance_fetch`, which returns `[]`, and the error would read "no settled bars", not "invalid open". So the reply contained the 2026-11-05 row with a NaN or 0 `Open`.
6. **What I could not do:** observe the bad row live. Yahoo had already finalised it before I could fetch. Nothing in this plan depends on which of NaN or 0 it was.

## 2. Fix (one function, `_validated`)

**Rule:** a reply's latest bar, dated on the latest settled weekday, with an invalid price field means the provider has not finalised that day yet. That bar is dropped from the validated reply and a warning is logged naming the date, the source and the field. Everything else stays exactly as strict as today.

The bar is dropped only when **all** of these hold:

- (a) Its date `d == L`, where `L` is the ET date of `hs.last_settle_boundary(now)` and `now = hs._utcnow()`, read once per call.
- (b) Every invalid field is a price field: `open`, `high`, `low` or `close`. An invalid `adj_factor` still rejects the reply.
- (c) Its `source` is a known basis (`alpaca`, `tiingo` or `yfinance`). It still counts for the duplicate-date and mixed-source checks, so it cannot hide a reply defect.
- (d) No other kept, settled, in-window bar is dated after `d`. Only a weekend-dated bar could be. Such a bar leaves `d` not the latest, so the reply is rejected with today's `invalid <field> on <d>` message.

Anything else raises exactly as today, with the same message text, including:

- an invalid bar on any older date;
- an invalid latest bar when its date is not `L` (for example on a holiday, or on a reply that ends early).

**Why this is safe:**

- **No bad bar is ever stored.** The dropped bar is not in the returned dict, and every writer stores only `_validated` output.
- **A date that is already stored stays protected.** If `d` was already stored, the caller's existing checks still refuse with rows and state untouched:
  - `required <= set(candidate)` in `_single_provider_locked` and `refresh_adjustments`;
  - `retained <= set(current)` in `_write_kept_prefix`;
  - `required <= candidate_dates` in the full path.
- **The classifier and the writer stay consistent.** Both read `_validated` with the same `hs._utcnow()`:
  - `classify_nightly_symbol` (`invalid_alpaca`);
  - `classify_single_provider_window` (`invalid_reply`);
  - each writer.
- **The dropped day is retried.** It is fetched again by the next run that refetches the window:
  - yfinance basis refetches the whole window on every run;
  - a Tiingo-basis window starts at `window_verified_through - overlap`, and `window_verified_through` is `max(candidate)`, so the day before `d`;
  - Alpaca-suffix symbols refetch the suffix every run.
  On that run `d` is no longer `L`, so a still-bad bar is rejected loudly, exactly as today.

**Known residuals** (accepted, recorded in the PR):

- **R1, one-night lag.** At 20:00 ET a symbol whose provider has not finalised the day is stored only through the previous trading day, so it stays one trading day behind after the nightly. That is instead of 1–4 days (or forever) today. If Yahoo always lags at 20:00 ET, the yfinance-basis symbols will be 1 day behind after every nightly. The fix for that is the schedule, not the code: `ingestion.time` in Settings → Data is Kenneth's setting. This is question Q1 for Kenneth, not part of this phase.
- **R2, Tiingo basis.** A Tiingo-basis symbol whose window write dropped `d` sets `window_verified_at = now`. That is after `last_settle_boundary`, so a second run before the next settle boundary classifies it `SINGLE_PROVIDER_CURRENT` and does not fetch. It is filled by the next nightly, which is the same one-night lag as R1. No wrong data.
- **R3, holiday.** On a holiday, `L` is the holiday itself, which has no bar. A bad bar on the day before is rejected as today. That bar was already settled and fetched the night before, so this is no regression.

## 3. Tests first

New file `backend/tests/test_history_latest_bar_unfinalized.py`. Python 3.11 (`backend/.venv`). The clock is patched through `hs._utcnow`.

**Unit tests on `_validated`:**

- `NOW = 2026-11-06 01:00 UTC`; the reply has yfinance bars for 2026-10-26 … 11-05.
  - U1: the 11-05 `open` is parametrised over NaN, 0, None, -1 and inf. Result: 10-26 … 11-04, with 11-05 absent and one warning naming 2026-11-05.
  - U2: the same for `high`, `low` and `close` (one each).
  - U3: an invalid `open` on 11-04 (not the latest) raises `invalid open on 2026-11-04`.
  - U4: the reply ends on 11-04 and its 11-04 bar is invalid. It raises, because 11-04 is not `L`.
  - U5: an invalid `adj_factor` on the 11-05 bar raises.
  - U6: a duplicate of the invalid 11-05 bar raises `duplicate provider date`.
  - U7: the invalid 11-05 bar has a different source from the rest. It raises `mixes sources`.
  - U8: the invalid 11-05 bar has an unknown source. It raises `unknown adjustment basis`.
- U9: `NOW = Sun 2026-11-08 12:00 UTC`, so `L` is Fri 11-06. An invalid 11-06 bar followed by a valid Saturday 11-07 bar raises.
- U10: `NOW = 2026-11-05 20:00 UTC` (15:00 ET, before the settle). The forming 11-05 bar is ignored as today, whatever its values. This pins that the existing settle filter runs first.

**Writer tests** (in-memory SQLite, the `test_history_single_provider.py` pattern):

- W1: a yfinance-basis symbol (state `basis_provider="yfinance"`) with stored rows through 10-30, run through `update_history`. The reply has a NaN-open 11-05. Bars through 11-04 are stored, no 11-05 row exists, and `window_verified_through == 11-04`. This reproduces the SPY failure.
- W2: `rebuild_single_provider` for a seam-refused (Alpaca-seeded) symbol. Tiingo raises `ProviderUnavailable("tiingo requests_per_hour budget exhausted (50/50)")`. yfinance returns a reply with a NaN-open 11-05. The symbol is rebuilt from yfinance through 11-04. This reproduces the 61 refused rebuilds.
- W3: as W1, but an 11-05 row is already stored from an earlier valid fetch. The reply's invalid 11-05 is dropped, so the reply omits a stored date. The update is refused (`SingleProviderRefused`, "omits existing stored dates") and rows and state are byte-identical to before.
- W4: an Alpaca-suffix symbol on the incremental path (SUFFIX_ONLY: state with seam and signature as in `test_history_incremental_writer.py`). The Alpaca reply's 11-05 bar has NaN open. Result: SUFFIX_ONLY through 11-04, with the prefix unchanged.

Each test fails on `main` before the fix, except U3–U8, U10 and W3, which pin unchanged behaviour. Then the fix makes them pass. The relevant existing suites must stay green: `test_history_single_provider*.py`, `test_history_incremental*.py`, `test_history_floor_and_job.py`, `test_history_nightly_run.py`, `test_ingestion_job.py` and `test_history_adjustment_completeness.py`. Then the full backend suite runs on Python 3.11, from a short path (the alembic MAX_PATH note in #413).

## 4. Question 3 of the brief: can the 61 rebuilds finish under 50 requests per hour?

- **Queue and retry today:**
  - The Tiingo ledger (`tiingo_budget`) counts a rolling 60 min.
  - A refused attempt is refused immediately, never waited on or retried within the run.
  - There is no carry-over queue between nights. Every night reclassifies from stored rows and state.
  - Pass 2 runs in priority order: SPY, then `SINGLE_PROVIDER_*` (24 Tiingo-basis symbols), then FULL and rebuilds (priority 3, input order), CONFIRM, and revalidations.
- **The ledger:** every nightly since 2026-11-03 made exactly 50 nightly requests (42 in the 01:00 hour, 8 in the 02:00 hour) and was refused after that. The run ends in about 71 min, so the rolling hour barely reopens.
- **So no, Tiingo alone cannot rebuild 61 symbols in one pass** after the 24 Tiingo-basis updates and the FULL/CONFIRM work.
- **With this fix they can still all finish in one pass.** `rebuild_single_provider` already falls back to yfinance when Tiingo is refused, and yfinance has no budget. The 61 failed only because the yfinance reply hit this bug.
- **Consequence to flag (Q2 for Kenneth, out of scope):** symbols rebuilt from yfinance become yfinance-basis permanently. `_classify_single_provider` always refetches the full window from yfinance, and nothing ever promotes a yfinance-basis symbol back to Tiingo or Alpaca. That is the existing design, not changed here.

## 5. After merge

A deploy restarts the backend. `startup_catch_up` then starts an ingestion run on its own, because SPY's last bar (2026-11-02) is before `most_recent_trading_day() - 1`. A restart during ET daytime, when Yahoo has finalised the previous day, brings every symbol current through the previous day. **No separate manual run is needed** if the backend is restarted after merge. If it is not restarted, the next nightly closes the backlog to at most one day (R1).

## 6. Completion milestones

The `task-ratings.md` table applies unchanged. Typecheck is N/A (backend only).
