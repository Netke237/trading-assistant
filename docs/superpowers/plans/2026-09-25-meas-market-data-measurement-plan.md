# MEAS — Market-data measurement: plan

Package: **MEAS** (docs/superpowers/plans/2026-09-25-work-packages.md, section "MEAS").
Decision implemented: BACKLOG-DECISIONS-2026-09-25, Q20 + Q28 — the session prepares exact scan
settings and a results sheet; Kenneth runs the scans on his machine during US market hours on
at least two different days (different regimes); a later session proposes values from the results.
**No threshold changes without Kenneth's yes.**

Owned files (docs only):

- `docs/superpowers/measurements/PROTOCOL.md` — new: the run-book Kenneth (or a local agent on his
  machine) follows on a measurement day.
- `docs/superpowers/measurements/protocol-requests/*.json` — new: the exact request bodies.
- `docs/superpowers/measurements/RESULTS-SHEET.md` — new: one section per measured day, plus the
  proposal table Kenneth answers yes/no.
- `docs/superpowers/measurements/README.md` — a pointer to the two new files.
- this plan, and the MEAS phase entry in `docs/superpowers/PROJECT_STATE.json`.

No code, no config, no test changes. `backend/config/*.yaml` is not touched.

## 1. Re-check of the 9 backlog entries against current code (2026-09-25, main 91e6725)

