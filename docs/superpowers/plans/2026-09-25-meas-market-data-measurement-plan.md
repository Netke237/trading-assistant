# MEAS — Market-data measurement: plan (v2, after plan round 1)

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
| Bearish direction floors (`scoring_rules.yaml` `horizons.<h>.direction_conviction.bearish_min_trend`, 30 Swing / 40 Position) | S1–S4 `direction_gate` counts (the stock path gates before the strategy signal). Options apply the same floor after contracts; the O-scans' `failed_direction` is reported alongside it. |
| Confidence gate `confidence_reject_below` 35 (Step-3 / settingsStore) | Counterfactual scans C1–C4, run end-to-end, so the contract floors and the direction gate are evaluated too |
| `min_stock_score` 55 (contract_rules.yaml hard_reject) | Counterfactual C5 (override 35, the stock gate's own pass line) |
| `min_volume` 50 / `min_open_interest` 200 (contract_rules.yaml) | Counterfactual C6 (overrides 0/0). **Report only**, see §6 |
| `regime_sizing.min_mult` 0.3 (scoring_rules.yaml) | Per-candidate `sentiment.conviction_pct` / `stability` on **stock** results (the value `_process_stock` actually sizes with). Options candidates do not carry it; the market `/api/regime` conviction is used only to classify the day. |
| `iv_rank_pass_max` / `iv_rank_caution_max` per horizon (scoring_rules.yaml), `preferred_iv_rank_max` 55 (contract_rules.yaml) | Rank-basis rows from O1–O4 (percentile source ON), each carrying both `detail_iv_rank` and `detail_iv_abs` |
| `max_iv_rank` 70 (contract_rules.yaml hard ceiling) | **Not measurable from survivors** (every row already passed it). Only the `iv_rank_too_high` truncation count is reported. |
| `iv_rank_threshold` 50 (rank-basis credit/debit line, ScanRequest) | Bearish rank rows (O1, O3) |
| `ivAbsThreshold` / `iv_abs_threshold` 50 (absolute-basis credit/debit line) | Bearish absolute IVs pooled from `detail_iv_abs` on O1/O3 rows, plus A1/A2 (percentile source OFF), which also show the structure the picker actually builds on the absolute basis |

## 3. The scan set (per measurement day, fixed order)

Position bodies are the 2026-09-18 bodies, JSON-equal (the only difference is the file name).
**Swing bodies are rebuilt from the Swing Step-3 defaults** (`frontend/lib/executionParamDefaults.ts`
`PARAM_DEFAULTS_PER_HORIZON.Swing`), taking the same keys the 09-18 bodies override: MA 20 SMA,
slope 10, ADX 25/20, RS 20 against NDX (2.0 / -1.0), options `confidence_atr_mult_target` 3.0,
hold 5–15. The 2026-09-18 Swing stock scans ran on Position parameters (their bodies carry MA 50 /
RS 50 / SPX), so they are **not comparable** for the Swing floor and are excluded from it; this is
recorded in the results sheet.

| # | id | Endpoint | Direction | Horizon | Body |
|---|---|---|---|---|---|
| 1 | O1 | POST /api/scan | Bearish | Position (15–45) | `options-position-bearish` (= 09-18) |
| 2 | O2 | POST /api/scan | Bullish | Position | `options-position-bullish` (= 09-18) |
| 3 | O3 | POST /api/scan | Bearish | Swing (5–15) | `options-swing-bearish` |
| 4 | O4 | POST /api/scan | Bullish | Swing | `options-swing-bullish` |
| 5 | S1 | POST /api/stock-scan | Bearish | Swing | `stocks-swing-bearish` |
| 6 | S2 | POST /api/stock-scan | Bullish | Swing | `stocks-swing-bullish` |
| 7 | S3 | POST /api/stock-scan | Bearish | Position | `stocks-position-bearish` (= 09-18) |
| 8 | S4 | POST /api/stock-scan | Bullish | Position | `stocks-position-bullish` (= 09-18) |
| 9 | C1 | POST /api/scan | Bearish | Position | O1 + `confidence_reject_below: 30` |
| 10 | C2 | POST /api/scan | Bearish | Position | O1 + `confidence_reject_below: 25` |
| 11 | C3 | POST /api/stock-scan | Bearish | Position | S3 + `confidence_reject_below: 30` |
| 12 | C4 | POST /api/stock-scan | Bearish | Position | S3 + `confidence_reject_below: 25` |
| 13 | C5 | POST /api/scan | Bearish | Position | O1 + `overrides.min_stock_score: 35` |
| 14 | C6 | POST /api/scan | Bearish | Position | O1 + `overrides.min_volume: 0, min_open_interest: 0` |
| — | backend restart with the percentile source OFF | | | | |
| 15 | A1 | POST /api/scan | Bearish | Position | O1 body |
| 16 | A2 | POST /api/scan | Bearish | Swing | O3 body |

The counterfactual bodies are **derived by the runner** from their base file plus the one named
change, so they cannot drift from the base. Expected run time is about 16 × 5 min plus the restart,
roughly 1 h 40 min.

Context captured by the runner: `GET /auto-trade/status` before every options scan;
`GET /api/data-sources` at start, before A1, and at the end; `GET /api/scan-schedule` at start;
`GET /api/regime?horizon=position&lookback=20&threshold=0.02&smoothing=0` and the same with
`horizon=swing`, at start and at end (pinned URLs, recorded in the manifest); `git rev-parse HEAD`;
`git status --porcelain -- backend/config`; sha256 of every `backend/config/*.yaml` (including the
git-ignored `settings.yaml`), at start and at end; per-scan start/end UTC and ET.

## 4. Safety and validity rules (enforced by the runner; any breach stops the run)

1. **Auto-trader disarmed.** `POST /api/scan` fires an armed auto-trade when a PASS candidate
   exists (scan.py:1816-1845). The runner reads `GET /auto-trade/status` immediately before
   **every** options scan and stops if `armed` is true. Stock scans never fire it.
2. **No scheduled scans.** The runner stops at start if `GET /api/scan-schedule` lists any
   `enabled` entry. The frontend stays **closed** for the whole run (its continuous scan would POST
   /api/scan and replace the result the run is reading). The runner also warns that each POST
   replaces the UI's "last scan" and its deltas.
3. **Config is main's.** At start, `git status --porcelain -- backend/config` must be empty (tracked
   YAML equals HEAD). Hashes at start and end must match, or the run is marked INVALID.
   `risk_rules.yaml` / `strategy_params.yaml` can be rewritten by the app (Settings → Risk,
   strategy adopt), which is why the end hash is taken.
