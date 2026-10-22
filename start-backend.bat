@echo off
setlocal
title Bamendjou - Backend
set "ROOT=%~dp0"
cd /d "%ROOT%backend"

rem Bind address. Default 127.0.0.1 = this PC only. To open the app from
rem another PC on the LAN, set BAMENDJOU_BACKEND_BIND=0.0.0.0 in the root .env
rem (local, gitignored) together with CORS_EXTRA_ORIGINS - see .env.example.
rem The API has no authentication, so LAN binding is opt-in, never the default.
rem %%~B drops surrounding quotes, so BAMENDJOU_BACKEND_BIND="0.0.0.0" also works.
set "BIND_HOST=127.0.0.1"
if exist "%ROOT%.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%.env") do (
        if /i "%%A"=="BAMENDJOU_BACKEND_BIND" if not "%%~B"=="" set "BIND_HOST=%%~B"
    )
)

:kill_8000
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /L /C:"127.0.0.1:8000 " /C:"0.0.0.0:8000 " /C:"%BIND_HOST%:8000 " ^| findstr /L "LISTENING"') do (
    echo Killing PID %%P on port 8000...
    taskkill /F /PID %%P /T >nul 2>&1
)
timeout /t 1 /nobreak >nul 2>&1
netstat -ano 2>nul | findstr /L /C:"127.0.0.1:8000 " /C:"0.0.0.0:8000 " /C:"%BIND_HOST%:8000 " | findstr /L "LISTENING" >nul 2>&1
if not errorlevel 1 goto kill_8000

rem docker-compose.yml interpolates bare ${POSTGRES_USER}/${POSTGRES_PASSWORD}/
rem ${POSTGRES_DB} with no defaults. Without .env, Compose substitutes empty
rem strings, still EXITS 0, and the Postgres entrypoint then aborts with
rem "superuser password is not specified" - reproducing the exact connection-
rem refused error this script exists to prevent. Fail loudly instead.
if not exist "%ROOT%.env" (
    echo ERROR: %ROOT%.env is missing.
    echo Copy .env.example to .env and fill in POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB.
    pause
    exit /b 1
)

rem --wait blocks on the compose healthcheck and returns non-zero on timeout,
rem so this one call replaces the hand-rolled "docker inspect" polling loop AND
rem makes errorlevel meaningful. 120s covers a cold volume, where the container
rem runs initdb plus backend/migrations/init-scripts before pg_isready passes.
echo Starting Postgres (Docker) and waiting for it to become healthy...
docker compose -f "%ROOT%docker-compose.yml" up -d --wait --wait-timeout 120 db
if errorlevel 1 (
    echo.
    echo ERROR: Postgres did not come up healthy.
    echo   - Is Docker Desktop running?
    echo   - Check the container logs: docker compose logs db
    echo Refusing to start the backend against a database that is not ready,
    echo because that is what produces the asyncpg "connection refused" error.
    pause
    exit /b 1
)

echo Running database migrations...
call .venv\Scripts\python.exe -m alembic -c migrations/alembic.ini upgrade head
if errorlevel 1 (
    echo.
    echo ERROR: Alembic migration failed - the backend would run against a
    echo stale or empty schema. Fix the migration before retrying.
    pause
    exit /b 1
)

call .venv\Scripts\python.exe -m uvicorn app.main:app --ws websockets-sansio --host %BIND_HOST% --port 8000
pause
