# MEAS-LIVE-DB-ISOLATION — implementation plan (board item #230)

Status: DRAFT v1, for plan-audit round 1. Branch `board/meas-live-db-isolation-c461488d`.

## 0. Problem (evidence, verified 2026-10-13)

`C:\Users\<user>\bamendjou-jobs\meas_day.ps1` (out of repo, run by Task Scheduler) stops the live backend on
:8000, `git switch --detach meas-freeze-1` **in the main checkout**, and starts the frozen backend there with the
same environment. The frozen code then talks to the **live** Postgres database:

- `backend/app/main.py` on the tag calls `load_dotenv()` with no path. `python-dotenv`'s `find_dotenv` walks up
  from the calling file's directory, so any checkout **under** `C:\GitHub\trading-assistant` (including
  `.claude/worktrees/*`) loads the repo-root `.env`: live `DATABASE_URL`, `BAMENDJOU_TELEGRAM_*`,
  `BAMENDJOU_GMAIL_*`, `TRADIER_*`, `TIINGO_API_TOKEN`. `load_dotenv` does not override variables that already
  exist in the process environment.
- Tag startup catch-up: if the DB looks stale it runs `start_ingestion_task(_universe, years=6)`; tag
  `ingestion_job._prune_old_rows` then deletes `ohlcv_daily` rows older than `years*365` days. Main today uses
  `max(requested, scheduling.history_years=17)`; the tag has no such floor. Evidence: freeze-run backend log lines
  2505–2507, `DELETE FROM ohlcv_daily WHERE date < 2020-10-10` committed 2026-10-09 18:50:48 Berlin.
- The tag also starts every scheduler (scan schedule, nightly ingestion with the same 6-year rule, EDGAR, S&P
  liquidity, tuning, strategy watch, chart-alert, portfolio-alert, regime monitor, IBKR keep-alive) and can send
  Telegram/Gmail from env vars or from `backend/config/settings.yaml` (gitignored runtime file, read relative to
  the code folder). Options scans fire an **armed** auto-trade (`routers/scan.py`); the runner already refuses if
  armed.
- All tag file paths (`settings.yaml`, `local_credentials.yaml`, `sp500.csv`, `strategy_params.yaml`,
  `audit.log`, `alert_dedup.json`, `backend/data/confidence_cache.db`, `dev.db`) are relative to the code folder
  or the backend cwd. No `Path.home()`, `APPDATA` or hard-coded `:8000` self-calls in tag `backend/app`.
- The runner (`docs/superpowers/measurements/run_measurement_day.py` on the tag) already takes `--base`
  (backend URL) and `--repo` (checkout to hash/compare), records `sha256` of every `backend/config/*.yaml`
  except `local_credentials.yaml`, requires `backend/app` (minus `sp500.csv`) + `scoring_rules.yaml` +
  `contract_rules.yaml` to equal the tag in the **working tree**, and writes the day folder under
  `<repo>/docs/superpowers/measurements/scans/<date>/`.

