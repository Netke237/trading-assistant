# CONTRACT-LIQUIDITY-DTE — plan (r5: round-4 findings fixed, line refs re-based on main 4c520006; NOT audited clean; nothing built)

- **Phase:** `CONTRACT-LIQUIDITY-DTE` (PROJECT_STATE.json). Status `not_started`.
- **Branch:** `claude/contract-liquidity-dte` (from `origin/main` at `599b9da2`).
- **Origin:** Kenneth, 2026-09-30, looking at the Semi-annual Bullish SP500 options scan (518 scanned → 2
  candidates) and at Step 6, where almost every contract in the MSFT and AAPL chains read REJECT. An
  adversarial review of the first proposal ("drop the volume hard reject") found it weaker than stated; this
  plan replaces it and starts from measured data instead.
- **Kenneth answered §6 on 2026-09-30** (all recommendations). No code until a plan round is clean.

## 1. What is true on main (599b9da2)

*Line references in `contract_validator.py` and `auto_trader.py` are re-based onto main `4c520006`,
merged into this branch 2026-09-30. DOCC-4 added 11 lines to `contract_validator.py` (the config-health
watch); nothing else in scope moved.*

1. `contract_validator._hard_reject_reasons` (`contract_validator.py:95-98`):
   - `volume < min_volume` (50) is a hard reject **unless** `volume == 0 and oi >= min_open_interest`.
     The comment calls 0 "Tradier's off-hours sentinel" and OI "the real liquidity proxy".
   - `oi < min_open_interest` (200) is a separate hard reject.
   - Result: volume 0 with OI 319 passes; volume 3 with OI 1,534 is rejected. The better-traded contract
     loses (AAPL 315C 2027-04-16: vol 3, OI 1,534, spread 1.2%, REJECT).
2. `_score_liquidity` (`:163-176`) raises **two** soft flags from one axis: `low_volume` (< 200) and
   `low_open_interest` (< 1,000). `validate_contract` rejects at `max_soft_fail_count` = 3 flags
   (`:464-467`). A long-dated contract usually carries both liquidity flags, so a single further flag
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
   - `auto_trader.maybe_fire_on_scan` (`auto_trader.py:2736`) fires the strategy the user *armed* from a
     card, and the scan is only its trigger, not a gate.
   - The armed contract can be a Step 6 pick.
   - The only fire-time market check, `_market_is_open` (`:418`), probes whether a *stock* price comes
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

## 3. Design (r5 — fixes 1 and 2 only; fix 3 split out)

**Fix 3 moved to its own phase** on 2026-09-30, by Kenneth's call (decision
`CONTRACT-LIQUIDITY-DTE-SPLIT-2026-09-30`). It is the off-hours "no live quote" treatment; see
`docs/superpowers/plans/2026-09-30-no-live-quote-plan.md` and phase `NO-LIVE-QUOTE`. It produced every high
finding across plan rounds 1 and 2, and its input (what Tradier returns off-hours) has never been observed.
This plan changes nothing about quotes or spreads, so the fabricated off-hours 0% spread (§1 item 4) is
still built exactly as on main. **One accepted residual (round 3, finding 4):** fix 1 changes *which*
fabricated-spread rows survive.
- **Pre-market:** volume is 0, and the kept exemption already lets those rows through on main. No change.
- **After the close and overnight:** volume keeps the day's count. Rows with volume 1–49 that main rejected
  as `volume_too_low` now pass the hard gates with a fabricated 0% spread.
- So an evening scan and Step 6 after the close show more contracts graded on a spread nobody measured.
- The blast radius is the scan and the Step 6 display. Auto-trade does not inherit the scan's grade
  (§1 item 5), and its own off-hours gate is NO-LIVE-QUOTE's job.
- This residual is listed first on NO-LIVE-QUOTE's starting list. Kenneth can order NO-LIVE-QUOTE to land
  first if he doesn't want the window at all. The two phases have no code dependency in either direction,
  so neither lists the other in `depends_on`.

