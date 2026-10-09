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

### Code round 1 (2026-10-09) — NOT CLEAN, 2 gate findings, fixed
- Reviewer: fresh independent subagent (bmad-review-adversarial-general), scope 55232a50..959f0221.
- F1 gate 4: docstring claimed exact strike; matching truncates to int (pre-existing). Docstring fixed (c84556aa); exact-strike bug spun off as its own task.
- F2 gate 1/2: missing quote -> $0 mark on Portfolio + persisted equity snapshot; widened by NLQ-1. Fixed c84556aa, 67a99f44, 0c605733 (quoteUnavailable, snapshot skip, '—', display totals exclude, exposure sums at entry price).
- BELOW-GATE (logged, not fixed): yaml comment says 'NYSE session' though no holiday/early-close calendar (sandbox early-close residual 13:00-13:45); max_age_minutes 1e308 overflows to inf; NaN bid with fresh stamps reads live (Tradier JSON has no NaN); sandbox quoteAgeS excludes the 15-min lag.
- Round 2 scope: git diff 5b14896e..0c605733 (fixes only) + interactions.
