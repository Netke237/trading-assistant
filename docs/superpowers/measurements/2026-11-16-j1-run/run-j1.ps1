# One scheduled session of the J1 tuning (#115): completed cells only, stops between cells.
# Run-book: docs/superpowers/measurements/2026-11-12-j1-tuning/runbook.md, section 5, with
# machine- and run-specific changes agreed with Kenneth (2026-11-16 .. 11-23):
#   * Workers 3 (the mini PC has 4 logical cores);
#   * the quiet window ends at 01:30 (nightly ingestion 02:00). A tuner call starts only if
#     now + its expected length <= window end; cells are never cut. This is the run-book's
#     LatestStart, computed per call instead of passed as one fixed time.
#   * Paired cell calls (2026-11-20). A cell's --resume identity hashes the benchmarks of the
#     scoring horizons selected in that call (Swing -> Swing; Position, Quarterly, SemiAnnual,
#     Annual -> Position). Every call therefore selects one cell of each scoring horizon
#     ("<h>,Swing"; for Swing a finished Position-type cell, else Annual), so it has the group's
#     identity: a finished partner is reused, an unfinished one is computed in the same call, and
#     the group pass reuses all five cells and only writes the report.
#   * Gap filling (2026-11-23, Kenneth: "Yes, fill the gaps"). Between calls the session takes the
#     first unfinished cell in queue order; if that call does not fit before the window end, it
#     takes the first later cell (same group first, then later groups) whose call fits, and keeps
#     going until nothing fits. A group whose five cells are finished, in any order, gets its
#     group pass (window-guarded) and GROUP_DONE before the next cell is chosen.
#   * Expected length of a cell = probe hours of its group x K x the horizon's share x $Margin.
#     K = the largest measured/probe ratio among finished groups (at least 1.0), raised for a group
#     whose own finished cells already ran slower than that. Shares are upper bounds of what the
#     finished groups measured (11-20 .. 11-22: Swing 0.52, Position 0.31, Quarterly 0.32,
#     SemiAnnual 0.14, Annual 0.16). A call's length is its cell plus its partner if unfinished.
# Test hook: J1_TEST_CLOCK (a file holding an ISO time) replaces the clock; unset in production.
param([string]$WindowEnd = "01:30", [string]$WindowStart = "03:30", [int]$Workers = 3, [double]$Margin = 1.3, [double]$GroupPassHours = 1.0,
      [double]$SessionHours = 22.0,
      [string]$Root = "C:\bamendjou-tuning",
      [string]$Py = "C:\GitHub\trading-assistant\backend\.venv\Scripts\python.exe",
      [string]$Tuner = "")
$ErrorActionPreference = "Continue"
(Get-Process -Id $PID).PriorityClass = "BelowNormal"     # inherited by python and its pool
if (-not $Tuner) { $Tuner = "$Root\code\backend\scripts\tune_horizons.py" }
$Bars    = "$Root\bars-2026-11-13"
$Cache   = "$Root\cache"
$Symbols = ((Get-Content "$Bars\manifest.json" -Raw | ConvertFrom-Json).universes.selected) -join ","
$Queue = @("pullback_ema|Bullish", "breakout_base|Bullish", "ma_crossover|Bullish",
           "mean_reversion_rsi|Bullish", "mean_reversion_bb|Bullish", "mean_reversion_multi|Bullish",
           "pullback_ema|Bearish", "breakout_base|Bearish", "ma_crossover|Bearish",
           "mean_reversion_rsi|Bearish", "mean_reversion_bb|Bearish", "mean_reversion_multi|Bearish")
$Horizons = @("Swing", "Position", "Quarterly", "SemiAnnual", "Annual")
$PositionType = @("Position", "Quarterly", "SemiAnnual", "Annual")
# Projected hours per strategy/direction at 3 workers (probe on the frozen bars, 2026-11-16).
$GroupHours = @{
    "pullback_ema|Bullish" = 5.39;  "breakout_base|Bullish" = 5.94;  "ma_crossover|Bullish" = 7.01
    "mean_reversion_rsi|Bullish" = 10.39; "mean_reversion_bb|Bullish" = 17.27; "mean_reversion_multi|Bullish" = 36.57
    "pullback_ema|Bearish" = 4.94;  "breakout_base|Bearish" = 6.52;  "ma_crossover|Bearish" = 5.87
    "mean_reversion_rsi|Bearish" = 10.65; "mean_reversion_bb|Bearish" = 15.36; "mean_reversion_multi|Bearish" = 42.56
}
$HorizonShare = @{ "Swing" = 0.55; "Position" = 0.35; "Quarterly" = 0.35; "SemiAnnual" = 0.18; "Annual" = 0.18 }

