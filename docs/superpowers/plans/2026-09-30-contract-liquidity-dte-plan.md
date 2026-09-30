# CONTRACT-LIQUIDITY-DTE — plan (r2: round-1 findings fixed; NOT audited clean; nothing built)

- **Phase:** `CONTRACT-LIQUIDITY-DTE` (PROJECT_STATE.json). Status `not_started`.
- **Branch:** `claude/contract-liquidity-dte` (from `origin/main` at `599b9da2`).
- **Origin:** Kenneth, 2026-09-30, looking at the Semi-annual Bullish SP500 options scan (518 scanned → 2
  candidates) and at Step 6, where almost every contract in the MSFT and AAPL chains read REJECT. An
  adversarial review of the first proposal ("drop the volume hard reject") found it weaker than stated; this
  plan replaces it and starts from measured data instead.
- **Kenneth answered §6 on 2026-09-30** (all recommendations). No code until a plan round is clean.

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
   Watchlist refresh). `augment.py` only mentions it in a docstring. **Auto-trade does not inherit the
   scan's grade** (corrected in r2, round 1 H2):
   - `auto_trader.maybe_fire_on_scan` (`auto_trader.py:2726`) fires the strategy the user *armed* from a
     card, and the scan is only its trigger, not a gate.
   - The armed contract can be a Step 6 pick.
   - The only fire-time market check, `_market_is_open` (`:417`), probes whether a *stock* price comes
     back, and one does off-hours too.
   - Booking (`auto_trade_booking.py:366`) happens *after* the broker order.
   So auto-trade needs its own gate (fix 3).
6. `min_volume` is a user-facing Step 3 parameter ("Min option volume", `step-3-direction/page.tsx:299`),
   in all four presets of `executionParamDefaults.ts`, and can be carried by saved search profiles and by a
   scan's `contract_rules` (STEP6-SCAN-CONTRACT-RULES).
7. **The PRD already says volume is soft.** FR-24 (hard) lists "open interest equals zero" and spread over
   the hard threshold, not volume. FR-25 (soft) lists "daily volume below preferred threshold" and "open
   interest below preferred threshold but above zero". Today's code is stricter than the spec on volume and
   looser than it on missing quotes (item 4). My earlier review (finding 12) had this backwards.
8. Tests that may pin the current behaviour (r2, re-derived by grep; the full suites are the arbiter).
   - Backend (`backend/tests/`): `test_contract_validator.py`, `test_contracts_scoring.py`, `test_overrides.py`,
     `test_step6_contract_rules.py`, `test_iv_null_wire.py`, `test_market_data_fixes.py`, `test_alternatives.py`,
     `test_scan_endpoint.py`, `test_scan_iv_rank.py`, `test_scan_router_spreads.py`, `test_trade_plan.py`,
     `test_integration.py`, `test_horizon_dte.py`.
   - Frontend: `step-6-contracts/__tests__/contractRules.test.tsx` (LOOSE `min_volume: 20`),
     `lib/__tests__/api.test.ts:147`, `__tests__/step6-topN.test.tsx`, `TradeCard/__tests__/*`,
     `SendToBrokerDialog/__tests__/index.test.tsx`, `AutoTradeArm/__tests__/AutoTradeArm.test.tsx`,
     `ScanLog/__tests__/*`.
   - `tests/test_strategy_engine.py` is **not** relevant: its one match is a stock-bar volume test. r1
     listed it wrongly.

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

| Window | Today's hard liquidity rules (clear → also < 3 flags) | OI ≥ 200 + spread ≤ 20% only (clear → also < 3 flags) | Same, with one merged liquidity flag (also < 3 flags) |
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
2. Two liquidity soft flags are the next-largest loss. Merging them raises the names that also clear the
   soft-failure count from 15 → 28 (Swing), 29 → 35, 39 → 48 and 7 → 10. That roughly doubles only for Swing.
3. **Semi-annual is thin for real.** Only 29 of 60 names even list a ~198-day expiry, and their median OI is
   16. Even with fixes 1 and 2, about 10 of those 29 have a gradeable contract. Loosening the OI floor to
   make Semi-annual look healthy would admit genuinely illiquid contracts, so this plan does **not** scale
   the OI floor by DTE. The honest answer for Semi-annual is in §6 Q4, not in a lower bar.
4. The review's idea of DTE-scaled *preferred* minimums is not supported by the data: OI grows with DTE up to
   quarterly and then collapses; volume is low everywhere. A merged flag (fix 2) does the work without
   inventing a DTE curve.

## 3. Design (r1 — Kenneth's §6 answers folded in)

