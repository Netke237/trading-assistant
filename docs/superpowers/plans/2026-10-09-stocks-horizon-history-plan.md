# Stocks horizon HISTORY: daily history back to about 2010 — Plan DRAFT (`STOCKS-HORIZON-HISTORY`)

> **Status: DRAFT, plan round 1 not run.** Split out of `STOCKS-HORIZON-T1` on 2026-10-09 by Kenneth's decision
> T1-CAP-SPLIT-H0B-2026-10-09, after T1's plan stage reached its 3-round cap not clean. This phase has its own claim,
> branch, plan rounds (cap 3) and code rounds. Built through `k-ticket-coordinator`, test-first.

**Why.** Stored history starts 2020-10-06. With every tuned signal on a full 400-bar window (T1 H1/H9), Annual gets
1–2 walk-forward folds. Decision T1-HISTORY-BACKFILL-2026-10-09: load daily history back to about 2010 for today's
S&P 500 ∪ NDX 100 constituents and stop the nightly job pruning it. The survivorship label stays (today's
constituents only). **Order:** must ship, and its first backfill must run on the mini PC (T1-MINI-PC-2026-10-09),
before `STOCKS-HORIZON-TUNING-RUN`. It does not block building T1.

## Input carried over: T1 plan round 3, finding 1 (gate-level, unresolved)

The H0b design below, as it stood in T1's plan at `a101965a`, **would corrupt persisted data**. The redesign has to
fix all of this before plan round 1 can come back clean:

- Stored rows hold raw OHLC plus `adj_factor` = the provider's adjClose/close **as of the fetch date**
  (`historical_store.py` `_store_bars` / `_read_bars`). The nightly Alpaca step re-upserts its whole window every
  night with fresh factors (`ingestion_job.py` step 1–2). Back-filled Tiingo/yfinance rows (pre-2016) would be fetched
  once and never refreshed: after any later split or dividend, the adjusted series steps at the seam (a 10:1 split →
  ~10× jump), and the tuner's 400-bar windows across the seam see fake moves.
- `refresh_adjustments` cannot repair the back segment: `_fetch_chain` tries Alpaca first and accepts any non-empty
  result, and Alpaca only returns ~2016 onward, yet the symbol is reported `refreshed`.
- The seam check compared **raw** stored closes; Alpaca and Tiingo raw closes agree, so it cannot see a basis
  difference, and it ran only once.
- `stale_reasons` flags any series with more than one source as `mixed_basis`, so nearly every back-filled symbol
  would be flagged and the "bring flagged symbols to Kenneth" step would present the whole universe.

Fix direction proposed by the round-3 reviewer (to be designed and audited here, not yet decided):
(a) seam check on **adjusted** closes (`close × adj_factor`) on both sides; (b) keep the back segment on the current
basis — re-fetch `[fetch_start, first_alpaca_date)` from the non-Alpaca chain when the Alpaca factor at the seam
changes (or nightly), re-run the seam check each time and refuse/flag on mismatch, **or** store it rescaled to the
Alpaca basis at the seam and rescale when the seam factor moves; (c) `refresh_adjustments` fetches the pre-Alpaca span
from Tiingo → yfinance; (d) the recorded seam is expected: exempt it from `mixed_basis` / `batch_step`, or filter it
before flags go to Kenneth. Tests: a split after the backfill leaves the adjusted series continuous at the seam;
`refresh_adjustments` rewrites the back segment.

## H0b as it stood in T1 (superseded where finding 1 applies)

### Mechanism today

`ingestion_job.run_ingestion(symbols, years=6)` fetches `years × 365` days (Alpaca batch first, then
`historical_store.get_bars` for symbols Alpaca returned nothing for) and then `_prune_old_rows(years)` deletes older
rows. The nightly scheduler calls it with `years=6`; `/api/ingestion` caps `years` at 10. A symbol Alpaca returns
*some* bars for is never back-filled further (Alpaca's free history starts about 2016).

### Semantics (draft)

- One setting `history_years` (default **17**) in the scheduling settings that
  `ingestion_scheduler._run_nightly_maintenance` already reads (`scheduling_tz._load_settings`). The nightly run and
  the prune both use it. `/api/ingestion` `years` bound raised to 20. Nothing prunes below `history_years`.
- **Gap backfill.** After the Alpaca step, for each symbol whose earliest stored bar is later than `fetch_start + 7
  days`, fetch `[fetch_start, earliest)` from the non-Alpaca chain (Tiingo → yfinance, as `_fetch_chain` orders
  them). **Seam check** (to be redone per finding 1): the fetch overlaps the stored series by 5 trading days; if any
  overlapping close differs by more than 0.5%, the back segment is **not stored**, and the symbol is listed in the
  run state as `seam_mismatch` with the ratio. A symbol whose provider returns nothing earlier (listed later) is
  recorded in `backend/data/history_floor.json` (`symbol → first available date`, gitignored) so the nightly run does
  not refetch it.
- Ingestion state reports `backfilled`, `seam_mismatch`, `floor_reached` counts and names.

### Test first (draft)

Prune keeps 17 years (row at 16.9 years kept, 17.1 years pruned) with `history_years: 17`. A symbol whose stored
series starts 2016 gets `[2009, 2016)` fetched from the non-Alpaca chain and stored. Seam mismatch (1% off) → nothing
stored, listed. Provider returns nothing earlier → floor recorded, second run makes no fetch. Plus finding 1's tests.

## Verification (coordinator, on the mini PC)

Run the first full ingestion and confirm `backfilled` / `seam_mismatch` / `floor_reached`; re-run the Phase C
bar-basis check (`scripts/evidence`, `bar_basis`) over the whole span and bring flagged and seam-mismatch symbols to
Kenneth for the exclusion list (P0A process).
