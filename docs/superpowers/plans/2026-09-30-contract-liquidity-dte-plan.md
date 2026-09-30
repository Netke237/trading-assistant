# CONTRACT-LIQUIDITY-DTE — plan (r3: narrowed to fixes 1+2 after round 2; NOT audited clean; nothing built)

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
   So auto-trade needs its own gate (now phase `NO-LIVE-QUOTE`).
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

## 3. Design (r3 — fixes 1 and 2 only; fix 3 split out)

**Fix 3 moved to its own phase** on 2026-09-30, by Kenneth's call (decision
`CONTRACT-LIQUIDITY-DTE-SPLIT-2026-09-30`). It is the off-hours "no live quote" treatment; see
`docs/superpowers/plans/2026-09-30-no-live-quote-plan.md` and phase `NO-LIVE-QUOTE`. It produced every high
finding across plan rounds 1 and 2, and its input (what Tradier returns off-hours) has never been observed.
This plan changes nothing about quotes or spreads, so the fabricated off-hours 0% spread (§1 item 4) stays
exactly as it is on main: no better, no worse.

**Fix 1 — volume is no longer a hard reject by default (FR-25; Q1 (b)).**
- Default `min_volume` goes from 50 to 0:
  - `backend/config/contract_rules.yaml`, `hard_reject.min_volume`, with its comment changed to "optional
    hard floor; 0 = off (FR-25 treats volume as soft)";
  - every row of `PARAM_DEFAULTS_PER_HORIZON` in `frontend/lib/executionParamDefaults.ts`. There are four
    literals (:31, :59, :85, :115), but the test covers every horizon key: Intraday, Swing, Position,
    Quarterly, SemiAnnual, Annual and Custom.
- `_hard_reject_reasons` (`contract_validator.py:84-85`): the volume branch gains an explicit
  `hr["min_volume"] > 0 and` guard.
  - The guard changes nothing for integer volumes: `volume < 0` is never true. It states the "0 = off"
    meaning in code, and the defect-marker probe (§7) relies on it.
  - The **zero-volume exemption stays** for an explicit floor above 0. Without a live-quote signal
    (NO-LIVE-QUOTE) volume 0 off-hours cannot be told apart from no trades, and deleting the exemption
    would reject every off-hours row for anyone with a floor.
  - So for a user who opts into a floor, "vol 0 / OI ≥ 200 passes, vol 3 fails" stays as it is today. That
    is a known, recorded residual that NO-LIVE-QUOTE revisits. At the default floor of 0 it disappears.
- Step 3 (`step-3-direction/page.tsx:299-300`):
  - the label becomes "Min option volume (0 = off)", and the hint says it is an optional hard floor, off
    by default, because volume is scored softly under Preferred Liquidity;
  - the `preferred_volume_min` hint (:319), which calls it "the hard 'Min option volume' floor above", is
    reworded to match;
  - the field, its `min: 0` and `CONTRACT_OVERRIDE_KEYS` stay.
- Saved search profiles and a scan's stored `contract_rules` are not rewritten. A profile that explicitly
  set `min_volume` keeps it as its floor. Step 3's `scanOverrides` holds only user-edited keys and is not
  persisted, so everyone else gets 0.
- `min_open_interest` (200) and `max_bid_ask_spread_pct` (0.20) are unchanged. They remain the liquidity
  hard gates.

**Fix 2 — one liquidity soft flag (Q2).**
- `_score_liquidity` (`contract_validator.py:152-165`) appends one `thin_liquidity` flag when either of
  these holds:
  - `pref_volume_min > 0 and volume < pref_volume_min`;
  - `pref_oi_min > 0 and oi < pref_oi_min`.
- It replaces `low_volume` and `low_open_interest`.
- The score arithmetic is unchanged: volume and OI still each weigh half.
- No UI or backend code reads the old flag names. I checked with grep over `frontend/` and `backend/app`;
  the only consumer is `len(soft_flags)` at `:453`.
- The reason stays visible through `detail["liquidity"]`, which already emits volume, OI and both preferred
  minimums.
- The Step 3 hints for `preferred_volume_min` and `preferred_oi_min` (:319, :321) say each "counts as one
  soft miss". They are reworded: "volume and open interest together count as at most one soft miss".
  The block comment above them (:309-317) is updated the same way.

**Fix 4 — tests, mutations, docs.** Each test names its home file.

*Backend, `backend/tests/test_contract_validator.py`:*
- vol 3 / OI 1,534 / spread 1.2% (the AAPL 315C shape) is not hard-rejected at the default config.
- At the default floor, vol 0 and vol 3 with every other field identical give an identical hard-reject list
  and an identical flag set. Scores are not compared: `int(3/200*60) == 0` makes them equal only by
  truncation.
- With `min_volume=50`:
  - vol 3 → `volume_too_low`;
  - vol 0 with OI ≥ 200 → not `volume_too_low`, because the exemption is kept, as pinned today by
    `test_overrides.py:300,311`.
