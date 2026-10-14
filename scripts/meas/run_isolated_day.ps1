# Thin Task Scheduler launcher for one isolated MEAS day (plan
# docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md section 2.1, #230).
# It runs `scripts\meas\isolated_day.py run` with the repo venv, tees the output to
# %USERPROFILE%\bamendjou-jobs\logs\meas-isolated-<stamp>.log and exits with the
# orchestrator's exit code. Everything else (guards, start, stop, evidence) is
# done by the Python orchestrator; this script changes no git state and starts
# or stops no backend itself.
$ErrorActionPreference = "Continue"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Py = Join-Path $Repo "backend\.venv\Scripts\python.exe"
$Orchestrator = Join-Path $PSScriptRoot "isolated_day.py"
$LogDir = Join-Path $env:USERPROFILE "bamendjou-jobs\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("meas-isolated-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
if (-not (Test-Path $Py)) {
    "repo venv python not found: $Py" | Tee-Object -FilePath $Log
    exit 2
}
$env:PYTHONUTF8 = "1"
& $Py $Orchestrator run 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $Log
$code = $LASTEXITCODE
exit $code
