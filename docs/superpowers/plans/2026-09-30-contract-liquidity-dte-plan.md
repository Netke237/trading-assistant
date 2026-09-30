# CONTRACT-LIQUIDITY-DTE — plan (draft r0; NOT audited; nothing built)

- **Phase:** `CONTRACT-LIQUIDITY-DTE` (PROJECT_STATE.json). Status `not_started`.
- **Branch:** `claude/contract-liquidity-dte` (from `origin/main` at `599b9da2`).
- **Origin:** Kenneth, 2026-09-30, looking at the Semi-annual Bullish SP500 options scan (518 scanned → 2
  candidates) and at Step 6, where almost every contract in the MSFT and AAPL chains read REJECT. An
  adversarial review of the first proposal ("drop the volume hard reject") found it weaker than stated; this
  plan replaces it and starts from measured data instead.
- **Waiting on Kenneth:** the four questions in §6. No code until they are answered and a plan round is clean.

## 1. What is true on main (599b9da2)

1. `contract_validator._hard_reject_reasons` (`contract_validator.py:84-87`):
   - `volume < min_volume` (50) is a hard reject **unless** `volume == 0 and oi >= min_open_interest`.
     The comment calls 0 "Tradier's off-hours sentinel" and OI "the real liquidity proxy".
   - `oi < min_open_interest` (200) is a separate hard reject.
   - Result: volume 0 with OI 319 passes; volume 3 with OI 1,534 is rejected. The better-traded contract
     loses (AAPL 315C 2027-04-16: vol 3, OI 1,534, spread 1.2%, REJECT).
2. `_score_liquidity` (`:152-165`) raises **two** soft flags from one axis: `low_volume` (< 200) and
   `low_open_interest` (< 1,000). `validate_contract` rejects at `max_soft_fail_count` = 3 flags
   (`:453-456`). A long-dated contract usually carries both liquidity flags, so a single further flag
   (spread > 8%, delta outside 0.30–0.70, DTE, IV) rejects it.
3. `volume` is Tradier's **session-to-date** count: `market.py:817` reads `int(c.get("volume") or 0)`, so a
   missing value also becomes 0. The option chain is Tradier-only (the yfinance `volume` lines in
   `market.py` are candle bars, not chains — this corrects my earlier review, finding 6).
4. **Spread off-hours is fabricated, not measured.** `market.py:808-813`: when `ask == 0` (Tradier outside
   market hours) the contract's price falls back to `last` and `spread = 0.0`; `augment.py:94-95` then builds
   `bid = ask = last`, so `spread_pct` is 0 and passes both the hard spread cap and the soft 8% preference.
   PRD FR-24 lists "missing bid or ask" and "spread cannot be calculated" as **hard rejects**. (From reading
   the code; not yet observed off-hours — the sample below was taken in session and saw 1 zero spread in
   8,389 contracts.)
5. Callers of `validate_contract`: `routers/scan.py` (scan) and `routers/contracts.py:244` (Step 6 and the
   Watchlist refresh). `augment.py` only mentions it in a docstring. No auto-trade path calls it directly;
   auto-trade consumes scan results, so it inherits whatever the scan grades.
6. `min_volume` is a user-facing Step 3 parameter ("Min option volume", `step-3-direction/page.tsx:299`),
   in all four presets of `executionParamDefaults.ts`, and can be carried by saved search profiles and by a
   scan's `contract_rules` (STEP6-SCAN-CONTRACT-RULES).
7. **The PRD already says volume is soft.** FR-24 (hard) lists "open interest equals zero" and spread over
   the hard threshold, not volume. FR-25 (soft) lists "daily volume below preferred threshold" and "open
   interest below preferred threshold but above zero". Today's code is stricter than the spec on volume and
   looser than it on missing quotes (item 4). My earlier review (finding 12) had this backwards.
8. Tests that pin the current behaviour: `tests/test_overrides.py`, `tests/test_step6_contract_rules.py`,
   `tests/test_strategy_engine.py` (grep `min_volume|volume_too_low|low_volume|too_many_soft_failures`).

### Corrections to the conversation that led here

- The scan ran at **15:24 UTC (11:24 ET), mid-session** — its volumes were partial-day. "Same contract,
  different verdict by time of day" holds for the scan (my review's finding 9 wrongly said the screenshots
  were after the close).