Current state (recorded in the #230 Log comment): the only MEAS task is disabled; the live DB history was
re-downloaded on 2026-10-12 (six symbols still short, handled by #114, out of scope here).

## 1. Goal and non-goals

Goal: a frozen MEAS day runs the **unchanged** `meas-freeze-1` code against a **disposable copy** of the live
database, from a checkout **outside** the repo tree, on its **own port**, with no notification credentials, and
the run **refuses** to start if anything would let the frozen backend reach the live database. The live backend,
main checkout and live DB are never stopped, switched or written.

Non-goals: changing the tag or any frozen file; changing the runner's measurement logic or its gates; changing
live retention (main's 17-year floor already exists); scheduling MEAS days (that is #189, after this ships);
the six short symbols / bar-basis re-check (#114).

## 2. Design

### 2.1 One orchestrator in Python, tested; a thin PowerShell launcher

New `scripts/meas/isolated_day.py` (stdlib + `yaml` only, runs on the main checkout's Python 3.11 venv; it
**never imports `app.*`**). New `scripts/meas/run_isolated_day.ps1`: 10-line launcher for Task Scheduler that
calls the Python orchestrator with the repo venv and writes the log to `C:\Users\<user>\bamendjou-jobs\logs\`.
The old `meas_day.ps1` is not edited (out of repo); the new run book (§2.8) says it is retired and the old task
stays disabled.

Subcommands: `setup` (one-time, Kenneth-approved, §2.3), `run` (a measurement day), `check` (all guards, no
start), `cleanup` (drop the copy DB, remove the meas worktree folder's runtime files).

### 2.2 Fixed names (constants in the orchestrator, overridable only by CLI flags used in tests)

| What | Value |
|---|---|
| Meas checkout | `C:\Users\<user>\bamendjou-jobs\meas-freeze-1\` (a `git worktree` of the repo at the tag, **outside** `C:\GitHub\trading-assistant`) |
| Meas DB | `bamendjou_meas` in the existing `tradingassistant-db` container |
| Meas DB role | `meas_runner` (LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE), owner of `bamendjou_meas` only |
| Meas port | `8100` (live backend stays on `8000`) |
| Live identity | parsed from the repo-root `.env` `DATABASE_URL`: (host, port, dbname, user) |

### 2.3 Three independent guards (any one failing → refuse, exit non-zero, live untouched)

G1 **Config guard (orchestrator, before anything starts).** Parse live `DATABASE_URL` from repo `.env` and the
meas `DATABASE_URL` the orchestrator is about to give the child. Refuse if: same dbname; meas dbname !=
`bamendjou_meas`; meas user != `meas_runner`; meas user == live user; meas port/base == `8000`; the meas checkout
path is inside the repo root (resolved, case-insensitive); any `.env` exists in the meas checkout's ancestor
directories above the checkout root (`find_dotenv` would stop at the checkout's own `.env` first, but this catches
a missing/mis-written own `.env`).

G2 **Database guard (Postgres, independent of the code).** One-time `setup`, run by the superuser through
`docker exec … psql`: create role `meas_runner`, create DB `bamendjou_meas` owned by it, and
`REVOKE CONNECT ON DATABASE <live> FROM PUBLIC` (the live app connects as the container superuser, which keeps
access; verified in setup by connecting as the live user afterwards). Effect: even if a wrong URL names the live
DB, `meas_runner` cannot connect to it. `check`/`run` verify, each time, that `meas_runner` **cannot** connect to
the live DB (expect a permission error) and is not superuser. This is the explicit production-DB refusal that
does not depend on any Python code being right. **`setup` changes privileges on the live database, so it runs
only after Kenneth's explicit yes in chat; it is reversible (`GRANT CONNECT … TO PUBLIC`), and the run book
prints the reverse command.**

G3 **Runtime guard (after the frozen backend is healthy, before the first scan, and again at the end).** Query
`pg_stat_activity` as superuser: every backend connection of `meas_runner` is on `bamendjou_meas`; the frozen
process's PID is the one the orchestrator started; the live backend on :8000 is still answering
`/api/config/health` with its pre-run PID. Any mismatch → stop the frozen backend (by its PID only) and refuse.

### 2.4 The meas checkout

- `git worktree add --detach <meas path> meas-freeze-1` once (or `git -C <meas path> checkout --detach
  meas-freeze-1` + verify clean); before each run: `git -C <meas path> status --porcelain --untracked-files=no`
  must be empty and `HEAD` must equal the tag commit; the runner's own `check_freeze` re-verifies.
- Written by the orchestrator into the meas checkout each run (all gitignored at the tag; verified with
  `git check-ignore`):
  - `<meas>\.env`: exactly `DATABASE_URL=<meas URL>`, `TRADIER_API_TOKEN`, `TRADIER_BASE_URL`, `TIINGO_API_TOKEN`
    copied from the live `.env` (market data, unchanged from days 1–2), plus `BAMENDJOU_MEAS_ISOLATED=1`
    (marker only). **No `BAMENDJOU_TELEGRAM_*`, no `BAMENDJOU_GMAIL_*`.**
  - `<meas>\backend\config\settings.yaml`: copy of the live file with `alert_delivery.masterEnabled: false`,
    `notifications.gmail` / `notifications.telegram` → `enabled: false` and every secret-looking value
    (`smtp_password`, `bot_token`, `chat_id`, `smtp_user`, `to`) blanked; `scan.schedule` entries →
    `enabled: false`; `ibkr.enabled: false`. Every other key copied byte-for-value. The manifest records the
    sha256 of the live file **and** of the sanitized copy (§2.6).
  - `<meas>\backend\config\local_credentials.yaml`: copy of the live file (tastytrade / Alpaca market data and
    the IV source the runner requires). Broker order paths stay reachable only through explicit order endpoints
    (the runner calls none) and armed auto-trade (the runner refuses unless disarmed; the copy DB carries the
    live armed state, so a live-armed auto-trader makes the run refuse, which is the safe direction).
- Child process environment: built **from scratch** as `os.environ` minus every key matching
  `DATABASE_URL|BAMENDJOU_*|TRADIER_*|TIINGO_*|ALPACA_*|TASTY*|IBKR_*|POSTGRES_*`, plus the `.env` keys above set
  explicitly (so `load_dotenv` finds nothing to add and the meas `.env` is belt-and-braces).
- Started with: `<repo venv python> -m uvicorn app.main:app --ws websockets-sansio --host 127.0.0.1 --port 8100`,
  cwd `<meas>\backend`, stdout/stderr to `logs\meas-<stamp>-backend.log`, `PYTHONUTF8=1`. Python version and
  `pip freeze` sha256 recorded (same venv as days 1–2).

### 2.5 The database copy (live DB is only read)

Each `run`: `DROP DATABASE IF EXISTS bamendjou_meas WITH (FORCE)`; `CREATE DATABASE bamendjou_meas OWNER
meas_runner`; `pg_dump -Fc <live>` piped to `pg_restore --no-owner --role=meas_runner -d bamendjou_meas`
inside the container (`docker exec`, superuser from the container's own env; no credentials on the command
line). Then verify: `ohlcv_daily` row count, `min(date)`, `max(date)` equal between live and copy at the moment
of the copy (live may gain rows later; the check reads live first), and `alembic_version` equal. Record the
counts in the manifest. The frozen backend's own startup catch-up / prune / nightly jobs then act only on the
copy. **The orchestrator never issues a write to the live DB**; its live-DB statements are `pg_dump` and
`SELECT`s, enforced by a static test that greps the orchestrator for live-DB writes (§4 T4).

### 2.6 Run sequence (`run`)

1. Weekday-in-ET check; Docker + `tradingassistant-db` healthy (start Docker Desktop if needed, as today).
2. G1 + G2 checks. Port 8100 free. Live backend on :8000 healthy → record its PID (absent is allowed: logged).
3. Refresh meas checkout files (§2.4), DB copy (§2.5).
4. Start frozen backend on 8100; wait for `/api/config/health` ok (180 s), else stop by PID and refuse.
5. G3. Wait until 13:00:30 ET (unchanged timing).
6. Run `<repo venv python> <meas>\docs\superpowers\measurements\run_measurement_day.py core
   --base http://127.0.0.1:8100 --repo <meas>` (the **tag's** runner, unchanged).
7. G3 again. Stop the frozen backend **by the PID it started** (`taskkill /T /PID`), never by port.
8. Copy `<meas>\docs\superpowers\measurements\scans\<date>\` to the main checkout's
   `docs\superpowers\measurements\scans\<date>\` (refuse to overwrite an existing non-empty folder; copy to
   `<date>-isolated-<stamp>` instead and log it). Add `isolation.json` next to the manifest: meas DB name,
   live/copy counts, guard results, live+sanitized `settings.yaml` sha256, tag commit, Python/pip hashes, ports,
   live backend PID before/after. No secrets, no absolute user paths (paths relative to the job folder).
9. Leave `bamendjou_meas` in place until the next run (inspectable); `cleanup` drops it.
   The live backend is never stopped or restarted at any step.

### 2.7 Comparability with days 1–2 (measurement hashes)

Unchanged: tag code, tag runner, gated config, `strategy_params.yaml` and `sp500.csv` (tag versions in the meas
checkout, as days 1–2 had after `git switch`), scan bodies, timing, venv. Changed and recorded: the DB is a copy
taken minutes before the run instead of the live DB (same content at copy time); `settings.yaml` is the
sanitized copy (its sha256 changes; it is not in `GATED_CONFIG` or `RUN_INVARIANT_CONFIG`, so pooling rules are
unaffected — to be confirmed against the plan §5 pooling rule in round 1); notification channels off.

### 2.8 Documentation

- `docs/superpowers/measurements/ISOLATED-RUN.md` (new): what the isolation guarantees, one-time setup (with the
  Kenneth-approval note and the reverse command), daily run, how to install the Task Scheduler entry for #189
  (`run_isolated_day.ps1`, ~18:35 Berlin, "wake to run", the old task stays disabled), what to do on each refusal,
  and the **recovery ordering**: (1) #230 merged + `setup` done + disposable verification passed; (2) #114
  re-backfill/backup on the live DB with the live backend only; (3) #189 days via the isolated runner only.
- `PROTOCOL.md` on **main** gets a short pointer at step 1–2: "run through `scripts/meas/isolated_day.py`; never
  switch the main checkout to the tag". (The tag's PROTOCOL.md is frozen and stays as is.)

## 3. Verification on disposable data (acceptance item 3)

`scripts/meas/verify_isolation_disposable.py` (run manually, recorded in the PR): uses a **throwaway Postgres
container** (`postgres:16`, random port, `--rm`) — never `tradingassistant-db`:
1. Create `fake_live` (superuser-owned) seeded with `ohlcv_daily` rows dated 2009–2026 for 3 symbols, `setup`
   against it, create the copy with the orchestrator's copy function.
2. Run the **tag's** `_prune_old_rows(6)` in a subprocess whose environment is the orchestrator's child
   environment (cwd = meas checkout `backend`, tag code imported from the meas checkout) — the exact code that
   deleted live history.
3. Assert: copy lost every row older than 6×365 days; `fake_live` row count/min date unchanged; a second
   subprocess with `DATABASE_URL` pointed at `fake_live` as `meas_runner` fails to connect (G2); orchestrator
   `check` refuses for each G1 violation.
Output saved under `docs/superpowers/measurements/isolation-verification-<date>.md` (counts only).

## 4. Tickets (build units; the phase is the audit target)

- **T1** `scripts/meas/isolated_day.py` config + guards: live/meas URL parsing, G1 rules, child-env builder,
  settings sanitizer, `.env` writer; pytest `scripts/meas/tests/test_isolated_day_guards.py` (every G1 refusal,
  env stripping incl. Windows case-insensitive keys, sanitizer leaves non-notification keys equal, no secrets
  written into `isolation.json`).
- **T2** DB layer: `setup`, copy (`pg_dump | pg_restore` via `docker exec`), G2 probe, G3 probe, count checks;
  tests with a fake `docker` runner (command lines asserted: live DB only appears in `pg_dump`/`SELECT`/the one
  `REVOKE` in `setup`). Blocked by T1.
- **T3** `run`/`check`/`cleanup` sequence, PID-only stop, day-folder copy without overwrite, `isolation.json`,
  `run_isolated_day.ps1`; tests with fake backend/runner processes. Blocked by T2.
- **T4** Disposable verification script (§3) + static test that the orchestrator has no write to the live DB
  outside `setup`'s REVOKE. Blocked by T3.
- **T5** Docs: `ISOLATED-RUN.md`, main `PROTOCOL.md` pointer, `PROJECT_STATE.json` phase entry. Blocked by T3.
- Coordinator: run the disposable verification for real (needs Docker on this PC), full backend test suite on
  Python 3.11, then the code audit.

Out of scope, explicitly: running `setup` on the real container (needs Kenneth's yes, done after merge);
creating #189's scheduled tasks; any change under `backend/app` or the tag.

## 5. Gate for audits

A finding blocks only if it can: let frozen MEAS code read or write the live database or live settings/credential
files; send a notification or broker request from a MEAS run; stop/restart/alter the live backend or main
checkout; corrupt or lose persisted data (live or copy-verification evidence); change what the measurement
measures versus days 1–2 without recording it; or make a refusal guard pass when it should refuse.

## 6. Open questions for the auditor to test (not for Kenneth unless the audit says so)

- Does any tag code path read a file outside the meas checkout or the backend cwd (e.g. `../../.env` style
  relative paths, `sp500.csv` writers, Alembic `env.py`)?
- Is the plan §5 pooling rule of the MEAS plan affected by a changed `settings.yaml` hash?
- Does the frozen startup run any DDL (`create_all`) that would conflict with a restored head-schema copy?
