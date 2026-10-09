# HISTORY: first operational run (#114, mini PC only)

Prerequisites: D2 #113 PR merged; the deployed backend uses Python 3.11; operational
Postgres and provider credentials are available on the mini PC. Follow decision
T1-MINI-PC-2026-10-09. Development verification uses disposable databases and mocked
providers; it does not establish availability or correctness of live provider history.

1. On the mini PC, pull the merged commit, activate its prepared Python 3.11 environment,
   and verify `python --version`. Follow the existing deployment backup procedure.
   From `backend/`, with its operational DATABASE_URL configured, run
   `python -m alembic -c migrations/alembic.ini upgrade head` before restarting the backend.
   Confirm head `c15d709a26b1` or a later descendant, and the deployed commit.
2. Set `scheduling.history_years: 17` (or the chosen 1..20 retention) through
   GET/PUT `/settings/scheduling` using the existing timezone returned by GET.
   A smaller manual
   request cannot shorten configured OHLCV retention. Audit/trade history retention
   is a separate setting.
3. Trigger POST `/api/data/ingest` against that backend with:

   ```json
   {"symbols": ["SP500", "NDX100"], "years": 17, "force_backfill": true}
   ```

   Poll GET `/api/data/ingest/status` until completed/error. Record commit, effective
   years, total/done/failed, Alpaca/gapfill counts, backfilled symbols, seam mismatches
   and ratios, observed floors, and prune count in #114. A failed symbol keeps its
   previous coherent bars; do not count it as successfully refreshed.
4. On the mini PC, from repository root, run the SELECT-only full-span report:

   ```bash
   python -m scripts.evidence.bar_basis_check --start 1990-01-01 --out history-bar-basis.md
   ```

   With no symbol filter it checks every stored symbol, including excluded symbols.
   Keep the commit/date-range header, violations, real jumps, stale reasons and
   residual exposure. A validated provider boundary suppresses only that boundary's
   source/batch warning; it does not suppress jumps or corporate-action warnings.
5. Inspect all unexplained failures and jumps before proposing exclusions. Record
   the provider, earliest available date, ratio/evidence and reason for each candidate.
   An observed provider floor is availability evidence, not proof of an IPO date.
   Apply only exclusions approved for their existing scope; rerun the full report
   without filtering excluded symbols. Do not mask a bad seam with an exclusion.
6. Confirm the next nightly ingestion retains the chosen span, re-fetches older
   adjustment factors and reports failures honestly. Keep #114 open until the live
   evidence and exclusions have been reviewed. No D3 commands run from the cloud or
   development Windows checkout.
