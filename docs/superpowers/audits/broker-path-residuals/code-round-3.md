# Code round 3 (code stage round 3 of 3) — main merge + Alembic merge revision

- Reviewer: fresh independent subagent applying `bmad-review-adversarial-general`, briefed on the audit_rule numeric/persistence gate. Read-only.
- Scope: `8c5b068d` (merge of origin/main 3210245f), `95338bea` (docs), `4356a27d` (`backend/migrations/versions/c29a451f911c_merge_backtest_artifacts_and_broker_attempts.py`), and interactions between the PR app diff `afbd292f..b1c9338c` and main's `afbd292f..3210245f`.
- Verdict: **0 gate findings.**

## Evidence
1. `git diff 3210245f 8c5b068d -- backend frontend` is byte-identical to the PR's reviewed app diff; the merge resolved no application code.
2. The only file both sides touched is `PROJECT_STATE.json`.
3. Single Alembic head `c29a451f911c`, down_revision (`b47d68e91a20`, `bpr001`), both revising `a93b8d24f760`.
4. Disjoint migrations: `b47d68e91a20` creates `backtest_artifacts`; `bpr001` creates `broker_attempts`, `exposure_guards`, `exposure_holds` and adds two `portfolio_positions` columns.
5. SQLite upgrade to head from `a93b8d24f760`, `b47d68e91a20` and `bpr001` each ends at one `alembic_version` row `c29a451f911c` with all tables/columns; downgrades back cleanly.
6. Main's changes (backtest-evidence capture, scan-report run id, optional PositionCardOut fields, api.ts helpers, chart link) reach no broker/auto-trader/position-writer/portfolio path; attempt fingerprints come from request fields only.
7. 143 focused tests passed on the merged tree.

## Non-gate notes
- `tests/test_broker_attempts_migration.py` upgrades to `bpr001`, not `head`; the full path through `c29a451f911c` is covered by `test_alembic_heads` and the manual run above.