- OI 150 → `open_interest_too_low` regardless of volume.
- `thin_liquidity` appears exactly once in each case:
  - vol < pref and OI < pref;
  - vol < pref only;
  - OI < pref only.

  No flag appears when both are at or above pref. `low_volume` and `low_open_interest` never appear.
- A contract with `thin_liquidity` plus exactly two other soft flags (spread above 8% and delta outside
  0.30–0.70) is `too_many_soft_failures`. The same contract with thin liquidity and one other flag is not.
  That pins "one axis costs one slot".
- A default-config test calls `validate_contract` with no overrides, so a YAML-default regression is caught
  and not masked by an override.

*Backend, updated deliberately, one by one:*
- `test_overrides.py`: every `low_volume` / `low_open_interest` assertion (:153-238, :277-290) moves to
  `thin_liquidity`. Tests named "…still_flags_low_volume" are renamed. `test_min_volume_override_rejects_illiquid`
  (:123) keeps its meaning.
- `test_step6_contract_rules.py`: its `_LOOSE` floors are unchanged; re-run it, and edit it only if an
  assertion names an old flag.
- The rest of §1 item 8 runs as part of the full suite. Any failure is examined, and fixed or justified in
  the commit, never bulk-edited.

*Frontend (Jest):*
- `lib/__tests__/executionParamDefaults.minVolume.test.ts` (new) asserts `min_volume === 0` for every
  `PARAM_DEFAULTS_PER_HORIZON` key, and that `min_open_interest` and `max_bid_ask_spread_pct` are unchanged.
  It follows the pattern of `executionParamDefaults.preferredLiquidity.test.ts`.
- `step-6-contracts/__tests__/contractRules.test.tsx` and `lib/__tests__/api.test.ts:147` pass explicit
  `min_volume` values and are expected to stay green unchanged.

*Mutations*, each of which must turn a named test red:
1. The YAML default goes back to `min_volume: 50`. The AAPL-shape test in `test_contract_validator.py`
   goes red.
2. One horizon row in `executionParamDefaults.ts` goes back to 50. `executionParamDefaults.minVolume.test.ts`
   goes red.
3. Restore two flags (`low_volume` + `low_open_interest`). The exactly-once test and the soft-slot test go
   red.
4. The merged flag only fires on volume. The OI-only case goes red.
5. Delete the zero-volume exemption. The `min_volume=50`, vol 0 case goes red.

*Docs:*
- CLAUDE.md needs no change.
- FR-25 is now satisfied for volume. FR-24's missing-quote clause is NO-LIVE-QUOTE's job.
- `contract_rules.yaml` comments are updated as above.

*Operational:*
- `_load_config` is `lru_cache`d (`contract_validator.py:44`), so the backend must restart to pick up the
  YAML default.
- A persisted `scanResult` whose `contract_rules` lack `min_volume` is re-graded in Step 6 at the new
  default of 0, while its cards were graded at 50. Step 6 and Step 7 disagree until the next scan; this is
  accepted and needs no migration.

## 4. Out of scope (named, not done)

- DTE-scaled OI or preferred minimums (data does not support them; see §2 point 4).
- Step 6 not listing the scan's own contract when `max_price` cuts it (MSFT 515C) — existing documented
  residual; separate task if wanted.
- Why IV rank 52 against a preferred max of 55 scores only 4–5/100 on IV attractiveness — worth a look,
  separate task.
- The funnel's single "Score + contracts" row hiding `failed_score` vs `failed_contracts` — separate UI task.
- Everything about quotes and spreads — fix 3 of r0–r2 — is now phase `NO-LIVE-QUOTE`
  (`2026-09-30-no-live-quote-plan.md`), which carries the round-2 findings as its starting list.
- ScanLog's reason parser mismatch (`[reason×N]` expected vs `reason(N)` emitted) — pre-existing, separate.

## 5. Expected effect

On the §2 sample (optimistic, see caveats): names with a gradeable contract roughly Swing 9 → 28,
Position 19 → 35, Quarterly 28 → 48, Semi-annual 3 → 10 of 29. The sample was taken in session, so it
measures fixes 1 and 2 alone; the split-off fix 3 does not change these numbers. The scan's end count also depends on the
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

- **Rounds so far:**
  - Round 1 (r1): 3 high, 7 medium, 6 low, all fixed in r2.
  - Round 2 (r2): 6 high, 6 medium, 8 low. Every high one was in fix 3; that led to the split (r3). Findings
    on fix 3 moved to NO-LIVE-QUOTE. Finding 16 (the preset test must cover every horizon key and be
    named) is fixed here. Finding 20 (reasons accumulate) is moot here, because fix 1 keeps today's
    exemption.
- **Next:** plan round 3 on r3 until clean → build with tests and mutations → code round until clean →
  merge.
- **Phase probe (§ PROJECT_STATE):** a defect marker on `min_volume: 50` in `contract_rules.yaml`. It goes
  away when fix 1 is built.
