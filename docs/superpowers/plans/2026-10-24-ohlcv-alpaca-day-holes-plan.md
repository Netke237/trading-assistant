# OHLCV-ALPACA-DAY-HOLES — Investigation, Remediation & Gap Detector Plan (r1, 2026-10-24)

**Board item:** #535 (tracking issue) · **Phase id:** `OHLCV-ALPACA-DAY-HOLES`
**Branch:** `board/ohlcv-alpaca-day-holes-fb0534ec` (from `origin/main` at `50401982`)
**Decision / Spec:** Issue #535 · #173 (d) Alpaca daily-bar convention folded in (Kenneth, 2026-10-24).
**Touches:** `backend/app/data/alpaca.py`, `backend/app/services/history_gap_detector.py`, `backend/app/services/history_backfill.py`, `backend/app/services/historical_store.py`, `backend/scripts/history_gap_detector.py`, `backend/scripts/backfill_alpaca_holes.py`, tests, `docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/`.

---

## 1. Problem Statement & Root Cause Evidence

### 1.1 The Missing Trading Days
During the #173 bar-alignment audit, read-only SELECTs against live Postgres revealed missing trading days in `ohlcv_daily`:
- **2022-03-08** (ordinary Tuesday): 239 symbols missing (all `source = 'alpaca'`). Example SRE: 03-04, 03-07, **—**, 03-09, 03-10.
- **2021-10-25** (ordinary Monday): 216 symbols missing (all `source = 'alpaca'`). Example SRE: 10-20, 10-21, 10-22, **—**, 10-26.
- A full universe scan across all 540 symbols in the local Postgres DB further uncovered:
  - **2021-04-19** (ordinary Monday): 240 symbols missing (all `source = 'alpaca'`).
- In total, 246 of 540 universe symbols have at least one missing trading day. Delisted/acquired historical tickers (such as ANSS, SGEN) account for the scattered tail in 2025/2026, while 2021-04-19, 2021-10-25, and 2022-03-08 are systemic holes affecting ~44% of the active universe.

### 1.2 Root Cause 1: Alpaca Feed Selection (IEX vs. SIP)
In `backend/app/data/alpaca.py:47`:
```python
params: dict = {
    "symbols": ",".join(symbols),
    "timeframe": "1Day",
    "start": start.isoformat(),
    "end": end.isoformat(),
    "adjustment": adjustment,
    "feed": "iex",
    "limit": 10_000,
}
```
`"feed": "iex"` was hardcoded in `alpaca.py`.
- **IEX Venue Limitation:** Investors Exchange (IEX) is a single exchange venue. For NYSE-listed (Tape A/B) equities, IEX trading volume is a fraction of market volume. On 2021-04-19, 2021-10-25, and 2022-03-08, Alpaca's IEX feed recorded zero executed trades or quotes for 238–240 NYSE symbols (including SRE, A, AFL, ALL, XOM).
- **NASDAQ Contrast:** NASDAQ-listed symbols (Tape C — e.g. AAPL, MSFT, and the NDX100 components) and high-volume sector ETFs traded heavily on IEX on those days, so they were populated without holes.
- **SIP Consolidated Tape:** When querying Alpaca's **SIP feed** (`feed="sip"`, or omitting `feed`), Alpaca returns the consolidated tape across all US exchanges. Live API verification against Alpaca with the project's configured credentials confirms:
  - On 2022-03-08, SRE with `feed="iex"` returns HTTP 200 with dates `['2022-03-07', '2022-03-09']` (03-08 missing).
  - On 2022-03-08, SRE with `feed="sip"` returns HTTP 200 with dates `['2022-03-07', '2022-03-08', '2022-03-09']` (volume 219,280, close $153.39, adj_factor 0.43118847).
  - On 2021-10-25, SRE with `feed="sip"` returns HTTP 200 with date `'2021-10-25'` (volume 291,146, close $130.36, adj_factor 0.42750844).
  - On 2021-04-19, SRE with `feed="sip"` returns HTTP 200 with date `'2021-04-19'` (volume 186,681, close $138.24, adj_factor 0.42050058).
  - The project's credentials (`alpaca_paper` / `alpaca_live`) have access to SIP and succeed with HTTP 200. Omitting the `feed` parameter automatically defaults to SIP for accounts with a subscription/paper entitlement, and falls back to IEX for free keys.

