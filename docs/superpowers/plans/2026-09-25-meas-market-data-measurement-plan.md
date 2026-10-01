# MEAS — Market-data measurement: plan (v6 + G1 fix (a), v5 re-derived against main 4c52000)

**G1 fix (a) (2026-09-30, decision `MEAS-G1-FIX-A-ROUND-6-2026-09-30`).** Plan round 5 found one
gate-level problem (G1). Since v6, the options shortlist cap ranks before it cuts, by finalStatus →
stockScore → contractScore (scan.py:1884-1888, clamp 50 at :1870). stockScore already grades
`iv_rank` against `iv_rank_pass_max` / `iv_rank_caution_max` (`_rule_vol`, stock_scorer.py:911,
keys at :950-951). So when a scan is truncated, the 50 names kept lean toward pass-band IV, and the
cut names, which appear only as a `Shortlist cap:` reason string with no `volDetail`, lean toward
high IV. v5's cut followed universe order and was roughly IV-neutral; v6's is not. Kenneth chose the
narrow fix:
- **A truncated options scan contributes no rows to any IV rule**, and each IV result lists it
  under "not used: truncated". This covers the shared IV sample (§6), so the rank-cut proposals
  (`iv_rank_pass_max`, `iv_rank_caution_max`, `preferred_iv_rank_max`), and the report-only IV
  items (`max_iv_rank`, `iv_rank_threshold`, `ivAbsThreshold`). It applies to O1–O4 and A1/A2.
- **Scope, deliberately narrow.** A truncated base stays valid for the day (§4.10), and its other
  uses are unchanged: the floor rule reads S-scan pipeline counters, which are counted before the
  cap; a C-pair with a truncated side was already excluded; the min_mult table is report-only
  with the proposal fixed at "keep 0.3". Option (b), excluding a truncated base from every rule that
  reads candidate rows, was not chosen.
- The edits are marked **[G1a]** in §4.10, §6, §7 and §9.

**Universe-file fix (2026-10-01, reported by Kenneth from a parallel round-5 run on
`ccr-3ec55775-kgawjr`) [U1].** R1 froze all of `backend/app/`, which includes
`backend/app/data/sp500.csv`, the only non-`.py` file git tracks there. The app rewrites it at
runtime: `services/sp500_update_service.py:15` sets the path and `:140` does
`os.replace(tmp_path, _CSV_PATH)`, from the daily cron (`services/sp500_scheduler.py:44-47`, when
`sp500_schedule.yaml` enables it) or the manual trigger (`routers/ingestion.py:178-181`). It is the
SP500 universe the scans read (`data/universe_presets.py:48`). One liquidity update after day 1
would make the runner refuse every later day, and since §4.0 forbids suggesting `git checkout` and
§5 pools only days on the same tag commit, the plan could never reach two valid days. (Round 5 had
logged it below the gate as "an S&P update makes the run stop"; it blocks the protocol.) Fix, marked
**[U1]** in §4.0, §5 and §9:
- the frozen paths are `backend/app/` minus that file (pathspec `':!backend/app/data/sp500.csv'`);
- its sha256 is recorded at the start and end of each block; a change during a block flags
  `INVALID:universe_changed_during_run`;
- a hash that differs **between** days is shown next to the per-day rates. It does not exclude a
  day: every rule computes its rate within one day.

**Build notes (2026-10-01, runner build) [B].** Folded in from the round-6 below-gate list where
cheap, and choices the plan left open:
- **B1** A truncated O1–O4/A1/A2 scan gets **no envelope file** (`envelope_file: null`,
  `envelope_skipped: "truncated"`), so §7 step 1 cannot collect it by mistake. The raw result is
  still saved.
- **B2** The manifest records the cap the backend **applied** (`cap`, parsed from a
  `Shortlist cap: … (cap N)` reason), not the body value, plus `original_count`.
- **B3** Each C-scan carries `pair_excluded`: the unusable flags (`state:`, `INVALID:`,
  `override_not_applied`, `truncated`) on it or on its base. Empty means the pair counts.
- **B4** A truncated or flagged A-scan, or an `INVALID:` on the A-block itself, sets
  `ivabs_usable: false`. That A-block does not use up the single A-block: it may be repeated on a
  later valid day (§5). The A-block's own block-level flags go to `ivabs_flags`, never to the
  day's `flags`, so a restart or edit after `core` ended cannot invalidate the core day.
- **B5** `/api/scan-schedule` is recorded as a summary (`entries`, `enabled`) only: the entries
  are the content of the gitignored `scan_schedule.yaml` (§4.3).
- **B6** A config-health `stale` line with no file ("cannot be judged") counts as a measured file
  at the end of a block.
