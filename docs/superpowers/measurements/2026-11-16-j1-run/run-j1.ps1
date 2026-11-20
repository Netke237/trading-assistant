# One scheduled session of the J1 tuning (#115): completed cells only, stops between cells.
# Run-book: docs/superpowers/measurements/2026-11-12-j1-tuning/runbook.md, section 5, with
# machine- and run-specific changes agreed with Kenneth (2026-11-16 .. 11-20):
#   * Workers 3 (the mini PC has 4 logical cores);
#   * the quiet window ends at 01:30 (nightly ingestion 02:00). A cell starts only if
#     now + its expected length <= window end, where the expected length is the larger of
#     (a) the probe's projected hours for its strategy/direction x the Swing fold share and
#     (b) the longest runtime_s of the group's finished cells, times $Margin. This is the
#     run-book's "LatestStart = window end minus the longest cell seen so far, plus margin",
#     computed per cell instead of passed as one fixed time.
#   * Paired cell calls (2026-11-20). A cell's --resume identity hashes the benchmarks of the
#     scoring horizons selected in that call (Swing -> Swing; Position, Quarterly, SemiAnnual,
#     Annual -> Position). A one-cell call therefore had another identity than the group call,
#     and the final group pass recomputed all five cells. Every per-cell call now also selects
#     one cell of the other scoring horizon ("<h>,Swing", or "Swing,Position" for Swing), so it
#     has the group's identity: an already finished partner is reused, an unfinished one is
#     computed in the same call. The group pass then reuses all five and only writes the report.
#   * A finished group is marked with GROUP_DONE and skipped by later sessions; the group pass
#     itself is also guarded by the window end.
param([string]$WindowEnd = "01:30", [int]$Workers = 3, [double]$Margin = 1.3, [double]$GroupPassHours = 1.0)
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
# Projected hours per strategy/direction at 3 workers (probe on the frozen bars, 2026-11-16).
$GroupHours = @{
    "pullback_ema|Bullish" = 5.39;  "breakout_base|Bullish" = 5.94;  "ma_crossover|Bullish" = 7.01
    "mean_reversion_rsi|Bullish" = 10.39; "mean_reversion_bb|Bullish" = 17.27; "mean_reversion_multi|Bullish" = 36.57
    "pullback_ema|Bearish" = 4.94;  "breakout_base|Bearish" = 6.52;  "ma_crossover|Bearish" = 5.87
    "mean_reversion_rsi|Bearish" = 10.65; "mean_reversion_bb|Bearish" = 15.36; "mean_reversion_multi|Bearish" = 42.56
}
$SwingShare = 51.0 / 169.0     # folds: Swing 51 of 169 in total, the largest cell
New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
Set-Location "$Root\code"      # the pinned worktree; never the development checkout
$Log = Join-Path "$Root\logs" ("j1-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
# Not $windowEnd: PowerShell names ignore case, so that would be the [string] parameter.
$windowEndAt = [datetime]::Today.Add([timespan]::Parse($WindowEnd))
if ($windowEndAt -lt (Get-Date)) { $windowEndAt = $windowEndAt.AddDays(1) }   # window crosses midnight
$env:PYTHONUTF8 = "1"
Add-Content -Path $Log ("session start {0:yyyy-MM-dd HH:mm}, window end {1:yyyy-MM-dd HH:mm}, workers {2}" -f (Get-Date), $windowEndAt, $Workers)

function Get-CellHours([string]$Item, [string]$Run) {
    $longest = $GroupHours[$Item] * $SwingShare
    Get-ChildItem "$Run\data\cells\*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $hit = Select-String -Path $_.FullName -Pattern '"runtime_s":\s*([0-9.eE+-]+)' -List
        if ($hit) { $hh = [double]$hit.Matches[0].Groups[1].Value / 3600.0; if ($hh -gt $longest) { $longest = $hh } }
    }
    return $longest * $Margin
}

function Invoke-Tuner([string]$Cells, [string]$Direction, [string]$Run) {
    & $Py -u $Tuner --cells $Cells --directions $Direction --symbols $Symbols --bars-dir $Bars `
        --data "$Run\data" --out "$Run\out" --cache-dir $Cache --workers $Workers --resume 2>&1 |
        ForEach-Object { "$_" } | Add-Content -Path $Log
    return $LASTEXITCODE                    # the only pipeline output of this function
}

function Test-Stop([string]$What, [double]$Need) {
    if (Test-Path "$Root\STOP") { Add-Content -Path $Log "STOP file present: stopping between cells"; return $true }
    if ((Get-Date).AddHours($Need) -gt $windowEndAt) {
        Add-Content -Path $Log ("{0} needs up to {1:N1} h, window ends {2:yyyy-MM-dd HH:mm}: stopping between cells" -f $What, $Need, $windowEndAt)
        return $true
    }
    return $false
}

foreach ($item in $Queue) {
    $strategy, $direction = $item.Split("|")
    $run = "$Root\runs\$strategy-$direction"
    if (Test-Path "$run\GROUP_DONE") { continue }                                   # report written
    foreach ($hz in $Horizons) {
        $cellFile = "$run\data\cells\${strategy}__${direction}__$hz.json"
        if (Test-Path $cellFile) { continue }                                       # finished
        if ($hz -eq "Swing") { $partner = "Position" } else { $partner = "Swing" }
        $need = Get-CellHours $item $run
        if (-not (Test-Path "$run\data\cells\${strategy}__${direction}__$partner.json")) { $need = 2 * $need }  # both computed
        if (Test-Stop "$strategy $direction $hz (+ $partner)" $need) { exit 0 }
        Add-Content -Path $Log ("{0:HH:mm} start {1} {2} {3} (call with {4}; allowing {5:N1} h)" -f (Get-Date), $strategy, $direction, $hz, $partner, $need)
        $code = Invoke-Tuner "${strategy}:$hz,${strategy}:$partner" $direction $run
        if ($code -ne 0) { Add-Content -Path $Log "tuner exit $code on $strategy $direction $hz"; exit $code }
    }
    # All five cells finished: rebuild this group's report from the finished cells. With paired
    # calls this prints "5 cells (5 finished, skipped by --resume)" and "projected runtime: 0.00 h".
    if (Test-Stop "$strategy $direction group report" $GroupPassHours) { exit 0 }
    Add-Content -Path $Log ("{0:HH:mm} group pass {1} {2}" -f (Get-Date), $strategy, $direction)
    $code = Invoke-Tuner $strategy $direction $run
    if ($code -ne 0) { Add-Content -Path $Log "tuner exit $code on the $strategy $direction group pass"; exit $code }
    Set-Content -Path "$run\GROUP_DONE" -Value (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    Add-Content -Path $Log ("{0:HH:mm} group done {1} {2}" -f (Get-Date), $strategy, $direction)
}
Add-Content -Path $Log "all groups finished"
