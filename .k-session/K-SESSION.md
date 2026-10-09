# K-Session: STOCKS-HORIZON-HISTORY

## Goal
D1 plan audit and D2 synthetic/mocked build, code audit and PR; D3 live execution is reserved for the mini PC.

## Status
D1 plan round 1 found two gate findings; plan fixes written; independent fixes-only round 2 next. No application code built.

## Done
- Read project state and coordinator/audit instructions; no initial state drift.
- Claimed STOCKS-HORIZON-HISTORY on codex/stocks-horizon-history; base aaa7102c.
- Preserved inherited draft from origin/claude/stocks-horizon-t1 and wrote complete redesigned plan with six work packages.

## Next steps
- [ ] Run fresh independent plan round 2 over the two fixes and interactions; cap three plan rounds.
- [ ] Publish build tickets and execute the unblocked frontier after plan clean.
- [ ] Run synthetic/mocked tests, fresh independent code audit, cap three code rounds.
- [ ] Publish PR and release handoff at the merge approval gate.

## Blockers / open questions
- D3 operational work requires mini PC and D2 merge; intentionally remains pending.

## Decisions
- Use repository numeric/persistence gate; preserve the separate capped T1 audit history.
- Persist floor and seam metadata with OHLCV bars in the same DB transaction.
- Refetch older provider span nightly; never infer a floor from empty/error replies.
- Do not access operational bars, provider credentials or a live broker on this host.

## Conventions
- Branch codex/stocks-horizon-history, base main; integrate with merge, never rewrite pushed history.
- Before every checkpoint/commit: frontend npm run typecheck.
- Backend tests: Python 3.11, isolated databases, mocked providers and no network.
- Audit records identify fresh reviewers, reviewed diff, findings, fixes and outstanding findings.

- Plan round 1 reviewer history_plan_audit_r1: ingestion backtest cache eviction and strict adjustment completeness fixed in the plan; not yet re-audited.
- Checkpoint on this Windows host: set KSESSION_PYTHON=python to avoid the python3 Store alias; the newly installed hook supports this override.
