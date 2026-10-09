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


## Code round 2 (continuous phase round 4)

Reviewer: fresh independent `history_code_audit_r2_resumed`, applying both required
skills and the numeric/persistence gate. The original `history_code_audit_r2`
was interrupted by the usage limit before a report. This replacement completes
that same unfinished round; no cap reset or extra completed round.

Fixes-only scope: `058295dfa2338dfd4f9724e68245fc3b7c6927ee..c188487bc8a9d3f2d880f47d4dcc964da6f6a4d5`.
Raw complete diff SHA-256: `d2367b42bec0d7bcb8a91484f3ee7517a05a203cbc45a855cdc1bc1be3e3ff64`.
Reviewed the 500-row write fix, all 218 added test lines, associated records,
and interactions with coherent writes, both refresh paths, legacy get_bars,
provider retries, floor/seam metadata and cache notification.

One gate finding: the legacy get_bars callback did not roll back after a later
chunk failed. SQLite permitted a shorter fallback reply to commit the rejected
provider's earlier chunks. Independent synthetic reproduction persisted/returned
600 rows: first 500 Alpaca adjusted close 10, final 100 Tiingo adjusted close 20.
The reviewer ran the added long-write tests: 4 passed, 4 PostgreSQL cases skipped
(no disposable PostgreSQL URL supplied); Python 3.11.17, network disabled.

Fix: roll back the provider attempt on any _store_bars/commit exception before
rethrowing to the provider chain. Added real later-chunk NOT NULL failures with
and without a usable fallback; verify returned/persisted prices, no abandoned
rows and appropriate cache preservation/eviction on both database dialects.

Fix verification: 12 long-write/fallback semantics passed on SQLite and disposable
PostgreSQL 15.19, plus 192 focused HISTORY/legacy-reader regressions on Python
3.11.17. Network disabled; mocked providers. Disposable PostgreSQL container and
socket volume removed. Frontend typecheck and diff whitespace check clean.

Outstanding: fresh fixes-only code round 3, the final allowed code-stage round.
Code audit_clean remains false.


## Code round 3 (continuous phase round 5) - CLEAN

Reviewer: fresh independent `history_code_audit_r3`, applying both mandated
skills and the numeric/persistence gate; zero gate findings after scope recheck.
Exact fixes-only range:
`1602051805f4c1f134889f515091bc3e43e575a5..eca4a41eb022fe77e34c2256c8a35c3894279469`.
Raw complete diff SHA-256:
`fdbde7f21a5447b9c6f9d5d0c9ec172d0129fe1b6397e4e557b0e77cbd331c2a`.

Reviewed executable/test changes in historical_store.py and
test_history_large_writes.py, plus four changed handoff/state/audit records.
Verified failed store/commit rollback before retries, no abandoned chunks in
fallback commits/final reads, successful and empty fallbacks, settled filtering,
healing's scalar date state after rollback, existing-row preservation, cache
notification after successful commit only, and unchanged coherent refresh
transaction ownership. _store_bars still owns no commits.

Independent verification: test_history_large_writes.py, test_historical_store.py,
and test_historical_store_settle.py: 26 passed, 6 PostgreSQL cases skipped because
no disposable PostgreSQL URL was supplied. Python 3.11.17, read-only source mount,
network disabled, mocked providers. PostgreSQL was verified by the implementing
agent's 12 SQLite/PostgreSQL semantic cases above, not by this reviewer.

Final code-stage tally: three completed independent rounds; one gate defect in
R1, one in R2, both fixed; R3 zero. No outstanding gate findings. Plan-stage tally:
two rounds, clean. Overall audit_rounds=5, audit_clean=true. PR #130 ready for
review; merge requires user approval. D3 #114 operational execution is unrun.


## Merge handoff

PR #130 merged with user approval on 2026-10-09 at
`aedb2f4227f7ced8d5014939a6e5b0e4f26ee527`; completed session files removed
before merge. Local main fast-forwarded. Final pre-merge CI frontend/build/Jest
and Playwright passed; backend 6,465 passed, 8 skipped, one unchanged commission
fixture failure tracked in #129. D1/D2 complete; D3 #114 mini PC execution unrun.
