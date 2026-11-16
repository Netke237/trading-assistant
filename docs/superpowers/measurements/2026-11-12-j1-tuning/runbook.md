# J1 per-horizon tuning on the mini PC — frozen-bar run-book

Phase TUNER-RECHECK-WINDOW (#638), Task 3 (#641). This is how the real J1 tuning
(#115) is to be run later on the Windows mini PC. **Nothing in this phase runs it.**
Its results are published on #115 for review; **no parameter is adopted** (nothing is
written to `active:`, `strategy_params.yaml` is not edited, `adopt()` is not called).

Every command Kenneth runs is Windows PowerShell 5.1. Paths below are examples: choose
them once, then never change them for the whole run, because `--bars-dir`, `--data`,
`--out` and `--cache-dir` are part of what makes `--resume` work across days.

| What | Example path (fixed for the whole run) |
|---|---|
| Repository (export only; has the repo-root `.env`) | `C:\GitHub\trading-assistant` |
| Pinned code (git worktree at one commit) | `C:\bamendjou-tuning\code` |
| Python 3.11 (the repo venv) | `C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe` |
| Frozen bars (`--bars-dir`) | `C:\bamendjou-tuning\bars-2026-11-13` |
| Signal/gate cache (`--cache-dir`, shared, keyed by full identity) | `C:\bamendjou-tuning\cache` |
| Per strategy/direction results (`--data`, `--out`) | `C:\bamendjou-tuning\runs\<strategy>-<Direction>\data`, `...\out` |
| Logs | `C:\bamendjou-tuning\logs` |

## 1. Export the bars once, with a fixed end date

Pick the end date (the last complete trading day, for example `2026-11-13`) and do it
once. The export is read only: one snapshot transaction, no ingestion, no healing, no
provider call. It refuses an existing destination.

```powershell
$Py  = "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe"
$End = "2026-11-13"
$Bars = "C:\bamendjou-tuning\bars-$End"
& $Py --version                       # must print Python 3.11.x; stop otherwise
New-Item -ItemType Directory -Force -Path "C:\bamendjou-tuning" | Out-Null
Set-Location "C:\GitHub\trading-assistant"   # repo root: the database URL comes from its .env
git status --short                     # note anything uncommitted; the export records the commit
git rev-parse HEAD | Set-Content "C:\bamendjou-tuning\PINNED_COMMIT.txt"
$env:PYTHONUTF8 = "1"
& $Py backend\scripts\export_tuning_bars.py --out $Bars --end $End
```

Do not run the export during the nightly ingestion or on a MEAS day (section 4).

## 2. Inspect the manifest and freeze the export

```powershell
$m = Get-Content "$Bars\manifest.json" -Raw | ConvertFrom-Json
$m.bounds                                  # start / end (inclusive) as requested
"selected {0}, trade {1}, fire {2}, available {3}, missing {4}" -f `
  $m.universes.selected.Count, $m.universes.trade.Count, $m.universes.fire.Count, `
  $m.available.Count, $m.missing.Count
$m.missing                                 # every requested symbol without stored bars
$m.benchmarks                              # scoring horizon -> benchmark name and proxy symbol
$m.provenance.git_commit
# Coverage: symbols whose history ends before the export end or is short.
$m.files.PSObject.Properties | ForEach-Object { $_.Value } |
  Where-Object { $_.last -ne $End -or $_.count -lt 1000 } |
  Select-Object file, count, first, last | Format-Table -AutoSize
```

Check before going on:

* `available` is in the hundreds (a handful means the export read the wrong database:
  delete that new export directory and fix the environment before exporting again);
* every benchmark proxy (for example `SPY`) is in `available`;
* the `missing` list and short histories are acceptable; they are reported in the
  results, never filled in.

Then save the file hashes and make the export read only:

```powershell
Get-FileHash -Algorithm SHA256 "$Bars\*.json" |
  Select-Object @{n='File';e={Split-Path $_.Path -Leaf}}, Hash |
  Export-Csv -NoTypeInformation "C:\bamendjou-tuning\bars-$End.sha256.csv"
attrib +R "$Bars\*.json"
```

Before each later session, compare the hashes again; any difference means the frozen
bars changed and the run is no longer the same run:

```powershell
$saved = Import-Csv "C:\bamendjou-tuning\bars-$End.sha256.csv"
$now = Get-FileHash -Algorithm SHA256 "$Bars\*.json" |
  Select-Object @{n='File';e={Split-Path $_.Path -Leaf}}, Hash
Compare-Object $saved $now -Property File, Hash     # must print nothing
```

## 3. Pin the code, configuration and universe for every resumed run

A cell's resume identity covers the cell, the `tuning:` block, its grid, the baseline
parameters, the exit block, the signal and gate source code, the scoring rules, the
sample, the trade/fire universes, every symbol's bars, the benchmarks, the sectors and
the sector counts. Change any of them and finished cells are recomputed. So:

* **Code and configuration**: run from a git worktree at the pinned commit, never from the
  development checkout, which keeps moving.

  ```powershell
  Set-Location "C:\GitHub\trading-assistant"
  git worktree add --detach "C:\bamendjou-tuning\code" (Get-Content "C:\bamendjou-tuning\PINNED_COMMIT.txt")
  ```

  The worktree holds `backend\config\*.yaml` (tuning block, grids, exclusions, scoring
  rules), `backend\app\data\sp500.csv`, `sector_overrides.csv` and the sector map at that
  commit. Do not edit them while the run is in progress. If the pinned commit differs from
  `$m.provenance.git_commit`, re-check that the files listed in
  `$m.provenance.source_hashes` are unchanged between the two commits.
* **Universe**: always pass the manifest's fixed symbol list with `--symbols`, so today's
  index membership cannot change the run:

  ```powershell
  $Symbols = ($m.universes.selected) -join ","
  ```

* **Benchmarks**: the proxies come from the same `--bars-dir`; the mapping printed by
  `$m.benchmarks` must stay the same for every session.

Optional projection for the frozen bars (a projection, not a guarantee; it uses the
manifest's end date and three probe symbols, and times nothing else):

```powershell
Set-Location "C:\bamendjou-tuning\code"
& $Py -u backend\scripts\tune_horizons.py --probe --bars-dir $Bars --symbols AAPL,MSFT,NVDA `
  --workers 6 --probe-json "C:\bamendjou-tuning\logs\probe-$End.json"
```

Each tuner invocation also prints the preflight projection of its own pending cells,
weighted per strategy and direction; zero pending cells project 0 h and time nothing.

## 4. Quiet window: no MEAS day, no nightly ingestion

The tuner reads only the frozen files, but it saturates the CPU. It must not overlap:

* the nightly OHLCV ingestion (its time is on Settings -> Data in the app);
* a MEAS isolated day (`scripts\meas\run_isolated_day.ps1` and its scheduled task):

  ```powershell
  Get-ScheduledTask | Where-Object { $_.TaskName -match 'meas|isolated' } |
    ForEach-Object { $_ | Get-ScheduledTaskInfo } | Select-Object TaskName, NextRunTime
  ```

Declare the quiet window in writing before the first night, for example
"tuning 22:30-06:00, ingestion at 06:30, no MEAS day this week", and keep it in
`C:\bamendjou-tuning\QUIET_WINDOW.txt`. On a MEAS day, disable the tuning task the day
before and enable it again afterwards:

```powershell
Disable-ScheduledTask -TaskName "Bamendjou J1 tuning"
Enable-ScheduledTask  -TaskName "Bamendjou J1 tuning"
```

A cell is never cut short to fit the window: the wrapper below starts a cell only before
`LatestStart` (window end minus the longest cell seen so far, read from `runtime_s` in the
finished cell files, plus margin), and stops between completed cells.

## 5. The wrapper and the scheduled task

Separate persistent result roots per strategy and direction, so the
`tuning_report.md` / `tuning_summary.json` of one group never overwrites another's.
Order: the **Bullish trend strategies first** (`pullback_ema`, `breakout_base`,
`ma_crossover`), then the Bullish mean-reversion strategies, then all Bearish groups
(computed and shown as blocked (P0B)).

Save as `C:\bamendjou-tuning\run-j1.ps1`:

```powershell
# One scheduled session of the J1 tuning: completed cells only, stops between cells.
param([string]$LatestStart = "03:00", [int]$Workers = 6)
$ErrorActionPreference = "Continue"
(Get-Process -Id $PID).PriorityClass = "BelowNormal"     # inherited by python and its pool
$Root    = "C:\bamendjou-tuning"
$Py      = "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe"
$Tuner   = "$Root\code\backend\scripts\tune_horizons.py"
$Bars    = "$Root\bars-2026-11-13"
$Cache   = "$Root\cache"
$Symbols = ((Get-Content "$Bars\manifest.json" -Raw | ConvertFrom-Json).universes.selected) -join ","
$Queue = @("pullback_ema|Bullish", "breakout_base|Bullish", "ma_crossover|Bullish",
           "mean_reversion_rsi|Bullish", "mean_reversion_bb|Bullish", "mean_reversion_multi|Bullish",
           "pullback_ema|Bearish", "breakout_base|Bearish", "ma_crossover|Bearish",
           "mean_reversion_rsi|Bearish", "mean_reversion_bb|Bearish", "mean_reversion_multi|Bearish")
$Horizons = @("Swing", "Position", "Quarterly", "SemiAnnual", "Annual")
New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
$Log = Join-Path "$Root\logs" ("j1-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$deadline = [datetime]::Today.Add([timespan]::Parse($LatestStart))
if ($deadline -lt (Get-Date).AddHours(-12)) { $deadline = $deadline.AddDays(1) }   # window crosses midnight
$env:PYTHONUTF8 = "1"

function Invoke-Tuner([string]$Cells, [string]$Direction, [string]$Run) {
    & $Py -u $Tuner --cells $Cells --directions $Direction --symbols $Symbols --bars-dir $Bars `
        --data "$Run\data" --out "$Run\out" --cache-dir $Cache --workers $Workers --resume 2>&1 |
        ForEach-Object { "$_" } | Add-Content -Path $Log
    return $LASTEXITCODE                    # the only pipeline output of this function
}

foreach ($item in $Queue) {
    $strategy, $direction = $item.Split("|")
    $run = "$Root\runs\$strategy-$direction"
    foreach ($h in $Horizons) {
        if (Test-Path "$run\data\cells\${strategy}__${direction}__$h.json") { continue }   # finished
        if (Test-Path "$Root\STOP") { Add-Content -Path $Log "STOP file present: stopping between cells"; exit 0 }
        if ((Get-Date) -gt $deadline) { Add-Content -Path $Log "past LatestStart ${LatestStart}, stopping between cells"; exit 0 }
        $code = Invoke-Tuner "${strategy}:$h" $direction $run
        if ($code -ne 0) { Add-Content -Path $Log "tuner exit $code on $strategy $direction $h"; exit $code }
    }
    # All five cells finished: rebuild this group's report from the finished cells. This must
    # print "5 cells (5 finished, skipped by --resume)" and "projected runtime: 0.00 h".
    $code = Invoke-Tuner $strategy $direction $run
    if ($code -ne 0) { exit $code }
}
Add-Content -Path $Log "all groups finished"
```

Register it once (an elevated PowerShell). `S4U` runs it whether or not Kenneth is logged
on, in a non-interactive session, so the PowerShell host, python and every pool worker
stay hidden; `-Priority 7` is below normal; the trigger is the start of the quiet window:

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\bamendjou-tuning\run-j1.ps1" -LatestStart 03:00 -Workers 6'
$trigger  = New-ScheduledTaskTrigger -Daily -At "22:30"
$settings = New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
  -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName "Bamendjou J1 tuning" -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal
```

(`-ExecutionTimeLimit 0` means no hard kill: the wrapper ends the session between cells.
Set `-LatestStart` and `-Workers` from the projection and from the `runtime_s` of
the cells already finished; a cell takes as long as it takes.)

## 6. Stop, restart, resume

* **Stop between completed cells** (preferred): create the stop file. The current cell
  finishes and writes its file; the wrapper then exits.

  ```powershell
  New-Item -ItemType File -Force -Path "C:\bamendjou-tuning\STOP" | Out-Null
  ```

* **Restart**: remove the stop file and start the task (or wait for the next trigger).
  Finished cells are skipped; `--resume` reloads them only when their identity is
  unchanged (same frozen bars, code, configuration, universe).

  ```powershell
  Remove-Item "C:\bamendjou-tuning\STOP" -ErrorAction SilentlyContinue
  Start-ScheduledTask -TaskName "Bamendjou J1 tuning"
  ```

* **Emergency stop** (the in-progress cell is lost): stop the task and the tuner's
  process tree.

  ```powershell
  Stop-ScheduledTask -TaskName "Bamendjou J1 tuning"
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*tune_horizons.py*' } |
    ForEach-Object { taskkill.exe /PID $_.ProcessId /T /F }
  ```

  An interrupted cell does **not** resume midway: on the next session it starts again from
  its beginning (signal series already written to `--cache-dir` may be reused, but the
  walk-forward, the re-check and the verdict are recomputed). Only cells whose file was
  written count as finished.

Progress at any time:

```powershell
Get-ChildItem "C:\bamendjou-tuning\runs\*\data\cells\*.json" | Measure-Object | Select-Object Count  # of 60
Get-Content (Get-ChildItem "C:\bamendjou-tuning\logs\j1-*.log" | Sort-Object LastWriteTime | Select-Object -Last 1) -Tail 20
```

## 7. Publish on #115, adopt nothing

When all twelve groups are finished, post on #115: each group's
`runs\<strategy>-<Direction>\out\tuning_report.md` (and `tuning_summary.json`), the
export's `manifest.json` bounds/missing/benchmarks, the saved hash file, the pinned
commit and the quiet-window note. The per-cell JSON files under `data\cells` hold the
trade lists; keep them with the run. The results are evidence for a later, separately
reviewed adoption decision: do not change `active:` parameters, `strategy_params.yaml` or
any configuration from these numbers.

Never start the full tuner on the development machine or inside an agent session.