**Fix 1 — volume is no longer a default hard reject (FR-25; Q1 (b)).**
- `_hard_reject_reasons`: replace the volume branch with
  `if hr["min_volume"] > 0 and volume < hr["min_volume"]: reasons.append("volume_too_low")`.
  The zero-volume/OI exemption is deleted. A floor of 0 is off. A floor above 0 is the user's explicit
  request and applies literally, including to volume 0: a pre-market scan with live quotes and a profile
  floor rejects every row as `volume_too_low`. Off-hours rows without a live quote are rejected first as
  `no_live_quote`. That holds only if the fix-3 verification gate (3g) passes.
- Default `min_volume` 50 → 0 in `backend/config/contract_rules.yaml` and in all four presets of
  `frontend/lib/executionParamDefaults.ts` (:31, :59, :85, :115). Step 3's label becomes
  "Min option volume (0 = off)"; the field, its `min: 0` and `CONTRACT_OVERRIDE_KEYS` stay.
- Saved search profiles and a scan's stored `contract_rules` are not rewritten. A profile that explicitly
  set `min_volume` keeps it as its floor (decision `CONTRACT-LIQUIDITY-DTE-ANSWERS-2026-09-30`).
- `min_open_interest` (200) and `max_bid_ask_spread_pct` (0.20) are unchanged. They remain the liquidity
  hard gates.

**Fix 2 — one liquidity soft flag (Q2).**
`_score_liquidity` appends one `thin_liquidity` flag when `(pref_volume_min > 0 and volume < pref_volume_min)`
or `(pref_oi_min > 0 and oi < pref_oi_min)`. It replaces `low_volume` and `low_open_interest`. The score
arithmetic is unchanged: volume and OI still each weigh half. No UI reads the old flag names; checked with
grep over `frontend/` and `backend/app`, and the only consumer is `len(soft_flags)`. The reason stays
visible through `detail["liquidity"]`: volume, OI and both preferred minimums are already emitted.

**Fix 3 — a contract with no live two-sided quote is never graded or traded as a 0% spread (FR-24; Q3 (a)
plus a label).** The reason key is `no_live_quote`; it replaces r1's `quote_stale`. It also covers FR-24's
"missing bid", so the name had to be broader.

*3a. Data.*
- `fetch_option_chain_async` (`market.py` ~:1489-1496, the live one) and its dead sync twin (`:808-814`,
  changed identically) set `"quote_live": bid > 0 and ask > 0` on every row.
- When `quote_live` is False, the row's `spread` is `None` instead of `0.0`. `price` still falls back to
  `last`, for display only.
- `fetch_contract_quote_async` returns the chain row, so the quote endpoint and every quote consumer see the
  same two fields.
- `_augment` (`augment.py:94-95`) passes `quote_live` through. When it is False, `_augment` sets
  `bid = ask = None` in place of `mid ± spread/2`.

*3b. Grading.* `validate_contract(..., stale_quote: Literal["reject", "label"] = "reject")`.
- The rule fires only when `contract.get("quote_live") is False`. A missing key counts as live, so fixtures
  and hand-built dicts keep working. A test pins that both chain builders always set the key.
- In both modes:
  - the spread hard and soft rules are skipped for that row, so the one cause is not also reported as
    `spread_too_wide`;
  - `detail["spread"]["spread_pct"]` is `None`, never the 1.0 that `_score_spread` computes from a zero
    mid;
  - the new `ContractScoreCard.no_live_quote` is True.
- `"reject"` (the default, so any new caller is safe): hard reject reason `no_live_quote`.
- `"label"`: the row is graded on the other axes, with a spread score of 0 (unknown counts as worst).
  - Its status is capped at CAUTION, so a row without a live quote can never read PASS.
  - This is a deliberate, recorded deviation from FR-24's "blocks recommendation" for the display path
    only. It is logged as a decision when the plan is clean, and §3 Docs no longer claims FR-24 is
    satisfied everywhere.

*3c. Callers and wire.*
- `routers/scan.py:852` keeps `"reject"`.
- `routers/contracts.py:244` (Step 6 and the Watchlist refresh) passes `"label"`.
- `OptionContract` (schemas `:224`) gains `noLiveQuote: bool = False`. `OptionContract.spread`,
  `ContractQuoteResponse.spread` and `SpreadDetail.spread_pct` become `Optional[float]`.
- `scan.py:1015-1016` reads `float(contract.get("bid", 0))`. Under `"reject"` it can't be reached with
  `bid = None`, since picks come only from non-REJECT cards. It is still hardened to treat None as missing,
  so the default-flip mutation fails on an assertion and not on a TypeError.

*3d. Auto-trade fire gate (round 1 H2).*
- New `_option_quote_is_live(option_symbol)` in `auto_trader.py`, next to `_market_is_open`, with the same
  pattern: worker thread, 3 s deadline, never under the lock. It fetches the contract's chain row.
  - It returns True only for a row with `quote_live is True`.
  - Exception, timeout, a missing row or False all refuse.