4. **Right IV source for each block.**
   - Before O1: `tastytrade` must be `connected` in `/api/data-sources`, or stop.
   - After each O/C options result: every candidate's `stockBreakdown.volDetail.iv_basis` must be
     `rank`. Otherwise the scan is flagged `iv_source_mismatch`: kept for funnel counts, excluded
     from the IV analysis.
   - Before A1: `tastytrade` must be `unconfigured` and `ibkr` must not be `connected`, or stop.
   - After A1/A2: zero `rank` candidates, and every `contractDetails.ivRank` null. Otherwise the
     file is marked INVALID.
5. **Percentile source OFF without touching the real credentials file.** `credential_store.py`
   reads `BAMENDJOU_CREDS_PATH`. `run_measurement_day.py strip-creds --out <path outside the repo>`
   copies `backend/config/local_credentials.yaml` minus the `tastytrade_paper` and
   `tastytrade_live` slots (Tradier kept: it supplies the chains) and refuses a path inside the
   repo. Kenneth stops the backend and the IBKR gateway, then in the **same** cmd window runs
   `set BAMENDJOU_CREDS_PATH=<path>` and `start-backend.bat` (setlocal inherits it). After A2 he
   stops that backend, opens a **new** cmd window (so the variable is gone), and runs
   `start-backend.bat`. `restore-check` then confirms `tastytrade` is `connected`, and he deletes
   the copy. **Never** `POST /settings/credentials` to blank a slot: that rewrites the real file.
   (Side effect, harmless: backend startup chmods the file it loads.)
