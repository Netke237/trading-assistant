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

## Independent integrated code audit

Continuous round 2, code round 1 of 3. Fresh independent reviewer
`/root/backtest_code_audit_r1` applied the BMad adversarial skill to the complete
exact diff `64b9d53f21f92e0266cb7dd7790c66e3f19f1397..bc81207942574257eb123f3479ce37da668dfc4f`
against the approved plan and current callers. Two source passes returned
**zero numeric/persistence gate findings**. No fixes or outstanding findings.

Reviewed engine/detail collection, model/service/router/migration, fresh
validation/service, scan capture/cache/linkage, report projection, frontend
route/navigation/stale guards, historical series/fills/inspection, fresh
controls/API/types and associated tests/documents. Second pass checked summary
preservation, epoch mapping, actual fills, equity/return reconciliation, gross
long benchmark, open/zero/unavailable states, complete parameters, cache
collisions, expiry, opposite directions, stale replies, fresh request agreement
and original/report/trading-state isolation.

Independent Python 3.11 matrix: 12 cases across all six supported fresh strategies
and both directions passed explicit parameter validation, effective-parameter
parity, ending-return reconciliation and benchmark baseline. No real provider,
order, alert or save calls. Auditor made no edits. Plan1/code1 clean; total2.

## Final local checks

- Frontend: 261 suites / **5344 tests passed**, 326 seconds, stable source.
- Typecheck: passed.
- Production build: passed with the actual Google Fonts fetch in this environment.
- Mocked Chromium: **10 cases passed** (9 matrix/availability + 1 fresh separation).
- Focused backend: **76 passed**, including 15 fresh-run tests.
- Full Python 3.11 backend: **9084 passed, 9 skipped, 1 failed** in 960.18 seconds. Sole failure is the route-wide untyped-field inventory, which detects the new `FreshBacktestRequest.params` entry. Bounded inventory/documentation and HTTP regression follow-up pending; no production-code validation defect observed.
- Exact-head hosted CI: not started because publication authorization is pending.

No application code changed after the clean audit. This documentation records
its verdict only. Local audit-clean/built does not mean shipped or merge-ready:
full backend completion, publication authorization and exact-head CI remain.

## Full-suite inventory follow-up

The full run completed; its single failure is
`test_request_finite_inventory.py::test_untyped_leaves_match_the_section_1_inventory`.
The runtime registry now has 35 untyped dictionary leaves; the historical
inventory listed 34. Fresh implementer `/root/backtest_inventory_fix` is
checking the existing strict parameter/middleware validation, recording the
new route deliberately, and adding direct/nested nonfinite HTTP refusals.
Original independent clean code round1 remains in history; overall clean
status is pending the bounded follow-up audit within the remaining cap.

Follow-up implemented at `2625a73f` by the fresh implementer. Three changed
files: the exact request inventory test, fresh HTTP tests and section1 of the
existing finite-input inventory plan. Exact original34 entries and float-leaf
probes remain; only the deliberate new endpoint is added (current total35).
Twenty new HTTP nonfinite literal/string cases cover direct and nested multi
parameters and prove422 before any history/engine call; finite controls reach
history. All tests passed against unchanged production validation.

Combined follow-up verification: request finite inventory, JSON finite guard,
fresh endpoint and artifact suites **84 passed** in7.59seconds. Typecheck and
diff checks passed. The full16-minute backend run was not repeated after this
test/documentation-only correction; every other test had already passed, and
the sole failed check now passes in the affected suites. Exact-head hosted CI
still must pass after authorized publication and before any merge. Fresh
shrinking follow-up audit is pending; no application code changed.

## Follow-up audit and final checkpoint

Continuous round3, code round2 of3: fresh independent reviewer
`/root/backtest_code_audit_r2` applied BMad adversarial to only
`bc81207942574257eb123f3479ce37da668dfc4f..413e1e4a2556dc5845bc99785c83d469a086aea4`
and its interactions with the existing strict parameter validator, whole-body
JSON guard and real app registration. **Zero gate findings**, no fixes or
outstanding findings. Original34 tuples preserved, sole new tuple total35,
float probes unchanged. Independent22 targeted tests passed;220 invalid
configurations rejected;12 finite direct/multi configurations accepted.
Second pass checked anti-vacuity, nested mutation, middleware/model rejection,
strict keys/types/ranges/nulls, selected-variant recursion and mechanism claims.
No reviewer edits or real provider/order/alert/save calls.

Plan1/code2 independently clean; continuous total3 within per-stage caps.
Application code remains unchanged after the first whole-feature clean audit.
The entire local implementation is built and reviewed. The full backend run
had9084passed/9skipped/1inventoryfailure; the sole failure was corrected by the
test/documentation-only change and all84 affected checks passed. No second
full backend run was made. Frontend5344, typecheck, production build and10
mocked browser checks passed. Hosted CI must still pass on the published exact
head before merge. Nothing is merged or recorded shipped.

Publication/child-ticket closure is pending explicit user authorization after
automatic approval review rejected those external writes. New commits are
local; the remote continuation branch still contains the recovered checkpoint.
A local continuation bundle is prepared alongside the repository for recovery
if publication stays blocked.

## Authorized publication and pending merge

The user explicitly authorized pushing the reviewed branch, opening its PR and
merging only after required CI passes (2026-10-15, this chat). Publication is
now authorized; prior automatic-approval blockage is historical. PR #333 is
open. SELF-MERGE PENDING; phase remains built. Last independent clean scope
ends at413e1e4a; subsequent commits record only verdict/validation/pending-merge
documentation. No application changes. Exact final published head must be
MERGEABLE with every required CI check successful before a matched-head merge.
