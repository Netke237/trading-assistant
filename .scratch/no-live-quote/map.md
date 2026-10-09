# Ticket map — NO-LIVE-QUOTE → CONTRACT-LIQUIDITY-DTE

Branch for NLQ tickets: `claude/priceless-jennings-995ab7`. Branch for CL tickets: `claude/contract-liquidity-dte`.

| ID | Title | Blocked by | Status |
|---|---|---|---|
| NLQ-1 | Data: quote classifier, config key, chain builders, quote expiry check (plan 3a) | — | done |
| NLQ-2 | Backend grading + wire + recompute + scheduled notice (3b, 3c, 3e-backend, 3f) | NLQ-1 | done — code round 1 clean |
| NLQ-3 | Auto-trade fire gate (3d) | NLQ-1 | open |
| NLQ-4 | Frontend: Step 6/Watchlist tag, Step 7 warning + send-time gate + tick, recompute, ScanLog (3e) | NLQ-2 | open |
| NLQ-5 | Final clearance: full regression, mutations table, state bookkeeping, report to Kenneth | NLQ-2, NLQ-3, NLQ-4 | open |
| CL-1 | CONTRACT-LIQUIDITY-DTE: bring NLQ + main in, re-base plan r5, build fixes 1, 2, 4 | NLQ-5 | open |
| CL-2 | CONTRACT-LIQUIDITY-DTE: final clearance + report | CL-1 | open |
| TG-1 | Route every Tradier call through the rate limiter (separate, own plan) | NLQ-3 | open |
| JOIN | Kenneth: merge NLQ to main, then CL; sync local main with origin/main | NLQ-5, CL-2 | waiting on Kenneth |

## Current Frontier
- NLQ-3
- NLQ-4

## Rules
- Audit per ticket: fresh independent subagent applying bmad-review-adversarial-general, gate-briefed;
  round 1 = whole ticket diff, round N>1 = previous fixes only; cap 3 per ticket; >3 gate findings in one
  round → stop and tell Kenneth.
- Commit subjects: `NO-LIVE-QUOTE NLQ-<n>: ...`, audit records `NO-LIVE-QUOTE NLQ-<n> code round K ...`.
- No merge to main without Kenneth.

Scoped cap is explicitly authorized by user decision NO-LIVE-QUOTE-SCOPED-AUDITS-2026-10-09; see orchestration exception and phase audit_scopes.
