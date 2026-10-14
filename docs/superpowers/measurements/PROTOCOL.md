# MEAS — measurement-day run-book

Plan: `docs/superpowers/plans/2026-09-25-meas-market-data-measurement-plan.md` (v6 + [G1a] + [U1]).
The runner, `run_measurement_day.py`, enforces every check below and stops or flags on a breach.
This page is the part it cannot do for you.

**Nothing here changes a threshold.** A later session reads the results under rules that were
fixed before the data existed (plan §6). Every proposed change needs Kenneth's yes.

What you need: **at least two valid days**, on different calendar days, on the same freeze tag.
Ideally the days are in different market regimes. One of the days also runs the A-block (steps 3–7).

All commands run from the repo root in a Windows `cmd` window, with the backend's Python:

```
set PY=backend\.venv\Scripts\python.exe
set PYTHONUTF8=1
```

---

## Step 0 — once, before day 1: the freeze tag

1. **The MEAS build must be merged to `main` first.** The runner and the bodies live on `main` from
   then on. Tagging a commit without them leaves you with no runner.
2. `git checkout main` and `git pull`, then tag that commit: `git tag meas-freeze-1`. Every day
   runs on this one commit.
3. Restart the backend (`start-backend.bat`) so it runs the tagged code.

**On every later day, put yourself back on the tag before anything else:**
`git switch --detach meas-freeze-1`, then restart the backend. `main` moves almost every day, so
staying on `main` would fail the freeze check. Switching to the tag is the normal start of a day.
It is different from the forbidden move below, which is running `git checkout` on files to make
the runner's mismatch go away. After the last day, `git switch main`.

The runner stops if `backend/app/` (except `backend/app/data/sp500.csv`) or `scoring_rules.yaml` /
`contract_rules.yaml` differ from the tag, including uncommitted edits. If it does, **do not run
`git checkout` to make it pass**: show the listed files to a Claude session first.

`sp500.csv` is not frozen, because the S&P liquidity update rewrites it. Its hash is recorded, and a
rewrite **during** a block invalidates that block (see the checklist).

> **Since 2026-10-14 (#230): day runs go through the isolated runner. This note overrides the
> "switch to the tag" instructions above and in steps 1–2.**
> - Run a day only with `scripts/meas/run_isolated_day.ps1` (Task Scheduler) or
>   `scripts/meas/isolated_day.py run`; check first with `isolated_day.py check`. They run the
>   unchanged tag code and the tag's own runner from a separate checkout outside the repo, on port
>   8100, against a copy of the database. How: [ISOLATED-RUN.md](ISOLATED-RUN.md).
> - **Never switch the main checkout to `meas-freeze-1`** (no `git switch --detach meas-freeze-1`
>   here), and never stop the live backend for a MEAS day. On 2026-10-09 that let the frozen code
>   prune the live `ohlcv_daily` history.
> - The old wrapper `C:\Users\<user>\bamendjou-jobs\meas_day.ps1` and its scheduled task are
>   retired; keep them disabled and unused.
> - The isolated runner runs the core block only; there is no isolated A-block (steps 3–7) yet.

## Step 1 — checklist before each day (13:00 ET at the latest)

- [ ] A normal US trading day: **not a weekend, not an NYSE half-day** (the runner cannot know
      half-days).
- [ ] You are on the freeze tag (`git switch --detach meas-freeze-1`). After any switch,
      checkout or pull, restart the backend.
      The runner sees config, but not which code the running backend loaded.
- [ ] Backend running, with **one** worker.
- [ ] **IBKR gateway stopped.** Its IV ranks override tastytrade's, and a day must use one rank
      vendor.
- [ ] tastytrade connected (Settings → Brokers). `degraded` is accepted and recorded.
- [ ] Auto-trader **disarmed**. `POST /api/scan` fires an armed auto-trade on a PASS candidate.
- [ ] Every scan-schedule entry **disabled**.
- [ ] Do not start the S&P liquidity update during the run. Its daily cron must not fall
      between 13:00 and 16:00 ET.
- [ ] Do not edit any config, and do not use Strategy adopt or Tuning, during the run.
- [ ] Do not run scans from the app during the run. Each runner POST also replaces the app's
      "last scan" and its rank deltas.

## Step 2 — the core block (start 13:00–13:15 ET)

```
%PY% docs\superpowers\measurements\run_measurement_day.py core
```

It refuses to start outside 13:00–13:15 ET or at a weekend, and it never overwrites an existing day
folder. For a second attempt on the same day, add `--run-tag run2`.

It runs 13 scans in a fixed order, which takes about 90 minutes: O1 C1 C5 C6 O2 C1b C5b O3 O4 S1 S2 S3 S4.
- Each counterfactual (C) scan runs right after its base.
- C-scans are skipped (`skipped:time`) when the bases are projected to finish after 14:50 ET.
  The bases always run.

Before every options scan, it checks that the auto-trader is still disarmed.

At the start and the end it records:
- `GET /api/config/health`, including the backend pid;
- data sources and the position regime;
- the sha256 of each config file and of `sp500.csv`;
- a copy of the git-tracked config files. Gitignored files, such as `settings.yaml` and the
  schedules, are hashed only and never copied.

Output goes to `docs/superpowers/measurements/scans/<date>/`, with a `manifest.json` that lists
every scan, its `scan_id` and its flags.

**If it stops:** read the message.
- A stop in the pre-checks, before it prints the `NOTE:` line, leaves no folder. Fix the cause and
  rerun the same command.
- A stop after that keeps the folder, marks it `day_invalid: core_block_not_completed`, and never
  overwrites it. For a second attempt the same day, add `--run-tag run2`, if it is still before
  13:15 ET.
- O1 itself must start by 13:15 ET. If the pre-checks run past that, the runner stops.

**The day counts only if** it has all eight base scans, none flagged `state:`, `INVALID:` or
`late_for_comparison`, the manifest's `core_status` is `core_complete` (a manifest still reading
`running` means the run was killed before its end checks: the day does **not** count), and the
manifest has no `day_invalid` (an unfinished core block always writes one),
`INVALID:config_changed_during_run`, `INVALID:backend_restarted` or
`INVALID:universe_changed_during_run`. A `snapshot_failed:core_end` flag means only the end-of-run
context (data sources, regime) is missing. The validity checks ran before it.

