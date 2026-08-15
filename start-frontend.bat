@echo off
title Bamendjou - Frontend
cd /d "%~dp0frontend"

:kill_3001
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":3001" ^| findstr /L "LISTENING"') do (
    echo Killing PID %%P on port 3001...
    taskkill /F /PID %%P /T >nul 2>&1
)
timeout /t 1 /nobreak >nul 2>&1
netstat -ano 2>nul | findstr ":3001" | findstr /L "LISTENING" >nul 2>&1
if not errorlevel 1 goto kill_3001

call npm run dev
pause
