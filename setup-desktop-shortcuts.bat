@echo off
setlocal
rem One-time setup. Run this by double-clicking it once.
rem   1. Adds "Bamendjou Backend" and "Bamendjou Frontend" shortcuts to your Desktop.
rem   2. Registers start-db.bat to run minimized at every login, so Postgres is
rem      already up before you ever click the Backend shortcut.
rem Safe to re-run; it just overwrites the same shortcuts.
set "ROOT=%~dp0"
rem Passed to PowerShell through the environment, not interpolated into the
rem -Command string: a single quote in the path (C:\Users\O'Brien\...) would
rem otherwise terminate the PowerShell string literal and fail to parse.
set "BAMENDJOU_ROOT=%ROOT%"

rem The Desktop and Startup folders are resolved INSIDE PowerShell via
rem GetFolderPath rather than hardcoded from %USERPROFILE%/%APPDATA%. With
rem OneDrive Known Folder Move enabled (the default on most consumer Windows
rem installs) the real Desktop is %USERPROFILE%\OneDrive\Desktop and the
rem hardcoded path does not exist, so Save() threw and BOTH shortcuts were
rem silently skipped. GetFolderPath honours the redirection; ErrorActionPreference
rem plus the errorlevel check below means a failure is reported, not swallowed.
echo Creating desktop shortcuts and registering Postgres autostart...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$root = $env:BAMENDJOU_ROOT;" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$startup = [Environment]::GetFolderPath('Startup');" ^
  "$defs = @(" ^
  "  @{ Path = (Join-Path $desktop 'Bamendjou Backend.lnk');  Target = 'start-backend.bat';  Icon = 'shell32.dll,21';  Style = 1 }," ^
  "  @{ Path = (Join-Path $desktop 'Bamendjou Frontend.lnk'); Target = 'start-frontend.bat'; Icon = 'shell32.dll,220'; Style = 1 }," ^
  "  @{ Path = (Join-Path $startup 'Bamendjou DB.lnk');       Target = 'start-db.bat';       Icon = 'shell32.dll,21';  Style = 7 }" ^
  ");" ^
  "foreach ($d in $defs) {" ^
  "  $s = $ws.CreateShortcut($d.Path);" ^
  "  $s.TargetPath = (Join-Path $root $d.Target);" ^
  "  $s.WorkingDirectory = $root;" ^
  "  $s.IconLocation = $d.Icon;" ^
  "  $s.WindowStyle = $d.Style;" ^
  "  $s.Save();" ^
  "  Write-Host ('  created ' + $d.Path);" ^
  "}"
if errorlevel 1 (
    echo.
    echo ERROR: shortcut creation failed - see the message above.
    echo Shortcuts are created one at a time in order (Backend, Frontend, then
    echo the Startup DB entry) - any "created ..." lines already printed above
    echo DID get installed; only the one that failed (and any after it) did not.
    echo Fix the cause and re-run - this script overwrites the same shortcuts,
    echo so it is safe to run again even after a partial failure.
    pause
    exit /b 1
)

echo.
echo Done:
echo   - Desktop: Bamendjou Backend, Bamendjou Frontend (each kills any
echo     existing session on its port before starting, same as before).
echo   - Postgres now starts at login, minimized. start-db.bat waits for the
echo     Docker engine first and logs to start-db.log, so if it ever fails
echo     you can see why.
echo.
echo One more one-time step (can't be scripted): open Docker Desktop -^>
echo Settings -^> General -^> enable "Start Docker Desktop when you log in".
echo Without that, Docker itself won't be running yet at login for the
echo Postgres autostart above to attach to.
pause
