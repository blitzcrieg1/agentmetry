@echo off
rem Agentmetry local launcher — no Docker required.
rem Optional services (Qdrant/Postgres/Ollama): scripts\start-services.bat

echo Starting orchestrator...
cd /d "%~dp0..\apps\orchestrator"
start "Agentmetry orchestrator" cmd /k ".venv\Scripts\activate && uvicorn api.main:app --reload --port 8000"

echo Starting dashboard...
cd /d "%~dp0..\apps\dashboard"
start "Agentmetry dashboard" cmd /k "npm run dev"

echo.
echo Agentmetry is launching. Dashboard: http://localhost:3000
echo Logs: apps\orchestrator\data\logs\orchestrator.log
