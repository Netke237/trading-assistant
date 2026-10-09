# NLQ-3 — Auto-trade fire gate

Status: done — code round 1 clean
Blocked by: NLQ-1
Plan sections: 3d (incl. the conftest autouse fixture + real_quote_gate marker registration) of `docs/superpowers/plans/2026-09-30-no-live-quote-plan.md`
Tests to add (plan 3g): T8
Mutations that must fail a test (plan 3g): M7, M8

## Acceptance
- Implements exactly the named plan sections with Kenneth's answers (spec.md); nothing else.
- Every plan line reference re-located on the current branch before editing.
- Named tests added in the files the plan names; each listed mutation applied, shown to fail, reverted.
- Python 3.11 backend tests for touched modules pass; frontend typecheck clean when frontend touched.
- One fresh gate-briefed adversarial round returns zero gate findings (cap 3).

## Findings
(audit rounds recorded here)

## Added 2026-10-09 (Kenneth): Tradier rate limiter is mandatory
The fire gate's direct Tradier GET MUST take a token from the existing governor's `tradier` bucket
(`backend/app/data/governor.py`, 120/min, capacity 15) and respect its circuit breaker. `fire()` is sync and
runs the probe in a worker thread, while the governor is asyncio-based: add a thread-safe, non-blocking sync
acquire (e.g. `try_acquire()` under a threading lock) rather than calling the async API from a foreign loop.
No token / open circuit -> `"unavailable"` -> ArmPreservedError (nothing sent, armed state kept). A 429 counts as a
failure for the circuit. Tests pin: no token -> no HTTP call and refusal; 429 -> refusal + failure recorded.

Round 1: fresh /root/nlq3_audit1, zero gate findings; 268 focused tests. Exact scope/report: docs/superpowers/audits/2026-10-10-no-live-quote-nlq3.md. M7/M8 behavioral failures verified; original bytes restored.
