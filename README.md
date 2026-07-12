# AgentAudit

**A local, governed flight recorder for AI agents.** Every tool call, every denial, every human approval — recorded to a durable log you own, replayable on demand, and forwardable to the SIEM you already run (or a free Loki homelab).

> Built on **BLACKBOX** (`agentic-os`) — a local agent runtime with an MCP driver host, a forced human-in-the-loop approval gate, and a durable event bus. AgentAudit is the audit layer on top: it turns "the agent did something at 02:00" into a line you can grep, replay, and detect on.

`Apache-2.0` · Windows/Linux · Python + SQLite · optional Docker for the homelab SIEM · **257 tests passing, 2 skipped**

---

## Why this exists

When an autonomous agent runs a tool, most stacks keep nothing you could hand to an incident responder. AgentAudit records the run as it happens:

- **What tool** ran, on **which MCP server**, with a **SHA-256 of the arguments** (arguments themselves are redacted by default)
- **Every denial** — a tool the agent tried to call but the allowlist blocked
- **Every approval** — what a human granted or rejected, and when
- A **`correlation_id`** (the LangGraph thread) tying the whole run together

The record is a plain JSONL line and a durable SQLite outbox. No vendor cloud in the path. If you want it in Loki, Elastic, or Splunk, it forwards there too — but the audit trail exists whether or not you ever stand up a SIEM.

---

## What it captures (canonical schema v1.0.0)

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
  "schema_version": "1.0.0",
  "correlation_id": "thread-8892",
  "timestamp_utc": "2026-07-12T09:14:22.041+00:00",
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success"},
  "agent": {"name": "blackbox", "skill_id": "customer_reply"},
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
| **B** | Agent reaches tools via an API proxy / AI gateway you route through | **Partial** — same schema **if** the proxy emits events; you wire it |
| **C** | Unmanaged ChatGPT, Cursor with auto-approve, browser copilots on the same machine | **Not visible.** This is a CASB / secure-web-gateway problem, not an agent-audit one |

**AgentAudit is Tier A remediation — a flight recorder for the agents you govern. It is not a Tier C shadow-AI spy, and it does not replace a CASB.** If your problem is unmanaged copilots, you need network/endpoint policy; this won't catch them and won't pretend to.

---

## Quick start (the audit path)

Local, Gemini for the LLM, no Docker required for L0–L1.

```powershell
# 1. Configure
copy .env.example apps\orchestrator\.env
# Edit apps\orchestrator\.env — set GEMINI_API_KEY, BLACKBOX_OPERATOR_ID, and:
#   BLACKBOX_AUDIT_EXPORT_ENABLED=1
#   BLACKBOX_AUDIT_SINK=file

# 2. Install + start
cd apps\orchestrator
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
cd ..\..
scripts\blackbox.bat start          # detached; waits for health

# 3. Run any governed skill (dashboard at http://127.0.0.1:8000, or the API),
#    then replay it and tail the audit log:
blackbox replay <thread_id>                         # ASCII timeline from events.db
Get-Content apps\orchestrator\data\audit-forward.jsonl -Tail 5
```

You now have an L0 + L1 audit trail. Every governed run is in `events.db` and appended to `audit-forward.jsonl`.

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
Skills / MCP tools
        │
   EventBus  ──►  events.db  (SQLite outbox — system of record, never drops)
        │
   audit_exporter  ──►  file | webhook | Elastic | Splunk   (best-effort forwarders)
```

- **Governed host** (`core/drivers/host.py`) — mounts MCP drivers, enforces per-skill tool allowlists, hashes every tool argument
- **Approval gate** (`core/execution/service.py`) — human-in-the-loop interrupts; grants and denials are audit events
- **Canonical normalizer** (`core/audit/canonical.py`) — bus events → schema v1.0.0
- **Sinks** (`core/audit/sinks.py`, `core/audit/adapters/`) — file, webhook, Elastic ECS, Splunk HEC
- **Replay** (`core/audit/replay.py`) — reconstructs a run timeline from the outbox

---

## Tests

```powershell
cd apps\orchestrator
pip install -e ".[dev]"
pytest -q
```

**257 passing, 2 skipped** (the skips need optional `python-docx` / `pypdf`). Audit coverage lives in `test_agent_audit.py`, `test_replay.py`, `test_audit_sinks.py`.

---

## Examples & extensions

BLACKBOX ships example skills that exercise the governed host — they are **demonstrations of the audit pipeline, not the product**. Each produces the same canonical audit trail as anything else.

- **Document intake** — drop a PDF/DOCX, get a structured summary (`doc_summarize`)
- **Meeting notes → actions** (`summarize_meeting`), **weekly review** (`weekly_review`)
- **Governed email drafting** — read a thread, draft a reply, human approves before anything is written back; nothing auto-sends (`customer_reply`, draft-only, Gmail driver ships disabled)
- **Obsidian vault** as the local knowledge/store surface, with a companion plugin

These live under the skill definitions in `vault/.system/skill-definitions/` and the docs below. If you're here for the flight recorder, you can ignore all of them — they just give you traffic to audit.

Older product framing (SMB/inbox positioning) is retained for reference in [`docs/`](docs/) but is **not** the current direction.

---

## License

Apache-2.0. Contributions, schema feedback, and detection rules welcome — especially from IRT/SOC folks who can tell me where the schema falls short of a real investigation.

<details>
<summary>Advanced / optional — Docker stack, dashboard dev, full env reference</summary>

### Optional services (Docker)

Qdrant, PostgreSQL, and Ollama are optional accelerators — BLACKBOX runs without them on in-memory RAG and SQLite. Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

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
| `BLACKBOX_AUDIT_WEBHOOK_URL` | empty | Generic JSON POST sink |
| `BLACKBOX_AUDIT_ELASTIC_URL` | empty | Elasticsearch cluster URL |
| `BLACKBOX_ELASTIC_API_KEY` | empty | Elastic API key (`id:secret`) |
| `BLACKBOX_AUDIT_SPLUNK_HEC_URL` | empty | Splunk HEC base URL |
| `BLACKBOX_SPLUNK_HEC_TOKEN` | empty | Splunk HEC token |
| `BLACKBOX_COST_ALERT_THRESHOLD` | `1.0` | Session cost alert in USD |
| `BLACKBOX_GEMINI_FLASH_DAILY_LIMIT` | `20` | Daily Flash request budget |
| `BLACKBOX_GMAIL_SEND_ENABLED` | `false` | Phase 4-E: allow `gmail.send_draft` after dogfood gate |

Further docs: [operator guide](docs/blackbox-operator-guide.md) · [Obsidian plugin](apps/obsidian-plugin/README.md) · [compliance Trust-Kit](docs/compliance/README.md) · [session handoff](docs/tomorrow-handoff.md)

</details>
