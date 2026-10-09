# TIINGO-GOVERNOR code audit

Separate follow-up to the merged HISTORY target. Gate: reachable wrong user/order
numbers or corrupt persisted data; bounded mechanism-comment exception. Code cap
three fresh independent rounds. No operational provider calls during verification.

Scope: governed async Tiingo adapter, production history and fixture callers,
request-admission symbol budget, shared429 cooldown and offline regressions.
Existing configured pacing and budget are preserved; no account-tier assumptions
are changed. Governor state remains process-local; multiple independent backend
processes/account users do not share it. Provider quotas beyond configured limits
can still return429. Price seam checks remain unchanged.

## Independent code round 1: clean

Reviewer: `/root/tiingo_governor_audit_r1`, fresh independent subagent applying
both required audit skills. Entire 13-file target reviewed:
`b7c5b38c5dd98738eb99f4a92a8918ed1fc67323..c4addf9bd206bff447492651c835d2a86451060c`.
Raw diff SHA256: `dfc165d17d4b0628235b3691d47e974fa56bae3e570f3906103e7e4c0d3f6ffb`.

Scope verified: request admission, normalized symbol budget, pacing, exhausted
429 propagation, shared cooldown, concurrency, both history fallback paths,
fixture conversion, other provider interactions, normalization and persistence
guards. Findings: zero gate findings. Fixes: none. Outstanding findings: none.
`audit_rounds=1`, `audit_clean=true`. Original HISTORY counters remain unchanged.

Independent verification: 123 passed, network disabled and read-only source.
Author focused suite: 169 passed, 6 PostgreSQL-dependent skips. Frontend
typecheck passed. PR132 pending merge; no deployment or live provider retry.

Additional provider regression run: 35 passed, 2 Tradier credential-probe test
failures. The same complete run against an archive of unchanged base b7c5b38c
reproduced exactly 35 passed and the same 2 failures. The main checkout's local
configuration masked them; the archived baseline and implementation both used
the same isolated environment without local credentials. No unrelated fixes.
