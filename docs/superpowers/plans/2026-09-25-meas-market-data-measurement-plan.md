# MEAS — Market-data measurement: plan (v3, after plan rounds 1 and 2)

Package: **MEAS** (docs/superpowers/plans/2026-09-25-work-packages.md, section "MEAS").
Decision implemented: BACKLOG-DECISIONS-2026-09-25, Q20 + Q28. This session prepares exact scan
settings and a results sheet. Kenneth runs the scans on his machine during US market hours on at
least two different days (different regimes). A later session then proposes values from the
results. **No threshold changes without Kenneth's yes.**

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

## 1. Re-check of the 9 backlog entries against current code (main 91e6725)

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
| 9 | "ivAbsThreshold (spread picker, default 50) is UNMEASURED" | Yes. | `settingsStore.ts` ivAbsThreshold 50; 0 absolute rows |

No other package has fixed any of these. None can close in this session: each closes only after
Kenneth has run the days and answered the proposal table.

Side answer for the rescued entry "FOUND 2026-09-09 … 'Min option volume' … set to 0 DO NOT reach
validate_contract" (not a MEAS entry): scan C6 below sends `min_volume: 0` / `min_open_interest: 0`
as body `overrides`, which `contract_validator.py:335-343` maps. If C6 still shows
`volume_too_low`, the backend drops the key. If not, any loss is in the UI. The runner records this;
it does not fix it.

## 2. Thresholds in scope, and which data answers each