6. **Timing (ET is authoritative).** Start O1 between 13:00 and 13:45 ET (2026-09-18 started 13:20
   ET). The core block (O1–S4) must finish by 15:00 ET, or those scans are flagged
   `late_for_comparison`. Every scan must finish by 15:55 ET, or the runner stops. It refuses to run
   on a weekend, and Kenneth skips NYSE half-days (the runner cannot know them; this is in the
   protocol checklist).
7. **No overwrite.** The runner refuses an existing `scans/<date>/` unless `--run-tag` names a new
   sub-run (`scans/<date>-<tag>/`). A same-day rerun is a new tag, never an overwrite.
8. **Encoding.** All files are written as UTF-8 bytes exactly as received (no re-encoding), which
   avoids the 09-18 mojibake.
9. The runner never writes under `backend/`. Nothing in this package runs the app lifespan in a
   test, and no test writes `backend/config/*.yaml`.

## 5. Day rules (Q28)

- At least **two new valid days**, on different calendar days, not counting 2026-09-18. A day is
  valid if the core block O1–S4 is complete, not INVALID, and not `late_for_comparison`.
- Day regime is taken from the pinned position-horizon `/api/regime` snapshot at start:
  conviction_pct, `omm.stability`, `omm` state, `hmm_state`, VIX (`metrics`), regime_direction.
  Two days are **different regimes** if at least one of these holds:
  - |Δ conviction_pct| ≥ 15
  - `omm.stability` differs
  - |Δ VIX| ≥ 5
  - regime_direction differs
  - `hmm_state` differs
- min_mult is only proposable when the collected days (09-18 included) span two different regimes.
  Otherwise the sheet says "not proposable yet: need a different regime", and Kenneth decides
  whether to run another day.

## 6. Reading rules, fixed before the data exists (whether to propose, and what value)

A proposal cites the rows it used. Below a sample floor the answer is **"not enough data"**, never a
number.

- **Bearish direction floors.** The trend score takes only the values
  L = {0, 15, 30, 40, 45, 55, 60, 70, 85, 100} (stock_scorer.py:268-292: price {0,40} + slope
  {0,30} + ADX {0,15,30}), so a floor acts as the smallest L-value at or above it. Per valid day
  and horizon: bearish rate = rejected / entered (from `direction_gate`), and bullish rate on the
  same day and horizon.
  - Keep: the bearish rate is < 50% and within 10 points of the bullish rate on every day.
  - Propose one step **down** (the next lower L-value: Swing 30→15, Position 40→30): the bearish
    rate is ≥ 50% on ≥ 2 valid days.
  - Propose one step **up** (the next higher L-value: Swing 30→40, Position 40→45): the bearish
    rate is < 2% on every valid day **and** S1/S3 produced ≥ 1 candidate on ≥ 2 valid days.
  - Otherwise, keep.
- **Confidence gate 35.** From C1–C4 against O1/S3 on the same day: added = candidates in Cx that
  are not in the base.
  - Propose **30** if C1 or C3 adds ≥ 1 candidate on ≥ 2 valid days.
  - Otherwise, propose **25** if C2 or C4 adds ≥ 1 candidate on ≥ 2 valid days.
  - Otherwise, keep 35.
  - Report each added candidate's confidence, final status and backtest. The bullish pass rate is a
    reference, not a target.
- **min_stock_score 55.** From C5 against O1: propose if C5 adds ≥ 1 candidate on ≥ 2 valid days.
  Value = the median `stockScore` of all added candidates across days, rounded down to a multiple
  of 5, clamped to [35, 55]. Otherwise keep.
- **min_volume / min_open_interest.** Report only: candidates C6 adds, with their contract volume,
  OI and spread. No proposal from this package; liquidity protects fills and is not lowered on
  bearish starvation. C6 also records whether the override reached the validator
  (`volume_too_low` count must be 0).
- **min_mult 0.3.** Report, per valid day and direction, the distribution of stock-candidate
  `sentiment.conviction_pct`, its `stability`, and the multiplier each candidate gets under
  min_mult ∈ {0.2, 0.3, 0.4} with `full_conviction_pct` 40 (formula in scoring_rules.yaml
  regime_sizing). The proposal is **keep 0.3**, and the table is shown so Kenneth can choose
  another value himself. It is shown only under the different-regime condition in §5.
