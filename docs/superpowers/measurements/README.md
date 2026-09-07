# Measurements

Evidence, not prose. Everything here is written by a script and read by a human
deciding whether to move a number.

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
