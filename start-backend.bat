@echo off
title Bamendjou — Backend
cd /d "%~dp0backend"

if exist "%~dp0.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
)

echo Starting FastAPI backend on http://localhost:8000
echo Press Ctrl+C to stop.
echo.
call .venv\Scripts\activate.bat
uvicorn app.main:app --reload --port 8000
pause
