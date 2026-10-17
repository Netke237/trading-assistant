# APP-AUDIT-B-CAP-UNITS — repair Options market-cap units (#368)

Part of the user-authorized remediation of #350. This is one independent phase,
not an extension/reset of the evidence phase's review cap. No calibration,
Stocks-universe fix, broker call, notification or shared job is included.

## Existing behavior and intended result

Step2 labels M as millions. The shared buildOptionsScanRequestBody currently
uses 1 for M and 1e9 for B. Both RunScanButton and the Options branch of
resolveProfileToScanRequest call that builder. The backend scan request and
candidate filter compare literal USD. Thus minimum25M incorrectly sends25USD.
The shared conversion must send25,000,000USD, and2B must remain2,000,000,000USD.
Preserve explicit zero, omitted empty values, finite-value checks, both min/max,
profile storage shape, risk gates and all other request fields.

## Task1 — regression and shared conversion

Fresh implementer owns only frontend/lib/resolveOptionsScanRequest.ts and
focused tests around that builder, frontend/lib/__tests__/scanScheduleResolve.test.ts,
RunScanButton tests, and a focused backend filter test if required by acceptance.
The schedule resolver should continue delegating to the shared builder; do not
introduce a second conversion or alter its production behavior separately.

1. Add failing table-driven expectations from literal unit arithmetic, covering
   min/max25M and2B, fractional M/B, explicit0 and empty omission. Exercise the
   shared builder, the saved Options-profile resolver, and an actual rendered
   manual RunScanButton with mocked postScanBody (capture the posted USD fields).
   Keep other stores explicitly seeded so regime/portfolio gates do not hide the
   request. Confirm failure specifically reports25 instead of25,000,000.
2. Change the M multiplier to1e6 in the shared builder. Preserve B1e9 and existing
   finite/empty semantics. Avoid unrelated parsing/range cleanup.
3. Retest backend effective filtering on deterministic market-cap fixtures
   below/at/above the captured minimum and maximum using the actual candidate
   filter with unrelated providers/scorers mocked. Reuse existing backend
   fixtures/helpers where possible; no app lifespan, provider or order access.
4. Run targeted frontend regressions, frontend typecheck and full frontend
   suite. Use the prepared Python3.11 environment for the focused backend test;
   if any backend source changes unexpectedly become necessary, stop and report
   the plan deviation rather than widening this phase. Record actual commands,
   counts and RED/GREEN output. Never modify audit captures or golden numbers.
5. Commit application/tests only with a fix subject referencing368; do not edit
   coordinator state/audit fields or push. Coordinator records build closure,
   merges current main, reruns required checks and starts independent code review.

## Plan1 finding — stored schedules must not replay ambiguous old values

Independent reviewer fix368_plan_r1 reproduced a reachable gap: schedules saved
before this repair persist literal25 in resolved_request; the scheduler replays
that blob without rebuilding from a profile. Units cannot be inferred from the
number because both legitimateB/USD values and brokenM values are possible.
Never blindly multiply existing stored filters or rewrite ambiguous source data.

Extend Task1's production scope to backend/app/schemas/__init__.py and
backend/app/services/scan_schedule_scheduler.py, with focused schema/scheduler
regressions. Keep scan_schedule_store.py and profile persistence untouched so
this phase stays disjoint from381/401. Add an explicit optional request marker
cap_filter_units_version:Literal[1]|None (defaultNone), and have the corrected
shared Options builder send1. It describes the unit conversion convention,
not a tunable score override. Preserve marker through resolved_request storage.
Direct manual API ScanRequest remains compatible without the marker; do not
reject a legitimate explicit USD manual request.

Before dispatching an Options scheduled scan with any nonzero cap filter, require
marker1. Legacy/no-marker requests with nonzero caps must refuse BEFORE the scan
core/provider is called, using the existing scheduled-run error channel with a
clear message to re-save the Search Profile and confirm filter units. Do not
silently alter stored values, delete/disable entries or send actual test notices.
No-filter and zero-only legacy schedules remain safe and continue normally.
A newly resolved/resynced schedule carries marker1, correctUSD amounts, and runs.

Add RED/GREEN regressions for a pre-fix persisted25 minimum (and maximum),
no invocation of scan core until explicit fresh profile-resolved request,
correct new25M/2B execution, old no-filter/zero-only schedules, preservation of
raw stored requests, and explicit error status/message. Use isolated scheduler
stubs/temp DB and mocked reporting/notifications/providers. Verify marker is
retained through real schedule schema and storage roundtrip. Schema rejects
unsupported explicit marker versions without any data mutation. Run full
backend pytest because backend production files now change, and all frontend
checks already specified. This restores safe execution without inventing lost
profile-unit intent or requiring a real scheduled job.

## Acceptance and reviews

One fresh independent plan reviewer must verify this concrete plan against the
named sources before the build ticket is cut. One fresh independent code
reviewer then reviews the integrated phase diff; cap3 per stage, later rounds
only fixes/interactions. Numeric/persistence gate applies. A clean review is
not evidence of a merge. Publish the exact regression evidence and PR; self-merge
only under board.md conditions with every CI check green on the exact head.