**Fix 1 — volume is no longer a hard reject by default (FR-25; Q1 (b)).**
- Default `min_volume` goes from 50 to 0:
  - `backend/config/contract_rules.yaml`, `hard_reject.min_volume`, with its comment changed to "optional
    hard floor; 0 = off (FR-25 treats volume as soft)";
  - every row of `PARAM_DEFAULTS_PER_HORIZON` in `frontend/lib/executionParamDefaults.ts`. There are four
    literals (:31, :59, :85, :115), but the test covers every horizon key: Intraday, Swing, Position,
    Quarterly, SemiAnnual, Annual and Custom.
- `_hard_reject_reasons` (`contract_validator.py:95-96`): the volume branch gains an explicit
  `hr["min_volume"] > 0 and` guard.
  - The guard changes nothing for integer volumes: `volume < 0` is never true. It only states the
    "0 = off" meaning in code; the phase probe does not depend on it.
  - The new YAML comment must not contain the string `min_volume: 50`, because the PROJECT_STATE defect
    marker matches `min_volume: 50\b` in that file.
  - The **zero-volume exemption stays** for an explicit floor above 0. Without a live-quote signal
    (NO-LIVE-QUOTE) volume 0 off-hours cannot be told apart from no trades, and deleting the exemption
    would reject every off-hours row for anyone with a floor.
  - So for a user who opts into a floor, "vol 0 / OI ≥ 200 passes, vol 3 fails" stays as it is today. That
    is a known, recorded residual that NO-LIVE-QUOTE revisits. At the default floor of 0 it disappears.
- Step 3 (`step-3-direction/page.tsx:299-300`):
  - the label becomes "Min option volume (0 = off)";
  - the hint says it is an optional hard floor, off by default, because volume is scored softly under
    Preferred Liquidity;
  - the hint also says the figure is **session-to-date** volume (§1 item 3), not a full-day total, so with
    a floor set, results change with the time of day;
  - the `preferred_volume_min` hint (:319), which calls it "the hard 'Min option volume' floor above", is
    reworded to match;
  - the field, its `min: 0` and `CONTRACT_OVERRIDE_KEYS` stay.
- Stored values are not rewritten; each of these keeps an explicit `min_volume` as its floor, and one
  without the key gets the new default of 0:
  - saved search profiles (browser);
  - a scan's stored `contract_rules`;
  - scheduled-scan entries' frozen `resolved_request` (`scan_schedule_scheduler.py:138`).

  Step 3's `scanOverrides` holds only user-edited keys and is not persisted.
- **Canonical profile seed (round 3, finding 5).** `docs/search-profiles/search-profiles-export.json` and the
  identical `RAW` string in `docs/search-profiles/import-search-profiles.js:21` seed 18 profiles:
  - `*_Loose_*` has `min_volume: 20`;
  - Intraday and Swing `*_Restrictive_*` have 200;
  - SemiAnnual `*_Restrictive_*` has 50;
  - the Baselines have none.

  After fix 1, every Loose profile would be *stricter* on volume than its Baseline. So the seed changes,
  all in one commit.
  - **JSON and JS:** `min_volume: 0` on the six Loose profiles, and their `updatedAt` moves to the build
    date, per the README's convention for edited profiles (`README.md:69-71`). The JS `RAW` string stays
    byte-identical to the JSON. Restrictive and Baseline profiles are untouched.
  - **The xlsx** mirrors the JSON; its legend says so. Update:
    - the six Baseline rows' Min Volume, 50 → 0 (they show the app default);
    - the six Loose rows' Min Volume, 20 → 0;
    - the legend's "SemiAnnual_Restrictive keeps volume at the Baseline floor (50)" → "keeps an explicit
      50; the Baseline floor is now 0 (off)";
    - the legend's "flagged 'low_volume'" and "flagged 'low_open_interest'" → "flagged 'thin_liquidity'
      (volume and open interest together count as one soft miss)";
    - the legend's Min Volume row → "optional hard floor; 0 = off".
  - **README.md:**
    - `:23` "min volume 50 (the Baseline floor)" → "an explicit min volume of 50 (the Baseline floor is now
      0, off)";
    - `:125` "0.30/20/75" → "0.30/0/75".
  - Profiles already imported into the browser are **not** touched (settled in §6). Kenneth re-imports or
    edits them if he wants the new Loose value.
