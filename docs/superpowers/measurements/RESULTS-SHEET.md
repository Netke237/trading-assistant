# MEAS — results sheet

Filled in by a Claude session after each measurement day (PROTOCOL.md, "After each day").
**Nothing on this sheet changes a threshold.** Each row of the proposal table needs Kenneth's yes
or no, and each answer is recorded as a decision.

The reading rules at the bottom are copied verbatim from the plan
(`docs/superpowers/plans/2026-09-25-meas-market-data-measurement-plan.md` §6 and §7). They were fixed
before any data existed. If the plan and this copy ever differ, the plan wins, and the difference is
a finding.

## Proposal table (fill in after the last day)

| Threshold | Seed | Proposed | Rule that fired | Rows / days cited | Kenneth |
|---|---|---|---|---|---|
| `bearish_min_trend` Swing | 30 | | | | |
| `bearish_min_trend` Position | 40 | | | | |
| `confidence_reject_below` (both directions) | 35 | | | | |
| `min_stock_score` (both directions) | 55 | | | | |
| `iv_rank_pass_max` Swing / Position | | | | | |
| `iv_rank_caution_max` Swing / Position | | | | | |
| `preferred_iv_rank_max` (one key, horizons pooled) | 55 | | | | |
| `regime_sizing.min_mult` | 0.3 | keep 0.3 (table only) | | | |
| `min_volume` / `min_open_interest` | 50 / 200 | report only | | | — |
| `max_iv_rank` | 70 | report only | | | — |
| `iv_rank_threshold` / `ivAbsThreshold` | 50 / 50 | report only | | | — |

When **every** row has Kenneth's answer, and each is recorded as a decision, add a line reading
exactly `MEAS-ALL-PROPOSALS-ANSWERED` directly below this paragraph. The MEAS verify probe reads that
line: until it exists, the phase is in progress.

"not enough data" is a valid answer for any row, and so is "new question for Kenneth" (plan §6,
direction scope).

## Reference line — 2026-09-18 (does not count, feeds no rule)

Pre-freeze, Position parameters for Swing, no C- or A-scans. Regime: conviction +27, Choppy, VIX
15.4, MIXED. Stability **missing** (never captured). Its IV rows (`REC-20260907-7FB87376`,
`REC-20260918-74674A41`) are excluded from every IV rule by scan id.

## Measurement days

### Day 2026-10-01

- Freeze tag / commit: `meas-freeze-1` / `61a03e49`
- Valid day? (plan §5) **yes**. All eight base scans ran on the tag, none INVALID or
  `late_for_comparison` (O1 13:00:45 ET, last base S4 ended 14:06 ET).
- Manifest `core_status`: `core_complete` (status `ivabs_complete`)
- Manifest flags / `day_invalid` / `snapshot_failed`: none / none / none. No scan carries a flag.
- Day regime (position `/api/regime` at start): conviction **+20** · **Choppy** · **Fragile** · VIX **17.0** · **MIXED**
  (hmm Bull, alignment Diverging, overall PASS)
- `strategy_params.yaml` sha256 (start): `6e60d95a…a764`. The manifest hashes the files as they
  were on disk (CRLF line endings). The committed `config-start/` copies are stored with LF, so
  re-hashing them gives a different value. [v6 R1] compares the manifest values, never a re-hash of
  a committed copy.
- `sp500.csv` sha256 (core start / end): `6d7eae00…60e3` / same. Other days: none yet [U1]
- Config health pid start / end: core 12568 / 12568; A-block 19880 / 19880 (the stripped-credentials backend)
- C-scans skipped (`skipped:time`): none
- Pairs excluded (`pair_excluded`): none
- Truncated scans: none
- A-block run today? **yes**, usable (`ivabs_unusable_because`: [])

**Direction floors (S-scans; measured only, plan §6 [v6 R3])**

