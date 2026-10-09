# K-Session: STOCKS-HORIZON-HISTORY

## Goal
D1 plan audit and D2 synthetic/mocked build, code audit and PR; D3 live execution is reserved for the mini PC.

## Status
D1 plan stage clean after two independent rounds; D2 retention #124 implemented/verified, atomic backfill #125 starts. Code audit not run.

## Done
- Read project state and coordinator/audit instructions; no initial state drift.
- Claimed STOCKS-HORIZON-HISTORY on codex/stocks-horizon-history; base aaa7102c.
- Preserved inherited draft from origin/claude/stocks-horizon-t1 and wrote complete redesigned plan with six work packages.

## Next steps
- [x] Plan round 2 clean over the two fixes and interactions (fb19f2f3).
- [x] Published tracking #123 and build tickets #124 to #128.
- [ ] Execute #124 retention, then #125 backfill, #126 refresh/evidence, #127 verification.
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

- Retention slice: 32 targeted tests passed on isolated Python 3.11; frontend typecheck clean. No live data calls.