- `min_open_interest` (200) and `max_bid_ask_spread_pct` (0.20) are unchanged. They remain the liquidity
  hard gates.

**Fix 2 — one liquidity soft flag (Q2).**
- `_score_liquidity` (`contract_validator.py:145-176`, flags at :172-175) appends one `thin_liquidity` flag when either of
  these holds:
  - `pref_volume_min > 0 and volume < pref_volume_min`;
  - `pref_oi_min > 0 and oi < pref_oi_min`.
- It replaces `low_volume` and `low_open_interest`.
- The score arithmetic is unchanged: volume and OI still each weigh half.
- No UI or backend code reads the old flag names. I checked with grep over `frontend/` and `backend/app`;
  the only consumer is `len(soft_flags)` at `:464`.
- The reason stays visible through `detail["liquidity"]`, which already emits volume, OI and both preferred
  minimums.
- The Step 3 hints for `preferred_volume_min` and `preferred_oi_min` (:319, :321) say each "counts as one
  soft miss". They are reworded: "volume and open interest together count as at most one soft miss".
  The block comment above them (:309-317) is updated the same way.

**Fix 4 — tests, mutations, docs.** Each test names its home file.

*Backend, `backend/tests/test_contract_validator.py`* — **fixture rules (round 3, findings 2 and 3).**
- Use the existing `_contract_with_expiry(40, …)` (`test_contract_validator.py:159-162`), not a new
  helper. It gives:
  - a computed expiry 40 days out, avoiding `_base_contract`'s past literal `2026-09-19` and 315C's real
    198 DTE, which `max_dte: 90` rejects;
  - bid 2.00 / ask 2.10 (4.9% spread);
  - delta 0.45;
  - `iv_rank` 30, snake_case, with no `iv_basis`, so it is judged as absolute against 55.
    (`test_overrides._make_contract`'s camelCase `ivRank` is never read, and a missing rank adds
    `no_iv_rank_data`.)
  - vol 500 and OI 2,000.

  Call it with `stock_score=70`.
- Every test overrides only the fields it is about, and asserts the **exact** `soft_flags` list, so a stray
  flag cannot hide.

The tests:
- **AAPL-315C liquidity shape:** vol 3, OI 1,534, spread 1.2% (bid/ask chosen to give it), on the helper's
  40-DTE base → `reject_reasons == []` at the default config, with no overrides.
- At the default floor, vol 0 and vol 3 (everything else identical) → identical `reject_reasons` and
  `soft_flags`. Scores are not compared: `int(3/200*60) == 0` makes them equal only by truncation.
- With `overrides={"min_volume": 50}`:
  - vol 3 → `volume_too_low`;
  - vol 0 with OI ≥ 200 → no `volume_too_low` (the exemption is kept).
- OI 150 → `open_interest_too_low`, at vol 0, 3 and 500.
- `thin_liquidity` appears exactly once when vol < pref and OI < pref, when only vol < pref, and when only
  OI < pref. No flag when both are at or above pref. `low_volume` and `low_open_interest` never appear.
- **One axis costs one slot.** Base: vol 100 (< 200) **and** OI 500 (in [200, 1000)), so both liquidity
  sub-conditions are below preference.
  - With the spread in (8%, 20%) → `soft_flags == ["thin_liquidity", "spread_elevated"]` and
    `reject_reasons == []`.
    - Assert **only** `reject_reasons`, never `status`: this contract's weighted score is 44 (liquidity
      30, spread 0, delta 75, DTE 97, IV 45), below `caution` 45. So its status is "REJECT" by score,
      with no reasons, on the unmutated code.
  - Adding delta 0.25 (in [0.20, 0.30)) → three flags → `"too_many_soft_failures" in reject_reasons`.
  - Under mutation 3, the first case has three flags and `"too_many_soft_failures" in reject_reasons`, so
    it goes red independently of the flag-name test.
- **Score unchanged.** vol 100 / OI 500 → `breakdown.liquidity_score == 30`, an exact value. This kills a
  merge that also changed the arithmetic; today's assertions only check `== 100` / `< 100`.
