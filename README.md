# AgentAudit

**Local flight recorder for AI agent tool-use.** Every tool call, every denial, every human approval — hashed, correlated, and stored in a JSONL trail you own. Replay on demand; forward to Loki, Elastic, or Splunk when you want a SIEM.

> **Two tiers:** **Tier A** — governed runs through the built-in host (MCP allowlists + approval gate). **Tier B** — Cursor, Claude Code, Codex CLI, and Antigravity via lifecycle hooks. Same canonical schema either way.

> **Audit stays local by default.** Inference (Ollama, mock, or a cloud key) is a separate choice — the flight recorder does not leave your machine unless you point a sink at a SIEM.

`Apache-2.0` · Windows/Linux · Python + SQLite · optional Docker for homelab SIEM · **233 tests passing**

---

## What's in this repo

| Component | Path | Role |
|-----------|------|------|
| Orchestrator | `apps/orchestrator/` | Audit pipeline, governed host, ingest API |
| Dashboard | `apps/dashboard/` | Flight Recorder + Analytics UI |
| Hook client | `scripts/agentaudit_ingest.py` | Tier B stdin → `POST /api/v1/audit/ingest` |
| Demo skill | `vault/.system/skill-definitions/audit_demo.yaml` | Tier A dogfood without a cloud LLM |
| Driver template | `vault/.system/drivers.json.example` | Copy to `drivers.json` on first boot |

---
## Why this exists

When an autonomous agent runs a tool, most stacks keep nothing you could hand to an incident responder. AgentAudit records the run as it happens:

- **What tool** ran, on **which MCP server**, with a **SHA-256 of the arguments** (arguments themselves are redacted by default)
- **Every denial** — a tool the agent tried to call but the allowlist blocked
- **Every approval** — what a human granted or rejected, and when
- A **`correlation_id`** (the LangGraph thread) tying the whole run together

The record is a plain JSONL line and a durable SQLite outbox. No vendor cloud in the path. If you want it in Loki, Elastic, or Splunk, it forwards there too — but the audit trail exists whether or not you ever stand up a SIEM.

---

## What it captures (canonical schema v1.1.0)

Every governed run emits typed events. The wire format is documented in [`docs/agent-audit-event-schema.md`](docs/agent-audit-event-schema.md).

| Bus topic | `action.type` | Default `action.outcome` |
|-----------|---------------|--------------------------|
| `run/started` | `session_start` | `success` |
| `run/completed` | `session_end` | `success` |
| `run/failed` | `session_end` | `error` |
| `run/terminated` | `session_end` | `denied` |
| `run/approval_required` | `approval_request` | `pending` |
| `run/approval_granted` | `approval_response` | `success` |
| `run/approval_denied` | `approval_response` | `denied` |
| `run/tool_called` | `tool_called` | `success` |
| `run/tool_denied` | `tool_called` | `denied` |
| `driver/mounted` | `config_change` | `success` |
| `driver/failed` | `config_change` | `error` |

One `run/tool_called` line looks like:

```json
{
  "schema_version": "1.1.0",
  "correlation_id": "thread-8892",
  "timestamp_utc": "2026-07-12T09:14:22.041+00:00",
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success"},
  "agent": {"name": "blackbox", "skill_id": "audit_demo"},
  "tool": {"qualified": "vault_fs.read_file", "server": "vault_fs",
           "input_hash": "e3b0c442...b855", "parameters_redacted": true},
  "model": {"id": "gemini-2.5-flash-lite", "provider": "gemini"}
}
```

---

## Adoption ladder

Start at L0. You never have to leave it. Each rung up is optional and independent.

| Level | What you run | Who it's for |
|-------|--------------|--------------|
| **L0** | `events.db` (SQLite outbox) + `blackbox replay <thread_id>` + dashboard | Everyone — works out of the box |
| **L1** | `audit-forward.jsonl` file sink | Solo operators, tinkerers who grep |
| **L2** | Docker **Loki + Grafana** homelab | Learning a SIEM for free |
| **L3** | **Webhook** → Vector / Fluent Bit | Small teams with a pipeline |
| **L4** | **Elastic ECS** + **Splunk HEC** | Enterprise / IRT with existing tooling |

The SQLite outbox is the **system of record** and never drops events. Forwarders (L1–L4) are best-effort on top of it — if your SIEM is down, the outbox still has the full run and `replay` still works.

---

## Coverage — read this before you trust it

AgentAudit records agents that run **through this host's governed pipeline**. It is honest about what it cannot see.

