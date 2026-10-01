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

## Day template (copy once per measurement day)

### Day <YYYY-MM-DD>[-<run-tag>]

- Freeze tag / commit:
- Valid day? (plan §5) yes / no — why:
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
     `failed_direction` counter for options, because it adds the two together [v6 R3].
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