- **Exemption keeps its OI clause.** `min_volume=50`, vol 0, OI 150 → both `volume_too_low` and
  `open_interest_too_low`. This kills a mutant that drops `oi >= min_open_interest` from the exemption.
  - Flag names verified: `spread_elevated` (`contract_validator.py:202`) and `delta_outside_preferred`
    (`:222`). The order follows the liquidity + spread + delta concatenation at `:463`.

*Backend, `backend/tests/test_overrides.py`* — updated deliberately, one assertion at a time:
- `:204` (`test_loose_tier_combined_override_…`): vol 25 at the default config now asserts
  `volume_too_low` **not** in `reject_reasons`, while `open_interest_too_low` still is.
- `:296-300` (`test_zero_volume_with_adequate_oi_is_not_rejected`): re-pointed at
  `overrides={"min_volume": 50}`, so it pins the kept exemption.
- `:310-314` (`test_low_nonzero_volume_is_rejected`): re-pointed at `overrides={"min_volume": 50}`, so it
  pins that an explicit floor rejects vol 10.
- Mutation 5 is killed by the `:296-300` test above.
- Every positive `low_volume` / `low_open_interest` assertion (:158, :169, :191, :283, :290) →
  `thin_liquidity`. Tests named `…still_flags_low_volume` / `…low_open_interest` are renamed.
- Every **negative** assertion → `"thin_liquidity" not in …`, each checked to hold under fix 2. Left on the
  old names they would pass vacuously:
  - `:160`: vol 100 / OI 2000 with a lowered volume preference;
  - `:171`: vol 2000 / OI 500 with `preferred_oi_min` 400;
  - `:213-214`, `:231`, `:238`.
- `:185-191` (`test_preferred_liquidity_overrides_do_not_mutate_cached_config`): the fixture moves to
  `oi=2000`. With OI 500, `card_a` would carry `thin_liquidity` from OI alone, and the cache-mutation guard
  would stop discriminating. After the change `card_a` has no `thin_liquidity` and `card_b` has it. This
  test is added to mutation 3's kill list.
- Docstrings:
  - `:152` "above the hard default (50)" is corrected;
  - `:195-201` "fails the DEFAULT hard floor on two axes (volume<50, oi<200)" → one axis (OI), matching
    the `:204` edit;
  - `:297` and `:311` mention the explicit `min_volume` 50 they now use;
  - `:124` "passes default" stays true (vol 50 passes a floor of 0) and is left alone.
- `test_min_volume_override_rejects_illiquid` (:123) keeps its meaning.

*Backend, others:*
- `test_step6_contract_rules.py`: `_THIN` (vol 47, OI 162) is still rejected on OI; its soft count drops
  from 2 to 1 with no status change. Edited only if an assertion names an old flag.
- The rest of §1 item 8 runs as part of the full suite. Any failure is examined and fixed or justified in the
  commit, never bulk-edited.

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
3. Restore two flags (`low_volume` + `low_open_interest`). The exactly-once test, the soft-slot test and
   `test_overrides.py:185-191` go red.
4. The merged flag only fires on volume. The OI-only case goes red.
5. Delete the zero-volume exemption. The `min_volume=50`, vol 0 cases in `test_contract_validator.py` and
   `test_overrides.py:296-300` go red.

*Docs:*
- CLAUDE.md needs no change.
- `llm-contexts/22-contract-validation.md` (:113, :187-188, :221-223, :408-427) documents `min_volume: 50`,
  the two old flags and "`volume=0` → `volume_too_low`".
  - The edit is limited to the volume floor, the kept exemption and `thin_liquidity`.
  - Other stale content in that file is not part of this phase and is logged in `open_questions` at build:
    - a `_score_liquidity` snippet without its `<= 0` guards;
    - "4+ soft failures" where the code rejects at 3;
    - a YAML block missing `max_iv_abs` / `preferred_iv_abs_max`.
- The seed-profile files: see fix 1.
- FR-25 is now satisfied for volume. FR-24's missing-quote clause is NO-LIVE-QUOTE's job.
- `contract_rules.yaml` comments are updated as above.