| Tier | Setup | AgentAudit coverage |
|------|-------|---------------------|
| **A** | Agent runs through the BLACKBOX governed host (MCP driver host + approval gate) | **Full** — tool calls, denials, approvals, `correlation_id`, arg hashes |
| **B** | IDE hooks (Cursor, Claude, Codex, Antigravity), MCP proxy, or `POST /api/v1/audit/ingest` | **Partial → full for wired events** — same JSONL schema; see [`docs/external-agent-audit.md`](docs/external-agent-audit.md) |
| **C** | Unmanaged ChatGPT, Cursor with hooks off, browser copilots on the same machine | **Not visible.** CASB / secure-web-gateway territory |

**AgentAudit is Tier A remediation — a flight recorder for the agents you govern. It is not a Tier C shadow-AI spy, and it does not replace a CASB.** If your problem is unmanaged copilots, you need network/endpoint policy; this won't catch them and won't pretend to.

---

## Two pipes: inference vs audit

AgentAudit has two independent data paths. Conflating them is the most common misread, so it's stated plainly:

| | **Pipe 1 — inference** | **Pipe 2 — audit** |
|---|---|---|
| What flows | The prompt/content sent to an LLM to draft, critique, or summarize | Tool calls, denials, approvals, driver mounts |
| Where it goes | Your **chosen provider**: local Ollama, mock, or a cloud API (Gemini) | `events.db` (SQLite outbox) + `audit-forward.jsonl` — **local by default** |
| Leaves the box? | **Only if you choose a cloud provider.** Ollama and mock never leave the machine | **No** — unless you deliberately set a network sink (webhook/Elastic/Splunk) |
| Contains prompts? | Yes — that's the point of the call | **No.** Tool arguments are **hashed**; prompts are not on tool events |

**The audit trail is a separate decision from the inference provider.** You can send prompts to Gemini and still keep an entirely local audit record — or run fully air-gapped with Ollama so neither pipe leaves the box. If you choose Gemini, be honest with yourself: your **prompts** go to Google. Your **audit export** does not.

For a fully local setup, use [`apps/orchestrator/.env.agentaudit-ollama`](apps/orchestrator/.env.agentaudit-ollama).

---

## Installation & Quick Start

