# NLQ-2 — Backend grading + wire + recompute + scheduled-scan notice

Status: open
Blocked by: NLQ-1
Plan sections: 3b, 3c, 3e (backend parts: RecomputePlanRequest.quote_live, assess_entry quote_live), 3f (ScanResult.noLiveQuoteNames + scheduler notice clause) of `docs/superpowers/plans/2026-09-30-no-live-quote-plan.md`
Tests to add (plan 3g): T6, T7, T9, T10
Mutations that must fail a test (plan 3g): M4, M5, M6

## Acceptance
- Implements exactly the named plan sections with Kenneth's answers (spec.md); nothing else.
- Every plan line reference re-located on the current branch before editing.
- Named tests added in the files the plan names; each listed mutation applied, shown to fail, reverted.
- Python 3.11 backend tests for touched modules pass; frontend typecheck clean when frontend touched.
- One fresh gate-briefed adversarial round returns zero gate findings (cap 3).

## Findings
(audit rounds recorded here)