| Horizon | Dir | scanned | failed_history | failed_score | entered | failed_direction_unmeasured | measured entrants | failed_direction | rate | candidates |
|---|---|---|---|---|---|---|---|---|---|---|
| Swing | Bearish (S1) | 518 | 2 | 171 | 345 | 0 | 345 | 7 | 2.03% | 0 |
| Swing | Bullish (S2) | 518 | 2 | 395 | 121 | 0 | 121 | 4 | 3.31% | 3 |
| Position | Bearish (S3) | 518 | 2 | 173 | 343 | 0 | 343 | 12 | 3.50% | 1 |
| Position | Bullish (S4) | 518 | 2 | 328 | 188 | 0 | 188 | 28 | 14.89% | 9 |

Rejected trend scores: S1 {0: 5, 15: 2}; S2 {0: 3, 15: 1}; S3 {0: 2, 15: 2, 30: 8}; S4 {0: 1, 15: 2, 30: 25}.
Bearish − bullish gap (information only): Swing −1.3 pt, Position −11.4 pt.
O-scan direction removals: `direction_conviction:` 0 and `direction_conviction_unmeasured:` 0 on
O1–O4 (min trend 40 Position, 30 Swing).

Floor-rule note for the last-day reading: S1's bearish rate is 2.03%, just above the < 2% step-up
line, and S1 produced 0 candidates. S3 is 3.5% with 1 candidate. One day decides nothing (§6 needs
2 counted days per horizon).

**Confidence (C1 / C1b):**
- C1 (bearish, vs O1): 0 attributed, 0 drift. C1 returned the same single name as O1.
- C1b (bullish, vs O2): 1 attributed, passes the quality bar: **AMD** (CAUTION, stop cost CAUTION,
  contractScore 67 ≥ base median 58.5; base breakdown confidence 32, fundamentals 95). 0 drift.
- S-scan confidence-gate rejects ("would clear at 30 / 25"): S1 2 rejects (0 / 0), S2 1 (0 / 1),
  S3 1 (0 / 0), S4 0.

**min_stock_score (C5 / C5b):** every added name lay in [35, 55); drift (≥ 55): 0 on both.
- C5 (bearish, vs O1; quality bar contractScore ≥ 56): 4 attributed, **2 quality**: CSCO
  (stockScore 53, cs 64) and NFLX (38, 65). Below the bar: CEG (50, cs 52) and CPRT (50, cs 47).
- C5b (bullish, vs O2; bar ≥ 58.5): 9 attributed, **5 quality**: NOW (54, cs 66), MSFT (48, 64),
  INTC (43, 68), AAPL (43, 63) and GOOGL (38, 67). Below the bar: PANW (53, 48), APH (44, 50),
  LRCX (42, 47) and XOM (38, 48).
- `contract_rules` echo: C5 / C5b `{"min_stock_score": 35}` ✓.

**Liquidity (C6, report only):**
- 4 attributed (bearish, vs O1), 1 passes the quality bar.
- All four trade below the frozen `min_volume` 50, so none is drift.

| Symbol | Volume | OI | Spread % | contractScore | Quality |
|---|---|---|---|---|---|
| LULU | 4 | 2853 | 7.4 | 58 | yes |
| ALB | 8 | 210 | 8.7 | 52 | no |
| ROST | 0 | 2360 | 10.5 | 48 | no |
| MDT | 2 | 919 | 15.2 | 48 | no |

- `contract_rules`: C6 shows all four keys at 0 ✓. O1–O4, C1, C1b, A1 and A2 show `{}` ✓.
- No C6 reject reason contains `volume_too_low` or `open_interest_too_low`. Every C6 candidate echoes
  `preferred_volume_min` / `preferred_oi_min` 0.
- `override_not_applied:liquidity`: **no**.

**min_mult:** not shown yet. The table is gated on two valid days in different regimes (§5), and this
day's regime line is above. The inputs below are read from the `*.result.json` files; the
`scan-funnel.jsonl` rows do not carry candidate sentiment. Only base and A-scans with candidates
are listed: O3, S1 and A2 had none, and the C-scans are not listed.

