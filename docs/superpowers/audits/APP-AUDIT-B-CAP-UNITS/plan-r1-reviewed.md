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

## Acceptance and reviews

One fresh independent plan reviewer must verify this concrete plan against the
named sources before the build ticket is cut. One fresh independent code
reviewer then reviews the integrated phase diff; cap3 per stage, later rounds
only fixes/interactions. Numeric/persistence gate applies. A clean review is
not evidence of a merge. Publish the exact regression evidence and PR; self-merge
only under board.md conditions with every CI check green on the exact head.