- **B7** The `iv_rank_too_high` count is the number of names whose reject reason contains
  `iv_rank_too_high`; the IV results print their row counts per direction; `stockScore` grades
  `iv_rank` against the pass/caution cuts on the rank basis only (the G1a header's wording).
- **B8** §8's `kind: present` probe on the runner cannot be used: `scripts/state.py` reads a found
  pattern as "built", and this phase stays `in_progress` until the days are run and answered, so
  the probe would be permanent drift. The probe is `kind: absent` on `RESULTS-SHEET.md`, pattern
  `^MEAS-ALL-PROPOSALS-ANSWERED$`, a line written only once every proposal has Kenneth's answer.
  The runner's guards are pinned by the §9 scratch tests, as before.
- **B9** A non-`Stop` exception inside a block, or Ctrl+C, sets the manifest status to `crashed: …`
  or `interrupted: …` instead of leaving it at `running` (round-4 below-gate item).
- **B10 (code round 1, gate-level fix).** The end of a block runs the local checks (config
  hashes, universe hash) first, then config health and pid, and the context snapshot **last**. A
  failed end snapshot is the flag `snapshot_failed:<block>`, not a stop. Any exit from `core`
  before `core_complete` (a stop, crash or Ctrl+C, including inside these end checks) writes
  `day_invalid: core_block_not_completed`, so a day whose end checks did not all run can never
  pass §5. Any such exit from `ivabs` leaves `ivabs_usable: false`.
- **B11 (code round 1, below-gate).**
  - The start copy and snapshot run inside the block.
  - O1's own start time is checked against 13:15 ET, not only the command's start time.
  - The A-block's config is compared against `config_ivabs_start`, its own start.
  - C6's secondary liquidity check skips a candidate with no `liquidityDetail` and counts it
    under `no_liquidity_detail`.
  - PROTOCOL.md now says: merge, then tag; be on the tag on later days; use a second window for
    `ivabs`; pass the same `--run-tag` to `restore-check`.

**What changed in v6 (2026-09-30, decision `MEAS-V6-REFRESH-ONE-ROUND-2026-09-30`).** v5 was written
on main 91e6725e. Before the refresh, 37 commits had touched its gate code: `stock_scan.py` +419 lines,
`scan.py` +259, `contract_validator.py` +142. Kenneth chose to refresh v5 and give it **one** confirmation
round (plan round 5). If that round is not clean, the work stops and goes back to him. Each item below
was verified against the code at 4c52000. Sections that changed are marked **[v6]**.

- **R1 Freeze scope.** P3a is merged, so the prerequisite in decision (1) is met. The tag
  `meas-freeze-1` was never created: Kenneth creates it on the commit he runs. The frozen set grows
  from 8 named modules to **all of `backend/app/`** plus the two measured YAMLs. The gate logic now
  also lives in modules v5 did not list: `services/config_loader.py` resolves the floor,
  `scoring/conviction_sizing.py`, `services/money_config.py`, `dte_window.py`, `spread_builder.py`,
  and the `stock_scan` helpers that `scan.py` imports. Naming modules one by one is how v5 missed
  them (the round-4 below-gate item "unfrozen gate-shaping files").
  `strategy_params.yaml` is not frozen, because tuning adopts rewrite it. Instead, S-scan rules pool
  only days that share its hash (§5) (§4.0).
- **R2 Shortlist cap.** Both paths now **rank before the cut**: options by finalStatus → stockScore
  → contractScore (scan.py:1875-1901), stocks by `_shortlist_rank_key` (stock_scan.py:477-482,
  :1633-1651). Every cut name goes into `rejected` as `Shortlist cap: …`. The caps stay as they are
  (options 50, the clamp; stocks 600, no clamp). A scan with `shortlist_truncated: true` is flagged
  `truncated`, and a C-pair with either side truncated is excluded from its rule (§3, §4.10).
- **R3 The direction gate has two outcomes.** A *measured* trend below the floor
  (`direction_conviction:`) and an *unmeasured* trend (`direction_conviction_unmeasured:`, decisions
  P3A-UNMEASURED-TREND-REMOVE-2026-09-25 and P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25). Moving
  the floor changes only the first, so the floor rule's rate counts measured removals over measured
  entrants. Two details:
  - The stock pipeline has separate `failed_direction` and `failed_direction_unmeasured` counters.
  - The options `failed_direction` counter **added both together** until DCG-SEMANTICS-VISIBILITY
    (main 1c06098, 2026-10-01); since then it counts measured only, with a separate
    `failed_direction_unmeasured`. Options rows are split by the reason prefix (§6, §7), which is
    correct on either version.
- **R4 Position bodies follow today's defaults.** ec712489 aligned `PARAM_DEFAULTS_POSITION` with
  `scoring_rules.yaml`: `additive_adx_pass` went from 20 to 25. The 09-18 Position bodies carry the
  drifted 20. v6 Position bodies use 25, and the check becomes "Position override values equal
  `PARAM_DEFAULTS_PER_HORIZON.Position`". 09-18 is a reference row only (decision (1)), so nothing
  depends on matching it (§3, §9).
- **R5 Proof that the override was applied.** `ScanResult.contract_rules` now records exactly the
  contract overrides the validator applied (`effective_contract_overrides`, contract_validator.py:371-383;
  commit 062f0e4, STEP6-SCAN-CONTRACT-RULES). The runner checks it on every options scan:
  - base scans must show `{}`;
  - C5 must show `min_stock_score: 35`;
  - C6 must show the four liquidity keys at 0;
  - `null` or a mismatch flags `override_not_applied`.
  This replaces the indirect `liquidityDetail` inference as the primary check (§4.11, §6).
- **R6 Live config check.** `GET /api/config/health` (DOCC-4) compares each loader's live cached value
  with the file on disk for scoring_rules, risk_rules and contract_rules, and returns the backend
  `pid`. The runner reads it at start and at end (§4.3):
  - at start: `ok: false`, or a non-empty `stale` naming a measured file, stops the run;
  - at end: a stale measured file flags `INVALID:config_changed_during_run`;
  - a changed `pid` flags `INVALID:backend_restarted`.
  This closes part of v5's gap ("the runner cannot see what the running backend loaded"). It covers
  config only; for code, the restart remains a checklist step.
- **R7 min_mult formula.** The ramp has been two-sided since 2026-09-19:
  `mult = m + (1 − m) · clamp((c + F) / 2F, 0, 1)` (`scoring/conviction_sizing.py` `conviction_mult`).
  The table uses this formula. **Options cards are not conviction-sized**: only the auto-trader's
  fire applies the ramp. So the options column is labelled "what the fire's ramp would give from the
  scan's reading", not a card size (§6).
- **R8 Line references** re-pinned to 4c52000 throughout.
- **R9 Logged, not MEAS scope.** Step 3's `min_stock_score` (stocks section, default 35 on every
  horizon) is not stripped by `resolveOptionsScanRequest.ts`. After a user edits it, an options scan
  posts it in `overrides`, and the validator applies it as its hard floor
  (`_CONTRACT_OVERRIDES["min_stock_score"]`). The field's hint says "the Options scan does not read
  it". The MEAS bodies do not send the key, so O-scans measure the YAML 55. The defect goes into
  `open_questions`.