| Threshold (file : key) | Answered by |
|---|---|
| Bearish direction floors (`scoring_rules.yaml` `horizons.<h>.direction_conviction.bearish_min_trend`: 30 Swing, 40 Position) | S1–S4 `direction_gate` counts. The stock path gates before the strategy signal. Options apply the same floor after contracts; the O-scans' `failed_direction` is reported next to it. |
| Confidence gate `confidence_reject_below` 35 (Step-3 / settingsStore; applies to **both** directions) | C1 (bearish) and C1b (bullish), each paired with its base, plus "would clear the gate" counts from S-scan reject strings |
| `min_stock_score` 55 (contract_rules.yaml hard_reject; **both** directions) | C5 (bearish) and C5b (bullish): override to 35, the stock gate's CAUTION floor (PASS is 55, scoring_rules.yaml:9-11) |
| `min_volume` 50 / `min_open_interest` 200 | C6: hard floors **and** the soft preferred bands at 0. **Report only** (§6). |
| `regime_sizing.min_mult` 0.3 | Per-candidate `sentiment.conviction_pct` / `stability` on stock results (what `_process_stock` sizes with) and on options results (built around scan.py:600). Candidates with no sentiment are tabulated separately (`sizing_basis` `floor:unmeasured`). The market `/api/regime` is used only to classify the day. |
| `iv_rank_pass_max` / `iv_rank_caution_max` per horizon, `preferred_iv_rank_max` 55 | Rank-basis **primary** rows from O1–O4 |
| `max_iv_rank` 70 (hard ceiling) | Not measurable from survivors. Only the `iv_rank_too_high` truncation count is reported. |
| `iv_rank_threshold` 50 (rank-basis credit/debit line) | `stock_iv` of bearish rank-basis primary rows from O1 and O3: the ATM figure `choose_primary` compares (scan.py:680-686, :1132; spread_builder.py:118-121) |
| `ivAbsThreshold` 50 (absolute-basis credit/debit line) | `stock_iv` of **A1/A2** primary rows with `stock_basis == "absolute"` (percentile source OFF). The O-row `detail_iv_abs` is reported only as a labelled proxy (it is the picked contract's own IV, not the ATM figure). |

## 3. The scan set (per measurement day, fixed order)

**Body sources.** The Position bodies are the 2026-09-18 bodies, with one change: the shortlist
cap is raised so no candidate is dropped silently. The cap cuts `candidates[:N]` in universe order,
after every gate (scan.py:1680-1689, stock_scan.py:1371-1373); the dropped names are not in
`rejected`, and 09-18's bullish results were cut 18→10, 13→10 and 12→10.
- Options set `overrides.shortlist_max_candidates: 50`, the backend clamp.
- Stocks set `shortlist_max_candidates: 600`.

The funnel counts other than `failed_shortlist` stay comparable with 09-18.

**Swing bodies** are rebuilt from `PARAM_DEFAULTS_PER_HORIZON.Swing`
(`frontend/lib/executionParamDefaults.ts`) for the keys the 09-18 bodies override:
- MA 20 SMA, slope 10, ADX 25/20
- RS 20 against NDX, 2.0 / -1.0
- options `confidence_atr_mult_target` 3.0
- hold 5–15

09-18's Swing stock scans ran on Position parameters, so they are excluded from the Swing floor.

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
| — | restart with the percentile source OFF (optional block, §5) | | | | |
| 14 | A1 | /api/scan | Bearish | Position | O1 body |
| 15 | A2 | /api/scan | Bearish | Swing | O3 body |

**Dropped after round 2.**
- Stock confidence counterfactuals: on 09-18 the bearish stock scans had zero confidence-gate
  rejects; they fail at the signal (276 / 258). The S-scans' reject strings
  `confidence gate REJECT: x% < 35%` are reported as "would clear at 30 / 25" counts instead.
- A 25 confidence variant: only 30 is tested end-to-end, so only 30 can be proposed.

**Time budget.** Measured 2026-09-18: options scan about 7.4 min, stock scan about 5 min. 9 × 7.4 +
4 × 5 ≈ 87 min. The optional A block adds about 15 min plus a restart.

**Context captured by the runner:**
- `GET /auto-trade/status` before every options scan
- `GET /api/data-sources` at start, before A1, and at the end
- `GET /api/scan-schedule` at start
- `GET /api/regime?horizon=position&lookback=20&threshold=0.02&smoothing=0` at start and end. The
  daily OMM does not depend on `horizon`, so one call is enough.
- `git rev-parse HEAD`
- sha256 **and a copy** of every non-credential `backend/config/*.yaml` at start, plus sha256 at the end
- per-scan start/end, in UTC and ET

## 4. Safety and validity rules (the runner enforces them; a breach stops the run or marks data)

1. **Auto-trader disarmed.** `POST /api/scan` fires an armed auto-trade on a PASS candidate
   (scan.py:1816-1845). The runner reads `/auto-trade/status` right before **every** options scan
   and stops if `armed` is not false. Stock scans never fire it.
2. **No scheduled scans, frontend closed.** The runner stops if any `/api/scan-schedule` entry is
   `enabled`. Kenneth keeps the frontend closed: its continuous scan would POST /api/scan. The runner
   prints that each POST replaces the app's "last scan" and its deltas.
3. **Config.**
   - **Required equal to HEAD:** `scoring_rules.yaml` and `contract_rules.yaml`. They hold the
     thresholds under measurement, and the app never writes them. If they differ, the runner stops
     and tells Kenneth to show the diff to a session. It never suggests `git checkout`.
   - **Recorded, not required:** `strategy_params.yaml`, `strategy_watches.yaml`, `risk_rules.yaml`,
     `settings.yaml` and the schedule files. The app rewrites these at runtime (strategy adopt /
     tuning, watch state, Settings → Risk, settings migrations), so they are recorded with a hash and
     a copy in the day folder.
   - **End-of-run check:** if `scoring_rules.yaml`, `contract_rules.yaml` or `strategy_params.yaml`
     (read by the stock scans) changed during the run, the day is flagged INVALID. Changes to the
     other files are recorded, not flagged.
4. **One rank vendor, the right IV source per block.**
   - **Before O1:** `tastytrade` must be `connected` and `ibkr` must not be `connected`. IBKR ranks
     override tastytrade (market.py:1504-1511); a mixed-vendor day is not allowed.
   - **After each options scan:** the runner records the per-candidate `volDetail.iv_basis` counts.
     If more than 20% are not `rank`, the scan is flagged `iv_source_mismatch`. Analysis always
     filters per row on `stock_basis`.
   - **Before A1:** `tastytrade` must be `unconfigured`, `ibkr` must not be `connected`, and
     `tradier` must be `connected`. This catches a mistyped `BAMENDJOU_CREDS_PATH`, which loads empty
     defaults and would take Tradier down too.
   - **After A1/A2:** any `rank` basis or any non-null `contractDetails.ivRank` marks the scan
     INVALID.
5. **Percentile source OFF without touching the real credentials file.**
   - Run `strip-creds --out <path outside the repo>`, with the backend venv's Python (it needs
     PyYAML). It copies `backend/config/local_credentials.yaml` minus `tastytrade_paper` and
     `tastytrade_live`, keeping every other slot (both Tradier slots: live takes precedence,
     market.py:40-45). It refuses a path inside the repo, and prints the slots it kept.
   - Kenneth stops the backend and the IBKR gateway. In the **same** cmd window he runs
     `set BAMENDJOU_CREDS_PATH=<path>` and then `start-backend.bat` (`setlocal` inherits the
     variable).
   - After A2 he closes that window, opens a **new** one and runs `start-backend.bat`.
   - `restore-check` then requires `tastytrade` `connected`, and Kenneth deletes the copy.
   - Never `POST /settings/credentials` to blank a slot: that rewrites the real file.
