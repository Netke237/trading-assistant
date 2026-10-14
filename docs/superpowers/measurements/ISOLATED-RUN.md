# MEAS — isolated measurement-day run book

Plan: `docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md` (#230).
Code: `scripts/meas/isolated_day.py` (the orchestrator), `scripts/meas/run_isolated_day.ps1` (the Task
Scheduler launcher), `scripts/meas/verify_isolation_disposable.py` (the proof on throwaway data).

This page replaces the "switch the main checkout to the tag" part of `PROTOCOL.md`. The measurement
itself (13 scans, the timing, the validity rules) is unchanged: the frozen tag's own runner still
does it. Only where the frozen backend runs, and against which database, has changed.

In this page `C:\Users\<user>` is your Windows profile folder and `<repo>` is the main checkout,
`C:\GitHub\trading-assistant`. All commands are Windows PowerShell 5.1.

---

## 1. Why this exists, and what it guarantees

**The incident (2026-10-09).** The old wrapper `C:\Users\<user>\bamendjou-jobs\meas_day.ps1` stopped the
live backend, ran `git switch --detach meas-freeze-1` **in the main checkout** and started the frozen
backend there. The frozen code read the repo-root `.env`, so it used the **live** database. Its
startup catch-up ingestion decided the data looked stale, re-ingested 6 years and then pruned
`ohlcv_daily`: every live row older than 6 years was deleted
(`DELETE FROM ohlcv_daily WHERE date < 2020-10-10`, committed 18:50:48 Berlin). Main keeps
17 years; the tag has no such floor. The same frozen code could also have sent Telegram/Gmail and
run every scheduler against live data.

**What the isolated run guarantees.**

- The frozen `meas-freeze-1` code runs **unchanged**, from its own checkout
  `C:\Users\<user>\bamendjou-jobs\meas-freeze-1\` (a `git worktree`, **outside** the repo folder).
- It runs on its **own port, 8100**, bound to `127.0.0.1`. The live backend on :8000 is never
  stopped, restarted or switched; the main checkout is never switched.
- It talks only to **`bamendjou_meas`**, a fresh copy of the live database made minutes before
  the run, as the role **`meas_runner`**, which Postgres itself refuses entry to the live
  database. Whatever the frozen code deletes or prunes, it deletes in the copy.
- It gets **no notification credentials** (no `BAMENDJOU_TELEGRAM_*`, no `BAMENDJOU_GMAIL_*`;
  its `settings.yaml` is a sanitized copy with every channel off).
- The live database is only **read** (`pg_dump` and `SELECT`s). The one exception is the
  one-time `setup` (section 3), which changes the live database's privileges and only runs
  after your explicit yes.
- If anything would let the frozen backend reach the live database, the run **refuses** before
  the first scan.

---

## 2. The three guards

Every guard prints one line per rule: `ok` or `FAIL`, the rule name, and a detail. A refusal
looks like `G1 refused: <rule> (<detail>); ...`. Each `run` also writes them into `isolation.json`
(section 6).

### G1 — configuration (before anything starts)

| Rule | Fails when | What to do |
|---|---|---|
| `same_dbname` | the meas URL names the live database | Code or `.env` is wrong. Do not run; ask a Claude session. |
| `meas_dbname` | the meas database is not `bamendjou_meas` | Same. |
| `meas_user` | the meas user is not `meas_runner` | Same. |
| `meas_user_is_live_user` | the meas user equals the live user | Same. |
| `meas_port` | the frozen backend would use port 8000 | Same. |
| `checkout_outside_repo` | the meas checkout is inside `<repo>` | Same. The checkout must be `C:\Users\<user>\bamendjou-jobs\meas-freeze-1`. |
| `no_dotenv_above_checkout` | a `.env` exists in a folder above the meas checkout (`bamendjou-jobs`, `C:\Users\<user>`, `C:\Users`, `C:\`) | Move that `.env` away. The frozen code could load it. |
| `ibkr_ports_not_listening` | anything listens on TCP port **5000 or 7499**, on any address | Close the IBKR gateways (Client Portal, IB Gateway/TWS). If it is not IBKR, find the program (below) and stop it for the run. |
| `ibkr_ports_not_connectable` | a TCP connect to `127.0.0.1` or `[::1]` on 5000 or 7499 succeeds | Same. |

Who holds port 5000 or 7499:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000,7499 | Select-Object LocalAddress,LocalPort,OwningProcess
Get-Process -Id <OwningProcess>
```

The IBKR rule exists because the frozen code calls `https://localhost:5000` / `:7499` from scans,
from the data-source status page and from its IBKR keep-alive job, which it always starts. With the
ports closed those calls hit nothing and reach no broker.

Also checked before the start (not G1, but they refuse the same way):

| Rule / message | Meaning | What to do |
|---|---|---|
| `meas_port_free` | something already listens on, or answers at, port 8100 | Usually a frozen backend left over from a killed run: see section 8. |
| `repo-root .env not found` / `has no DATABASE_URL` | the orchestrator was started from a folder that is not the main checkout | Always use `<repo>\scripts\meas\...`, never a copy in a worktree. |
| `meas secret file is missing; run setup` | `setup` was never run | Section 3. |
| `the Docker engine is not running` (`check` only) | `check` never starts Docker | Start Docker Desktop, then `check` again. (`run` starts it itself and waits up to 300 s.) |
| `container tradingassistant-db is not healthy` | the DB container is down or unhealthy | Start it in Docker Desktop. |
| `... is a weekend in New York` (`run` only) | the ET date is Saturday/Sunday | Nothing: no measurement on weekends. |
| `the meas checkout has modified tracked files` / `HEAD is not the meas-freeze-1 commit` | someone edited or switched the meas checkout | Do not "fix" it with `git checkout`. Show the output to a Claude session. |
| `... is not gitignored in the meas checkout` | the tag would track a runtime file the orchestrator writes | Same. |
| `copy verification: ...`, `dump/restore failed` | the database copy is incomplete (missing table, empty table, too many `ohlcv_daily` rows or a later date than live, different `min(date)` or `alembic_version`) | Nothing was started. Read the message; rerun later. Repeated: ask a Claude session. |

### G2 — the database refuses (Postgres itself, independent of the code)

`setup` makes `meas_runner` a normal role (not superuser) that owns only `bamendjou_meas`, and
removes the public right to connect to the live database (`REVOKE CONNECT ... FROM PUBLIC`). The live
app keeps working because it connects as the container's superuser/owner. So even a wrong URL
pointing `meas_runner` at the live database fails inside Postgres. `check` and `run` prove this
every time by actually trying to connect as `meas_runner` to the live database.

| Rule | Fails when | What to do |
|---|---|---|
| `g2_meas_role_not_superuser` | `role meas_runner does not exist; run setup` | Section 3 (needs your yes). |
| `g2_meas_role_not_superuser` | `role meas_runner is a superuser` | Someone changed the role. Do not run; ask a Claude session. |
| `g2_live_db_refused` | `meas_runner CONNECTED to the live database` | The REVOKE is missing or was undone. Do not run. Re-run `setup` (with your yes). |
| `g2_live_db_refused` | `could not verify: the connect attempt failed, but not a permission refusal` | Usually the password in the secret file no longer matches the role (or the container is down). Re-running `setup` with your yes re-syncs the role to the file. |

### G3 — runtime (after the frozen backend is healthy, before the first scan, and again at the end)

| Rule | Fails when |
|---|---|
| `g3_health_pid_descendant` | the PID that `http://127.0.0.1:8100/api/config/health` reports is not the process the orchestrator launched (or its child: the venv `python.exe` is a launcher whose child is the real interpreter) |
| `g3_health_pid_stable` | that PID changed since the backend became healthy (it restarted) |
| `g3_listener_owner` | port 8100 is not owned by exactly that PID on `127.0.0.1` |
| `g3_meas_connections_on_copy` | a `meas_runner` connection is on any database other than `bamendjou_meas`, or there is no `meas_runner` connection at all (the backend is not using the copy) |
| `g3_live_backend_pid_unchanged` | the live backend on :8000 now reports a different PID than before the run (it was restarted). If it was not running before, this rule passes. |
| `ibkr_ports_not_listening`, `ibkr_ports_not_connectable` | the G1 IBKR rule, checked again |

G3 failing **before the first scan** refuses (exit 2) and stops the frozen backend. G3 failing **at
the end** is recorded as a failure (exit 1): the scans already ran, so read the failure before you
count the day. **Do not restart the live backend during a run**: that alone fails
`g3_live_backend_pid_unchanged`.

After the run the orchestrator stops the frozen backend and records three more rules:
`stop_taskkill` (the forced kill of the launched PID worked), `stop_port_free` (nothing listens on
8100) and `stop_pids_gone`. If one fails, see section 8.

---

## 3. One-time setup — changes the live database; only after Kenneth's explicit yes

`setup` is the only step that writes to the live database. It:

1. creates the role `meas_runner` (LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION,
   NOBYPASSRLS) with a random password;
2. creates the database `bamendjou_meas`, owned by `meas_runner`;
3. runs `REVOKE CONNECT ON DATABASE <live> FROM PUBLIC` on the live database;
4. checks that the live user can still connect, and that G2 now holds.

The password is generated once into `C:\Users\<user>\bamendjou-jobs\meas_db.secret` (one line,
Windows permissions limited to your user). It is never printed, logged, put on a command line or
into `isolation.json`. Because only your user can read the file, `check`, `run` and the scheduled task
must run **as the same Windows user** that ran `setup`.

It refuses (and changes nothing) if the live database does not exist in the container, or if the
live user is neither superuser nor owner of it (the REVOKE would lock the live app out).

**Run it only after Kenneth has said yes in chat.** Docker Desktop and `tradingassistant-db` must be
running. From any folder:

```powershell
$env:PYTHONUTF8 = "1"
& "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe" "C:\GitHub\trading-assistant\scripts\meas\isolated_day.py" setup --i-have-kenneths-approval
```

Without `--i-have-kenneths-approval` it prints what it would change and refuses (exit 2). It is safe
to run again: it re-syncs the role to the secret file, keeps the database and repeats the REVOKE.
`--rotate` (together with the approval flag) writes a new password and changes the role to it.
Exit codes: 0 done, 2 refused.

It prints the exact reverse command with the real live database name, twice (after the REVOKE
and at the end, also as `reverse_command` in its JSON output). Keep that line.

**To undo the REVOKE** (gives the public right to connect back to the live database):

```powershell
'GRANT CONNECT ON DATABASE "<live>" TO PUBLIC;' | docker exec -i tradingassistant-db sh -c 'psql -U $POSTGRES_USER -d postgres'
```

`<live>` is the database name from `<repo>\.env` `DATABASE_URL` (the part after the last `/`), as
printed by `setup`.

**To abandon the isolated setup completely**, in this order:

1. Stop any frozen backend (section 8) and run `cleanup --reset-cache` (section 7).
2. Undo the REVOKE (above).
3. Drop the copy and the role:
   ```powershell
   'DROP DATABASE IF EXISTS bamendjou_meas WITH (FORCE);' | docker exec -i tradingassistant-db sh -c 'psql -U $POSTGRES_USER -d postgres'
   'DROP ROLE IF EXISTS meas_runner;' | docker exec -i tradingassistant-db sh -c 'psql -U $POSTGRES_USER -d postgres'
   ```
   If `DROP ROLE` reports dependent objects, stop and ask a Claude session; do not force it.
4. Make sure every day folder you need is in `<repo>\docs\superpowers\measurements\scans\`, then
   remove the meas checkout and the secret file:
   ```powershell
   git -C C:\GitHub\trading-assistant worktree remove --force C:\Users\<user>\bamendjou-jobs\meas-freeze-1
   Remove-Item C:\Users\<user>\bamendjou-jobs\meas_db.secret
   ```

---

## 4. Before a measurement day

- [ ] `setup` done, and section 10 step (1) complete.
- [ ] A normal US trading day: not a weekend (the orchestrator refuses those), **not an NYSE holiday
      or half-day** (nothing checks those for you).
- [ ] **IBKR gateways closed**: nothing on ports 5000 or 7499 (G1 refuses otherwise).
- [ ] **Auto-trader disarmed.** The frozen backend keeps its armed state in memory and starts
      disarmed, and the tag runner checks it is disarmed before every options scan. Never arm
      anything on :8100. The live app's auto-trader on :8000 is separate and is not used by the run.
- [ ] The **live backend may keep running** on :8000. Do not restart it while the run is going
      (section 2, G3). Scans you run in the live app no longer touch the measurement.
- [ ] Docker Desktop can start (the run starts it if it is not running) and `tradingassistant-db`
      is healthy.
- [ ] **The PC stays on and awake.** Plugged in, not sleeping. Once, in PowerShell:
      ```powershell
      powercfg /change standby-timeout-ac 0
      ```
      (Undo later with `powercfg /change standby-timeout-ac <minutes>`.)
- [ ] **Windows Update cannot restart the PC during the run**: Settings → Windows Update →
      Advanced options → Active hours, covering at least 17:00–23:00.
- [ ] Do not edit any config, and do not touch the meas checkout, during the run.

Then run `check` (it starts nothing and writes nothing):

```powershell
$env:PYTHONUTF8 = "1"
& "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe" "C:\GitHub\trading-assistant\scripts\meas\isolated_day.py" check
$LASTEXITCODE
```

It runs G1, G2 and the port-8100 check, reports the live backend's PID (or "absent"), resolves the
tag and, if the meas checkout exists, checks that it is clean at the tag. It ends with
`check OK: every guard passes (nothing was started or written)` and exit 0, or `REFUSED: ...` and
exit 2. `check` does not start Docker: start Docker Desktop first.

---

## 5. The day: `run`

Normally the scheduled task does this (section 9). By hand, from PowerShell, between about
12:30 and 12:45 ET:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\GitHub\trading-assistant\scripts\meas\run_isolated_day.ps1"
```

(or the orchestrator directly: `... isolated_day.py run`; its own output then goes only to the
console, while the backend and runner logs are written as below).

What `run` does, in order:

1. Refuses on a New York weekend. Starts Docker Desktop if needed; waits for `tradingassistant-db`.
2. G1, G2, port 8100 free. Records the live backend's PID on :8000 (absent is allowed and logged).
3. Creates the meas checkout on the first run (`git worktree add --detach ... meas-freeze-1`),
   checks it is clean at the tag, writes its runtime files (meas `.env`, sanitized `settings.yaml`,
   a copy of `local_credentials.yaml`), prepares the confidence cache, then drops and re-creates
   `bamendjou_meas` from a `pg_dump` of the live database and verifies the copy.
4. Starts the frozen backend on `127.0.0.1:8100` and waits up to 180 s for it to report healthy.
5. G3. Waits until 13:00:30 ET.
6. Runs the **tag's** runner: `run_measurement_day.py core --base http://127.0.0.1:8100 --repo <meas checkout>`.
   It takes about 90 minutes and refuses by itself if O1 cannot start by 13:15 ET.
7. G3 again, then stops the frozen backend with `taskkill /F /T /PID <the PID it launched>` (never
   by port or name) and checks that nothing listens on 8100 any more.
8. Copies the day folder into the main checkout and writes `isolation.json` (section 6).
9. Leaves `bamendjou_meas` in place for inspection; the next `run` replaces it, `cleanup` drops it.

**Exit codes** (`run`, and the launcher passes them through):

| Code | Printed as | Meaning |
|---|---|---|
| 0 | `RESULT OK (exit 0)` | the runner finished, every check passed, evidence copied |
| 1 | `RESULT FAILED (exit 1): ...` | something failed **after** the runner started (runner exit not 0, G3 at the end, stop verification, no day folder, `isolation.json` not written) or an unexpected error. Read the message before counting the day. |
| 2 | `RESULT REFUSED (exit 2): ...` | a guard refused before the runner started. No scan ran; if the frozen backend had been started, it was stopped. The launcher also exits 2 if the repo venv Python is missing. |

The orchestrator has no `--run-tag`: the tag runner refuses a second `core` on the same ET date
in the meas checkout (its day folder already exists there). One isolated run per trading day.

### Where things land

| What | Where |
|---|---|
| Launcher log (everything the orchestrator prints) | `C:\Users\<user>\bamendjou-jobs\logs\meas-isolated-<yyyyMMdd-HHmmss>.log` (local time) |
| Frozen backend log | `C:\Users\<user>\bamendjou-jobs\logs\meas-<UTC stamp>-backend.log` |
| Tag runner log | `C:\Users\<user>\bamendjou-jobs\logs\meas-<UTC stamp>-runner.log` |
| Day folder, as the runner writes it | `C:\Users\<user>\bamendjou-jobs\meas-freeze-1\docs\superpowers\measurements\scans\<ET date>\` |
| Day folder copy (the one you commit) | `<repo>\docs\superpowers\measurements\scans\<ET date>\` |
| `isolation.json` | inside that copy, next to `manifest.json` |

`<UTC stamp>` looks like `20261015T163512Z`. Nothing is ever overwritten: if
`scans\<ET date>\` already exists in the main checkout and is not empty, the copy goes to
`scans\<ET date>-isolated-<UTC stamp>\` instead (logged), and `isolation.json` is created only
if it does not exist yet. Only a day folder the runner created during this run is copied: if the
runner wrote no day folder (for example after a refusal), or the meas day folder already existed
before the runner started (a second run on the same ET date), or its `manifest.json` start is
earlier than the runner start, nothing is copied, there is no `isolation.json`, the run exits 1 and
the launcher log is the record.

After the day, commit the copied day folder on a branch and hand it to a Claude session, as in
`PROTOCOL.md` "After each day".

---

## 6. What `isolation.json` records

Tag and tag commit; meas database and role; ports (8100, 8000, 5000/7499); the live database
identity (host, port, database name, user: never the password); every guard result (`g1`, `g2`,
`port`, `g3_start`, `g3_end`, `stop`); live backend PID before and after; launched and health PID of
the frozen backend; the sha256 of the live `settings.yaml` and of the sanitized copy; whether
`local_credentials.yaml` was copied; the confidence-cache origin and counts; the copy's per-table
row counts next to live's, and which tables differ; Python version and `pip freeze` sha256;
timestamps; the runner exit code; the exit code and failures. No secrets and no absolute user
paths (paths are relative: `<meas>`, `<jobs>`, `<repo>`, `~`); the orchestrator refuses to write it
otherwise.

---

## 7. `cleanup`

```powershell
& "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe" "C:\GitHub\trading-assistant\scripts\meas\isolated_day.py" cleanup
```

Drops `bamendjou_meas` and removes the meas checkout's `.env`, `backend\config\settings.yaml` and
`backend\config\local_credentials.yaml` (the latter holds broker tokens). It **keeps** the meas
confidence cache (`backend\data\confidence_cache.db`), which carries over between isolated days on
purpose (section 11); `cleanup --reset-cache` also deletes it (logged). It keeps the meas checkout
itself and the logs. It refuses (exit 2) while anything listens on port 8100; otherwise exit 0.

Optional after a day (the next `run` rewrites everything anyway); do it when the measurement
series ends.

---

## 8. Failure handling

**The orchestrator was killed** (Task Scheduler time limit, closed window, reboot without power
loss...). Killing the orchestrator does **not** stop the frozen backend. It keeps running on 8100,
against the copy only, until you stop it. The live side is not affected.

1. Find its PID in the launcher log: the line
   `frozen backend healthy, health pid <H> (launched <L>)`. If the log has no such line (killed
   during start-up), ask Windows:
   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 8100 | Select-Object LocalAddress,OwningProcess
   Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match '--port 8100|run_measurement_day|isolated_day' } | Select-Object ProcessId,ParentProcessId,CommandLine
   ```
   Only processes whose command line contains `--port 8100`, `run_measurement_day` or
   `isolated_day` belong to the run. **Never stop the live backend (`8000`).**
2. Stop it: `taskkill /F /T /PID <L>` (the launched PID; use `<H>` if `<L>` is gone). Stop a
   leftover tag runner (`run_measurement_day`) the same way.
3. Run `cleanup` (section 7). It refuses while anything still listens on 8100.

**The tag runner has no timeout.** If it hangs, the orchestrator waits for it forever. A normal
core block is over by about 14:30 ET (20:30 Berlin). If the launcher log has not printed `RESULT`
by about 16:00 ET, read the runner log, then stop the processes as above.

**The frozen backend crashed at start-up.** The orchestrator does not notice the crash itself: it
waits the full **180 s** for `/api/config/health`, then refuses (exit 2,
`the frozen backend did not report healthy on :8100 within 180 s`) and stops the launched PID.
The reason is in `meas-<UTC stamp>-backend.log`.

**`stop_port_free` or `stop_pids_gone` failed.** Something still holds 8100 or the PID still
exists. The orchestrator never stops anything by port. Check by hand with the commands in step 1,
stop it by PID, then `cleanup`.

---

## 9. The Task Scheduler entry for #189 (document only; create it when #189 starts)

One task per chosen trading day (or one task with several one-time triggers):

- **General:** run as the Windows user that ran `setup` (the secret file is readable only by that
  user), "Run only when user is logged on", so Docker Desktop can start.
- **Trigger:** One time, on the chosen trading day, about **18:35 Europe/Berlin** (12:35 ET). Start
  it no earlier than about 30 minutes before 13:00 ET; the orchestrator then waits until 13:00:30 ET.
  **Watch the DST gaps:** when Europe and the US are not both on summer or both on winter time
  (2026: Mon 26 Oct – Fri 30 Oct; 2027: Mon 15 Mar – Fri 26 Mar), 13:00 ET is **18:00** Berlin,
  so start at about **17:35**. A start at 18:35 then is past 13:15 ET and the runner refuses.
- **Action:** Program `powershell.exe`, arguments
  ```
  -NoProfile -ExecutionPolicy Bypass -File "C:\GitHub\trading-assistant\scripts\meas\run_isolated_day.ps1"
  ```
  Always the main checkout's copy of the script: it finds the repo (and the live `.env`) from its
  own location.
- **Conditions:** tick **"Wake the computer to run this task"**.
- **Settings:** "Stop the task if it runs longer than" at least 4 hours. Remember that a kill does
  not stop the frozen backend (section 8).

**Retired, must stay disabled and unused:**

- the old task `\Bamendjou\Bamendjou MEAS day 2 (2026-10-09)`;
- the old wrapper `C:\Users\<user>\bamendjou-jobs\meas_day.ps1`.

To confirm the old task is disabled:

```powershell
Get-ScheduledTask -TaskPath '\Bamendjou\' | Select-Object TaskName,State
```

**Never `git switch` the main checkout to `meas-freeze-1`**, and never run the frozen code from
`<repo>` or from any worktree under it. That is exactly what deleted the live history.

---

## 10. Recovery ordering

1. **#230 merged, `setup` done (Kenneth's yes), disposable proof passed.** The proof runs the
   orchestrator's own functions and the tag's own prune against a throwaway Postgres container,
   never `tradingassistant-db`:
   ```powershell
   & "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe" "C:\GitHub\trading-assistant\scripts\meas\verify_isolation_disposable.py"
   ```
   It needs Docker running and the `postgres:15-alpine` image already present (it uses
   `--pull never`), writes `docs\superpowers\measurements\isolation-verification-<date>.md`
   (`--no-report` skips that) and exits 0 only if every check passes. Evidence of the passing run on
   the build branch: [isolation-verification-2026-10-14.md](isolation-verification-2026-10-14.md)
   (26/26 checks; the copy lost every row older than 6 years, `fake_live` kept all 13335 rows).
2. **#114**: re-backfill and back up the live database **with the live backend only**. No frozen
   code runs during this step.
3. **#189**: further measurement days, **only** through the isolated runner (`run_isolated_day.ps1`
   / `isolated_day.py run`).

