@echo off
rem One-time setup. Run this by double-clicking it once.
rem   1. Adds "Bamendjou Backend" and "Bamendjou Frontend" shortcuts to your Desktop.
rem   2. Registers start-db.bat to run (minimized, silently) every time you log in,
rem      so Postgres is already up before you ever click the Backend shortcut.
rem Safe to re-run; it just overwrites the same shortcuts.
setlocal
set "ROOT=%~dp0"
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

echo Creating desktop shortcuts...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut('%DESKTOP%\Bamendjou Backend.lnk');" ^
  "$s.TargetPath = '%ROOT%start-backend.bat';" ^
  "$s.WorkingDirectory = '%ROOT%';" ^
  "$s.IconLocation = 'shell32.dll,21';" ^
  "$s.Save();" ^
  "$s2 = $ws.CreateShortcut('%DESKTOP%\Bamendjou Frontend.lnk');" ^
  "$s2.TargetPath = '%ROOT%start-frontend.bat';" ^
  "$s2.WorkingDirectory = '%ROOT%';" ^
  "$s2.IconLocation = 'shell32.dll,220';" ^
  "$s2.Save();"

echo Registering Postgres auto-start on login...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s3 = $ws.CreateShortcut('%STARTUP%\Bamendjou DB.lnk');" ^
  "$s3.TargetPath = '%ROOT%start-db.bat';" ^
  "$s3.WorkingDirectory = '%ROOT%';" ^
  "$s3.WindowStyle = 7;" ^
  "$s3.Save();"

echo.
echo Done:
echo   - Desktop: Bamendjou Backend, Bamendjou Frontend (each kills any
echo     existing session on its port before starting, same as before).
echo   - Postgres will now start automatically in the background at login.
echo.
echo One more one-time step (can't be scripted): open Docker Desktop -^>
echo Settings -^> General -^> enable "Start Docker Desktop when you log in".
echo Without that, Docker itself won't be running yet at login for the
echo Postgres autostart above to attach to.
pause