6. **Timing (ET is authoritative; the runner computes US DST itself).**
   - O1 must start between **13:00 and 13:15 ET**.
   - Base scans (O1–O4, S1–S4) must finish by 15:00 ET, or they are flagged `late_for_comparison`.
   - No scan may start after 15:40 ET.
   - The runner refuses weekends. Kenneth skips NYSE half-days; that is a checklist item, because the
     runner cannot know them.
7. **No overwrite.** An existing `scans/<date>/` is refused unless `--run-tag` names a new sub-run.
8. **Encoding.** Results are written as the exact bytes received.
9. The runner never writes under `backend/`, and no test writes `backend/config/*.yaml` or runs the
   app lifespan.

## 5. Days (Q28)

- **Valid day:** base scans O1–O4 and S1–S4 complete, none INVALID, none `late_for_comparison`.
  At least **two new valid days**, on different calendar days.
- **09-18's role:** it is a valid day **for the Position direction floor and for the IV rank rows
  already in the store**. It does not count for Swing (Position parameters), for the counterfactual
  rules (it has no C-scans), for ivAbsThreshold (no A-scans), or towards the two new days.
- **The A block is optional per day.** It must run on at least two days in total. If a day runs
  late, skip it that day.
- **Day regime,** from the position `/api/regime` at start: `conviction_pct`, `omm.state`,
  `omm.stability`, VIX (from `metrics`), `regime_direction`. For 09-18 these come from the recorded
  funnel regime (conviction +27, Choppy, MIXED, VIX 15.4), with stability Fragile from its candidate
  sentiment.
- **Two days are different regimes** if any of these holds (a missing value never counts as
  different):
  - |Δ conviction_pct| ≥ 15
  - |Δ VIX| ≥ 5
  - regime_direction differs
  - `omm.state` **and** `omm.stability` both differ
- **min_mult** is shown only if the days span two different regimes.

## 6. Reading rules, fixed before the data exists

A proposal cites its rows. Below a sample floor the answer is **"not enough data"**. Every proposed
value applies to **both directions** (that is how each key is implemented today), so each proposal
shows its effect on both directions. If the data says the two directions want different values,
that is a **new question for Kenneth at proposal time** (a per-direction key is a code change);
it is not decided here.

**Attribution (C-scans).** A symbol is "added" by Cx only if it is a Cx candidate, it is not a base
candidate, and its **base** rejection is the gate that was varied:
- C1 / C1b: base reason starts `Score gate:`, `breakdown.confidence` ≥ 30 and < 35, and
  `breakdown.fundamentals` is not below `fundamentals_reject_below`.
- C5 / C5b: base reason contains `stock_score_below_threshold`.
- C6: base reason contains `volume_too_low`, `open_interest_too_low` or `too_many_soft_failures`.
- Any other new name is counted as **drift** and reported, never used.

**Quality bar for an added candidate:** `finalStatus` PASS or CAUTION, `stopCostStatus` not REJECT,
and `contractScore` ≥ the median `contractScore` of that day's base candidates in the same direction
(45 if the base has none).

