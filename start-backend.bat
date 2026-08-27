@echo off
title Bamendjou - Backend
set "ROOT=%~dp0"
cd /d "%ROOT%backend"

:kill_8000
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /L "127.0.0.1:8000" ^| findstr /L "LISTENING"') do (
    echo Killing PID %%P on port 8000...
    taskkill /F /PID %%P /T >nul 2>&1
)
timeout /t 1 /nobreak >nul 2>&1
netstat -ano 2>nul | findstr /L "127.0.0.1:8000" | findstr /L "LISTENING" >nul 2>&1
if not errorlevel 1 goto kill_8000

echo Starting Postgres (Docker)...
docker compose -f "%ROOT%docker-compose.yml" up -d db
if errorlevel 1 (
    echo WARNING: Could not start the db container. Is Docker Desktop running?
    echo Continuing anyway - the app will fall back to SQLite if DATABASE_URL is unset.
)

echo Waiting for Postgres to become healthy...
set /a _tries=0
:wait_db
for /f %%H in ('docker inspect -f "{{.State.Health.Status}}" tradingassistant-db 2^>nul') do set "_health=%%H"
if /I "%_health%"=="healthy" goto db_ready
set /a _tries+=1
if %_tries% GEQ 30 (
    echo WARNING: Postgres did not become healthy in time. Continuing anyway...
    goto db_ready
)
timeout /t 1 /nobreak >nul 2>&1
goto wait_db
:db_ready

echo Running database migrations...
call .venv\Scripts\python.exe -m alembic -c migrations/alembic.ini upgrade head
if errorlevel 1 (
    echo WARNING: Alembic migration failed. Continuing anyway...
)

call .venv\Scripts\python.exe -m uvicorn app.main:app --ws websockets-sansio --host 127.0.0.1 --port 8000
pause
