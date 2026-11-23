# J1 per-horizon tuning run (#115): provenance and status

Run-book: [`../2026-11-12-j1-tuning/runbook.md`](../2026-11-12-j1-tuning/runbook.md). Nothing here adopts a
parameter: no `active:` write, no `backend/config/*` edit, no `adopt()` call. Adoption is #116.

## Status

| Date (Berlin) | Step |
|---|---|
| Mon 2026-11-16 23:00 | Frozen export, end 2026-11-13 (2.6 min, read-only `SELECT`s in one snapshot) |
| Mon 2026-11-16 23:10 | Probe on the frozen bars: **169.46 h at 3 workers** (upper bound) |
| Tue 2026-11-17 | Kenneth approved the full run in chat. `run-j1.ps1` written. Kenneth registered the `Bamendjou J1 tuning` task from an elevated PowerShell; verified: daily 03:30 starting 2026-11-18 (first `NextRunTime` 2026-11-18 03:30), S4U, `Limited`, priority 7, no execution time limit, `IgnoreNew`, arguments `-WindowEnd 01:30 -Workers 3` |
| Wed 11-18, Thu 11-19 03:30 | **Both sessions stopped before their first cell (2 days lost).** PowerShell variable names ignore case, so the wrapper's local `$windowEnd` was the `[string]` parameter `$WindowEnd`: the window end became the string "…01:30:00" of the same morning, and the crosses-midnight `AddDays(1)` never applied. Fixed in commit `7ff1b20c` (renamed to `$windowEndAt`), dry-tested with a stub in place of Python (a past window end rolls over to the next day; STOP and the too-long-cell guard still work) |
| Thu 2026-11-19 06:27 | Frozen-bar hashes re-checked (0 differences) and the pinned worktree is clean at `d15620d8`. Today's session was started by hand (`Start-ScheduledTask`), window end Fri 11-20 01:30; 3 tuner processes at about 90 % CPU |
| Thu 11-19 08:33 → 21:52 | The mini PC was put to sleep from the Start menu (System 1074 / Kernel-Power 42; no reboot). The tuner was frozen and resumed; only wall time was lost. `runtime_s` includes the sleep (Position recorded about 15 h), which made the guard end that session early |
| Fri 11-20 07:06 | Group 1 `pullback_ema` Bullish done: 4 of 5 pass. Its report shows `projected 6.61 h` for the group pass, so **the group pass had recomputed all 5 cells**. Cause: `data_hash` includes the benchmarks of the scoring horizons selected in the call (Swing → Swing, the other four → Position). One-cell calls ({Swing} or {Position}) never matched the group call ({Swing, Position}). Results unaffected; about 30 % extra time |
| Fri 11-20 08:15 | Kenneth: "Yes, fix it". Wrapper `40a81fb4`: paired per-cell calls (`<h>,Swing`; `Swing,Position`) carry the group's identity, so a finished partner is reused, and the group pass only writes the report. Checked with the tuner's own `select_cells` / `scoring_horizon_for` (every paired call = the group's set) and a stub run of the whole sequence. Finished groups get `GROUP_DONE`; the group pass is window-guarded. The old session was stopped between cells with the STOP file after `breakout_base` Bullish Swing (fails, 7,300 s). New session started 09:09: its `pullback_ema` group pass printed `5 cells (5 finished, skipped by --resume)` and `projected runtime: 0.00 h` (1 min) |
| Fri 11-20 → Sun 11-22 | Groups 2–4 done (`breakout_base`, `ma_crossover`, `mean_reversion_rsi` Bullish); `mean_reversion_bb` Bullish Swing and Position done. Measured/probe per group: 0.29–1.04 for trend groups, **1.27 for `mean_reversion_rsi`** (the probe is not an upper bound for mean reversion). The 11-21 and 11-22 sessions stopped at 16:44 and 16:13 because the next cell in order did not fit before 01:30: about 9 h idle each day |
| Mon 11-23 07:45 | Kenneth (via the coordinating session): "Yes, fill the gaps". Wrapper gap filling: when the next call in order does not fit, the first later call that fits runs instead, until nothing fits; group passes run whenever a group's five cells are finished, in any order. Per-call estimate = probe group hours × K (largest measured/probe ratio of finished groups, ≥ 1) × horizon share × 1.3; a hand start between 01:30 and 03:30 is refused. Stub-simulated over five sessions from the real 22-cell state: no call ends after 01:30, every call has both scoring horizons, every group pass computes nothing. Frozen-bar hashes re-checked (0 differences). Installed while the 03:30 session ran (that session keeps the version it parsed) |
| — | Run in progress: progress per cell is posted on #115. **Open: `mean_reversion_multi` (both directions) does not fit a 22 h session**: its Swing cell is estimated at about 23 h measured-scale (33 h with margin) on the probe × 1.27 basis. The wrapper never starts it and logs it daily. **Decided 11-23, Kenneth: "Publish 50, run later"**: the 50 other cells are published as a partial result when done; mean_reversion_multi runs later by a method Kenneth picks then (past 01:30 through ingestion, ingestion paused, or 4 workers; see #115) |
| Mon 11-23 16:41 | `mean_reversion_bb` Bullish group done (3 of 5 pass, 25.8 h = 1.49 × probe). Gap-filling wrapper took over at 16:41 (`pullback_ema` Bearish Swing + Annual). Estimate for the 50 cells: Thu 11-26 to Fri 11-27 |

## Inputs (fixed for the whole run)

| What | Value |
|---|---|
| Machine | the mini PC, 4 logical cores → `--workers 3`, Python 3.11.9, `backtesting==0.6.6` |
| Pinned code | `C:\bamendjou-tuning\code`, a detached worktree at [`PINNED_COMMIT.txt`](PINNED_COMMIT.txt) = `d15620d8` (= `origin/main` on 2026-11-16) |
| Frozen bars | `C:\bamendjou-tuning\bars-2026-11-13`: 511 symbol files + `manifest.json` ([`export-manifest.json`](export-manifest.json)), files read-only |
| Hashes | [`export-bars-2026-11-13.sha256.csv`](export-bars-2026-11-13.sha256.csv): SHA256 of all 512 files; manifest `5CD0B3CC…7B8C` |
| Universe | [`symbols.txt`](symbols.txt): `basket.universe_union()` at `d15620d8` (534) **minus SGEN and ANSS** = 532 selected; trade 498, fire 512 |
| Bounds | requested 2000-01-01 → 2026-11-13 inclusive; 432 of 511 symbols start 2009-11-20 (the first stored bar) |
| Benchmarks | none: every scoring horizon's trend method is `additive` (`scoring_rules.yaml` at `d15620d8`), so the proxies are null and QQQ's missing rows don't matter |
| Costs, gates | as configured at `d15620d8` (`strategy_params.yaml` `tuning:` block, `scoring_rules.yaml`); their hashes are in the manifest's `provenance` |

### How the export deviates from the run-book

The run-book runs the export from the repo root, for its `.env`. Here the export ran from the pinned worktree
instead, with the root `.env`'s `DATABASE_URL` passed through the process environment. The dev checkout was on an
older board branch with an uncommitted `backend/app/data/sp500.csv`, which the universe is built from. This way the
export, the manifest's `source_hashes` and every tuning session use the same committed files.

### Exclusions and coverage

- **Excluded (Kenneth, 2026-11-16):** SGEN and ANSS. After their acquisitions the database holds only filler bars
  with one constant close and about zero volume: SGEN 175 bars after 2023-12-14, ANSS 166 after 2025-07-17.
- **Missing:** L3H (no stored bars).
- **Ending before 2026-11-13:** QRVO 2026-10-05, WBD 10-07, KVUE 10-30, VICI and VST 11-11.
- **Short histories:** SOLV 663, VLTO 784, KVUE 877 and GEHC 982 bars.
- Database-wide, 30 symbols end more than 7 days before 11-13. The flagged sector ETFs (XLK/XLC/XLV, stopped
  mid-October) and EA/AVB/EQR (stopped in August) are not in the trade or fire universe, so the export did not
  request them. Nothing is filled in.

## Projection (measured probe on the frozen bars)

See [`probe.txt`](probe.txt) and [`probe-summary.json`](probe-summary.json). Bullish trend groups 18.3 h, all
Bullish 82.6 h, all Bearish 86.9 h; total 169.46 h = signals 141.75 h + gate masks 0.99 h + simulation 26.72 h.
That is 5.7× the 29.5 h fixture projection in `../2026-11-12-j1-tuning/probe.txt`. Real 4,271-bar series make a
simulated window cost about 4–8 ms instead of 0.15 ms, and mean-reversion signal calls 2–4 ms instead of
0.2–0.5 ms.

## Quiet window and scheduling

[`QUIET_WINDOW.txt`](QUIET_WINDOW.txt): sessions run 03:30 → 01:30 daily at below-normal priority. The nightly
ingestion runs at 02:00. The run skips the MEAS day Tue 2026-11-17 (the trigger starts on 11-18).

[`run-j1.ps1`](run-j1.ps1) is the run-book §5 wrapper with two changes:

- `-Workers 3`;
- a per-cell start guard in place of the fixed `-LatestStart`. A cell starts only if now plus its expected length
  is before the 01:30 window end. The expected length is 1.3 × the larger of the probe's group hours × the Swing
  fold share (51/169) and the longest `runtime_s` among the group's finished cells.

Queue: Bullish `pullback_ema`, `breakout_base`, `ma_crossover`, then Bullish mean-reversion, then every Bearish
group. Since 11-23 the queue order is a preference, not a barrier: a call that does not fit before 01:30 is
passed over for the first later one that does (gap filling). Every invocation uses `--resume`, and each group finishes with a group-level `--resume` pass that writes
its `tuning_report.md`.

## Next steps (for whoever continues)

1. Before each session, compare the export hashes (run-book §2): `Compare-Object` must print nothing.
2. Watch progress (run-book §6): count `C:\bamendjou-tuning\runs\*\data\cells\*.json` (of 60) and tail the latest
   `logs\j1-*.log`. Post progress per cell on #115. While a tuner call is running, its `Add-Content` pipeline holds
   the log open, so `Get-Content` on it fails until that cell ends. Between cells the log reads normally; the cell
   files are the reliable progress signal.
3. Before any future MEAS day, disable `Bamendjou J1 tuning` the day before and enable it afterwards.
4. When all 12 groups are done, copy each `runs\<strategy>-<Direction>\out\tuning_report.md` and
   `tuning_summary.json` here, open the docs PR, comment on #115 and release the claim `KENNETH-J1-TUNING-RUN`.
