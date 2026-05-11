@echo off
title Bamendjou -- Frontend
setlocal enabledelayedexpansion

set LOG=%USERPROFILE%\Desktop\frontend-startup.log
echo === STARTUP %date% %time% === >> "%LOG%"

if not exist "%~dp0frontend\package.json" (
    echo ERROR: package.json not found in %~dp0frontend >> "%LOG%"
    echo ERROR: package.json not found. This .bat must be run from the repo root.
    pause
    exit /b 1
)
cd /d "%~dp0frontend"

node -e "process.exit(0)" >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: node not found in PATH >> "%LOG%"
    echo ERROR: Node.js not found. Check your nvm-windows setup.
    pause
    exit /b 1
)

npm -v >nul 2>&1
if !errorlevel! neq 0 (
    echo ERROR: npm not found in PATH >> "%LOG%"
    echo ERROR: npm not found. Check your Node.js installation.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('node -v') do echo Node %%v >> "%LOG%"
for /f "delims=" %%v in ('npm -v')  do echo npm %%v  >> "%LOG%"

if not exist "node_modules\.bin\next.cmd" (
    echo node_modules missing. Running npm install... >> "%LOG%"
    echo node_modules missing. Running npm install...
    call npm install
)

netstat -ano | findstr "LISTENING" | findstr ":3001 " >nul 2>&1
if !errorlevel! equ 0 (
    echo WARNING: Port 3001 is already in active use. >> "%LOG%"
    echo WARNING: Port 3001 is already in active use. Kill the existing process first.
    pause
    exit /b 1
)

echo Starting Next.js frontend on http://localhost:3001
echo Press Ctrl+C to stop.
echo.
echo Logs also written to: %LOG%
echo.

call npm run dev 2>&1 | powershell -Command "$input | Tee-Object -FilePath '%LOG%' -Append"

if !errorlevel! neq 0 (
    echo.
    echo npm run dev exited with code !errorlevel! -- check %LOG% for details
)
pause