Package: **MEAS** (docs/superpowers/plans/2026-09-25-work-packages.md, section "MEAS").
Decision implemented: BACKLOG-DECISIONS-2026-09-25, Q20 + Q28. This session prepares exact scan
settings and a results sheet. Kenneth runs the scans on his machine during US market hours on at
least two different days (different regimes). A later session then proposes values from the
results. **No threshold changes without Kenneth's yes.**

**What changed in v4.** Kenneth's decision `MEAS-PLAN-CAP-DECISIONS-2026-09-25`:
- (1) A code freeze: every day runs on one tagged post-P3a commit (§4.0), and 2026-09-18 becomes a
  reference row only (§5).
- (2) `iv_rank_threshold` and `ivAbsThreshold` become report-only, and the A-block runs on one day
  (§5, §6).
- (3) This is the final plan round.

Round-3 fixes:
- G1: gitignored config is never copied (§4.3).
- G2: the IV dedup key includes `stock_basis` (§6).
- G3: the C6 check is narrowed to the liquidity flags (§6).
- G5: the floor rules are evaluated in a fixed order (§6).
- The below-gate list is marked **[r3]** where it lands.

Owned files (all under `docs/superpowers/`, none of them app code or config):

- `measurements/PROTOCOL.md` (new): the run-book.
- `measurements/run_measurement_day.py` (new): a stdlib-only runner that sends the exact bodies,
  enforces every safety and validity check below, and writes the raw files. It lives in the docs
  tree, is not imported by the app, and writes only under `measurements/scans/<date>/`. The one
  exception is `strip-creds`, which writes a copy outside the repo to a path Kenneth names.
  **Why a script rather than prose steps:** round 1 showed that the checks a measurement day needs
  (auto-trader state before every options scan, IV source per result, config hashes, no-overwrite,
  UTF-8, Windows shell) are exactly what a hand-run curl sequence gets wrong.
- `measurements/protocol-requests/*.json` (new): the exact request bodies.
- `measurements/RESULTS-SHEET.md` (new): one section per day, plus the proposal table.
- `measurements/README.md`: a pointer to the files above.
- This plan, and the MEAS phase entry in `PROJECT_STATE.json`.

No app code, no `backend/config/*.yaml`, no tests in `backend/tests` or `frontend/`.

## 1. Re-check of the 9 backlog entries against current code (main 91e6725; v6: still open at 4c52000, as are the entries' own evidence lines below)

| # | Entry (opening words) | Still open? | Evidence now |
|---|---|---|---|
| 1 | "PLAN OF RECORD, AGREED BY KENNETH 2026-09-16" | Yes, but only the measurement half is measurement. The other three items belong elsewhere: the probe rounds are scripts/state.py tooling (the P6 package title covers "state-tool hygiene"); branch deletion is Kenneth's local git action; the below-gate sweep is superseded by Q22 (stale items folded into their owning packages). MEAS reports these three and does not do them. | `measurements/scans/` has only `2026-09-18` |
| 2 | "MEASURED 2026-09-18, 19:37" | Yes, the measurement half. The banner half (`stock_scan.py` `not candidates and _dir_filtered > 0`) is P3a's (work-packages P3a entry "Negative bearish backtest price unfixed … Misleading 'market structure' empty-scan banner"). | `scan-funnel.jsonl` 6 rows, one date |
| 3 | "DONE 2026-09-09: DIRECT-SEND-STOP-GATE" | Only its item (5), the parked IV measurement. | `iv-basis-samples.jsonl`: 0 absolute rows |
| 4 | "DONE 2026-09-09: PHASE E (piece 6" | Only its item (5), as above. | same |
| 5 | "ANSWERED 2026-09-19 BY READING THEM" | Yes. min_mult needs a different conviction value. | `scoring_rules.yaml` regime_sizing `min_mult: 0.3`, `full_conviction_pct: 40` |
| 6 | "RESCUED … CORRECTED 2026-09-09" | Yes, the absolute half has never been measured. | 0 absolute rows |
| 7 | "RESCUED … MEASUREMENT PAUSED 2026-09-09" | Yes, the bearish walls remain. | `contract_rules.yaml:18-19,43` min_volume 50 / min_open_interest 200 / min_stock_score 55; `confidence_reject_below` 35 |
| 8 | "Phase A percentile thresholds are UNMEASURED" | Yes. | `scoring_rules.yaml:132-133,402-403` "UNMEASURED — seeded" |
| 9 | "ivAbsThreshold (spread picker, default 50) is UNMEASURED" | Yes. After Kenneth's decision this entry closes with a **report**, not a value (§6). | `settingsStore.ts` ivAbsThreshold 50; 0 absolute rows |

