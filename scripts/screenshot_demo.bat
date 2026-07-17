@echo off
rem Isolated demo trail for marketing screenshots — no real paths, ingest OFF.
rem
rem   scripts\screenshot_demo.bat
rem
rem Then in a second terminal:
rem   cd apps\dashboard && npm run dev
rem   open http://localhost:3000
rem
rem Resume real capture afterward: scripts\agentmetry.bat stop && scripts\agentmetry.bat start

cd /d "%~dp0.."

echo.
echo Agentmetry screenshot mode — sanitized fake events only
echo.

call scripts\agentmetry.bat stop 2>nul

echo [1/2] Seeding demo trail (generic paths, no C:\Users\...)...
rem Must be the venv python: seed_demo imports core.config, whose dependencies
rem install.ps1 only puts in the venv. Bare "python" works only on machines
rem that happen to have them system-wide.
apps\orchestrator\.venv\Scripts\python.exe scripts\seed_demo.py
if errorlevel 1 (
  echo seed_demo.py failed
  exit /b 1
)

echo.
echo [2/2] Starting orchestrator on :8000 with demo-trail.jsonl...
set AGENTMETRY_AUDIT_EXPORT_PATH=%CD%\apps\orchestrator\data\demo-trail.jsonl
set AGENTMETRY_AUDIT_DB_PATH=%CD%\apps\orchestrator\data\demo-trail.db
set AGENTMETRY_DETECTION_LIVE_DB_PATH=%CD%\apps\orchestrator\data\demo-detection-live.db
set AGENTMETRY_OPERATOR_ID=home-lab
set AGENTMETRY_AUDIT_INGEST_ENABLED=0
set AGENTMETRY_LLM_PROVIDER=mock
set AGENTMETRY_ALLOW_MOCK=1
set AGENTMETRY_STARTUP_VAULT_INDEX=0

cd apps\orchestrator
start "Agentmetry screenshot demo" cmd /k ".venv\Scripts\activate && uvicorn api.main:app --port 8000 --log-level warning"

echo.
echo Ready. In another terminal:
echo   cd apps\dashboard
echo   npm run dev
echo.
echo Open http://localhost:3000  — time window: Last 1h
echo.
echo Fake sessions include credential-exfil, guardrail bypass, recon, and
echo ordinary refactors. No local usernames or project paths.
echo.
echo When done: close the demo server window, then  scripts\agentmetry.bat start