---

## 11. Accepted outside traffic, and what is not sent

The frozen backend still fetches **read-only market data**, the same as on days 1–2:
tastytrade IV metrics, Tradier quotes and option chains, Alpaca / Tiingo / yfinance bars, and the
status probes behind `/api/data-sources`. For that it gets the Tradier and Tiingo keys in its `.env`
and a copy of `local_credentials.yaml` (tastytrade, Alpaca).

Not sent:

- **No Telegram or Gmail**: no notification keys in its environment or `.env`; the sanitized
  `settings.yaml` has the master switch off, both channels off and every token, chat id, user and
  password blanked; scan-schedule entries are disabled.
- **No broker orders**: the runner calls no order endpoint, and the auto-trader starts disarmed and
  is checked before every options scan.
- **No IBKR**: ports 5000 and 7499 are closed and guarded (G1, and G3 twice).

---

## 12. Comparability with days 1–2

Unchanged: the tag code, the tag runner, the gated config (`backend/app`, `scoring_rules.yaml`,
`contract_rules.yaml`), `strategy_params.yaml` and `sp500.csv` (the tag versions in the meas checkout,
as days 1–2 had after `git switch`; their hashes equal both day manifests), the scan bodies, the
timing, the venv.

Changed, and recorded:

- **The database** is a fresh copy taken minutes before the run instead of the live database
  (same content at copy time). The per-table counts are in `isolation.json`.
- **`settings.yaml`** is the sanitized copy: its sha256 changes and both hashes are recorded. It is
  not gated and not a pooling key (S-scans pool only on the `strategy_params.yaml` hash; the
  `settings.yaml` hash already differed between day 1 and day 2).
- **Notifications off; IBKR gateways must be closed** (the runner already stopped when IBKR was
  authenticated).
- **The confidence cache** is carried between isolated days in the meas checkout, as the shared
  file carried it before: the first isolated run seeds it once from the live file (read-only),
  later runs keep it. Since 8ee11537 main writes cache keys the tag never reads, so only rows the
  tag wrote itself can be hit. Each day records the origin (`seeded-from-live`, `carried-over` or
  `cold`) and its **tag-hittable row count**, so the analysis can see a cold start. Day 1's warm
  cache (tag-format rows main wrote before 8ee11537) cannot be reproduced.

---

## 13. What the A-block (PROTOCOL steps 3–7) does not have

The isolated runner runs the **core** block only. It has no isolated path for the A-block
(`strip-creds`, `ivabs`, `restore-check`), which `PROTOCOL.md` describes on the switched main
checkout. Do not run the A-block the old way; ask a Claude session first.
