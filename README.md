# BLACKBOX — Obsidian-Cortex Agentic OS

A state machine execution environment where Obsidian is the non-volatile state ledger, LangGraph orchestrates agent workflows, and the dashboard is mission control.

## Quick Start

### 1. Infrastructure (Docker)

```bash
docker compose up -d
```

Starts Qdrant (6333), PostgreSQL (5432), and Ollama (11434).

### 2. Orchestrator (Python)

```bash
cd apps/orchestrator
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e .
uvicorn api.main:app --reload --port 8000
```

### 3. Dashboard (Next.js)

```bash
cd apps/dashboard
npm install
npm run dev
```

Open http://localhost:3000

## Architecture

- **vault/** — Obsidian vault with skill definitions, knowledge base, and archive
- **apps/orchestrator/** — FastAPI + LangGraph backend with RAG and WebSocket streaming
- **apps/dashboard/** — Next.js mission control with React Flow graph visualization

## Lead Gen Skill Workflow

1. Click "Execute" on the Lead Gen skill card
2. Orchestrator queries Qdrant for relevant vault context
3. LangGraph runs Planner → Researcher → Writer → Critic
4. If confidence < 0.9, the approval modal blocks execution
5. On completion, a memory closeout note is written to `vault/30-Archive/`