- Step 6's MSFT "A — Recommended" row (575C, REJECT 34) is **not** the scan's contract. The scan picked
  **MSFT 515C** (contract score 50, CAUTION); Step 6 never lists it because `max_price` filters it out
  (~$58 premium). That is the residual `contracts.py` already documents ("the card's contract can still be
  absent here"). Out of scope here; noted under §7.

## 2. Measurement (2026-09-30, 13:24 ET, in session)

**Method:** 60 symbols drawn at random (seed 7) from the scan's names that reached an option chain.
`GET /api/contracts` with calls, `limit=100`, `max_price=500`, and hold windows 5–15 / 15–45 / 45–60 / 98–105
days (DTE ≈ 2× hold; one expiry per chain). Kept only contracts with delta 0.20–0.85 (the current hard delta
band). Volume is **partial-day** (13:24 ET). One day, calls only, Tradier only, a sample biased toward names
that scored bullish. Enough to size the problem, not to set final numbers.

| Window (DTE) | Contracts / symbols | Volume p50 / p90 (share at 0) | OI p50 / p90 | Spread p50 / p90 |
|---|---|---|---|---|
| Swing (16–23) | 567 / 59 | 1 / 36 (49%) | 37 / 496 | 12.8% / 32.9% |
| Position (51) | 614 / 60 | 3 / 162 (39%) | 165 / 3,360 | 7.9% / 23.2% |
| Quarterly (107) | 798 / 57 | 1 / 60 (48%) | 432 / 4,729 | 7.3% / 21.4% |
| Semi-annual (198) | 472 / 29 | 0 / 7 (77%) | 16 / 231 | 8.9% / 31.2% |

Symbols with at least one contract that clears each rule set (and, second number, also has fewer than 3 of
the liquidity/spread/delta soft flags — DTE and IV flags not modelled, so this is optimistic):

| Window | Today's hard liquidity rules | OI ≥ 200 + spread ≤ 20% only | Same + one merged liquidity flag |
|---|---|---|---|
| Swing | 18 → 9 | 29 → 15 | 28 |
| Position | 30 → 19 | 38 → 29 | 35 |
| Quarterly | 48 → 28 | 51 → 39 | 48 |
| Semi-annual | 8 of 29 → 3 | 11 → 7 | 10 |

Contracts with OI ≥ 200 and spread ≤ 20% that are rejected **only** for 1–49 volume today: swing 58 (22 symbols),
position 148 (32), quarterly 268 (43), semi-annual 38 (8).

**What the numbers say:**

1. The zero-vs-small-volume inconsistency is real at every horizon, not just 6 months out, and it is the
   largest single avoidable loss (quarterly: 268 good contracts across 43 of 57 names).
2. Two liquidity soft flags are the next-largest loss: merging them roughly doubles the survivors that also
   clear the soft-failure count.
3. **Semi-annual is thin for real.** Only 29 of 60 names even list a ~198-day expiry, and their median OI is
   16. Even with fixes 1 and 2, about 10 of those 29 have a gradeable contract. Loosening the OI floor to
   make Semi-annual look healthy would admit genuinely illiquid contracts, so this plan does **not** scale
   the OI floor by DTE. The honest answer for Semi-annual is in §6 Q4, not in a lower bar.
4. The review's idea of DTE-scaled *preferred* minimums is not supported by the data: OI grows with DTE up to
   quarterly and then collapses; volume is low everywhere. A merged flag (fix 2) does the work without
   inventing a DTE curve.

## 3. Design

**Fix 1 — volume stops being a hard reject (matches PRD FR-25).**
Remove the `volume_too_low` branch from `_hard_reject_reasons`. Liquidity hard gates become OI
(`min_open_interest`) and spread (`max_bid_ask_spread_pct`). The zero-volume exemption disappears with it —
there is nothing left to exempt. Volume stays in the liquidity score and the merged soft flag.
What happens to the `min_volume` override is Q1.

**Fix 2 — one liquidity soft flag.**
`_score_liquidity` raises a single `thin_liquidity` flag when volume < `preferred_volume_min` **or** OI <
`preferred_oi_min` (both still configurable, both still shown in the detail). The liquidity score itself is
unchanged (volume and OI still each weigh half), so a thin contract still scores lower; it just stops
spending two of its three soft-failure allowance on one axis. `low_volume` / `low_open_interest` stay visible
as detail text so the reason is not lost (exact shape decided in the plan round).

**Fix 3 — no fabricated spread.**
When the chain has no live bid/ask (Tradier `ask == 0`), mark the contract `quote_stale` instead of building
`bid = ask = last`. Grading then treats the spread as unknown (Q3 decides: hard reject per FR-24, or grade
without the spread rule and label it). The price may still fall back to `last` for display. Must be verified
off-hours before building — §1 item 4 is from reading the code.

**Fix 4 — tests and visibility.**
- Unit: vol 3 / OI 1,534 / tight spread → not hard-rejected; vol 0 and vol 3 with identical other fields
  grade identically; OI 150 → `open_interest_too_low` regardless of volume; volume < pref and OI < pref →
  exactly one liquidity flag; `ask == 0` chain row → `quote_stale`, never a 0% spread.
- Both callers: a scan test and a `/api/contracts` test asserting the same contract grades the same on both.
- Mutations: restore the volume hard reject; restore two flags; restore `bid = ask = last` — each must fail a test.
- Update the pinned tests listed in §1 item 8 deliberately, one by one, not by bulk edit.

## 4. Out of scope (named, not done)

- DTE-scaled OI or preferred minimums (data does not support them; see §2 point 4).
- Step 6 not listing the scan's own contract when `max_price` cuts it (MSFT 515C) — existing documented
  residual; separate task if wanted.
- Why IV rank 52 against a preferred max of 55 scores only 4–5/100 on IV attractiveness — worth a look,
  separate task.
- The funnel's single "Score + contracts" row hiding `failed_score` vs `failed_contracts` — separate UI task.

## 5. Expected effect

On the §2 sample (optimistic, see caveats): names with a gradeable contract roughly Swing 9 → 28,
Position 19 → 35, Quarterly 28 → 48, Semi-annual 3 → 10 of 29. The scan's end count also depends on the
stock-score gates (`min_stock_score` 55 cut 97 of the 148 contract-stage names in the 2026-09-30 scan), which
this plan does not touch. Expect Semi-annual scans to stay small.

## 6. Questions for Kenneth

**ANSWERED 2026-09-30 (decision `CONTRACT-LIQUIDITY-DTE-ANSWERS-2026-09-30`): all four recommendations —
Q1 (b), Q2 yes, Q3 (a) in scan/auto-trade with a label-only treatment in Step 6/Watchlist, Q4 (a).**
Consequence of Q1 (b): a saved search profile that explicitly set `min_volume` keeps that value as its
hard floor; profiles are not rewritten.

- **Q1 — `min_volume` after fix 1.** (a) Remove it from Step 3, the presets and `CONTRACT_OVERRIDE_KEYS`;
  saved profiles that carry it are ignored with a one-line notice. (b) Keep it as an *optional* hard floor,
  default 0 (off), so a user can still demand volume. (c) Keep it, but only applied when the quote is live and
  DTE ≤ 60. Recommendation: **(b)** — the spec makes volume soft, and a default of 0 changes nothing for anyone
  who never set it, while keeping the knob honest.
- **Q2 — merged flag.** Accept fix 2 as designed (one flag, score unchanged)? Recommendation: yes.
- **Q3 — no live quote.** (a) Hard reject as `quote_stale` (FR-24). (b) Grade without the spread rule and
  label the row "no live quote". Recommendation: **(a)** for the scan and auto-trade; (b) only as a label in
  Step 6/Watchlist. Note (a) means off-hours scans return far fewer candidates — which is correct, since
  nobody can know the spread then.
- **Q4 — Semi-annual.** The data says 6-month options on most S&P names are thin. Options: (a) leave it and
  let the funnel say so; (b) for Semi-annual/Annual, cap the DTE multiplier (e.g. 1.5× instead of 2×) so
  contracts land in the liquid ~100–150 day band and are rolled; (c) steer long horizons to Stocks mode.
  Recommendation: **(a) now**, (b) as a separate measured task if you want it.

## 7. Loop

Kenneth answers §6 → plan round (adversarial) until clean → build with tests and mutations → code round
until clean → merge. Measurement script: `backend/scripts/contract_liquidity_sample.py`; rerun off-hours to verify
§1 item 4 before fix 3 is built.
