@echo off
rem BLACKBOX single-process mode: build the dashboard into a static export and
rem serve both the API and the UI from one uvicorn process on :8000.
rem (Use start-dev.bat for the two-terminal hot-reload dev workflow.)

echo Building dashboard export...
cd /d "%~dp0..\apps\dashboard"
set NEXT_PUBLIC_SAME_ORIGIN=true
call npm run build
if errorlevel 1 (
    echo Dashboard build failed.
    exit /b 1
)

echo.
echo Starting BLACKBOX (single process) on http://localhost:8000
cd /d "%~dp0..\apps\orchestrator"
start "" http://localhost:8000
.venv\Scripts\uvicorn api.main:app --host 0.0.0.0 --port 8000
