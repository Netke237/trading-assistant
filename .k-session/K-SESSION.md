# K-Session: STOCKS-HORIZON-HISTORY

## Goal
D1 plan audit and D2 synthetic/mocked build, code audit and PR; D3 live execution is reserved for the mini PC.

## Status
D1 plan stage clean after two independent rounds. D2 draft PR #130 is open.
Fresh replacement completed interrupted code round 2: one fallback-transaction
leak found. Per-provider rollback fix and real SQLite/PostgreSQL constraint
failure regressions passed: 12 SQLite/PostgreSQL tests and 192 focused regressions.
Frontend typecheck clean; disposable database resources removed. Final allowed code round 3
next. Code audit remains unclean and merge approval is outstanding.

## Done
- Read project state and coordinator/audit instructions; no initial state drift.
- Claimed STOCKS-HORIZON-HISTORY on codex/stocks-horizon-history; base aaa7102c.
- Preserved inherited draft from origin/claude/stocks-horizon-t1 and wrote complete redesigned plan with six work packages.

## Next steps
- [x] Plan round 2 clean over the two fixes and interactions (fb19f2f3).
- [x] Published tracking #123 and build tickets #124 to #128.
- [x] Implement and verify #124 retention, #125 backfill, #126 refresh/evidence and #127 verification; ticket closure awaits final audit.
- [ ] Finish rollback regressions and fresh fixes-only code round 3; cap three code rounds.
- [x] Publish draft PR #130.
- [ ] Finalize audit record/PR and release handoff at the merge approval gate.

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
