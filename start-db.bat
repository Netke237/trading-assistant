@echo off
rem Brings up the Postgres container. Meant to run silently at login (see
rem setup-desktop-shortcuts.bat, which registers this in the Startup folder)
rem so Postgres is always up before you ever run start-backend.bat.
cd /d "%~dp0"
docker compose up -d db >nul 2>&1
