@echo off
setlocal
rem Brings up the Postgres container. Meant to run at login (see
rem setup-desktop-shortcuts.bat, which registers this in the Startup folder)
rem so Postgres is already up before you ever run start-backend.bat.
rem
rem At login this races Docker Desktop itself: the Startup folder fires within
rem seconds of the shell loading, while the Docker engine (WSL2 VM + daemon)
rem typically needs 30-90s to accept commands. Without the wait below, the
rem compose call just failed into >nul and the autostart did nothing at all.
cd /d "%~dp0"
set "LOG=%~dp0start-db.log"

echo [%DATE% %TIME%] waiting for the Docker engine...> "%LOG%"
set /a _tries=0
:wait_engine
docker info >nul 2>&1
if not errorlevel 1 goto engine_up
set /a _tries+=1
if %_tries% GEQ 120 (
    echo [%DATE% %TIME%] ERROR: Docker engine not reachable after ~120s; giving up.>> "%LOG%"
    exit /b 1
)
timeout /t 1 /nobreak >nul 2>&1
goto wait_engine
:engine_up

echo [%DATE% %TIME%] engine up after ~%_tries%s; starting db...>> "%LOG%"
docker compose up -d --wait --wait-timeout 120 db >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR: db did not become healthy. See above.>> "%LOG%"
    exit /b 1
)
echo [%DATE% %TIME%] db is healthy.>> "%LOG%"