function Get-Now {
    if ($env:J1_TEST_CLOCK) { return [datetime]::Parse((Get-Content $env:J1_TEST_CLOCK -Raw).Trim(), [Globalization.CultureInfo]::InvariantCulture) }
    return Get-Date
}

New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
Set-Location "$Root\code"      # the pinned worktree; never the development checkout
$Log = Join-Path "$Root\logs" ("j1-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$sessionStart = Get-Now
# Not $windowEnd: PowerShell names ignore case, so that would be the [string] parameter.
$windowEndAt = $sessionStart.Date.Add([timespan]::Parse($WindowEnd))
if ($windowEndAt -lt $sessionStart) { $windowEndAt = $windowEndAt.AddDays(1) }   # window crosses midnight
$env:PYTHONUTF8 = "1"
# A session started by hand between the window end and the window start (the ingestion slot)
# would otherwise run into the next day's window end: refuse it.
$quietFrom = $sessionStart.Date.Add([timespan]::Parse($WindowEnd)); $quietTo = $sessionStart.Date.Add([timespan]::Parse($WindowStart))
if ($sessionStart -ge $quietFrom -and $sessionStart -lt $quietTo) {
    Add-Content -Path $Log ("session start {0:yyyy-MM-dd HH:mm} is between {1} and {2} (ingestion slot): not starting" -f $sessionStart, $WindowEnd, $WindowStart)
    exit 0
}
Add-Content -Path $Log ("session start {0:yyyy-MM-dd HH:mm}, window end {1:yyyy-MM-dd HH:mm}, workers {2}, gap filling" -f $sessionStart, $windowEndAt, $Workers)

function Get-RunDir([string]$Item) { $s, $d = $Item.Split("|"); return "$Root\runs\$s-$d" }
function Get-CellFile([string]$Item, [string]$Hz) { $s, $d = $Item.Split("|"); return "$(Get-RunDir $Item)\data\cells\${s}__${d}__$Hz.json" }
function Test-Cell([string]$Item, [string]$Hz) { return (Test-Path (Get-CellFile $Item $Hz)) }

function Get-RuntimeHours([string]$File) {
    $hit = Select-String -Path $File -Pattern '"runtime_s":\s*([0-9.eE+-]+)' -List
    if ($hit) { return [double]$hit.Matches[0].Groups[1].Value / 3600.0 }
    return 0.0
}

function Get-Calibration {       # K: the largest measured/probe ratio among finished groups, >= 1.0
    $k = 1.0
    foreach ($it in $Queue) {
        if (-not (Test-Path "$(Get-RunDir $it)\GROUP_DONE")) { continue }
        $sum = 0.0
        foreach ($h in $Horizons) { if (Test-Cell $it $h) { $sum += Get-RuntimeHours (Get-CellFile $it $h) } }
        $ratio = $sum / $GroupHours[$it]
        if ($ratio -gt $k) { $k = $ratio }
    }
    return $k
}

function Get-GroupFactor([string]$Item, [double]$K) {   # K, raised if this group already runs slower
    $sum = 0.0; $share = 0.0
    foreach ($h in $Horizons) {
        if (Test-Cell $Item $h) { $sum += Get-RuntimeHours (Get-CellFile $Item $h); $share += $HorizonShare[$h] }
    }
    if ($share -gt 0) { $g = $sum / ($GroupHours[$Item] * $share); if ($g -gt $K) { return $g } }
    return $K
}

function Get-CellHours([string]$Item, [string]$Hz, [double]$F) { return $GroupHours[$Item] * $F * $HorizonShare[$Hz] * $Margin }

function Get-Call([string]$Item, [string]$Hz, [double]$F) {      # the paired call for one cell
    $need = Get-CellHours $Item $Hz $F
    if ($Hz -eq "Swing") {
        $partner = $null
        foreach ($h in $PositionType) { if (Test-Cell $Item $h) { $partner = $h; break } }
        if (-not $partner) { $partner = "Annual"; $need += Get-CellHours $Item $partner $F }   # computed too
    } else {
        $partner = "Swing"
        if (-not (Test-Cell $Item "Swing")) { $need += Get-CellHours $Item "Swing" $F }
    }
    $s, $d = $Item.Split("|")
    return [pscustomobject]@{ Item = $Item; Strategy = $s; Direction = $d; Hz = $Hz; Partner = $partner; Need = $need }
}

function Invoke-Tuner([string]$Cells, [string]$Direction, [string]$Run) {
    & $Py -u $Tuner --cells $Cells --directions $Direction --symbols $Symbols --bars-dir $Bars `
        --data "$Run\data" --out "$Run\out" --cache-dir $Cache --workers $Workers --resume 2>&1 |
        ForEach-Object { "$_" } | Add-Content -Path $Log
    return $LASTEXITCODE                    # the only pipeline output of this function
}

while ($true) {
    if (Test-Path "$Root\STOP") { Add-Content -Path $Log "STOP file present: stopping between cells"; exit 0 }
    $now = Get-Now

    # 1. Group report for a group whose five cells are finished, in whatever order they finished.
    $passed = $false
    foreach ($item in $Queue) {
        $run = Get-RunDir $item
        if (Test-Path "$run\GROUP_DONE") { continue }
        if (@($Horizons | Where-Object { -not (Test-Cell $item $_) }).Count -gt 0) { continue }
        $s, $d = $item.Split("|")
        if ($now.AddHours($GroupPassHours) -gt $windowEndAt) {
            Add-Content -Path $Log ("{0} {1} group report needs up to {2:N1} h, window ends {3:yyyy-MM-dd HH:mm}: stopping between cells" -f $s, $d, $GroupPassHours, $windowEndAt)
            exit 0
        }
        Add-Content -Path $Log ("{0:HH:mm} group pass {1} {2}" -f $now, $s, $d)
        $code = Invoke-Tuner $s $d $run
        if ($code -ne 0) { Add-Content -Path $Log "tuner exit $code on the $s $d group pass"; exit $code }
        Set-Content -Path "$run\GROUP_DONE" -Value ((Get-Now).ToString("yyyy-MM-ddTHH:mm:ss"))
        Add-Content -Path $Log ("{0:HH:mm} group done {1} {2}" -f (Get-Now), $s, $d)
        $passed = $true
        break
    }
    if ($passed) { continue }

    # 2. Next cell: the first unfinished one in queue order, else the first later one that fits.
    $k = Get-Calibration
    $first = $null; $pick = $null; $never = @()
    foreach ($item in $Queue) {
        if (Test-Path "$(Get-RunDir $item)\GROUP_DONE") { continue }
        $f = Get-GroupFactor $item $k
        $groupFirst = $true
        foreach ($hz in $Horizons) {
            if (Test-Cell $item $hz) { continue }
            $c = Get-Call $item $hz $f
            if ($groupFirst -and $c.Need -gt $SessionHours) { $never += $c }   # the group's next call
            $groupFirst = $false
            if ($null -eq $first) { $first = $c }
            if ($now.AddHours($c.Need) -le $windowEndAt) { $pick = $c; break }
        }
        if ($null -ne $pick) { break }
    }
    if ($null -eq $first) { Add-Content -Path $Log "all groups finished"; exit 0 }
    if ($null -eq $pick) {
        Add-Content -Path $Log ("no unfinished cell fits (K {0:N2}): next in order {1} {2} {3} (+ {4}) needs up to {5:N1} h, window ends {6:yyyy-MM-dd HH:mm}: stopping between cells" -f $k, $first.Strategy, $first.Direction, $first.Hz, $first.Partner, $first.Need, $windowEndAt)
        foreach ($c in $never) {
            Add-Content -Path $Log ("  longer than a whole {0:N0} h session: {1} {2} {3} (+ {4}) {5:N1} h" -f $SessionHours, $c.Strategy, $c.Direction, $c.Hz, $c.Partner, $c.Need)
        }
        exit 0
    }
    if ($pick -ne $first) {
        Add-Content -Path $Log ("{0:HH:mm} next in order {1} {2} {3} (+ {4}) needs up to {5:N1} h, past the window end: filling the gap" -f $now, $first.Strategy, $first.Direction, $first.Hz, $first.Partner, $first.Need)
    }
    Add-Content -Path $Log ("{0:HH:mm} start {1} {2} {3} (call with {4}; allowing {5:N1} h, K {6:N2})" -f $now, $pick.Strategy, $pick.Direction, $pick.Hz, $pick.Partner, $pick.Need, $k)
    $run = Get-RunDir $pick.Item
    $code = Invoke-Tuner ("{0}:{1},{0}:{2}" -f $pick.Strategy, $pick.Hz, $pick.Partner) $pick.Direction $run
    if ($code -ne 0) { Add-Content -Path $Log ("tuner exit {0} on {1} {2} {3}" -f $code, $pick.Strategy, $pick.Direction, $pick.Hz); exit $code }
    if (-not (Test-Cell $pick.Item $pick.Hz)) {     # never loop on a call that writes nothing
        Add-Content -Path $Log ("no cell file after {0} {1} {2}: stopping" -f $pick.Strategy, $pick.Direction, $pick.Hz); exit 1
    }
}
