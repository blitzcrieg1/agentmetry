# BLACKBOX — Obsidian-Cortex Agentic OS

A state machine execution environment where Obsidian is the non-volatile state ledger, LangGraph orchestrates agent workflows, and the dashboard is mission control.

## Quick Start (Docker — full stack)

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then:

```bash
docker compose up -d --build
docker exec -it agentic-os-ollama-1 ollama pull llama3.2
docker exec -it agentic-os-ollama-1 ollama pull nomic-embed-text
```

Open http://localhost:3000

This starts Qdrant, PostgreSQL, Ollama, the orchestrator, and the dashboard.

## Quick Start (Local dev)

```bash
cp .env.example .env

# Infrastructure only
docker compose up -d qdrant postgres ollama

# Orchestrator
cd apps/orchestrator
python -m venv .venv && .venv\Scripts\activate
pip install -e .
uvicorn api.main:app --reload --port 8000

# Dashboard
cd apps/dashboard && npm install && npm run dev
```

Without Docker, the system runs in dev mode with keyword RAG fallback and mock LLM responses.

## Adding a New Skill

1. Create a YAML definition in `vault/.system/skill-definitions/my_skill.yaml`
2. Implement a graph builder in `apps/orchestrator/core/graphs/`
3. Register the builder in `core/graphs/registry.py` under `_GRAPH_BUILDERS`
4. Call `POST /api/v1/skills/reload` or restart the orchestrator

The skill auto-appears in The Armory on next dashboard load.

## Skills

| Skill | Graph | Description |
|-------|-------|-------------|
| `lead_gen` | Planner → Researcher → Writer → Critic → Approval → Finalize | B2B outreach with human approval gate |
| `summarize_meeting` | Ingest → Extract → Summarize → Finalize | Meeting notes → action items |

## Architecture

- **vault/** — Obsidian vault with skill definitions, knowledge base, and archive
- **apps/orchestrator/** — FastAPI + LangGraph backend with RAG and WebSocket streaming
- **apps/dashboard/** — Next.js mission control with React Flow graph visualization

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/health` | System status (vault, Qdrant, Ollama, Postgres) |
| `GET /api/v1/telemetry` | Historical execution stats |
| `GET /api/v1/vault/tree` | Vault folder/file listing |
| `GET /api/v1/vault/notes/{path}` | Read a vault note |
| `GET /api/v1/skills/` | List skills + registered graphs |
| `POST /api/v1/skills/reload` | Re-scan vault skill definitions |
| `POST /api/v1/skills/execute` | Run a skill |
| `POST /api/v1/skills/approve` | Approve/reject paused skill |
| `WS /ws/{session_id}` | Real-time telemetry stream |

## Environment

See `.env.example` for all configuration options. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BLACKBOX_USE_POSTGRES` | `false` | Use PostgreSQL for telemetry (auto `true` in Docker) |
| `BLACKBOX_VAULT_PATH` | `./vault` | Obsidian vault location |
| `BLACKBOX_COST_ALERT_THRESHOLD` | `1.0` | Session cost alert in USD |