| # | Entry (opening words) | Still open? | Evidence now |
|---|---|---|---|
| 1 | "PLAN OF RECORD, AGREED BY KENNETH 2026-09-16" | Yes. Measurement half is this package. Its other three items are **not measurement**: probe rounds (scripts/state.py, P6), branch deletion (Kenneth's local git action), below-gate sweep (superseded by Q22: stale items folded into owning packages). MEAS reports them, does not do them. | `measurements/scans/` has only `2026-09-18` |
| 2 | "MEASURED 2026-09-18, 19:37" | Yes, measurement half. The banner half (`stock_scan.py`, `not candidates and _dir_filtered > 0`) is owned by **P3a**, not MEAS. | `scan-funnel.jsonl` 6 rows, one date |
| 3 | "DONE 2026-09-09: DIRECT-SEND-STOP-GATE" | Only its item (5), the parked IV measurement. | `iv-basis-samples.jsonl`: 0 absolute rows |
| 4 | "DONE 2026-09-09: PHASE E (piece 6" | Only its item (5), same. | same |
| 5 | "ANSWERED 2026-09-19 BY READING THEM" | Yes — min_mult needs a different conviction value. | `scoring_rules.yaml` regime_sizing `min_mult: 0.3`, `full_conviction_pct: 40` unchanged |
| 6 | "RESCUED … CORRECTED 2026-09-09" (absolute half never measured) | Yes. | 0 absolute rows |
| 7 | "RESCUED … MEASUREMENT PAUSED 2026-09-09" (bearish walls) | Yes. | `contract_rules.yaml` min_volume 50 / min_open_interest 200 / min_stock_score 55; `confidence_reject_below` 35 |
| 8 | "Phase A percentile thresholds are UNMEASURED" | Yes. | `scoring_rules.yaml` iv_rank_pass_max 34/44, caution 55/65 "UNMEASURED — seeded" |
| 9 | "ivAbsThreshold (spread picker, default 50) is UNMEASURED" | Yes. | `settingsStore.ts` ivAbsThreshold 50; 0 absolute rows |

Nothing was already fixed by another package. None of the nine can close in this session: they
close only after Kenneth has run the days and answered the proposal table.

## 2. What gets measured, and which scan answers it

| Threshold (file:key) | Answered by |
|---|---|
| Bearish direction floors `direction_conviction_min_trend` 30 Swing / 40 Position (scoring_rules.yaml) | stock scans S1–S4 (`direction_gate` counts) |
| Confidence gate `confidence_reject_below` 35 (Step-3 / settingsStore) | options + stock scans, per-reject breakdown `confidence` |
| Contract floors `min_volume` 50, `min_open_interest` 200, `min_stock_score` 55 (contract_rules.yaml) | options scans O1–O4, contract reject reasons |
| `regime_sizing.min_mult` 0.3 (scoring_rules.yaml) | regime snapshot (`conviction_pct`, OMM `stability`) on each day; needs a day whose conviction differs from +27 |
| `iv_rank_pass_max` / `iv_rank_caution_max` (scoring_rules.yaml), `preferred_iv_rank_max` 55, `max_iv_rank` 70 (contract_rules.yaml) | options scans O1–O4 with the percentile source ON (rank rows) |
| `ivAbsThreshold` 50 (spread picker; settingsStore / ScanRequest.iv_abs_threshold) | O5: bearish options scan with the percentile source OFF (absolute rows) |

## 3. The scan set (per measurement day)

Bodies are the 2026-09-18 bodies **byte-for-byte** where one exists, so the days compare. New ones
(O3/O4 Swing options, O5) are the O1 body with only the horizon fields changed.

| id | Endpoint | Direction | Horizon / preset | Body file |
|---|---|---|---|---|
| O1 | POST /api/scan | Bearish | Position / Position (hold 15–45) | `options-position-bearish.request.json` (= 2026-09-18 `sp500-position-bearish`) |
| O2 | POST /api/scan | Bullish | Position / Position | `options-position-bullish.request.json` (= 2026-09-18) |
| O3 | POST /api/scan | Bearish | Swing / Swing (hold 5–15) | `options-swing-bearish.request.json` (new) |
| O4 | POST /api/scan | Bullish | Swing / Swing | `options-swing-bullish.request.json` (new) |
| S1–S4 | POST /api/stock-scan | Bearish/Bullish × Swing/Position | pullback_ema | `stocks-{swing,position}-{bearish,bullish}.request.json` (= 2026-09-18) |
| O5 | POST /api/scan, **percentile source OFF** | Bearish | Position | `options-position-bearish.request.json` again, result saved as `ivabs-options-position-bearish` |

Context captured on the same run: `GET /auto-trade/status`, `GET /api/data-sources`,
`GET /api/regime?horizon=swing` and `?horizon=position` (before the first and after the last scan),
backend git commit, start/end UTC.

## 4. Safety rules baked into the run-book

1. **Auto-trader must be disarmed.** `POST /api/scan` fires an armed auto-trade when a PASS candidate
   exists (scan.py run_scan). The run-book checks `GET /auto-trade/status` → `armed: false`
   before **every** options scan and stops otherwise. Stock scans never fire it.
2. **Percentile source OFF without touching the real credentials file.** The backend reads
   `BAMENDJOU_CREDS_PATH` (credential_store.py). The run-book copies
   `backend/config/local_credentials.yaml` to a file **outside the repo** with the `tastytrade_paper`
   and `tastytrade_live` slots removed (Tradier kept — it supplies the chains), stops the IBKR
   gateway, restarts the backend with that env var, verifies via `/api/data-sources` that
   `tastytrade` is `unconfigured` and `ibkr` is not `connected`, runs O5, then restarts the backend
   normally and verifies tastytrade is `connected` again. The copy is deleted afterwards.
   Never `POST /settings/credentials` to blank a slot (that rewrites the real file).
3. **Timing.** US regular hours, starting no earlier than 12:00 ET (18:00 CEST), so daily
   option volume has accumulated (the 2026-09-09 timing wall). 2026-09-18 ran 13:20–13:57 ET.
4. **Backend on current main**, restarted before the run (09-18 found a stale backend).
5. Nothing the run writes is under `backend/config/`. Output goes to
   `docs/superpowers/measurements/scans/<YYYY-MM-DD>/`.

## 5. Day rules (Q28)

- At least **two new days**, not counting 2026-09-18, on different calendar days.
- "Different regime" is recorded, not assumed: the results sheet prints each day's
  conviction_pct, OMM state + stability, HMM state, VIX, regime_direction. A day counts as a
  **different regime** from another if at least one holds: |Δ conviction_pct| ≥ 15, OMM stability
  differs (Stable vs Fragile), VIX differs by ≥ 5 points, or regime_direction differs.
- min_mult is proposed only if the collected days (09-18 included) contain at least two different
  regimes by that rule. Otherwise the sheet says "not proposable yet" and asks for another day.

## 6. Reading rules, fixed before the data exists

The proposing session applies these rules and nothing else; each proposal lists the rows it used.

- **Bearish direction floors (30/40).** Per day and horizon: bearish reject rate =
  rejected / entered. Keep the floor if, on every day, the bearish rate is within 10 points of the
  bullish rate on the same day and horizon **and** below 50%. Propose one quantised step down
  (15 points; the trend score moves in steps of 15) only if the bearish rate is ≥ 50% on at least
  two days. Propose one step up only if the bearish rate is < 2% on every day **and** bearish
  candidates reach the shortlist. Otherwise keep.
- **Confidence gate (35).** Report, per bearish scan, how many score-gate rejects have confidence
  as the only cause and how many would clear at 30 and 25 (read from the breakdown). Propose a
  change only if the lower value adds candidates on ≥ 2 days; the bullish pass rate is a reference,
  not a target (plan of record, refinement).
- **Contract floors (50 / 200 / 55).** Report per options scan the symbols lost to each reason.
  min_stock_score: report the count in the 35–54 band lost to `stock_score_below_threshold`.
  Propose only with ≥ 2 days showing the same wall; liquidity floors are not lowered on bearish
  starvation alone (liquidity protects fills).
- **min_mult (0.3).** Report the multiplier each day's conviction produces under the shipped block
  and under ±0.1 around it, and each day's stability. Proposal needs the different-regime condition
  in section 5.
- **IV rank thresholds.** Needs ≥ 30 rank-basis rows across ≥ 2 days (today 10). Report where
  pass_max / caution_max / preferred_iv_rank_max / max_iv_rank fall as percentiles of the rank sample,
  per horizon, and the right-truncation count the report prints. Propose moving a seed only if the
  sample puts the current cut outside the 20th–80th percentile band of its own basis.
- **ivAbsThreshold (50).** Needs ≥ 15 absolute-basis rows from O5 across ≥ 2 days. Report the share
  of rows on each side of 50 and the structure picked (credit vs debit) with its net credit/debit.
  Propose only if one side of 50 holds < 20% of rows (the line is then not splitting anything).

Below a sample-size floor the sheet says **"not enough data"** for that threshold; it never
proposes from a smaller sample.

## 7. After Kenneth runs a day

A session (any machine) with the new `scans/<date>/` folder:

1. `cd backend && .venv/bin/python scripts/iv_basis_analysis.py collect --json <file>` for each
   options result, where `<file>` is a `{"request": …, "result": …}` envelope built from the pair
   (O5 included); the script pairs thresholds from the request.
2. Appends one row per scan to `scan-funnel.jsonl` in the 2026-09-18 row shape.
3. Fills that day's section in RESULTS-SHEET.md.
4. After the last day: fills the proposal table under the reading rules and asks Kenneth yes/no
   per threshold. Each "yes" becomes a separate config change with its own loop; each answer is
   recorded as a decision.

## 8. Verify probe

Phase `MEAS-MARKET-DATA-MEASUREMENT`: `kind: present`, path
`docs/superpowers/measurements/PROTOCOL.md`, pattern `BAMENDJOU_CREDS_PATH` (the safety-critical
step that switches the percentile source off without touching real credentials). Status
`in_progress` until the days are run and the proposals answered.

## 9. Tests / mutation checks

Docs only, so no unit tests. Instead, mechanical checks run before the code round:

- every `protocol-requests/*.json` parses and validates against the current Pydantic models
  (`ScanRequest`, `StockScanRequest`) in a scratch script (not committed);
- the 2026-09-18-derived bodies are byte-identical in content (JSON-equal) to their sources;
- every endpoint path in PROTOCOL.md exists in the routers (grep);
- the credentials-strip snippet, run against a synthetic YAML in the scratchpad, removes exactly
  the two tastytrade slots and keeps the others (mutation: strip nothing → the verify step's
  check on the output must fail).
