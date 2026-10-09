# NLQ-1 — Data: quote classifier, config key, chain builders, quote expiry check

Status: open
Blocked by: —
Plan sections: 3a (and 2 for current facts) of `docs/superpowers/plans/2026-09-30-no-live-quote-plan.md`
Tests to add (plan 3g): T1, T2, T3, T4, T5
Mutations that must fail a test (plan 3g): M1, M2, M3, M10, M11

## Acceptance
- Implements exactly the named plan sections with Kenneth's answers (spec.md); nothing else.
- Every plan line reference re-located on the current branch before editing.
- Named tests added in the files the plan names; each listed mutation applied, shown to fail, reverted.
- Python 3.11 backend tests for touched modules pass; frontend typecheck clean when frontend touched.
- One fresh gate-briefed adversarial round returns zero gate findings (cap 3).

## Findings
(audit rounds recorded here)