| Scan | Candidates | No sentiment | Conviction % values | Stability |
|---|---|---|---|---|
| O1 | 1 | 1 | — | — |
| O2 | 4 | 0 | 33, 50, 67, 100 | 3 Fragile, 1 Stable |
| O4 | 3 | 0 | 0, 14, 64 | 2 Fragile, 1 Stable |
| A1 | 2 | 2 | — | — |
| S2 | 3 | 1 | −9, 0 | 2 Fragile |
| S3 | 1 | 0 | 50 | 1 Fragile |
| S4 | 9 | 0 | −67, −20, −20, 0, 11, 17, 25, 33, 43 | 9 Fragile |

**IV (rank basis, untruncated O1–O4):** "not used: truncated": none.
- Deduplicated primary rank rows:

| Horizon | Direction | Rows | Names (rank `stock_iv`) |
|---|---|---|---|
| Swing | Bullish | 3 | MU 14.2, AMD 27.7, SMCI 48.3 |
| Swing | Bearish | 0 | O3 had no candidates |
| Position | Bullish | 4 | MU 14.2, PFE 33.6, HPE 46.1, MRNA 65.6 |
| Position | Bearish | 1 | WMT 31.7 |

  Totals: Swing 3, Position 5, against a floor of ≥ 30 per horizon.
- `iv_rank_too_high` (names whose reason contains it): O1 3, O2 11, O3 0, O4 3.
- Spread build rate: O1 0/1, O2 0/4, O3 0/0, O4 0/3.
- Line counts (below / at or above) at 40 / 50 / 60:
  - O1: 1/0 at every line.
  - O2: 2/2 at 40, 3/1 at 50, 3/1 at 60. Moving the line to 40 flips 1 name.
  - O4: 2/1 at 40, 3/0 at 50, 3/0 at 60. Moving the line to 40 flips 1 name.
- Only the bearish scans can build a structure: at the tag, `_build_spreads` (routers/scan.py)
  returns nothing for any other direction, and `choose_primary` is the only reader of the line. So
  the bullish build rates (O2, O4) are 0 by design, and a bullish name crossing 40 / 50 / 60
  changes nothing. The bearish names that matter are O1's 1 and A1's 2: all below every line,
  and none built.

