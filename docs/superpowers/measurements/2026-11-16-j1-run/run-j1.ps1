# One scheduled session of the J1 tuning (#115): completed cells only, stops between cells.
# Run-book: docs/superpowers/measurements/2026-11-12-j1-tuning/runbook.md, section 5, with
# two machine-specific settings agreed with Kenneth on 2026-11-16/17:
#   * Workers 3 (the mini PC has 4 logical cores);
#   * the quiet window ends at 01:30 (nightly ingestion 02:00). A cell starts only if
#     now + its expected length <= window end, where the expected length is the larger of
#     (a) the probe's projected hours for its strategy/direction x the Swing fold share and
#     (b) the longest runtime_s of the group's finished cells, times $Margin. This is the
#     run-book's "LatestStart = window end minus the longest cell seen so far, plus margin",
#     computed per cell instead of passed as one fixed time.
param([string]$WindowEnd = "01:30", [int]$Workers = 3, [double]$Margin = 1.3)
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
$windowEnd = [datetime]::Today.Add([timespan]::Parse($WindowEnd))
if ($windowEnd -lt (Get-Date)) { $windowEnd = $windowEnd.AddDays(1) }   # window crosses midnight
$env:PYTHONUTF8 = "1"
Add-Content -Path $Log ("session start {0:yyyy-MM-dd HH:mm}, window end {1:yyyy-MM-dd HH:mm}, workers {2}" -f (Get-Date), $windowEnd, $Workers)

function Get-CellHours([string]$Item, [string]$Run) {
    $longest = $GroupHours[$Item] * $SwingShare
    Get-ChildItem "$Run\data\cells\*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $hit = Select-String -Path $_.FullName -Pattern '"runtime_s":\s*([0-9.eE+-]+)' -List
        if ($hit) { $h = [double]$hit.Matches[0].Groups[1].Value / 3600.0; if ($h -gt $longest) { $longest = $h } }
    }
    return $longest * $Margin
}

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
        $need = Get-CellHours $item $run
        if ((Get-Date).AddHours($need) -gt $windowEnd) {
            Add-Content -Path $Log ("{0} {1} {2} needs up to {3:N1} h, window ends {4:HH:mm}: stopping between cells" -f $strategy, $direction, $h, $need, $windowEnd)
            exit 0
        }
        Add-Content -Path $Log ("{0:HH:mm} start {1} {2} {3} (allowing {4:N1} h)" -f (Get-Date), $strategy, $direction, $h, $need)
        $code = Invoke-Tuner "${strategy}:$h" $direction $run
        if ($code -ne 0) { Add-Content -Path $Log "tuner exit $code on $strategy $direction $h"; exit $code }
    }
    # All five cells finished: rebuild this group's report from the finished cells. This must
    # print "5 cells (5 finished, skipped by --resume)" and "projected runtime: 0.00 h".
    $code = Invoke-Tuner $strategy $direction $run
    if ($code -ne 0) { exit $code }
}
Add-Content -Path $Log "all groups finished"
