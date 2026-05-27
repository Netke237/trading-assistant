@echo off
title Bamendjou - Backend
cd /d "%~dp0backend"

:kill_8000
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /L "127.0.0.1:8000" ^| findstr /L "LISTENING"') do (
    echo Killing PID %%P on port 8000...
    taskkill /F /PID %%P /T >nul 2>&1
)
timeout /t 1 /nobreak >nul 2>&1
netstat -ano 2>nul | findstr /L "127.0.0.1:8000" | findstr /L "LISTENING" >nul 2>&1
if not errorlevel 1 goto kill_8000

call .venv\Scripts\activate.bat

echo Running database migrations...
call python -m alembic -c migrations/alembic.ini upgrade head
if errorlevel 1 (
    echo WARNING: Alembic migration failed. Continuing anyway...
)

call python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