- `fire()` calls it right after `_market_is_open` for an option strategy (a 4-part `option_symbol`),
  *before* any broker call, and refuses with a named history reason: "no live option quote for
  <contract>".
- Stock strategies are untouched.

*3e. Frontend.*
- Step 6 (`step-6-contracts/page.tsx`) and the Watchlist Contracts tab (`watchlist/page.tsx`):
  - a "no live quote" tag on rows with `noLiveQuote`;
  - the SPREAD column renders "—" for `spread == null` and sorts it last;
  - such rows are never chosen as the "A — Recommended" row (`page.tsx:239`).
- `applyPickedContract` (`lib/tradeCardOverride.ts:26`) carries `noLiveQuote` onto `TradeCardData`, and a
  scan card defaults it to false.
- Step 7 (`TradeCard`) and `SendToBrokerDialog` show a "no live quote — entry price is the last trade"
  warning. It does **not** block: a manual limit order after hours is the user's call (Q3 said label
  outside the scan).
- Recompute-plan for such a pick sends `spread: null`.
  - `contracts.py`'s request model makes `spread` Optional; when it is None, `entry_bid = entry_ask = None`.
  - `assess_entry` (`entry_quality.py:51`) accepts None bid/ask and returns CAUTION with the reason
    "no live quote", with no spread reasons.
- The `OptionContract` and `TradeCardData` TS types gain the optional field, and the Jest mocks in
  `frontend/__mocks__/` are updated.
- `ScanLog`'s `REASON_CATEGORY` (`ScanLog/index.tsx:27`) gains `no_live_quote: 'DATA'`.

*3f. Consequences, stated honestly.*
- An off-hours options scan returns few or no candidates. Each affected name's rejection reason string
  reads `contracts rejected: no_live_quote(N)`, and the funnel counts it under the existing
  `failed_contracts` bucket. The funnel does **not** get its own `no_live_quote` row (§4).
- Scheduled options scans (`scan_schedule_scheduler.py:56-64,129-145`): a run with zero candidates and at
  least one `no_live_quote` rejection skips its rank diff and change notification. It sends one notice
  instead: "options scan at <time> ran without live option quotes". The previous row stays the diff base.
- Such a run can still trigger `maybe_fire_on_scan`, which 3d then refuses for an option strategy.

*3g. Verification gate: before any of fix 3 is built.*
- The off-hours shape is read from code comments, never observed. Rerun
  `backend/scripts/contract_liquidity_sample.py` pre-market, after the close and at a weekend. For every row,
  record `bid`, `ask`, `last`, `volume`, `bid_date`, `ask_date` and `trade_date`.
- Pass condition: off-hours rows show `bid == 0 or ask == 0`, and in-session rows are two-sided with
  current `bid_date`/`ask_date`.
- If off-hours rows carry non-zero *closing* quotes instead, `bid > 0 and ask > 0` cannot tell stale from
  live. The pre-decided fallback is then a quote age: stale when `max(bid_date, ask_date)` is older than 15
  minutes. That changes 3a, so fix 3 goes back for its own plan round.
- Fix 1's sentence "off-hours rows never reach the volume rule in the scan" holds only if this gate passes.

**Fix 4 — tests, mutations and visibility.** Each new test names its home file.

*Grading — `backend/tests/test_contract_validator.py`:*
- vol 3 / OI 1,534 / spread 1.2% is not hard-rejected.
- vol 0 and vol 3, otherwise identical, give an identical hard-reject list and flag set at the default floor.
  Scores are asserted only where they are defined to match; with `int(3/200*60) == 0`, vol 4 would differ.
- `min_volume=50`: vol 0 and vol 3 are both `volume_too_low` (explicit floor, no exemption). With a live
  quote and vol 0 the reason is `volume_too_low`, not `no_live_quote`.
- OI 150 gives `open_interest_too_low` regardless of volume.
- vol < pref and OI < pref give exactly one `thin_liquidity` flag; either one alone gives the same one flag.
- `quote_live=False` under `"reject"`: reason `no_live_quote` and no `spread_too_wide`;
  `detail["spread"]["spread_pct"] is None`; `no_live_quote` is True.
- `quote_live=False` under `"label"`: not rejected for spread; spread score 0; `spread_pct is None`; status
  never above CAUTION, even when every other axis is perfect.
- A missing `quote_live` is treated as live.

*Data — `backend/tests/test_market_data_fixes.py`:*
- Tradier rows go through `fetch_option_chain_async`:
  - `ask == 0, last > 0` → `quote_live False` and `spread is None`;
  - `bid == 0, ask > 0` → `quote_live False`;
  - two-sided → `quote_live True` and a numeric spread.