- **Bearish direction floors.** The trend score takes only the values
  L = {0,15,30,40,45,55,60,70,85,100} (stock_scorer.py:268-292, with the bodies' 40/30/30 maxima).
  A floor acts as the smallest L-value at or above it. On each valid day and horizon, compute the
  bearish reject rate (`direction_gate` rejected / entered) and the bullish rate on the same day.
  - Keep if the bearish rate is < 50% and within 10 points of the bullish rate on every valid day.
  - Step **down** one L-value (Swing 30→15, Position 40→30) if the bearish rate is ≥ 50% on
    ≥ 2 valid days.
  - Step **up** one L-value (Swing 30→40, Position 40→45) if the bearish rate is < 2% on every valid
    day **and** S1 / S3 produced ≥ 1 candidate on ≥ 2 valid days.
  - Otherwise keep.
- **Confidence 35.** Propose **30** if C1 has ≥ 1 attributed, quality-bar candidate on ≥ 2 valid
  days. Otherwise keep. Always show C1b's attributed additions (count and quality), and the S-scan
  "would clear at 30 / 25" counts.
- **min_stock_score 55.** Propose if C5 has ≥ 1 attributed, quality-bar candidate on ≥ 2 valid days.
  The value is the median `stockScore` of those candidates across days, rounded down to a multiple
  of 5 and clamped to [35, 55]. Always show C5b.
- **Liquidity floors.** Report only: the attributed C6 additions with their volume, OI and spread. C6
  also shows whether the overrides reached the validator: no `volume_too_low`, `open_interest_too_low`
  or `too_many_soft_failures` may remain. This answers the rescued "Min option volume set to 0" entry
  on the backend side.
- **min_mult 0.3.** For each valid day and direction, and separately for options and stock
  candidates, report:
  - the distribution of `sentiment.conviction_pct` and `stability`;
  - each candidate's multiplier under min_mult ∈ {0.2, 0.3, 0.4} with `full_conviction_pct` 40;
  - the count of candidates with no sentiment, which are sized at the floor.

  The proposal is **keep 0.3**, and the table is shown for Kenneth's own choice, only under the
  different-regime condition (§5).
- **Shared IV sample rules.** Only `row == "primary"` rows count, and only from O1–O4 and A1/A2: the
  runner writes envelopes for these scans alone. Rows are deduplicated on (symbol, trading day,
  horizon), keeping the first scan of the day.
- **IV rank pass/caution per horizon, and preferred_iv_rank_max.**
  - Floor: ≥ 30 deduplicated rank rows **per horizon**, over ≥ 2 days.
  - Rule (quantile matching on the same rows): q = the share of rows with `detail_iv_abs` ≤ the
    absolute cut (`iv_abs_pass_max` / the caution cut / `preferred_iv_abs_max`). The proposed rank
    cut is the q-quantile of `stock_iv` (rank), rounded to the nearest 5.
  - Propose only if it differs from the seed by ≥ 5.
  - Stated bias: `detail_iv_abs` is the picked contract's own IV, not the ATM figure the absolute
    cut judges. The (symbol, day) pairs present in both O and A rows give the true ATM absolute IV,
    and they are reported as a cross-check.
  - The truncation count is printed next to the result.
- **max_iv_rank 70.** Report the `iv_rank_too_high` count only.
- **iv_rank_threshold 50** (rank `stock_iv`, bearish O1/O3) and **ivAbsThreshold 50** (absolute
  `stock_iv`, A1/A2):
  - Floor: ≥ 20 deduplicated values of the relevant basis over ≥ 2 days. Expected about 5–10 per
    day, so more A-blocks may be needed. The sheet says so rather than lowering the floor.
  - Keep 50 if each side of 50 holds ≥ 20% of the values. Otherwise propose the median, rounded to
    the nearest 5.
  - Always report the structures A1/A2 built (spread type, net debit/credit).

## 7. After Kenneth runs a day

A session (any machine) that has the new `scans/<date>/` folder does the following.

1. Collect the IV rows, only for O1–O4 and A1/A2, using the runner's `*.envelope.json` files:
   ```
   cd backend
   .venv/bin/python scripts/iv_basis_analysis.py collect --json ../docs/superpowers/measurements/scans/<date>/<id>.envelope.json
   ```
   On Windows the interpreter is `.venv\Scripts\python.exe`, and `PYTHONUTF8=1` must be set:
   iv_basis_analysis.py reads the file with the platform encoding.
2. Add one `scan-funnel.jsonl` row per scan, using PROTOCOL.md § "Derived rows".
   - Stock `direction_gate.entered = scanned − failed_history − failed_score`.
   - Score-gate causes come from each score-gate reject's breakdown:
     - confidence below `confidence_reject_below`;
     - fundamentals below `fundamentals_reject_below`;
     - a None confidence counts as **unknown**;
     - `regime` is **not** a cause, because that rule always scores 0.
3. Fill in that day's section of RESULTS-SHEET.md.
4. After the last day, fill in the proposal table under §6 and ask Kenneth yes or no for each row.
   Each yes gets its own config-change loop, and each answer is recorded as a decision.

## 8. Verify probe

Phase `MEAS-MARKET-DATA-MEASUREMENT`:
- `kind: present`
- path `docs/superpowers/measurements/run_measurement_day.py`
- pattern `check_auto_trade_disarmed\(ctx\)\n        body = build_body`

This pins that the disarm check sits immediately before each scan body is built, not merely that
the function exists. The phase status stays `in_progress` until the days are run and the proposals
are answered.

## 9. Tests and mutation checks (scratchpad; nothing committed to backend/tests)

**Bodies**
- Every body validates against `ScanRequest` / `StockScanRequest`.
- Body keys must be a subset of `model_fields`.
- Override keys must be a subset of: the Step-3 keys, the contract-validator override keys, and
  `shortlist_max_candidates`.
- Position bodies equal 09-18 apart from the shortlist cap.
- Swing override values equal `PARAM_DEFAULTS_PER_HORIZON.Swing`.

**Runner against a fake HTTP server.** Covers the happy path, every stop and flag in §4, the
attribution-free recording of bases, and the ordering (each C directly after its base). Each guard
is mutated once and a test must fail for the right reason: not a crash, and a named assertion fails.

**strip-creds** on a synthetic YAML: removes both tastytrade slots, keeps both Tradier slots,
refuses an in-repo path.
