# HISTORY code audit

Gate: project numeric/persistence gate and bounded mechanism-comment exception.
Plan stage is independently clean after two rounds; code has its own three-round cap.
No live provider data, operational database or mini PC backfill used in this audit.

## Code round 1 (continuous phase round 3)

Reviewer: fresh independent `history_code_audit_r1`, applying
`K-adversarial-audit-loop` and `bmad-review-adversarial-general`.
Whole target: `aaa7102cfb163f5bc60ed2332daa96e5b9a45f12..058295dfa2338dfd4f9724e68245fc3b7c6927ee`.
Diff SHA-256: `930b9bb63601e981c69c76aab781f18f06754f0c4ea09770925be995be02bf8c`.
Reviewer verified all 40 changed files and provider, cache, reader, settings,
scheduler and DB interactions. 178 selected tests passed on Python 3.11.17.

One P1 gate finding: `_store_bars` built one statement with 12 binds per bar.
2,731 bars exceed asyncpg's 32,767 parameter limit. A disposable PostgreSQL 15
execution reproduced the exact InterfaceError; a 4,433-date synthetic refresh
compiled to 53,196 binds and retained adjusted close 100 instead of 10 after the
driver rejection. The legacy reader can serve those stale prices.

Fix: split upserts into 500-row statements within the same caller transaction;
no per-chunk commits. Preserve the full returned date set, shared fetched timestamp,
both-provider atomicity and cache notification only after commit.

Outstanding: independent fixes-only round 2; audit_clean remains false.

Fix verification: 8 semantic tests passed on SQLite and disposable PostgreSQL
15.19, Python 3.11.17, network disabled. They cover 4,433-date writes, production
and injected whole-span refresh (100 -> 10), and second-chunk rollback preserving
all original bars, floor/proof metadata and both warmed caches. Temporary PostgreSQL
container/socket volume removed. Further focused and legacy-store regressions:
228 passed. Frontend typecheck clean before checkpoint.

## Verification before the fix

- Final focused HISTORY suite: 199 passed on `058295df`, network disabled.
- Broader isolated run from the prior implementation snapshot `0ed6e88e`:
  6,436 passed, 2 skipped, 3 failed; 1,109 warnings.
- Unchanged base `aaa7102c` reproduced the exact same three failures in the two
  affected modules: 22 passed, 3 failed. Two shortlist fixtures attempt external
  yfinance data; commission fixture passes a MagicMock to dataclasses.replace.
  These baseline test limitations are tracked in #129 and are not fixed in the HISTORY branch.
- Temporary Alembic upgrade/downgrade preserved seeded daily bars. Frontend typecheck clean.