- A parity assertion runs the same rows through the sync twin.
- `_augment` on a `quote_live False` row gives `bid is None and ask is None`.

*Callers:*
- `backend/tests/test_step6_contract_rules.py` + `test_scan_endpoint.py`: the same live contract grades
  identically through the scan and `/api/contracts`.
- The same two files: a no-live-quote row is rejected by the scan, and returned by `/api/contracts` with
  `noLiveQuote: true`, `spread: null` and status ≤ CAUTION.

*Auto-trade and entry:*
- `backend/tests/test_auto_trader*.py` (the existing fire-gate test file):
  - `fire()` on an option strategy whose quote row is `quote_live False`, missing, raising or timing out
    refuses with the named reason and places no broker call;
  - a live row fires as before;
  - a stock strategy never calls the quote probe.
- `backend/tests/test_trade_plan.py`: recompute-plan with `spread: null` gives entry quality CAUTION with
  "no live quote", and no spread reason.

*Scheduled scans — the scan-schedule test file:* a zero-candidate run with `no_live_quote` rejections skips
the diff and notification, sends the one notice and keeps the previous row as the diff base.

*Frontend (Jest):*
- Step 6 and the Watchlist:
  - the tag renders;
  - SPREAD renders "—" and sorts last;
  - a no-live-quote row is never Recommended.
- `applyPickedContract` carries `noLiveQuote`.
- TradeCard and SendToBrokerDialog show the warning and do not block.
- The preset defaults test asserts `min_volume: 0` in all four presets.
- ScanLog files `no_live_quote` under DATA.

*Mutations* — each must turn a named test red, on an assertion rather than a TypeError:
1. Restore the volume hard reject at 50.
2. Restore two liquidity flags.
3. Restore `bid = ask = last` in `_augment`.
4. Restore chain `spread = 0.0` for a row with no live quote.
5. `quote_live` keyed on `ask` only.
6. `quote_live` always True.
7. Flip the `stale_quote` default to `"label"`.
8. A no-live-quote row still reports `spread_too_wide` under `"reject"`.
9. Label mode's spread score is not 0.
10. Drop the CAUTION cap.
11. Drop `noLiveQuote` from the `/api/contracts` response.
12. `applyPickedContract` drops `noLiveQuote`.
13. Remove the auto-trade quote gate.
14. Remove `no_live_quote` from ScanLog's categories.
15. Remove the scheduled-scan diff skip.

*Pinned tests and docs:*
- The pinned tests from §1 item 8 are updated one by one, not by bulk edit. Each change gets a one-line
  reason in the commit.
- CLAUDE.md needs no change.
- FR-25 is satisfied.
- FR-24 is satisfied for the scan and auto-trade. It deviates, deliberately and as a recorded decision, for
  the Step 6 and Watchlist display path (3b).
- `contract_rules.yaml` comments are updated for the new `min_volume` meaning.

*Operational:*
- `_load_config` is `lru_cache`d (`contract_validator.py:44`), so the backend must restart after the YAML
  default changes.
- A persisted `scanResult` whose `contract_rules` lack `min_volume` is re-graded in Step 6 at the new default
  of 0, while its cards were graded at 50. That is a transient Step 6 vs Step 7 disagreement until the next
  scan; accepted, no migration.
- `scanOverrides` is not persisted, so the new defaults reach existing users.

## 4. Out of scope (named, not done)

- DTE-scaled OI or preferred minimums (data does not support them; see §2 point 4).
- Step 6 not listing the scan's own contract when `max_price` cuts it (MSFT 515C) — existing documented
  residual; separate task if wanted.
- Why IV rank 52 against a preferred max of 55 scores only 4–5/100 on IV attractiveness — worth a look,
  separate task.
- The funnel's single "Score + contracts" row hiding `failed_score` vs `failed_contracts` — separate UI task.
- A separate funnel row for `no_live_quote`. It stays inside `failed_contracts` (3f).
- ScanLog's reason parser expects `[reason×N]`, but the backend emits `reason(N)`, so the categories never
  match today. This is pre-existing. The plan adds the category key only, and the parser is a separate task.
- `spread_builder.py:43,81` reads `long["ask"]`/`short["bid"]`, which real chain rows don't carry. Bearish
  spread legs are therefore never built from real chains; the KeyError is swallowed at `scan.py:432-457`.
  This plan still does not put `bid`/`ask` on chain rows, so it doesn't wake that path. If a later change
  does, it must handle `quote_live` there.
- `position_writer`'s save-time quote refetch falling back to frontend values when no quote is available.
  Pre-existing and unchanged. The auto-trade gate (3d) runs before the broker call, not at booking.

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
- **Q3 — no live quote.** (a) Hard reject as `quote_stale` (FR-24; renamed `no_live_quote` in r2). (b) Grade without the spread rule and
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
