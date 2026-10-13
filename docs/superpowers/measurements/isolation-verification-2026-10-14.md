# MEAS isolation verification on disposable data (2026-10-14)

Ticket #284 (MEAS-LIVE-DB-ISOLATION T4), plan `docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md` §3.
Produced by `scripts/meas/verify_isolation_disposable.py` against a throwaway `postgres:15-alpine` container (`meas-verify-<hex>`, `--rm`, host port chosen by Docker on 127.0.0.1); the live container, live database and live backend were not touched.

## Facts

- tag: meas-freeze-1 @ 61a03e49975a9384f72597a9148848d979769548
- postgres: postgres:15-alpine (server 15.19)
- seed: 3 symbols, weekdays 2009-10-01..2026-10-14, 13335 rows
- prune cutoff (tag rule, 6*365 days): 2020-10-15
- copy rows before / after prune: 13335 / 4695
- copy rows older than cutoff before / after: 8640 / 0
- copy min date before / after: 2009-10-01 / 2020-10-15
- fake_live rows before / after: 13335 / 13335
- fake_live min date before / after: 2009-10-01 / 2009-10-01
- python: 3.11.9
- platform: Windows

## Checks

26/26 checks passed.

- PASS container is a throwaway, never the live one: meas-verify-<hex> != tradingassistant-db
- PASS temporary tag checkout created outside the repo: git worktree add --detach <tmp>/meas-verify-<hex> meas-freeze-1: exit 0
- PASS temporary checkout HEAD is the tag commit: HEAD 61a03e49975a vs tag 61a03e49975a
- PASS throwaway container started (--pull never, --rm, Docker-chosen port): docker run exit 0
- PASS throwaway Postgres ready: pg_isready over TCP ok; host port chosen by Docker
- PASS tag ohlcv_daily DDL compiled from the tag model: exit 0
- PASS fake_live seeded: rows 13335 (expected 13335), older than cutoff 8640, min 2009-10-01, max 2026-10-14
- PASS isolated_day.setup against fake_live: role created, database created, REVOKE CONNECT on fake_live, G2 in setup ['g2_meas_role_not_superuser', 'g2_live_db_refused']
- PASS copy_live_to_meas + verify_copy: tables ['alembic_version', 'ohlcv_daily'], ohlcv_daily copy 13335 = live 13335, alembic_version ['meas_verify_0001']
- PASS psql accepts the SQL isolated_day sends on stdin from this platform: setup/copy/verify sessions succeeded; stdin newline here is CRLF (Windows)
- PASS G2 check_live_db_refused against fake_live: g2_meas_role_not_superuser=ok; g2_live_db_refused=ok
- PASS G3 meas_connections_ok fails with no meas_runner session: no meas_runner connection at all (the backend is not using the copy)
- PASS tag code holds a session on the copy as meas_runner: current_database|current_user = bamendjou_meas|meas_runner, app from the tag checkout 1
- PASS G3 meas_connections_ok passes while the tag code is connected: meas_runner connections by database: {'bamendjou_meas': 1}
- PASS tag _prune_old_rows(6) ran from the tag checkout: exit 0, app from the tag checkout 1, deleted 8640
- PASS copy lost every row older than 6*365 days: deleted 8640 (expected 8640), older rows after 0, min after 2020-10-15 >= cutoff 2020-10-15
- PASS fake_live unchanged by the prune: count 13335, min 2009-10-01, max 2026-10-14, older 8640
- PASS tag code with DATABASE_URL=fake_live as meas_runner cannot connect: exit 3, error class InsufficientPrivilegeError/InsufficientPrivilegeError, permission refusal 1
- PASS G2 still holds at the end: g2_meas_role_not_superuser=ok; g2_live_db_refused=ok
- PASS G1 passes for the valid meas config: all rules ok
- PASS G1 refuses same dbname: rule same_dbname failed; enforce_g1 refused
- PASS G1 refuses wrong meas user: rule meas_user failed; enforce_g1 refused
- PASS G1 refuses port 8000: rule meas_port failed; enforce_g1 refused
- PASS G1 refuses meas checkout inside the repo: rule checkout_outside_repo failed; enforce_g1 refused
- PASS throwaway container stopped and removed: docker ps -a shows no meas-verify-<hex> container
- PASS temporary tag checkout removed: git worktree remove --force + prune; path gone and not listed
