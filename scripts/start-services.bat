@echo off
rem Optional infrastructure (Qdrant, Postgres, Ollama) via Docker.
rem BLACKBOX runs without these — in-memory RAG and SQLite are the defaults.

docker compose version >nul 2>&1
if errorlevel 1 (
    echo Docker is not available. BLACKBOX works without it — run start-dev.bat.
    exit /b 1
)

cd /d "%~dp0.."
docker compose up -d
