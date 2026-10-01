# Measurements

Evidence, not prose. Everything here is written by a script and read by a human
deciding whether to move a number.

## MEAS measurement days

- `PROTOCOL.md`: the run-book for Kenneth's market-hours measurement days.
- `run_measurement_day.py`: the runner that sends the exact bodies, checks every safety rule,
  and writes `scans/<date>/` with a `manifest.json`.
- `protocol-requests/*.json`: the eight base request bodies. The counterfactual bodies are
  derived from these by the runner.
- `RESULTS-SHEET.md`: one section per day, the proposal table, and the reading rules fixed in
  advance.

Plan: `../plans/2026-09-25-meas-market-data-measurement-plan.md`.

## `iv-basis-samples.jsonl`

Produced by `backend/scripts/iv_basis_analysis.py`. One JSON object per
candidate row per scan: the IV figure the scan actually saw, which quantity it
was (`absolute` or `rank`), the thresholds in force at the time, and the spread
structure that got attached.

```bash
cd backend
.venv/bin/python scripts/iv_basis_analysis.py            # collect + report
.venv/bin/python scripts/iv_basis_analysis.py collect    # append today's scan
.venv/bin/python scripts/iv_basis_analysis.py report     # analyse the whole store
```

Over `--url` the thresholds come from `GET /api/scan/last-run`, which returns
them next to the `scan_id` of the result `/api/scan/last` is serving. The script
records them only when the two ids agree, so a scan finishing mid-collect is
caught rather than stamping one run's credit/debit line onto another run's rows.
A backend too old to return `scan_id` records no threshold at all, and the
report's section 4 says out loud that it is falling back to the schema default
of 50 — rows collected that way measure the distribution, not the line.

**It appends, and that is the point.** One scan is one day of one universe. The
seeded thresholds it measures are not to be edited off a single session — let
several accumulate, ideally across different volatility regimes, before anyone
touches `scoring_rules.yaml` or `contract_rules.yaml`.

Two things the file cannot tell you, and the report says so on every run:

- **Percentile rows only exist when IBKR or tastytrade answered.** With neither
  connected, every candidate resolves to the absolute basis and the sample
  contains nothing that can judge `iv_rank_pass_max` / `iv_rank_caution_max` /
  `preferred_iv_rank_max` / `max_iv_rank`. The report will look perfectly
  healthy while answering nothing about them.
- **`iv_abs_threshold` is only exercised by a Bearish scan** — `choose_primary`
  is the spread picker, and spreads are built for Bearish direction alone.

The rows are survivors: the pre-screen, the stock-score gate and the contract
hard-reject ceilings have all already run, so the distribution is truncated on
the right by the very numbers being judged. The report prints the truncation
count it can see.

Q7's stop-premium fractions (0.80 / 0.70 / 0.60) are **not** measured here.
They are a decided number with a stated revisit trigger, on a Phase B basis that
is not built — see `PROJECT_STATE.json` open question 0 and
`plans/2026-09-02-gate-basis-spec.md:39`.

## `scan-funnel.jsonl`

One row per options scan: the pipeline funnel counts, why the score gate
rejected (confidence / regime / fundamentals, from each reject's breakdown),
contract-rule reasons by symbol, the candidates, and the Step-1 regime captured
at the same time. The regime is there on purpose: the same floor means
different things in different regimes, so a single day's counts cannot separate
"floor too high" from "the market is not offering that side". Bullish rows are a
reference, not a target for the bearish pass-rate.

## `scans/<date>/`

The raw material behind the funnel rows, for analysis without re-running
anything: `*.request.json` is the exact `POST /api/scan` body sent,
`*.result.json` the full `ScanResult` returned — every candidate with its
contract, plan and breakdowns, and every rejected symbol with its reason and
per-rule score breakdown (trend, pullback, trigger, event, vol, confidence,
regime, fundamentals). A score-gate reject's cause is read from that breakdown:
`confidence` below the request's `confidence_reject_below`, `regime` 0, or
`fundamentals` below `fundamentals_reject_below`.
