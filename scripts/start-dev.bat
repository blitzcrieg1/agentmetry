@echo off
echo Starting BLACKBOX infrastructure...
docker compose up -d

echo.
echo Starting orchestrator...
cd apps\orchestrator
start cmd /k ".venv\Scripts\activate && uvicorn api.main:app --reload --port 8000"

echo.
echo Starting dashboard...
cd ..\dashboard
start cmd /k "npm run dev"

echo.
echo BLACKBOX is launching. Dashboard: http://localhost:3000
