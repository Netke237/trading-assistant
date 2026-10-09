# K-Session: STOCKS-HORIZON-HISTORY

## Goal
D1 plan audit and D2 synthetic/mocked build, code audit and PR; D3 live execution is reserved for the mini PC.

## Status
D1 plan clean after two independent rounds. D2 build and code audit complete;
code rounds 1 and 2 found one defect each, both fixed; fresh round 3 returned
zero gate findings. PR #130 ready for review; unmerged and awaiting approval.
12 SQLite/PostgreSQL semantic tests and 192 focused regressions passed; final
reviewer independently passed 26 tests (6 PostgreSQL cases skipped). D3 unrun.

## Done
- Read project state and coordinator/audit instructions; no initial state drift.
- Claimed STOCKS-HORIZON-HISTORY on codex/stocks-horizon-history; base aaa7102c.
- Preserved inherited draft from origin/claude/stocks-horizon-t1 and wrote complete redesigned plan with six work packages.

## Next steps
- [x] Implement/verify #124 to #127 and independent code audit #128.
- [x] Publish PR #130 with exact audit records and test limitations.
- [ ] Merge only after user approval; keep D2 parent/tracking open until merged.
- [ ] Run D3 #114 only on the mini PC after merge, following the runbook.

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
- Preserved original audit/trade retention tests; OHLCV tests moved to a separate file after a filename collision.
- Strict provider adapter tests: 73 passed; selective seam/evidence tests: 77 passed. Coherent write/refresh/job suite: 51 passed, one legacy endpoint mock adapted before rerun.
- Final pre-fix focused suite: 199 passed. Broad suite: 6436 passed, 2 skipped, 3 baseline failures reproduced unchanged on main; no unrelated fixes in this branch.
- Code round 1 reviewed base aaa7102c to 058295df; one confirmed asyncpg parameter-limit finding. Fix preserves one transaction across bounded upsert statements; audit record stored in docs/superpowers/audits/2026-10-09-stocks-horizon-history-code.md.

- Resumed existing worktree and renewed its claim after handoff confirmation. Interrupted code round 2 produced no report; completing its exact 058295df..c188487b fix scope with a fresh independent replacement, preserving the stage cap.

- Final R3 exact 16020518..eca4a41e: fresh history_code_audit_r3, zero gate findings. Three completed code rounds, two plan rounds; no fourth code round.
