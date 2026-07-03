# BLACKBOX — Obsidian-Cortex Agentic OS

A state machine execution environment where Obsidian is the non-volatile state ledger, LangGraph orchestrates agent workflows, and the dashboard is mission control.

## Quick Start (Local — Gemini, no Docker)

Recommended setup. Uses Google Gemini for LLM + embeddings and in-memory semantic RAG.

```powershell
# 1. Configure
copy .env.example apps\orchestrator\.env
# Edit apps\orchestrator\.env — set GEMINI_API_KEY

# 2. Orchestrator
cd apps\orchestrator
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn api.main:app --reload --port 8000

# 3. Dashboard (new terminal)
cd apps\dashboard
npm install
npm run dev
```

Open http://localhost:3000

System Status should show **Gemini: up** and **RAG: semantic memory**.

After the first setup, `scripts\start-dev.bat` launches both processes in one step
(no Docker required). Orchestrator logs persist to `apps\orchestrator\data\logs\orchestrator.log`.

## Single-process mode (one port, no dev server)

For always-on local use, serve the whole app from one process. `scripts\serve.bat`
builds the dashboard into a static export and hosts both the UI and API from
uvicorn on `http://localhost:8000`:

```powershell
scripts\serve.bat
```

Under the hood it runs `npm run build` (with `NEXT_PUBLIC_SAME_ORIGIN=true` so the
UI calls the API on whatever origin served it — LAN and phone access just work)
and the orchestrator mounts `apps/dashboard/out/` at `/`. No second terminal, no
CORS or port juggling. Rebuild the export after changing dashboard code; the
two-terminal `start-dev.bat` flow remains best for hot-reload development.

## Optional services (Docker)

Qdrant, PostgreSQL, and Ollama are optional accelerators — BLACKBOX runs without
them on in-memory RAG and SQLite. To start them, run `scripts\start-services.bat`
or use the full compose stack below.

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cp .env.example .env
# Set GEMINI_API_KEY in .env for the orchestrator service

docker compose up -d --build
```

Open http://localhost:3000

Docker starts Qdrant, PostgreSQL, Ollama, orchestrator, and dashboard. Pass `GEMINI_API_KEY` via compose env or a `.env` file at repo root.

Optional Ollama models (if not using Gemini):

```bash
docker exec -it agentic-os-ollama-1 ollama pull llama3.2
docker exec -it agentic-os-ollama-1 ollama pull nomic-embed-text
```

## Skills

| Skill | Graph | Description |
|-------|-------|-------------|
| `lead_gen` | Planner → Researcher → Writer → Critic → Approval → Finalize | B2B outreach with human approval gate |
| `summarize_meeting` | Ingest → Extract → Summarize → Finalize | Meeting notes → action items |
| `weekly_review` | Collect → Analyze → Prioritize → Finalize | Weekly vault review and priorities |

## Adding a New Skill

1. Create a YAML definition in `vault/.system/skill-definitions/my_skill.yaml`
2. Implement a graph builder in `apps/orchestrator/core/graphs/`
3. Register the builder in `core/graphs/registry.py` under `_GRAPH_BUILDERS`
4. Click **Reload Skills** in the dashboard or `POST /api/v1/skills/reload`

The skill auto-appears in The Armory on next load.

## Architecture

- **vault/** — Obsidian vault with skill definitions, knowledge base, and archive
- **apps/orchestrator/** — FastAPI + LangGraph backend with RAG and WebSocket streaming
- **apps/dashboard/** — Next.js mission control with React Flow graph visualization

## API Endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /api/v1/health` | Open | System status (vault, Qdrant, Gemini, Postgres) |
| `GET /api/v1/telemetry` | Open | Historical execution stats |
| `GET /api/v1/vault/tree` | Open | Vault folder/file listing |
| `GET /api/v1/vault/notes/{path}` | Open | Read a vault note (path-jailed) |
| `GET /api/v1/skills/` | Open | List skills + registered graphs |
| `GET /api/v1/runs/` | Open | Run history from the audit log (paged, newest first) |
| `GET /api/v1/runs/{thread_id}/events` | Open | Per-run node execution trace |
| `POST /api/v1/skills/reload` | API key | Re-scan vault skill definitions |
| `POST /api/v1/skills/execute` | API key | Run a skill |
| `POST /api/v1/skills/approve` | API key | Approve/reject paused skill |
| `POST /api/v1/vault/reindex` | API key | Full vault reindex |
| `WS /ws/{session_id}` | Open | Real-time telemetry stream |

Set `BLACKBOX_API_KEY` in orchestrator `.env` and `NEXT_PUBLIC_BLACKBOX_API_KEY` in dashboard env to enable auth. Leave empty for open local dev.

## Environment

See `.env.example` for all configuration options. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BLACKBOX_LLM_PROVIDER` | `gemini` | LLM backend: `gemini`, `ollama`, or `mock` |
| `BLACKBOX_ALLOW_MOCK` | `false` | Permit mock fallback when no real provider is available (archived as `mock-dry-run`) |
| `GEMINI_API_KEY` | — | Google AI Studio API key |
| `BLACKBOX_GEMINI_MODEL` | `gemini-2.5-flash` | Generation model |
| `BLACKBOX_GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | RAG embedding model |
| `BLACKBOX_API_KEY` | empty | Optional API key for mutating endpoints |
| `BLACKBOX_USE_POSTGRES` | `false` | Use PostgreSQL for telemetry + checkpoints |
| `BLACKBOX_VAULT_PATH` | `./vault` | Obsidian vault location |
| `BLACKBOX_COST_ALERT_THRESHOLD` | `1.0` | Session cost alert in USD |
| `BLACKBOX_GEMINI_FLASH_DAILY_LIMIT` | `20` | Daily Flash request budget (free tier ~20 RPD) |
| `BLACKBOX_GEMINI_FLASH_INTERACTIVE_RESERVE` | `8` | Calls kept for manual runs; autonomous runs pause below this |

## Production Features

- **Durable checkpoints** — LangGraph state persisted to SQLite (`data/checkpoints.db`) or Postgres
- **Pending approval recovery** — Paused threads survive orchestrator restarts
- **Persistent embedding cache** — Vectors cached in SQLite (`data/embeddings.db`); semantic
  memory rehydrates on restart with zero Gemini calls, and batch embedding
  (`batchEmbedContents`) indexes new content in one API call per ~100 chunks
- **No silent mock output** — Runs fail visibly when no LLM provider is configured;
  closeout notes record which provider produced them, and opted-in mock runs are
  archived as `mock-dry-run`, never as success
- **Append-only archive** — Closeout notes are timestamped per run with thread id;
  they are never overwritten
- **Gemini token/cost tracking** — Real usage metadata from API responses
- **Quota-aware throttling** — Flash and embedding calls are paced independently
  for free-tier RPM limits
- **Daily Flash budget** — Successful Gemini calls are counted per UTC day
  (`data/budget.db`); autonomous runs defer once only the interactive reserve
  remains, with a live meter in the dashboard and `/health`
- **Run history & node traces** — Every run and node event persists to JSONL,
  surfaced via `/api/v1/runs/` and the dashboard Run History card
- **Autonomous runs are visible** — A global event feed streams vault-trigger
  and cron activity into mission control as it happens
- **Incremental vault indexing** — File watcher re-indexes only changed notes;
  triggered skills receive the full content of the note that fired them
- **Path-jailed vault reads** — Prevents directory traversal outside vault root
- **Logs on disk** — Rotating orchestrator log at `data/logs/orchestrator.log`

## Tests

```bash
cd apps/orchestrator
pip install -e ".[dev]"
pytest
```
