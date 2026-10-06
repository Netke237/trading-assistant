# P0A live verification, 2026-10-06

Backend restarted on Python 3.11.9; /health returned ok; auto-trade status was unarmed before the options scan. No broker-order or arm endpoint was called.

## Swing Bullish SP500 options scan

Request: universe SP500, direction Bullish, horizon Swing, hold 2-15 calendar days, horizon_preset Swing; remaining settings use backend defaults.

- Scanned: 518. Sum of funnel buckets including candidates: 518.
- Excluded (data): 14, including CTVA and AVB. Exclusion reasons retain the shared YAML descriptions.
- Data bucket: 26; candidate count: 10.
- All ten candidates have confidence null and an Unvalidated interpretation; none has stock status or final status PASS.

| Symbol | Stock status | Final status |
|---|---|---|
| CCL | CAUTION | CAUTION |
| AMD | CAUTION | CAUTION |
| CSCO | CAUTION | CAUTION |
| HPE | CAUTION | CAUTION |
| CRWD | CAUTION | CAUTION |
| META | CAUTION | CAUTION |
| SMCI | CAUTION | CAUTION |
| MSFT | CAUTION | CAUTION |
| ON | CAUTION | CAUTION |
| WBD | CAUTION | REJECT |

## Calibration

SELECT-only harness on 20 requested symbols kept 18 and printed CTVA/AVB as excluded; loaded bars ended 2026-10-02, cache basis b3. See 2026-10-06-p0a-score-calibration.md.

## Stocks check

Request: protocol-requests/stocks-swing-bullish.request.json (pullback_ema with its recorded scan overrides).

- Scanned: 518. Sum of funnel buckets including candidates: 518.
- Excluded (data): 14, including CTVA and AVB, counted in failed_history.
- Candidate: MKTX, measured confidence 40, stock_status CAUTION. No Unvalidated stock candidate survived this scan; synthetic endpoint regressions cover the missing-confidence path.

## CI

P0A PR #88: backend 6174 passed, 2 skipped (Python 3.11); frontend typecheck/tests/build and repository test check passed. Local frontend: typecheck clean, Jest 4688/4689 passed with the previously recorded BarrierRaceCard locale failure. Supplemental local backend suite: 6151 passed, 4 skipped, 6 failed, 1 error. Four failures in test_atomic_yaml.py and the test_historical_store_settle.py::test_19 error are the recorded Windows baselines. Two test_conviction_sizing.py failures were FileNotFoundError from invoking the full suite at repo root; both passed when rerun from backend. State prerequisite suites were verified separately (117 passed), including the 14 newly added lifecycle cases. No code or pin was changed to accommodate these failures.