- **IV rank pass/caution per horizon, and preferred_iv_rank_max.** Floor: ≥ 30 rank rows **per
  horizon**, over ≥ 2 valid days, from O-scans not flagged `iv_source_mismatch`. Rule, quantile
  matching on the same rows: let q = the share of rows with `detail_iv_abs` ≤ the absolute cut
  (`iv_abs_pass_max` / the caution cut / `preferred_iv_abs_max`). The proposed rank cut is the
  q-quantile of `detail_iv_rank` over the same rows, rounded to the nearest 5. Propose only if it
  differs from the seed by ≥ 5. Both columns are truncated by the same survivor filter, and the
  report prints the truncation count next to it.
- **max_iv_rank 70.** Not measurable from survivors. Report the `iv_rank_too_high` count; no
  proposal.
- **iv_rank_threshold 50 and ivAbsThreshold 50 (bearish credit/debit lines).** Floor: ≥ 20 bearish
  values of the relevant basis over ≥ 2 valid days. For ivAbsThreshold, pool `detail_iv_abs` from
  valid O1/O3 rows with `contract_iv` from valid A1/A2 rows. For iv_rank_threshold, use
  `detail_iv_rank` from O1/O3.
  - Keep 50 if each side of 50 holds ≥ 20% of the values.
  - Otherwise, propose the pooled median rounded to the nearest 5; the line then splits the names it
    sees.
  - Report the structures A1/A2 actually built (spread type, net debit/credit).
  - Expected yield: about 5–10 bearish rows per scan, so 2 days should reach 20.

## 7. After Kenneth runs a day

A session (any machine) that has the new `scans/<date>/` folder does this:

1. For each valid options result, run
   `cd backend && .venv/bin/python scripts/iv_basis_analysis.py collect --json <envelope>`. The
   runner already writes the `{"request", "result"}` envelope file per options scan
   (`<id>.envelope.json`), which the script pairs thresholds from (iv_basis_analysis.py:232-238,
   293-295).
2. Append one row per scan to `scan-funnel.jsonl`, using the formulas pinned in PROTOCOL.md §
   "Derived rows". Examples: stock `direction_gate.entered = scanned − failed_history −
   failed_score`; `score_gate_causes` from each score-gate reject's breakdown (confidence <
   `confidence_reject_below`; regime == 0; fundamentals < `fundamentals_reject_below`).
3. Fill that day's section in RESULTS-SHEET.md.
4. After the last day, fill the proposal table under §6 and ask Kenneth yes/no for each threshold.
   Each yes is a separate config change with its own plan → round → build → round loop, and each
   answer is recorded as a decision.

## 8. Verify probe

Phase `MEAS-MARKET-DATA-MEASUREMENT`: `kind: present`, path
`docs/superpowers/measurements/run_measurement_day.py`, pattern `def check_auto_trade_disarmed`
(the check that keeps a measurement day from placing a real order). Status stays `in_progress`
until the days are run and the proposals are answered.

## 9. Tests and mutation checks (scratchpad; nothing committed to backend/tests)

- Every body parses and validates against `ScanRequest` / `StockScanRequest`. The body keys must be
  a subset of `model_fields`, and the override keys a subset of the Step-3 keys in
  `executionParamDefaults.ts` plus the contract-validator override keys.
- The Position bodies are JSON-equal to their 09-18 sources. The Swing bodies' overridden values
  equal `PARAM_DEFAULTS_PER_HORIZON.Swing`.
- The runner is run end-to-end against a fake HTTP server (stdlib) in the scratchpad, covering:
  - the happy path;
  - armed auto-trader → stop;
  - an enabled schedule → stop;
  - tastytrade not connected → stop;
  - a rank row in A1 → INVALID;
  - an existing folder → refuse;
  - dirty config → stop;
  - a changed hash at the end → INVALID.
  Each check is mutated (disabled) once to show a test notices.
- `strip-creds` is run on a synthetic YAML: it removes exactly the two tastytrade slots, keeps the
  Tradier token, and refuses an output path inside the repo.