No other package has fixed any of these. None can close in this session: each closes only after
Kenneth has run the days and answered the proposal table.

Side answer for the rescued entry "FOUND 2026-09-09 … 'Min option volume' … set to 0 DO NOT reach
validate_contract" (not a MEAS entry): scan C6 below sends `min_volume: 0` / `min_open_interest: 0`
as body `overrides`, which `contract_validator.py:319-364` (`_CONTRACT_OVERRIDES`) maps. If C6 still shows
`volume_too_low`, the backend drops the key. If not, any loss is in the UI. The runner records this;
it does not fix it.

## 2. Thresholds in scope, and which data answers each

| Threshold (file : key) | Answered by | Output |
|---|---|---|
| Bearish direction floors (`scoring_rules.yaml` `horizons.<h>.direction_conviction.bearish_min_trend`: 30 Swing, 40 Position) | S1–S4 `direction_gate` counts. The stock path gates before the strategy signal. Options apply the same floor after contracts; the O-scans' `failed_direction` is reported next to it. | proposal |
| Confidence gate `confidence_reject_below` 35 (Step-3 / settingsStore; applies to **both** directions) | C1 (bearish) and C1b (bullish), each paired with its base, plus "would clear the gate" counts from S-scan reject strings | proposal |
| `min_stock_score` 55 (contract_rules.yaml hard_reject; **both** directions) | C5 (bearish) and C5b (bullish): override to 35, the stock gate's CAUTION floor (PASS is 55, scoring_rules.yaml:9-11) | proposal |
| `min_volume` 50 / `min_open_interest` 200 | C6: hard floors **and** the soft preferred bands at 0 | report only |
| `regime_sizing.min_mult` 0.3 | Per-candidate `sentiment.conviction_pct` / `stability` on stock results (what `_process_stock` sizes with) and on options results (built around scan.py:655-672). **[v6 R7]** The options card is not conviction-sized, so this is what the auto-trader's ramp would read, not a card size. Candidates with no sentiment are tabulated separately (`sizing_basis` `floor:unmeasured`). The market `/api/regime` is used only to classify the day. | table, keep 0.3 |
| `iv_rank_pass_max` / `iv_rank_caution_max` per horizon, `preferred_iv_rank_max` 55 | Rank-basis **primary** rows from O1–O4 | proposal |
| `max_iv_rank` 70 (hard ceiling) | Not measurable from survivors. Only the `iv_rank_too_high` reject count is reported (names whose reason contains it) [B7]. | report only |
| `iv_rank_threshold` 50 (rank-basis credit/debit line) | `stock_iv` of rank-basis primary rows from O1–O4: the ATM figure `choose_primary` compares (scan.py:406-407, `choose_primary`; spread_builder.py:96) | **report only** (Kenneth, decision (2)) |
| `ivAbsThreshold` 50 (absolute-basis credit/debit line) | `stock_iv` of **A1/A2** primary rows with `stock_basis == "absolute"` (percentile source OFF). The O-row `detail_iv_abs` is reported only as a labelled proxy (it is the picked contract's own IV, not the ATM figure). | **report only** (Kenneth, decision (2)) |

## 3. The scan set (per measurement day, fixed order)

**Body sources [v6 R2, R4].** The Position bodies are the 2026-09-18 bodies with two changes. The
first is `additive_adx_pass: 25`, today's Position default, which matches `scoring_rules.yaml`
(09-18 sent the drifted 20). The second is a raised shortlist cap. The cap runs after every gate and
after a rank (scan.py:1875-1901; stock_scan.py:1633-1651), and every cut name is listed in `rejected`
as `Shortlist cap: …`. The default cap of 10 would still cut real survivors: 09-18's bullish results
were cut 18→10, 13→10 and 12→10. The pairs need the whole survivor set, so:
- Options set `overrides.shortlist_max_candidates: 50`, the backend clamp.
- Stocks set `shortlist_max_candidates: 600` (no clamp on this path).
- Any result with `shortlist_truncated: true` is flagged `truncated` (§4.10).

No body sends `min_stock_score`, neither in options `overrides` nor as the stock top-level field.
O-scans therefore measure `contract_rules.yaml`'s 55, which is what scheduled scans and the
auto-trader use. The stock top-level field defaults to `None` (off) (R9).

**Swing bodies** are rebuilt from `PARAM_DEFAULTS_PER_HORIZON.Swing`
(`frontend/lib/executionParamDefaults.ts`) for the keys the 09-18 bodies override:
- MA 20 SMA, slope 10, ADX 25/20
- RS 20 against NDX, 2.0 / -1.0
- options `confidence_atr_mult_target` 3.0
- hold 5–15

**Counterfactuals run immediately after their base**, about 7 minutes apart, to limit market
drift. Their bodies are derived by the runner as the base plus the named change, so they cannot
drift from the base file.

| # | id | Endpoint | Dir | Horizon | Body |
|---|---|---|---|---|---|
| 1 | O1 | /api/scan | Bearish | Position | `options-position-bearish` |
| 2 | C1 | /api/scan | Bearish | Position | O1 + `confidence_reject_below: 30` |
| 3 | C5 | /api/scan | Bearish | Position | O1 + `overrides.min_stock_score: 35` |
| 4 | C6 | /api/scan | Bearish | Position | O1 + `overrides` `min_volume: 0, min_open_interest: 0, preferred_volume_min: 0, preferred_oi_min: 0` |
| 5 | O2 | /api/scan | Bullish | Position | `options-position-bullish` |
| 6 | C1b | /api/scan | Bullish | Position | O2 + `confidence_reject_below: 30` |
| 7 | C5b | /api/scan | Bullish | Position | O2 + `overrides.min_stock_score: 35` |
| 8 | O3 | /api/scan | Bearish | Swing | `options-swing-bearish` |
| 9 | O4 | /api/scan | Bullish | Swing | `options-swing-bullish` |
| 10 | S1 | /api/stock-scan | Bearish | Swing | `stocks-swing-bearish` |
| 11 | S2 | /api/stock-scan | Bullish | Swing | `stocks-swing-bullish` |
| 12 | S3 | /api/stock-scan | Bearish | Position | `stocks-position-bearish` |
| 13 | S4 | /api/stock-scan | Bullish | Position | `stocks-position-bullish` |
| — | restart with the percentile source OFF (A-block, **one day only**, §5) | | | | |
| 14 | A1 | /api/scan | Bearish | Position | O1 body |
| 15 | A2 | /api/scan | Bearish | Swing | O3 body |

**Dropped after round 2.**
- Stock confidence counterfactuals: on 09-18 the bearish stock scans had zero confidence-gate
  rejects; they fail at the signal (276 / 258). The S-scans' reject strings
  `confidence gate REJECT: x% < 35%` are reported as "would clear at 30 / 25" counts instead.
- A 25 confidence variant: only 30 is tested end-to-end, so only 30 can be proposed.

**Time budget.** Measured 2026-09-18: options scan about 7.4 min, stock scan about 5 min. 9 × 7.4 +
4 × 5 ≈ 87 min. The A block adds about 15 min plus a restart.

**C-scans give way to the bases [r3].** Before each C-scan, the runner projects the end of the
last base scan:
- The projection is now + this C-scan + every remaining scan (C and base).
- Each scan's duration is the mean of this run's completed scans of the same endpoint so far,
  falling back to 7.4 min for options and 5 min for stocks.

If the projection passes **14:50 ET**, this C-scan and every later C-scan are skipped. They are
recorded in the manifest as `skipped:time`, and the bases still run. A skipped C-scan means that
day has no pair for that gate. The day stays valid; the C rules only count days that ran the pair.

**Context captured by the runner:**
- `GET /auto-trade/status` before every options scan
- `GET /api/data-sources` at start, before A1, and at the end
- `GET /api/scan-schedule` at start
- `GET /api/regime?horizon=position&lookback=20&threshold=0.02&smoothing=0` at start and end. The
  daily OMM does not depend on `horizon`, so one call is enough.
- `git rev-parse HEAD`, the freeze tag and the commit it points at (§4.0)
- `GET /api/config/health` at start and at end (§4.3) [v6 R6]
- config (§4.3): sha256 of every `backend/config/*.yaml` except `local_credentials.yaml`, at start
  and end. A **copy** is kept only of the git-tracked ones.
- per-scan start/end, in UTC and ET

## 4. Safety and validity rules (the runner enforces them; a breach stops the run or marks data)

0. **Code freeze (Kenneth, decision (1)).**
   - No measurement day runs before P3a is merged to main. Kenneth then tags that main commit
     `meas-freeze-1` and runs every day against it. [v6] P3a merged on 2026-09-25, and the tag does
     not exist yet: Kenneth creates it on the main commit he chooses for day 1.
   - The runner takes `--freeze-tag` (default `meas-freeze-1`) and stops if the tag does not exist.
     It also stops if any **frozen path** differs from the tag in the working tree:
     `git diff --name-only <tag> -- <frozen paths>` must be empty, which covers uncommitted edits
     too.
   - The frozen paths are [v6 R1]:
     - **all of `backend/app/` except `backend/app/data/sp500.csv` [U1]** (pathspec
       `':!backend/app/data/sp500.csv'`), the whole directory rather than a list of modules. The gate
       logic now spans `routers/scan.py`, `routers/stock_scan.py`, `scoring/*`, `services/config_loader.py`
       (the floor resolver), `scoring/conviction_sizing.py`, `services/money_config.py`,
       `dte_window.py`, `spread_builder.py`, `data/market.py` and the strategy services. A list is how
       v5 missed several of these;
     - the thresholds under measurement: `backend/config/scoring_rules.yaml` and
       `backend/config/contract_rules.yaml`. This replaces v3's "equal to HEAD".
   - **[U1]** `backend/app/data/sp500.csv` is **not** frozen: the S&P liquidity update rewrites
     it at runtime. Its sha256 is recorded at the start and end of each block
     (`universe_sha256_<block>_start/_end`); a change during a block flags
     `INVALID:universe_changed_during_run`.
   - `strategy_params.yaml` is **not** frozen, because strategy adopts and tuning rewrite it at
     runtime. Its sha256 is recorded in each day's manifest, and S-scan rules pool only days with the
     same hash (§5).
   - On a mismatch the runner lists the files and tells Kenneth to show the diff to a session. It
     never suggests `git checkout`.
   - The manifest records the tag name and the commit it points at. Only days with the **same tag
     commit** are pooled.
   - The runner cannot see the code the running backend loaded. PROTOCOL.md has Kenneth restart
     the backend after any `git checkout` / `git pull`, before `core`. That step is a checklist
     item.
1. **Auto-trader disarmed.** `POST /api/scan` fires an armed auto-trade on a PASS candidate
   (scan.py:2035-2046, `maybe_fire_on_scan`). The runner reads `/auto-trade/status` right before **every** options scan
   and stops if `armed` is not false. Stock scans never fire it.
2. **No scheduled scans, no UI scans [r3 wording].**
   - The old continuous scan is retired. `main.py` migrates it into a scan-schedule entry, so the
     only background scanner is the scan scheduler. The runner stops if any `/api/scan-schedule`
     entry is `enabled`.
   - Kenneth does not start scans from the app during the run. A manual Step-3 "Run Scan" POSTs
     the same endpoints and competes for the same data sources.
   - The runner prints that each POST replaces the app's "last scan" and its deltas.
3. **Config [G1].**
   - **Frozen:** `scoring_rules.yaml` and `contract_rules.yaml` (§4.0).
   - **Recorded, not required:** every other `backend/config/*.yaml` except
     `local_credentials.yaml`. The app rewrites these at runtime (strategy adopt / tuning, watch
     state, Settings → Risk, settings migrations, schedules).
   - **Copies only of git-tracked files.** The runner copies into `config-start/` only the files
     that `git ls-files backend/config` lists and that are not gitignored. The gitignored files
     (`settings.yaml` with `smtp_password` / `bot_token`, `scan_schedule.yaml`, the other
     `*_schedule.yaml` files) and any untracked yaml are **hashed only**. Their content never
     enters the day folder, which is meant to be committed.
   - **End-of-run check:** if `scoring_rules.yaml`, `contract_rules.yaml` or `strategy_params.yaml`
     (read by the stock scans) changed during the run, the day is flagged INVALID. Changes to the
     other files are recorded, not flagged.
   - **Live config [v6 R6].** Before O1, the runner reads `GET /api/config/health` and stops if `ok`
     is false or `stale` names `scoring_rules.yaml` or `contract_rules.yaml`. The endpoint compares
     each loader's cached live value with the file on disk, so this catches a YAML edited after the
     backend started and never reloaded. At the end of `core`, the runner reads it again:
     - a stale measured file flags `INVALID:config_changed_during_run`;
     - a `pid` different from the start flags `INVALID:backend_restarted`.
     The A-block reads its own start `pid` after its restart. The endpoint sees config only, so the
     restart after a checkout stays a checklist step for code.
4. **One rank vendor, the right IV source per block [r3: degraded].** A source whose status is
   `connected` or `degraded` counts as **up**. The data-sources router downgrades a connected probe
   to `degraded` under a tripped circuit, and the source is still serving.
   - **Before O1:** `tastytrade` must be up, and `ibkr` must not be up. IBKR ranks override
     tastytrade (market.py:1539-1558), so a mixed-vendor day is not allowed. A `degraded`
     tastytrade is recorded as a flag on the day.
   - **After each options scan:** the runner reads each candidate's
     `stockBreakdown.volDetail.iv_basis`. When `stockBreakdown.volDetail.iv_rank` is null, the
     basis counts as `none` [r3]. If more than 20% of a scan's candidates are not `rank`, the scan
     is flagged `iv_source_mismatch`. Analysis always filters per row on `stock_basis`.
   - **Before A1:** `tastytrade` must be `unconfigured`, `ibkr` must not be up, and `tradier` must
     be up. This catches a mistyped `BAMENDJOU_CREDS_PATH`, which loads empty defaults and would
     take Tradier down too.
   - **After A1/A2:** any `rank` basis or any non-null `contractDetails.ivRank` marks the scan
     INVALID.
5. **Percentile source OFF without touching the real credentials file (A-block day only).**
   - Run `strip-creds --out <path outside the repo>` with the backend venv's Python, which has
     PyYAML. It copies `backend/config/local_credentials.yaml` minus `tastytrade_paper` and
     `tastytrade_live`, and keeps every other slot, including both Tradier slots (live takes
     precedence, market.py:40-43). It refuses a path inside the repo and prints the slots it kept.
   - Kenneth stops the backend and the IBKR gateway. In the **same** cmd window he runs
     `set BAMENDJOU_CREDS_PATH=<path>` and then `start-backend.bat` (`setlocal` inherits the
     variable).
   - After A2 he closes that window, opens a **new** one and runs `start-backend.bat`.
   - `restore-check` then requires `tastytrade` to be up. Kenneth deletes the copy.
   - Never `POST /settings/credentials` to blank a slot: that rewrites the real file.
6. **Timing (ET is authoritative; the runner computes US DST itself).**
   - O1 must start between **13:00 and 13:15 ET**.
   - C-scans are skipped by the 14:50 projection in §3.
   - Base scans (O1–O4, S1–S4) must finish by 15:00 ET, or they are flagged `late_for_comparison`.
   - No scan may start after 15:40 ET.
   - The runner refuses weekends. Kenneth skips NYSE half-days; that is a checklist item, because the
     runner cannot know them.
7. **No overwrite.** An existing `scans/<date>/` is refused unless `--run-tag` names a new sub-run.
8. **Encoding.** Results are written as the exact bytes received.
9. The runner never writes under `backend/`, and no test writes `backend/config/*.yaml` or runs the
   app lifespan.
10. **Complete scans only [r3].**
    - An options result whose `state` is not `COMPLETED` (`PARTIAL` or `FAILED`) is flagged
      `state:<value>`.
    - Stock results carry no `state`. Their per-symbol exceptions land in
      `pipeline.other_rejected`, the residual bucket (`classify_stock_rejection`, stock_scan.py:505-540). Any
      `other_rejected > 0` is flagged `errors:<n>`. More than 2% of `scanned` is flagged
      `INVALID:errors`.
    - **A base scan** (O1–O4, S1–S4) with `state:PARTIAL`, `state:FAILED` or `INVALID:errors`
      makes the **day** invalid. The runner continues so the rest of the day is still recorded,
      and writes `day_invalid` into the manifest.
    - **A C-scan** with such a flag is excluded from its rule, and so is its pair on that day.
    - **An A-scan** with such a flag is excluded from the IV report.
    - **Truncated [v6 R2].** A result with `shortlist_truncated: true` is flagged `truncated`. A base
      with the flag stays valid, because the cut names are listed in `rejected`. A C-pair where
      either side is truncated is excluded from its rule: an added name could be one the cap cut on
      the other side.
      **[G1a]** A truncated O1–O4 or A1/A2 result also contributes no rows to any IV rule (§6):
      the cap ranks on stockScore, which grades `iv_rank`, so the kept names are an IV-censored
      sample. The manifest's per-scan `truncated` flag is what the IV rules read.
11. **Overrides reached the validator [v6 R5].** Every options result carries
    `contract_rules`, the contract overrides the validator applied. `effective_contract_overrides`
    (contract_validator.py:371-383) reads the same table as `validate_contract`, so the recorded
    value cannot drift from the applied one. The runner checks:
    - O1–O4 and A1/A2 must show `{}` (no body sends a contract key);
    - C5 / C5b must show exactly `{"min_stock_score": 35}`;
    - C6 must show exactly `min_volume`, `min_open_interest`, `preferred_volume_min` and
      `preferred_oi_min`, all 0;
    - C1 / C1b must show `{}` (their change is the top-level `confidence_reject_below`).

    A `null` or any other value flags `override_not_applied:<scan>`, and that pair is excluded
    from its rule.

## 5. Days (Q28, as amended by Kenneth's decision (1) and (2))

- **Valid day:**
  - all eight base scans O1–O4 and S1–S4 ran on the freeze tag;
  - none of them is INVALID or `late_for_comparison`;
  - **[R8]** the manifest's `core_status` is `core_complete` (the runner writes it only after the
    end-of-block checks pass; the A-block never overwrites it). `running` means the process died
    without unwinding (window closed, power loss) before the end checks ran: the day is invalid;
  - the manifest has no `day_invalid`, no `INVALID:config_changed_during_run` and no
    `INVALID:backend_restarted` [v6 R6], and no `INVALID:universe_changed_during_run` [U1].