*Operational:*
- `_load_config` is `lru_cache`d (`contract_validator.py:45`), so the backend must restart to pick up the
  YAML default. Since DOCC-4 (on main), the config-health poll flags that stale cache until the restart.
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
- Round 3 (r3): 1 high, 5 medium, 5 low, all fixed in r4:
  - the `test_overrides.py` pins at :204, :300 and :311;
  - the fixture preconditions;
  - the after-close residual, recorded;
  - the seed profiles;
  - the probe wording;
  - the vacuous negatives;
  - the docstrings;
  - `llm-contexts/22`;
  - the scheduled-entry carrier;
  - the line refs.
- Round 4 (r4): 1 high, 4 medium, 7 low, all fixed in r5:
  - the `test_overrides.py` :160 / :171 / :185-191 negatives;
  - the status-vs-reasons assertion;
  - the seed xlsx and README cells;
  - the PROJECT_STATE mechanics;
  - reuse of `_contract_with_expiry`;
  - the docstrings;
  - `:138`;
  - the exact liquidity score;
  - the exemption OI mutant;
  - the session-to-date hint;
  - the `depends_on` contradiction;
  - the `llm-contexts` scope.
- Round 5 (r5, 2026-09-30): 1 gate-level finding, NOT fixed — **HARD CAP reached** (plan stage at 5
  rounds vs cap 3; decision AUDIT-CAP-PER-STAGE-2026-09-25). Auditing stopped; pending Kenneth.
  - **Gate-level (can reach a broker order):** the §3 accepted residual and §1 item 5 say the blast radius
    is the scan and Step 6 only, and that the scan is "not a gate" for auto-trade. False:
    `scan.py:2036` fires `maybe_fire_on_scan` only when some candidate is PASS; Step 7 cards (armable,
    `AutoTradeArm/index.tsx:519` does not gate on contract status) come from the scan pick, which a
    fabricated 0% spread favours (`scan.py:870-872`); `_market_is_open` (`auto_trader.py:418`) is a
    price probe, not an hours test. So after the close, fix 1 lets a vol 1–49 / fabricated-spread
    contract be armed and fired by a re-scan within `max_arm_age_minutes` (30), and sent directly from
    Step 7. Options: accept this broker-order exposure explicitly, or land NO-LIVE-QUOTE first.
  - Not gate-level, logged against main (not fixed in-branch per audit_rule): Step 3 `min_volume` may
    never reach `validate_contract` (open_questions, 2026-09-09, unproven); `audit_rounds`/`active_phase`
    not updated and "r5"/"round-4" subjects evade `state.py`'s `\bround\s+(\d+)`; the fix-1
    `already_shipped` entry needs `audit_clean` at close; probe `min_volume: 0\b` also matches `0.5`
    (use `0(?![.\d])`); pre-market/after-close Tradier volume stated as fact but unobserved; AAPL-shape
    test bid/ask unpinned (2.00/2.025 verified); `test_step6_contract_rules.py:24` comment; xlsx title
    date; §1 header commit id.
  - Mandatory checks passed: weighted-44 fixture recomputed (43.8 → 44), every line ref, state.py exit-0
    mechanics, all five mutations killed.
  - Brief defect: the r5 brief did not tell the reviewer to report gate-level findings only, as
    audit_rule clause (1) requires; future briefs must.
- **PROJECT_STATE mechanics.** `scripts/state.py` counts it as drift when a phase's status disagrees with
  its probe (`state.py:717-728`).
  - Today: status `not_started`, with a defect marker on `min_volume: 50\b` in `contract_rules.yaml`.
  - The build commit that edits the YAML flips the status to `shipped_unaudited` in the **same** commit.
    `in_progress` with the marker gone also counts as drift.
  - A phase has one `verify`, and the build commit replaces it with a `present` probe on
    `"thin_liquidity"` in `contract_validator.py`, which pins fix 2.
  - Fix 1 is pinned by a new `already_shipped` entry, "min_volume default 0 (optional floor)", with its own
    `present` probe on `min_volume: 0\b` in `contract_rules.yaml` (`state.py:763-770`).
  - After a clean code round: `shipped`, with `audit_clean` true.
