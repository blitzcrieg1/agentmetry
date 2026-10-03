@echo off
rem Agentmetry single-process mode: build the dashboard into a static export and
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
rem Loopback only. This used to bind 0.0.0.0, which put the API on every
rem network the machine joined. For phone or LAN access use mobile.bat, or set
rem AGENTMETRY_BIND explicitly.
if "%AGENTMETRY_BIND%"=="" set AGENTMETRY_BIND=127.0.0.1
echo Starting Agentmetry (single process) on http://%AGENTMETRY_BIND%:8000
cd /d "%~dp0..\apps\orchestrator"
start "" http://127.0.0.1:8000
.venv\Scripts\uvicorn agentmetry.api.main:app --host %AGENTMETRY_BIND% --port 8000
