# Candidate backtest chart — integrated validation

Phase `CANDIDATE-BACKTEST-CHART`, parent #288, units #289–294.

## Preservation crosswalk

| Contract | Source / verification |
| --- | --- |
| Original summary and legacy date-only trade APIs keep their values | `strategy_backtest.py` optional same-invocation collector; detailed engine parity tests cover actual native equity, fills, fees, both directions, time exits and original source epochs. No second original invocation. |
| Optional original capture/storage never changes candidate eligibility, ranking, gate or trading fields | `test_stock_scan_artifacts.py` tests complete numeric/trading equality under cache/capture/storage faults; original-unavailable remains explicit. |
| Original exact identity cannot resolve to latest settings or same-symbol alternate run | Immutable SQLAlchemy artifact, opaque ID plus symbol, detached JSON, full-bars fingerprint, full effective inputs, unique per-scan linkage; roundtrip/concurrency/expiry/tombstone/cache tests. |
| Reports retain references without browser curve persistence | Additive UUID/status report projection and existing scan-report storage; no curve stored in scan stores. Existing aggregate-only reports stay unavailable. |
| Candidate navigation keeps clicked row and existing behavior | Stocks position card Jump to Chart; all three Pre-Breakout chart actions; typed route and stale-safe loading tests. Unsupported setup evidence cannot map to another strategy. |
| Historical chart is distinct from live chart signals | Dedicated historical organism, frozen source candles, exact fills, indexed native engine equity and gross long close-price benchmark. All historical fields are read from the selected artifact. |
| Fresh runs do not change saved original or trading inputs | Explicit configuration and separate fresh artifact/state; endpoint has no report, candidate, order or arm writes. Focused endpoint and UI checks plus mocked browser verification. |

## Scope and audit provenance

Recovered checkpoint `f34410054fe075ae72791981829c9489384cd163` contains BT-01–03. Interrupted BT-04 had no pushed commit and was rebuilt by a fresh implementer. Existing independent clean plan round 1 is preserved. Integrated code audit starts at code round 1, with three-round cap and fresh independent reviewers; author verification does not clear the audit gate.

Final checks and reviewed diff will be recorded after BT-04/05 and current-main reconciliation.

## BT-04 continuation evidence

Fresh implementer `/root/bt04_implementation`, commit `30ea2236`:
focused 3 suites / 12 tests and typecheck passed. Full frontend suite was started
on BT-04 before current-main reconciliation; its final result is recorded below
when available. Browser verification passed 9 cases using Chromium: both
Bullish/Bearish, dark/light, 1280/1920 widths; daily and intraday timestamps,
keyboard trade inspection with actual prices/returns, configuration provenance,
interval reset without another artifact read or a write, and successful zero
trades versus unsupported setup state. Screenshots inspected at 1280px.

The original 1200px attempt was obstructed by the existing `MinWidthGate`
(now 1280px); corrected to the actual supported minimum. No product code was
changed for this environment/test assumption.

Browser fixture regeneration (Python 3.11 backend environment, no providers,
orders, alerts or real persistence):

```sh
cd backend
PYTHONPATH=. .venv/bin/python ../docs/superpowers/plans/2026-10-15-candidate-backtest-browser-fixtures.py /tmp/backtest-browser-fixtures.json
cd ../frontend
BACKTEST_BROWSER_FIXTURES=/tmp/backtest-browser-fixtures.json npx playwright test e2e/tests/candidate-backtest.spec.ts --project=chromium
```

The browser suite is opt-in through `BACKTEST_BROWSER_FIXTURES` so ordinary smoke
CI collection needs neither the Python environment nor a pre-existing local
artifact file. It exercises the real frontend against frozen mocked API data
created from the real detailed engine, not a live backend/provider integration.

## Publication status

Automatic approval review rejected publishing newly implemented code and closing
#292 because it required explicit repository-publication authorization. A second
attempt was not made. All remaining implementation, verification and independent
audit continue locally; ask for publication permission only once the complete
change is concrete and reviewable. The earlier continuation branch reference
contains only the already-remote recovered checkpoint; new commits remain local.

## BT-05 continuation evidence

Fresh implementer `/root/bt05_implementation`, commit `6193551f`:
76 focused backend tests, 23 focused frontend tests and typecheck passed.
The fixed order-size contract is exactly the engine default
`0.9999999999999998`, not an approximate 0.9999. Server and browser validate
recorded parameters, direction, strategy, interval, date window, fees, hold/gate
settings and sizing against the explicit request. New IDs and `fresh` provenance
leave original artifacts untouched. Existing six daily top-level strategies are
supported; no setup strategy is silently mapped to a different original.

Final mocked browser verification: 9 matrix/availability cases passed on the
combined source, then the fresh case passed separately after correcting its
expected heading to the implemented `Fresh backtest (separate result)` label.
The fresh case submits reviewed values, checks its only write is the mocked
fresh endpoint, switches back to the original ID, and confirms saved scan inputs
are unchanged. No real orders, arms, alerts or saves were performed.

Current main remains `64b9d53f21f92e0266cb7dd7790c66e3f19f1397`, fetched again
before the integrated independent audit. Full backend/frontend/build outcomes
and the exact reviewed head are pending below.
