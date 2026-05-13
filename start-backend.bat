@echo off
title Bamendjou — Backend
cd /d "%~dp0backend"

:: Check if port 8000 is already occupied
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr /L "127.0.0.1:8000" ^| findstr /L "LISTENING"') do (
    echo ERROR: Port 8000 is already in use by PID %%P.
    echo        Run: taskkill /F /PID %%P /T   to free it, then retry.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
call uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