You can run AgentAudit entirely locally (Ollama/Mock) or with a cloud LLM (Gemini). **Either way, the audit trail never leaves your machine.**

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- *(Optional)* [Ollama](https://ollama.com/) if you want fully air-gapped local inference.

### 2. Core Setup (One-time)
Open a terminal in the root of the repository:

```powershell
# 1. Setup the Python Orchestrator
cd apps\orchestrator
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.agentaudit-demo .env  # Use the mock profile for zero-setup testing
cd ..\..

# 2. Local driver config (gitignored — copy from committed example)
copy vault\.system\drivers.json.example vault\.system\drivers.json

# 3. Setup the Next.js Dashboard
cd apps\dashboard
npm install
cd ..\..
```

*(Note: To use a real model instead of mock data, edit `apps/orchestrator/.env` and set `BLACKBOX_LLM_PROVIDER=gemini` or `ollama`.)*

### 3. Boot the Flight Recorder
Launch the orchestrator and the dashboard together. This also automatically spawns the background transcript watcher for Antigravity.

```powershell
scripts\start-dev.bat
```
*Your dashboard is now live at [http://localhost:3000](http://localhost:3000).*

### 4. Wire up your IDEs (Tier B Hooks)
To capture events from Cursor, Claude Code, or Codex, you need to install their lifecycle hooks. **You only need to do this once.** Keep the orchestrator (`start-dev.bat`) running, open a new PowerShell window, and run:

```powershell
# Install Cursor hooks (Applies to all workspaces)
powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1

# Install Claude Code hooks
powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1

# Codex CLI: Manually merge adapters/codex/hooks.agentaudit.json into your config,
# making sure to use the ABSOLUTE path to scripts/agentaudit_ingest.py.
```

*(After installing, fully quit and restart Cursor/Claude for the hooks to load).*

### 5. Verify the Connection

```powershell
# Tier B selftest (orchestrator must be running)
python scripts\agentaudit_ingest.py selftest
```

Then in your IDE, ask the agent to read a file or run a simple command. Events should appear in the dashboard **Flight Recorder** tab within a few seconds.
### Forward to a SIEM (optional)

| Sink | Env |
|------|-----|
| **File (default)** | `BLACKBOX_AUDIT_SINK=file` |
| **Webhook** | `BLACKBOX_AUDIT_SINK=webhook` + `BLACKBOX_AUDIT_WEBHOOK_URL=...` |
| **Elastic ECS** | `BLACKBOX_AUDIT_SINK=elastic` + `BLACKBOX_AUDIT_ELASTIC_URL` + `BLACKBOX_ELASTIC_API_KEY` |
| **Splunk HEC** | `BLACKBOX_AUDIT_SINK=splunk` + `BLACKBOX_AUDIT_SPLUNK_HEC_URL` + `BLACKBOX_SPLUNK_HEC_TOKEN` |
| **Several at once** | `BLACKBOX_AUDIT_SINK=file,elastic,splunk` or `all` |

### Free homelab SIEM (L2)

```powershell
docker compose -f docker-compose.loki.yml up -d
# Grafana → http://localhost:3001  (admin / agentaudit)
# Explore: {job="agent-audit"} | json
```

Full walkthroughs and detection rules:

| Stack | Setup | Detections |
|-------|-------|------------|
| **Loki (free)** | [loki-homelab.md](docs/integrations/loki-homelab.md) | [detections-loki.md](docs/integrations/detections-loki.md) |
| **Elastic ECS** | [elastic-ecs.md](docs/integrations/elastic-ecs.md) | [detections-elastic.md](docs/integrations/detections-elastic.md) |
| **Splunk HEC** | [splunk-hec.md](docs/integrations/splunk-hec.md) | [detections-splunk.md](docs/integrations/detections-splunk.md) |
| **Sigma (portable)** | [sigma/README.md](docs/integrations/sigma/README.md) | YAML rules for any Sigma target |

---

## CLI

`scripts\blackbox.bat` (or `blackbox` inside the orchestrator venv):

| Command | What it does |
|---------|--------------|
| `blackbox start` / `stop` / `status` | Run the orchestrator detached; check health, LLM mode, pending approvals |
| `blackbox replay <thread_id>` | ASCII audit timeline for one run, from `events.db` |
| `blackbox export --evidence --from DATE --to DATE` | Tamper-evident batch pack (JSON + SHA-256) → `vault/30-Archive/exports/` |
| `blackbox verify <evidence.json>` | Recompute the integrity hash on an evidence export |
| `blackbox doctor [--fix]` | Preflight: python, vault, portable `drivers.json` paths |
| `blackbox recovery [--resume PATH]` | List stale runs; resume orphans from checkpoint |
| `blackbox logs [-f]` / `backup` / `restore` | Tail logs; snapshot / restore all state stores |

> **Note:** `blackbox export --evidence` is a **batch compliance pack** (its own format, with hashes). The **live audit stream** is the canonical JSONL described above. A dedicated `blackbox export --audit` with a per-run hash chain is on the roadmap, not yet shipped.

---

## Architecture

```
Tier A (governed host)                Tier B (external IDEs)
Skills / MCP tools                    Cursor / Claude / Codex hooks
        │                                      │
   EventBus ──► events.db (SQLite)             POST /audit/ingest
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
              audit-forward.jsonl  ──►  Dashboard (Flight Recorder)
                       │
              file | webhook | Elastic | Splunk  (optional forwarders)
```

- **Governed host** (`core/drivers/host.py`) — mounts MCP drivers, enforces per-skill tool allowlists, hashes every tool argument
- **Approval gate** (`core/execution/service.py`) — human-in-the-loop interrupts; grants and denials are audit events
- **External ingest** (`core/audit/ingest.py`) — normalizes Tier B hook payloads into the same schema
- **Canonical normalizer** (`core/audit/canonical.py`) — bus events → schema v1.1.0
- **Sinks** (`core/audit/sinks.py`, `core/audit/adapters/`) — file, webhook, Elastic ECS, Splunk HEC
- **Replay** (`core/audit/replay.py`) — reconstructs a Tier A run timeline from the outbox
---

## Tests

```powershell
cd apps\orchestrator
pip install -e ".[dev]"
pytest -q
```

**233 passing** (audit coverage in `test_agent_audit.py`, `test_replay.py`, `test_audit_sinks.py`, `test_audit_tail.py`, `test_external_ingest.py`, `test_agentaudit_ingest_client.py`, `test_hook_bootstrap.py`).

---

## Examples & extensions

AgentAudit ships one demo skill — `audit_demo` — to exercise the governed host without a cloud LLM:

- **Tier A:** `audit_demo` reads a vault note via `vault_fs`, hits the human-approval gate, archives — every step lands in the audit trail
- **Tier B:** Cursor, Claude Code, Codex, and Antigravity hooks write the same JSONL schema via `POST /api/v1/audit/ingest`

If you only need external IDE capture, Tier B works standalone. Tier A adds evidence packs, replay, and approval-gated tool governance.

Skill definition: `vault/.system/skill-definitions/audit_demo.yaml`

---

## License

Apache-2.0. Contributions, schema feedback, and detection rules welcome — especially from IRT/SOC folks who can tell me where the schema falls short of a real investigation.

<details>
<summary>Advanced / optional — Docker stack, dashboard dev, full env reference</summary>

### Optional services (Docker)

Qdrant, PostgreSQL, and Ollama are optional — AgentAudit runs without them on SQLite. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).
```bash
cp .env.example .env
# Set GEMINI_API_KEY in .env for the orchestrator service

docker compose up -d --build
```

Open http://localhost:3000 — Docker starts Qdrant, PostgreSQL, Ollama, orchestrator, and dashboard.

Optional Ollama models (if not using Gemini):

```bash
docker exec -it agentic-os-ollama-1 ollama pull llama3.2
docker exec -it agentic-os-ollama-1 ollama pull nomic-embed-text
```

For always-on local use without a separate dashboard dev server, `scripts\serve.bat` builds the dashboard and hosts UI + API from uvicorn on port 8000.

### Environment reference

See `.env.example` for all options. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BLACKBOX_LLM_PROVIDER` | `gemini` | LLM backend: `gemini`, `ollama`, or `mock` |
| `BLACKBOX_ALLOW_MOCK` | `false` | Permit mock fallback when no real provider is available |
| `GEMINI_API_KEY` | — | Google AI Studio API key |
| `BLACKBOX_GEMINI_MODEL` | `gemini-2.5-flash-lite` | Generation model |
| `BLACKBOX_GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2` | RAG embedding model |
| `BLACKBOX_API_KEY` | empty | Optional API key for mutating endpoints |
| `BLACKBOX_USE_POSTGRES` | `false` | Use PostgreSQL for telemetry + checkpoints |
| `BLACKBOX_VAULT_PATH` | `./vault` | Obsidian vault location |
| `BLACKBOX_OPERATOR_ID` | empty | Actor id in canonical audit events |
| `BLACKBOX_AUDIT_EXPORT_ENABLED` | `true` | Enable audit forwarder |
| `BLACKBOX_AUDIT_SINK` | `file` | `file`, `webhook`, `elastic`, `splunk`, comma-separated, or `all` |
| `BLACKBOX_AUDIT_EXPORT_PATH` | `data/audit-forward.jsonl` | JSONL forward file |
| `BLACKBOX_AUDIT_INGEST_ENABLED` | `true` | Accept `POST /api/v1/audit/ingest` (Tier B) |
| `BLACKBOX_AUDIT_LOG_COMMANDS` | `0` | Keep shell command text in Tier B events (see also `BLACKBOX_AUDIT_LOG_FULL_ARGS`) |
| `BLACKBOX_AUDIT_INGEST_URL` | `http://127.0.0.1:8000` | Base URL for hook client selftest |
| `BLACKBOX_AUDIT_WEBHOOK_URL` | empty | Generic JSON POST sink |
| `BLACKBOX_AUDIT_ELASTIC_URL` | empty | Elasticsearch cluster URL |
| `BLACKBOX_ELASTIC_API_KEY` | empty | Elastic API key (`id:secret`) |
| `BLACKBOX_AUDIT_SPLUNK_HEC_URL` | empty | Splunk HEC base URL |
| `BLACKBOX_SPLUNK_HEC_TOKEN` | empty | Splunk HEC token |
| `BLACKBOX_COST_ALERT_THRESHOLD` | `1.0` | Session cost alert in USD |
| `BLACKBOX_GEMINI_FLASH_DAILY_LIMIT` | `20` | Daily Flash request budget |

Further docs: [validation checklist](docs/agentaudit-dogfood-checklist.md) · [Tier B hooks](docs/external-agent-audit.md) · [compliance Trust-Kit](docs/compliance/README.md)
**Audit-only / zero-cloud dogfood:** copy [`apps/orchestrator/.env.agentaudit-demo`](apps/orchestrator/.env.agentaudit-demo) → `.env` — mock LLM, no Gemini. Details: [dependency audit](docs/agentaudit-dependency-audit.md).

</details>