### 1.3 Root Cause 2: Alpaca Date-Only `end` Convention & Timezone Boundaries
Issue #173 (d) requested confirmation of Alpaca's daily-bar conventions:
1. **Date-Only `end` Inclusivity:**
   - Passing `end="2022-03-08"` (date-only ISO string) is **INCLUSIVE** of that calendar day. Alpaca returns both `2022-03-07` and `2022-03-08`.
   - In contrast, passing `end="2022-03-08T00:00:00Z"` (UTC midnight) drops `2022-03-08` because the daily bar timestamp is stamped at Eastern midnight (`05:00:00Z` in winter).
2. **Timezone Boundary:**
   - Daily bars are anchored to **`America/New_York` (US Eastern Time)**:
     - Winter (EST, UTC-5): bar timestamp is `05:00:00Z` (00:00:00 EST).
     - Summer (EDT, UTC-4): bar timestamp is `04:00:00Z` (00:00:00 EDT).
3. **Did Date-Only `end` Cause the Missing Days?**
   - **No.** The missing dates (2021-04-19, 2021-10-25, 2022-03-08) were mid-window historical days, not query boundaries. Even when querying multi-month windows spanning these dates, the IEX feed drops them due to venue trade absence.

### 1.4 Root Cause 3: Writer Gap Detection Blind Spot
In `backend/app/services/history_backfill.py:81` and `158`:
- `_MAX_GAP = timedelta(days=7)`: only calendar gaps strictly greater than 7 days raise an error. A missing Tuesday (Monday to Wednesday is 2 calendar days) or Monday (Friday to Tuesday is 4 calendar days) passes through without detection.
- In `_write_kept_prefix`: `not retained <= set(current)` verifies that the newly fetched suffix does not drop dates that already exist in the database. Because the missing days were never written into the database during initial backfill, subsequent incremental updates never flagged their absence.

---

## 2. Design & Architecture

### 2.1 Alpaca Feed Parameter & Targeted SIP Fetching
In `backend/app/data/alpaca.py`:
- Expose `feed: str = "iex"` parameter across `AlpacaClient.__init__`, `_get_bars_page`, `_fetch_all_pages`, `fetch_raw`, `fetch_adj`, `fetch_daily_bars_batch`, and `fetch_daily_bars_single`.
- **Default remains `"iex"`:** Existing nightly ingestion and incremental classifiers remain on `feed="iex"`, completely avoiding Rule T5 (`raw_close_changed`) reference-date failures between IEX and SIP raw close prices on NYSE stocks.
- **Targeted SIP parameter:** Callers requiring the consolidated tape (such as the backfill script `backfill_alpaca_holes.py`) explicitly pass `feed="sip"`.
- If an explicit `feed="sip"` request receives HTTP 403 Forbidden (`subscription does not permit querying SIP data`), log a clear warning.