## Step 3 — A-block, one day only: make a credentials copy without tastytrade

Run the A-block (steps 3–7) on **one** valid day, straight after `core`. It measures absolute IV,
so the percentile source must be off. **Never blank a slot in Settings**, because that rewrites the
real credentials file. Use a copy instead:

```
%PY% docs\superpowers\measurements\run_measurement_day.py strip-creds --out C:\Users\<you>\meas-creds.yaml
```

The copy goes **outside** the repo, and the runner refuses a path inside it. It keeps every slot
except `tastytrade_paper` and `tastytrade_live`. The Tradier slots stay, because the option chains
come from Tradier.

## Step 4 — restart the backend on the copy

1. Stop the backend. Keep the IBKR gateway stopped.
2. In **one** cmd window:
   ```
   set BAMENDJOU_CREDS_PATH=C:\Users\<you>\meas-creds.yaml
   start-backend.bat
   ```
   It must be the same window, because `start-backend.bat` inherits the variable.

## Step 5 — the A-block (A1, A2)

The backend now occupies the step-4 window, so open a **second** cmd window for the runner. Set
`PY` and `PYTHONUTF8` again there, as at the top of this page.

```
%PY% docs\superpowers\measurements\run_measurement_day.py ivabs
```

It requires:
- tastytrade `unconfigured`. Anything else means the backend is not running on the copy;
- Tradier up. Down means a mistyped `BAMENDJOU_CREDS_PATH`, which loads empty credentials;
- IBKR not up.

Add `--run-tag` if `core` used one.

If it prints **"A-block NOT usable"**, the block may be repeated on a later valid day:
- causes: a scan was truncated, a scan still showed rank IV, the backend restarted, or a config or
  universe file changed;
- the manifest's `ivabs_unusable_because` says which;
- the report uses the first **usable** A-block only.

## Step 6 — restart normally

Close that cmd window. Open a **new** one and run `start-backend.bat`. Then:

```
%PY% docs\superpowers\measurements\run_measurement_day.py restore-check
```

Use the same `--run-tag` as `core` and `ivabs`, if they had one. It requires tastytrade to be up again.

## Step 7 — delete the copy

Delete `C:\Users\<you>\meas-creds.yaml`. It holds broker tokens.

## After each day

Commit the new `scans/<date>/` folder on a branch and hand it to a Claude session. The session
follows plan §7: it collects IV rows from the `*.envelope.json` files and fills that day's section
of `RESULTS-SHEET.md`. A truncated scan has no envelope file on purpose.