**A-block (usable):**
- A1: 2 absolute rows, ROST 31.5 and WMT 27.2. Both sit below 40 / 50 / 60.
- A2: 0 candidates (as O3). A2 lost the same 213 names to `no option chain` as O3; see the
  expiry-gap observation below. The report's Swing absolute-IV sample is therefore empty. This
  block is usable, and under §5 ("at most one A-block feeds the report; the first valid one is
  used") a later A-block would not replace it. Using a later one would need Kenneth to amend §5,
  and even an A2 outside the gap may return 0 candidates. 0 candidates does not make the block
  unusable.
- Names removed by `max_iv_abs` 70 (`iv_too_high`) before the absolute sample: A1 22, A2 6.
- Structures built: none (0/2 spread build).
- ATM cross-check pair: WMT, ATM absolute 27.2 vs O1's picked-contract `detail_iv_abs` 28.3
  (rank 31.7).

**Independent check (2026-10-02, a second session; re-checked by a fresh reviewer 2026-10-03).**
These figures were recomputed from the raw `*.result.json` files through the manifest's scan ids,
with code written separately from the first reading:
- validity and flags;
- S1–S4 counters, rates and rejected trend scores, plus the "would clear" counts;
- C1/C1b/C5/C5b/C6 attribution, quality bars and drift;
- the C6 liquidity echoes, the min_mult inputs and the deduplicated rank rows;
- the `iv_rank_too_high` counts, the spread build rates and the 40/50/60 line counts.

All of them match, and no figure changed. The 2026-10-03 reviewer also re-derived:
- the header (regime, hashes, pids) and the A-block rows with the ATM pair;
- the 24 `iv-basis-samples.jsonl` rows, re-collected with the tag's `iv_basis_analysis.py`;
- the 15 `scan-funnel.jsonl` rows.

All of these match too.

**Observation, not a rule: the Swing O-scans lost many names to the expiry calendar.**
Of the names that reached the chain fetch, O3 rejected 213 of 347 (61%) as `no option chain` and O4
rejected 45 of 112 (40%). The Position bases lost far fewer: O1 10 of 315 (3%), O2 8 of 142 (6%).

Most of the Swing losses come from the expiry calendar:
- The Swing window is 10–30 DTE. The fetch drops expiries below hold_max + 1 = 16
  (`widened_min_dte`) and allows up to 40 (the tolerance), so it accepts 16–40 DTE.
- On 2026-10-01 the October monthly (Oct 16) was at 15 DTE and the November monthly (Nov 20) at 50.
  A name with no weekly options therefore had no expiry it could use.

How much is calendar, out of each no-chain set:

| Scan | No chain | Chain in a Position scan the same day (calendar) | No chain in the Position window (46–100 DTE) either (baseline) | Never reached a Position fetch |
|---|---|---|---|---|
| O3 | 213 | 193 | 10 | 10 |
| O4 | 45 | 32 | 6 | 7 |

- The baseline names also got no chain in the Position scans. Several are renamed, acquired or
  dotted-class tickers.
  O3's are ANSS, AVB, BF.B, BRK.B, CTRA, EQR, FI, IPG, MMC and NVR; O4's are AXL, CTRA, DAY, EA,
  HOLX and MMC.
- No name that reached the fetch in both O3 and O4 got a chain in one and not the other.
- All three O4 picks are the Oct 23 weekly.
- The expiry lists are cached per symbol per day (`market.py`), so O3/O4 reused the lists O1/O2
  had already fetched successfully.
- A2 ran about an hour later on a freshly restarted backend, with an empty cache. It fetched the
  lists again and lost exactly the same 213 names as O3.
- The cause is inferred from the code at the tag and this pattern. Tradier was not re-queried by
  hand.

**The gap repeats around every monthly expiry.** The weekdays with no third-Friday monthly in
16–40 DTE, through February 2027 (the next gap after that is 2027-03-04/05), are:
- 2026-10-01 to 10-09: **every trading day of the week of 10-05 is a gap day**;
- 2026-11-05 and 11-06;
- 2026-12-03 and 12-04;
- 2026-12-31 to 2027-01-08 (01-01 is an NYSE holiday);
- 2027-02-04 and 02-05.

Outside these, a monthly is in range and monthly-only names come back, for example from 2026-10-12,
when Nov 20 is at 39 DTE.

So the Swing O-scans' candidates and IV rows depend on the calendar day: in a gap they are
weekly-listed names only. The day stays valid (§5). The floor, confidence, min_stock_score and
liquidity readings compute per day, but the Swing IV rank rows pool across days.

**What day 2's date changes:**
- **Not affected:** the stock scans S1–S4, the Position C-scans (C1, C1b, C5, C5b, C6) and the
  Position IV rows.
- **Affected:** the Swing options scans (O3, O4): their candidates, their min_mult inputs and the
  Swing IV rank rows.
- **A gap day (any of 10-05 to 10-09)** gives the same weekly-listed-only population as day 1, so
  the two days compare like for like.
- **From 10-12 on,** monthly-only names come back, and the pooled Swing sample mixes the two
  populations.

Whether a 5–15-day hold should accept the 15-DTE monthly is a separate product question, outside the
freeze.

---

## Day template (copy once per measurement day)

### Day <YYYY-MM-DD>[-<run-tag>]

- Freeze tag / commit:
- Valid day? (plan §5) yes / no — why:
- Manifest `core_status` (must be `core_complete`; `running` = killed before the end checks = invalid):
- Manifest flags / `day_invalid` (incl. `core_block_not_completed`) / `snapshot_failed`:
- Day regime (position `/api/regime` at start): conviction_pct · omm.state · omm.stability · VIX · regime_direction
- `strategy_params.yaml` sha256 (start):
- `sp500.csv` sha256 (core start / end); differs from the other days? [U1]
- Config health pid start / end:
- C-scans skipped (`skipped:time`):
- Pairs excluded (`pair_excluded` per C-scan):
- Truncated scans (`original_count` → applied `cap`):
- A-block run today? usable? (`ivabs_unusable_because`):

**Direction floors (S-scans; measured only, plan §6 [v6 R3])**

| Horizon | Dir | scanned | failed_history | failed_score | entered | failed_direction_unmeasured | measured entrants | failed_direction | rate | candidates |
|---|---|---|---|---|---|---|---|---|---|---|
| Swing | Bearish (S1) | | | | | | | | | |
| Swing | Bullish (S2) | | | | | | | | | |
| Position | Bearish (S3) | | | | | | | | | |
| Position | Bullish (S4) | | | | | | | | | |

Bearish − bullish gap (information only). O-scan direction removals, split by reason prefix:
`direction_conviction:` (measured) and `direction_conviction_unmeasured:` (unmeasured).

**Confidence (C1 / C1b):** attributed additions, the quality bar, drift. S-scan "would clear at 30 / 25" counts.

**min_stock_score (C5 / C5b):** attributed additions with C5 `stockScore` in [35, 55), drift (≥ 55).

**Liquidity (C6, report only):** attributed additions with volume / OI / spread;
`contract_rules` check; `override_not_applied:liquidity`?

**min_mult (table, only under the different-regime condition):** per direction, options vs stock:
the conviction / stability distribution, the multipliers at m ∈ {0.2, 0.3, 0.4}, and the count with
no sentiment.

**IV (rank basis, untruncated O1–O4):** rows per horizon **and per direction**; "not used:
truncated" list; `iv_rank_too_high` count (names whose reason contains it); spread build rate;
`stock_iv` distribution; flips at 40 / 50 / 60. A-block (if usable): absolute `stock_iv`
distribution, the structures built, and the ATM cross-check pairs.

---

## Reading rules (verbatim from the plan)

### Plan §6 — Reading rules, fixed before the data exists

A proposal cites its rows. Below a sample floor the answer is **"not enough data"**. Only valid
days (§5) count. **Direction scope [r4 GL-3, Kenneth].** `confidence_reject_below` and
`min_stock_score` are single keys shared by both directions, so a proposal for either applies to
**both directions** and shows its effect on both. The direction floors are **separate** keys
(`bullish_min_trend` / `bearish_min_trend`), and the floor rule below moves **`bearish_min_trend`
only**; the bullish rate is a reference. For the shared keys, if the data says
the two directions want different values, that is a **new question for Kenneth at proposal
time**: a per-direction key is a code change, and it is not decided here.

**Rows by scan id.** Every rule reads result rows through the day's `manifest.json`: only
`scan_id`s the manifest lists for that scan id (O1, C1, …) are used [r3]. This keeps a stray app
scan, or a 09-18 row, out of the pool.

**Attribution (C-scans).** A symbol is "added" by Cx only if it is a Cx candidate, it is not a base
candidate, and its **base** rejection is the gate that was varied:
- C1 / C1b: the base reason starts with `Score gate:` and `breakdown.confidence` is ≥ 30 and < 35.
  The fundamentals filter is direction-aware [r3], with thresholds from the frozen
  `scoring_rules.yaml` `fundamentals_gate` because the bodies send null for the bearish pair:
  - C1b (bullish): `breakdown.fundamentals` ≥ `rejectBelow` (30).
  - C1 (bearish): `breakdown.fundamentals` ≤ `rejectAbove` (80).
  - A missing fundamentals score passes the filter. The gate is skipped when there are no
    fundamentals (stock_scorer.py:1207).
  - Safety-flag rejects are not visible in `breakdown`. They cannot be admitted by C1 either, so
    they cannot produce a false attribution.
- C5 / C5b: the base reason contains `stock_score_below_threshold` **and** the added name's
  `stockScore` in the C5 result lies in [35, 55) [r4 GL-2, Kenneth]. A name at or above 55 in C5
  would have cleared the unchanged floor, so it is live-IV re-scoring drift, not a gate effect,
  and is counted as drift.
- C6 [G3]: the base reason contains `volume_too_low` or `open_interest_too_low` (C6 is report-only;
  the same band idea applies: a name whose C6 contract would pass the unchanged liquidity floors is
  reported as drift).
  `too_many_soft_failures` alone is **not** attributed, because it is raised by any mix of soft
  flags (IV, spread, liquidity bands).
- Any other new name is counted as **drift** and reported, never used.

**Quality bar for an added candidate:** `finalStatus` PASS or CAUTION, `stopCostStatus` not REJECT,
and `contractScore` ≥ the median `contractScore` of that day's base candidates in the same direction
(45 if the base has none).

- **Bearish direction floors [G5].**
  - The trend score takes only the values L = {0,15,30,40,45,55,60,70,85,100}
    (`_trend_additive`, stock_scorer.py:296-370, with the bodies' 40/30/30 maxima; re-verified at 4c52000). A floor acts as the smallest
    L-value at or above it.
  - On each valid day and horizon, compute the bearish reject rate and the bullish rate on the same
    day, from the S-scans. **[v6 R3]** Only a *measured* trend reacts to the floor, so:
    - rate = `failed_direction` / (`entered` − `failed_direction_unmeasured`);
    - `entered` = `scanned − failed_history − failed_score`. The gate order is history → score
      (status REJECT, then the optional `min_stock_score` drop, which also counts as
      `failed_score`) → direction. Both were re-verified at stock_scan.py:1247-1255;
    - `failed_direction_unmeasured` is always shown next to the rate. It is data quality (a short
      MA history, a missing benchmark), not a floor effect.
    - The O-scans' direction removals are information only, as in v5. Their `failed_direction`
      counter adds measured and unmeasured together (scan.py:1837-1842), so they are split by the
      reason prefix: `direction_conviction:` is measured, `direction_conviction_unmeasured:` is
      unmeasured. Options drop an unmeasured trend before the chain fetch (scan.py:735-744), and a
      measured one after contracts.
  - A day whose bearish measured entrants (`entered − failed_direction_unmeasured`) are 0 for that horizon gives **no rate**. It does not count for
    that horizon, and it is shown as "no names reached the gate".
  - Fewer than 2 counted days for a horizon means **"not enough data"** for that horizon.
  - Otherwise the rules are evaluated **in this order, and the first that holds decides**:
    1. Step **down** one L-value (Swing 30→15, Position 40→30) if the bearish rate is ≥ 50% on
       ≥ 2 counted days.
    2. Step **up** one L-value (Swing 30→40, Position 40→45) if the bearish rate is < 2% on every
       counted day **and** S1 / S3 produced ≥ 1 candidate on ≥ 2 counted days.
    3. Otherwise **keep**.
  - The bearish-minus-bullish gap per day is always shown next to the result. It is information,
    not a rule.
- **Confidence 35.**
  - Propose **30** if C1 has ≥ 1 attributed, quality-bar candidate on ≥ 2 valid days that ran the
    C1 pair. Otherwise keep.
  - Always show C1b's attributed additions (count and quality), and the S-scan "would clear at
    30 / 25" counts.
- **min_stock_score 55.**
  - Propose a value if C5 has ≥ 1 attributed, quality-bar candidate on ≥ 2 valid days that ran the
    pair.
  - The value is the median `stockScore` of those candidates across days, rounded down to a
    multiple of 5 and clamped to [35, 55].
  - Always show C5b.
- **Liquidity floors [G3].** Report only: the attributed C6 additions with their volume, OI and
  spread. C6 also shows whether the overrides reached the validator. Both of these must hold:
  - no C6 `rejected` reason contains `volume_too_low` or `open_interest_too_low`;
  - every C6 candidate's `contractBreakdown.liquidityDetail.preferred_volume_min` and
    `preferred_oi_min` are 0 (contract_validator.py:454-455 echoes the effective values). **[v6 R5]** These two conditions are now secondary. The primary proof is §4.11's `contract_rules` check.

  Either failing flags `override_not_applied:liquidity`. This answers the rescued "Min option
  volume set to 0" entry on the backend side.
- **min_mult 0.3.** For each valid day and direction, and separately for options and stock
  candidates, report:
  - the distribution of `sentiment.conviction_pct` and `stability`;
  - each candidate's multiplier under min_mult ∈ {0.2, 0.3, 0.4} with `full_conviction_pct` 40,
    computed with the shipped two-sided ramp **[v6 R7]**:
    `m + (1 − m) · clamp((c + 40) / 80, 0, 1)` (`conviction_sizing.conviction_mult`). A candidate
    at conviction 0 gets 0.65 under m = 0.3, not the floor;
  - for options candidates, the multiplier is labelled "the fire's ramp on the scan's reading".
    Options cards are not conviction-sized; only an armed auto-trade fire applies the ramp;
  - the count of candidates with no sentiment, which are sized at the floor.

  The proposal is **keep 0.3**. The table is shown for Kenneth's own choice, only under the
  different-regime condition (§5).
- **Shared IV sample rules [G2].**
  - Only `row == "primary"` rows count, and only from O1–O4 and A1/A2 on valid days: the runner
    writes envelopes for these scans alone.
  - **[G1a] Truncated scans are not used.** A scan whose manifest entry carries `truncated`
    contributes no rows. The exclusion is by the scan's `scan_id` from the manifest, so a row that
    was collected anyway still does not count. It is applied **before** deduplication, so a name
    whose first scan of the day was truncated can still be counted from a later, untruncated
    scan of the same day and horizon. Every IV result (the rank cuts, `preferred_iv_rank_max`,
    `max_iv_rank`, and the `iv_rank_threshold` / `ivAbsThreshold` reports) lists these scans
    under **"not used: truncated"**, with each scan's `original_count` → cap.
  - Rows are deduplicated on **(symbol, trading day, horizon, stock_basis)**, keeping the first
    scan of the day. An A-row and an O-row for the same name and day therefore both survive, and
    that pair is the ATM cross-check below.
- **IV rank pass/caution per horizon, and preferred_iv_rank_max.** `preferred_iv_rank_max` is ONE
  global key (contract_rules.yaml:69) [r4 GL-1, Kenneth]: it is computed on **both horizons
  pooled**, against `preferred_iv_abs_max`, and yields a single value. Pass/caution stay per
  horizon.
  - Floor: ≥ 30 deduplicated **rank** rows **per horizon**, over ≥ 2 valid days. **[G1a]** Rows
    are counted after the truncated scans are removed, and a valid day counts toward the 2 only
    if at least one untruncated O-scan of that horizon contributed a deduplicated rank row
    (`stock_basis == "rank"`) **[G1a, round-6 fix]**.
  - Rule (quantile matching on the same rows): q = the share of rows with `detail_iv_abs` ≤ the
    absolute cut (`iv_abs_pass_max` / the caution cut / `preferred_iv_abs_max`). The proposed rank
    cut is the q-quantile of `stock_iv` (rank), rounded to the nearest 5.
  - Propose only if it differs from the seed by ≥ 5.
  - Stated bias: `detail_iv_abs` is the picked contract's own IV, not the ATM figure the absolute
    cut judges. The (symbol, day) pairs present in both O and A rows give the true ATM absolute IV,
    and they are reported as a cross-check.
  - The `iv_rank_too_high` count (the names `max_iv_rank` removed before the sample) is printed
    next to the result. **[G1a]** So is the "not used: truncated" list.
- **max_iv_rank 70.** Report the `iv_rank_too_high` count only, from untruncated O-scans. The
  count comes from `rejected`, which a cap does not change, but a truncated scan is still listed
  as not used so every IV result reads the same set of scans **[G1a]**.
- **iv_rank_threshold 50 and ivAbsThreshold 50: REPORT ONLY (Kenneth, decision (2)).** Neither
  value is proposed from these scans. A cross-sectional rule would move the line with the day's
  volatility regime, so moving either needs a later outcome-based study. For each **untruncated**
  O-scan, and for untruncated A1/A2 on the A-block day, the sheet reports (a truncated one is
  listed as "not used: truncated" instead **[G1a]**):
  - **spread build rate [r3]:** candidates with a non-null `spreadType`, divided by candidates;
  - the distribution of the relevant `stock_iv` (rank for O-scans, absolute for A-scans);
  - how many names would flip side of the line at 40 / 50 / 60;
  - the structures A1/A2 actually built (spread type, net debit/credit).

### Plan §7 — After Kenneth runs a day

A session (any machine) that has the new `scans/<date>/` folder does the following.

1. Collect the IV rows using the runner's `*.envelope.json` files, which exist only for O1–O4 and
   A1/A2:
   ```
   cd backend
   .venv/bin/python scripts/iv_basis_analysis.py collect --json ../docs/superpowers/measurements/scans/<date>/<id>.envelope.json
   ```
   On Windows the interpreter is `.venv\Scripts\python.exe`, and `PYTHONUTF8=1` must be set:
   iv_basis_analysis.py reads the file with the platform encoding.
   **[G1a]** Skip the envelope of any scan the manifest flags `truncated`, and note it under
   "not used: truncated" in the day's IV section. The IV rules also filter by the manifest flag
   (§6), so a mistaken collection does not change a result.
2. Add one `scan-funnel.jsonl` row per scan, using PROTOCOL.md § "Derived rows".
   - Stock `direction_gate.entered = scanned − failed_history − failed_score`;
     `direction_gate.rejected = failed_direction` (measured only);
     `direction_gate.unmeasured = failed_direction_unmeasured` [v6 R3].
   - Options direction rows: `rejected` counts the reasons starting `direction_conviction:`, and
     `unmeasured` counts those starting `direction_conviction_unmeasured:`. Never read the
     `failed_direction` counter for options: it added the two together before DCG-SEMANTICS-VISIBILITY
     (2026-10-01), so the prefix split is the one rule valid on every tag [v6 R3].
   - Score-gate causes come from each score-gate reject's breakdown:
     - confidence below `confidence_reject_below`. A `breakdown.confidence` of **0 reads as
       "0 or None"** [r3]: the scorer writes 0 for a missing confidence (stock_scorer.py:1183-1185),
       so a 0 goes to **unknown**, never to "confidence";
     - fundamentals outside the direction's reject bound (bullish < `rejectBelow`, bearish >
       `rejectAbove`);
     - **unexplained [r3]:** neither of the above. The reject came from the weighted score or a
       rule not in the breakdown;
     - `regime` is **not** a cause, because that rule always scores 0.
   - A candidate's IV basis is read from `stockBreakdown.volDetail.iv_basis`, and a null
     `iv_rank` there is basis `none` [r3].
3. Fill in that day's section of RESULTS-SHEET.md.
4. After the last day, fill in the proposal table under §6 and ask Kenneth yes or no for each row.
   Each yes gets its own config-change loop, and each answer is recorded as a decision.