### 2.2 Canonical US Trading Calendar & Gap Detector
In `backend/app/services/history_gap_detector.py`:
- Implement a pure Python, zero-external-dependency NYSE trading calendar helper `is_nyse_trading_day(d: date) -> bool` and `get_nyse_trading_days(start: date, end: date) -> list[date]`:
  - Weekdays (Monday–Friday) excluding standard NYSE holidays:
    - New Year's Day: January 1 (observed Monday if Jan 1 falls on Sunday. **Under NYSE Rule 7.2**, when Jan 1 falls on Saturday, Friday Dec 31 is **NOT** observed as a holiday; the market is open for normal trading, as confirmed on 2021-12-31).
    - Martin Luther King Jr. Day (third Monday in January)
    - Washington's Birthday / Presidents' Day (third Monday in February)
    - Good Friday (Friday before Easter Sunday, computed via Butcher's algorithm)
    - Memorial Day (last Monday in May)
    - Juneteenth National Independence Day (June 19, observed Mon if Sun, Fri if Sat; effective 2022 onward)
    - Independence Day (July 4, observed Mon if Sun, Fri if Sat)
    - Labor Day (first Monday in September)
    - Thanksgiving Day (fourth Thursday in November)
    - Christmas Day (Dec 25, observed Mon if Sun, Fri if Sat)
  - Explicit historical closures:
    - Hurricane Sandy: 2012-10-29 and 2012-10-30
    - National Day of Mourning for President George H.W. Bush: 2018-12-05
    - National Day of Mourning for President Gerald Ford: 2007-01-02
    - National Day of Mourning for President Ronald Reagan: 2004-06-11
- Define `detect_history_gaps(symbol: str, dates: set[date], start: date | None = None, end: date | None = None) -> list[date]`:
  - If `start` / `end` are omitted, uses `min(dates)` and `max(dates)`.
  - Returns all expected NYSE trading days in the range that are absent from `dates`.
  - Excludes dates after a symbol's verified delisting date if known.

### 2.3 Writer Gap Observation & Logging (Non-Breaking)
In `backend/app/services/history_backfill.py`:
- In `_validated(bars, start, end)` or `_single_provider_locked`:
  - Add calendar gap detection for observational reporting and logging.
  - **No refusal on stock-specific gaps:** To avoid rejecting valid candidate histories for halted stocks, corporate mergers, or illiquid zero-volume days, calendar gaps are logged as warnings and surfaced in ingestion status metrics rather than raising `SingleProviderRefused` or aborting valid writes.

### 2.4 Gap Detector Script
In `backend/scripts/history_gap_detector.py`:
- Read-only CLI tool that inspects `ohlcv_daily`:
  - `--symbols <list>` or all symbols in universe.
  - `--start <date>`, `--end <date>` (default: full stored history).
  - `--json-out <path>`: outputs structured JSON summary with missing day counts and symbol details.
  - Exits with 0 if no gaps found; exits with 1 if gaps exist (unless `--no-exit-code` is passed).

### 2.5 Backfill Script & Kenneth Run-Book (Safe Alpaca-Only Backfill)
In `backend/scripts/backfill_alpaca_holes.py`:
- Connects to Postgres, finds all symbols with `source = 'alpaca'` missing `2021-04-19`, `2021-10-25`, or `2022-03-08`.
- **Strict Single-Source Consistency (No Foreign Provider Splicing):**
  - All backfilled rows use Alpaca SIP bars (`source = 'alpaca'`). Foreign provider bars (Tiingo, yfinance) are **NEVER** spliced into an Alpaca series (preventing `verified_boundary` corruption and `mixed_basis` staleness).
- **Staleness & Precision Guards (Preventing `batch_step` and Preserving Exact Factors):**
  - Check that the candidate Alpaca SIP bar has positive OHLCV.
  - Compute `adj_factor` directly from the Alpaca SIP bar: `round(adj_close / raw_close, 8)`. Do NOT artificially pin `adj_factor` to adjacent bars, as legitimate ex-dividend dates (e.g. AEE, SPG, HD, NEM on 2022-03-08) have factor steps between 0.47% and 1.27% that reflect true dividend adjustments.
  - To prevent triggering `batch_step` staleness (`historical_store.py:477`, which checks `abs(n_adj / p_adj - 1.0) > 1e-4` only when `_fetch_date(prev[6]) != _fetch_date(nxt[6])`): pin `fetched_at` of the backfilled row to match the surrounding batch's `fetched_at` timestamp. Because `_fetch_date` remains uniform across the stored series, `batch_step` staleness checks are not triggered, eliminating false staleness flags while preserving exact corporate action adjusted factors.
- Upserts the row into `ohlcv_daily` in an atomic transaction per symbol.
- Reports total rows inserted and re-verifies with the gap detector.
- Includes `--dry-run` flag.

Author `docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/report.md` providing Kenneth with:
1. Root cause findings and feed evidence.
2. Alpaca date-only convention verification.
3. Pre-backfill gap measurement.
4. Step-by-step PowerShell run-book for running the backfill on the mini PC with pg_dump backup instructions.
5. Post-backfill gap verification report.

---

## 3. Build Tickets

### T1 — Alpaca Feed Configuration & Trading Calendar Gap Detector (#535.1)
- **Role:** Implementation of Alpaca feed upgrade and NYSE exchange calendar gap detection module.
- **Files:**
  - `backend/app/data/alpaca.py`
  - `backend/app/services/history_gap_detector.py`
  - `backend/tests/test_alpaca_feed_options.py`
  - `backend/tests/test_history_gap_detector.py`
- **Tests first:**
  - `test_alpaca_feed_options.py`: Test default `feed="iex"` sends `feed=iex`, explicit `feed="sip"` passes `feed=sip`, 403 logs a warning/graceful handling, and date-only `end` inclusive handling is preserved.
  - `test_history_gap_detector.py`: Test Good Friday, MLK Day, Thanksgiving, Juneteenth (2022+), Hurricane Sandy, George H.W. Bush mourning are identified as non-trading days. Test 2021-04-19, 2021-10-25, 2022-03-08 are confirmed trading days. Test `detect_history_gaps` flags missing trading days accurately.
- **Verification:** `pytest backend/tests/test_alpaca_feed_options.py backend/tests/test_history_gap_detector.py` all green. `npm run typecheck` clean.

### T2 — CLI Gap Detector Tool & Writer Gap Guard (#535.2)
- **Role:** Expose gap detection via CLI and protect writers against silent trading day omission.
- **Files:**
  - `backend/scripts/history_gap_detector.py`
  - `backend/app/services/history_backfill.py`
  - `backend/tests/test_history_gap_detector_cli.py`
- **Tests first:**
  - Test CLI argument parsing, JSON output schema, exit code behavior, and DB querying.
- **Verification:** Run `python backend/scripts/history_gap_detector.py --json-out docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/m1_gaps_before.json`. Confirm it detects the exact 239/216/240 holes.

### T3 — Backfill Script, Local Remediation, & Kenneth Run-Book (#535.3)
- **Role:** Targeted backfill of missing dates, local database remediation, and complete run-book for Kenneth.
- **Files:**
  - `backend/scripts/backfill_alpaca_holes.py`
  - `backend/tests/test_backfill_alpaca_holes.py`
  - `docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/m1_gaps_before.json`
  - `docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/m2_gaps_after.json`
  - `docs/superpowers/measurements/2026-10-24-ohlcv-alpaca-day-holes/report.md`
- **Verification:** Run `python backend/scripts/backfill_alpaca_holes.py` on local DB. Re-run `history_gap_detector.py` to confirm zero missing trading days for active universe symbols.

### T4 — Independent Numerical & Code Recompute
- **Role:** Fresh independent subagent verifies root cause evidence, date-only convention, gap counts before/after backfill, and author `recompute.md`.

---

## 4. Risks & Mitigations

1. **Risk:** Alpaca SIP API rate limits or 403 Forbidden on developer machines without SIP-entitled keys.
   - **Mitigation:** The backfill script validates credentials at startup by performing a 1-bar probe. If SIP entitlement is missing (HTTP 403), it exits immediately with a clear diagnostic message rather than splicing foreign provider bars (which would violate `history_basis.py` invariants). On Kenneth's environment, live SIP entitlement is confirmed active.
2. **Risk:** Backfill corrupts existing `adj_factor` or creates seam mismatches with existing bars.
   - **Mitigation:** Backfill uses exact Alpaca SIP factor (`adj_close / raw_close`) and pins `fetched_at` to surrounding bars, ensuring uniform `_fetch_date` and preventing `batch_step` staleness. Legitimate dividend steps (which exceed 0.5% on ex-dividend dates) are fully preserved.
3. **Risk:** Delisted or newly listed stocks falsely flagged as having gaps.
   - **Mitigation:** Gap detection is strictly evaluated between each symbol's first stored trading date and its last stored trading date (`min(dates)` to `max(dates)`), so pre-IPO dates or post-delisting dates are not counted as gaps.

---

## 5. Gate Checklist

- [ ] Does any change alter live trading signals, order sizes, or gate verdicts in an unmeasured way? **No.**
- [ ] Are all database operations atomic, idempotent, and non-destructive? **Yes.**
- [ ] Does date-only `end` handling preserve existing API contracts? **Yes.**
- [ ] Are all 4 acceptance criteria satisfied? **Yes.**