- **[U1]** A universe (`sp500.csv`) hash that differs between valid days does not exclude a day:
  every rule computes its rate within one day. The hash is shown next to the per-day rates.
- At least **two valid days**, on different calendar days and the same tag commit.
- **[v6 R1]** Rules that read S-scans (the floor rule, the S-scan "would clear" counts) pool only
  days whose start `strategy_params.yaml` sha256 is the same. If the valid days do not share a hash,
  those rules report per day and propose nothing ("not enough data: strategy params changed between
  days"). O-scan rules are unaffected, because the options path reads no strategy params.
- **2026-09-18 is a reference row only.** It ran before the freeze, on Position parameters for
  Swing, with no C- or A-scans. It is shown in RESULTS-SHEET.md as a labelled reference line next
  to each rule. It **does not count** toward the two days, and it **feeds no proposal rule**.
  - Its rows already in `iv-basis-samples.jsonl` (scan ids `REC-20260907-7FB87376`,
    `REC-20260918-74674A41`) are excluded from every IV rule by scan id (§6).
  - Its bullish options envelope was never collected. The session collects it once for the
    reference line only.
  - Its regime line is conviction +27, Choppy, VIX 15.4, MIXED, from the recorded funnel regime.
    Its **stability is recorded as missing [r3]**: the market-level value was never captured, and
    candidate sentiment is not the market regime.
- **The A-block runs on one valid day** (decision (2): its only consumer is now a report). If that
  day's A-block fails or is INVALID, it may be repeated on a later day. At most one A-block feeds
  the report; the first valid one is used.
- **Day regime,** from the position `/api/regime` at start: `conviction_pct`, `omm.state`,
  `omm.stability`, VIX (from `metrics`), `regime_direction`.
- **Two days are different regimes** if any of these holds (a missing value never counts as
  different):
  - |Δ conviction_pct| ≥ 15
  - |Δ VIX| ≥ 5
  - regime_direction differs
  - `omm.state` **and** `omm.stability` both differ
- **min_mult** is shown only if the valid days span two different regimes.

## 6. Reading rules, fixed before the data exists

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

## 7. After Kenneth runs a day

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

## 8. Verify probe [r3: honest claim]

Phase `MEAS-MARKET-DATA-MEASUREMENT`:
- **Until PROTOCOL.md exists:** `kind: absent`, path `docs/superpowers/measurements/PROTOCOL.md`,
  pattern `BAMENDJOU_CREDS_PATH` (the current probe).
- **After the build:** `kind: present` on `docs/superpowers/measurements/run_measurement_day.py`,
  pattern `check_auto_trade_disarmed\(ctx\)\n        body = build_body`.

The probe's note says what it is: a **presence** check that one line still follows another in the
file. It does not show that the guard behaves correctly. Behaviour is pinned only by the scratch
fake-server tests in §9, which are not committed. The phase status stays `in_progress` until the
days are run and the proposals are answered.

## 9. Tests and mutation checks (scratchpad; nothing committed to backend/tests)

**Bodies**
- Every body validates against `ScanRequest` / `StockScanRequest`.
- Body keys must be a subset of `model_fields`.
- Override keys must be a subset of: the Step-3 keys, the contract-validator override keys, and
  `shortlist_max_candidates`.
- Position override values equal `PARAM_DEFAULTS_PER_HORIZON.Position` (so `additive_adx_pass` is
  25), and the other body fields equal 09-18's, apart from the shortlist cap [v6 R4].
- No body carries `min_stock_score`, in `overrides` or at the top level [v6 R9].
- Swing override values equal `PARAM_DEFAULTS_PER_HORIZON.Swing`.

**Runner against a fake HTTP server and a throwaway git repo.** The tests cover:
- the happy path;
- every stop and flag in §4, including:
  - [v6 R1] a change to a `backend/app/` file outside v5's eight modules (for example
    `services/config_loader.py`) must stop the run;
  - [U1] `backend/app/data/sp500.csv` different from the tag (committed and uncommitted) must
    pass the freeze check with its hash recorded; a change during a block flags
    `INVALID:universe_changed_during_run`;
  - [v6 R6] config health: `ok: false` at start stops the run; `stale` naming a measured file stops
    it at start and flags INVALID at end; a `pid` change flags `INVALID:backend_restarted`;
    `stale` naming only `risk_rules.yaml` is recorded, not flagged;
  - [v6 R5] `contract_rules`: `{}` on a base passes; `null` on a base flags; C5 with
    `{"min_stock_score": 35}` passes; C5 with `{}` flags; C6 missing one of its four keys flags;
  - [v6 R2] `shortlist_truncated: true` flags `truncated` and excludes the pair;
  - [G1a] `shortlist_truncated: true` on an O-base and on A1 each writes `truncated` into that
    scan's manifest entry, keyed by its `scan_id`, and leaves the day valid;
  - the freeze tag: missing, a frozen file changed and committed, a frozen file with an
    uncommitted edit, and a non-frozen file changed, which must pass;
  - `degraded` counted as up, for both the tastytrade requirement and the IBKR refusal;
  - PARTIAL / FAILED options states;
  - stock `other_rejected` at 0, at ≤ 2% (flagged) and at > 2% (INVALID, `day_invalid`);
  - C-scan skipping at the 14:50 projection;
  - C6 flags: none on a clean result, a flag on `volume_too_low`, a flag on a candidate whose
    `preferred_oi_min` is 50, and **no** flag on `too_many_soft_failures` alone;
  - an iv_basis of `rank` with a null `iv_rank` counted as `none`;
- **G1:** a planted `smtp_password: PLANTED-SECRET` in a gitignored `settings.yaml` and a planted
  string in a gitignored `scan_schedule.yaml`. Neither string may appear in any file under the
  day folder. Both files' hashes must appear in the manifest;
- the attribution-free recording of bases;
- the ordering: each C directly after its base.

Each guard is mutated once, and a test must fail for the right reason: not a crash, and a named
assertion fails.

**strip-creds** on a synthetic YAML: removes both tastytrade slots, keeps both Tradier slots,
refuses an in-repo path.

G2 (dedup key), G5 (rule order) and the §6 / §7 reading rules are analysis rules for the later
session, not runner code. They are fixed here in writing, and RESULTS-SHEET.md repeats them
verbatim.
