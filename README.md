<div align="center">

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo/agentmetry-logo-white.svg">
    <img src="docs/logo/agentmetry-logo-black.svg" alt="Agentmetry" width="360" />
  </picture>
</p>

<h1>Agentmetry: SIEM for AI Agents</h1>

<p>The open-source framework and flight recorder for AI agent tool-use. Every tool call, every denial, every human approval — hashed, correlated, and stored in a JSONL trail you own. Replay on demand; forward to Loki, Elastic, or Splunk when you want a SIEM.</p>

<p align="center">
  <a href="https://github.com/blitzcrieg1/agentic-os/blob/master/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
  <a href="https://github.com/blitzcrieg1/agentic-os"><img src="https://img.shields.io/badge/status-public%20alpha-orange?style=for-the-badge" alt="Project status: public alpha"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platform: Windows | Linux">
</p>

</div>

---

> 🚧 **Public Alpha**: We are actively developing the Agentmetry framework. APIs and integration surfaces may evolve rapidly.

---

## Table of Contents

- [Why Agentmetry?](#why-agentmetry)
- [How Agentmetry Works](#how-agentmetry-works)
- [Coverage & Limitations](#coverage--limitations)
- [Install & Quick Start](#install--quick-start)
- [Forwarding to a SIEM](#forwarding-to-a-siem)
- [CLI Reference](#cli-reference)
- [License](#license)

---

## Why Agentmetry?

When an autonomous agent runs a tool, most stacks keep nothing you could hand to an incident responder. Agentmetry records the run as it happens:

- **What tool** ran, on **which MCP server**, with a **SHA-256 of the arguments** (arguments themselves are redacted by default)
- **Every denial** — a tool call the IDE or its permission policy blocked
- **Every approval prompt** — and its outcome (responses are inferred from whether the tool then ran, and explicitly flagged `inferred:*`)
- A **`correlation_id`** (the conversation/session) tying the whole run together

The record is a plain JSONL line and a durable SQLite outbox. No vendor cloud in the path. If you want it in Loki, Elastic, or Splunk, it forwards there too — but the audit trail exists whether or not you ever stand up a SIEM.

---

## How Agentmetry Works

Agentmetry captures agent activity through two paths, normalized into one canonical schema:

```
IDE lifecycle hooks                     MCP stdio proxy
Cursor / Claude / Codex / Antigravity   any MCP client (wraps the server command)
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
              POST /api/v1/audit/ingest
                       ▼
        canonical schema v1.1.0 (MITRE-enriched)
                       ▼
              audit-forward.jsonl  ──►  Dashboard (Flight Recorder)
                       │
              file | webhook | Elastic | Splunk  (optional forwarders + alert webhook)
```

- **Hook client** (`scripts/agentmetry_ingest.py`) — maps IDE lifecycle events (tool use, permission prompts, sessions) to canonical payloads; hashes arguments and scrubs secrets **in the hook process** before anything crosses the wire
- **MCP proxy** (`apps/orchestrator/tools/mcp_audit_proxy.py`) — wraps any stdio MCP server; logs every `tools/call` (and error responses) with a stable per-session correlation id
- **External ingest** (`core/audit/ingest.py`) — normalizes payloads, applies MITRE enrichment, infers approval responses (`inferred:*`), forwards to sinks and the alert webhook
- **Sinks** (`core/audit/sinks.py`, `core/audit/adapters/`) — file, webhook, Elastic ECS, Splunk HEC
- **Replay** (`core/audit/replay.py` / `blackbox replay`) — reconstructs a recorded timeline from the local outbox

### The Canonical Schema

Every run emits typed events. A single `run/tool_called` line looks like:

```json
{
  "schema_version": "1.1.0",
  "correlation_id": "thread-8892",
  "timestamp_utc": "2026-07-12T09:14:22.041+00:00",
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success"},
  "agent": {"name": "cursor", "skill_id": ""},
  "tool": {"qualified": "vault_fs.read_file", "server": "vault_fs",
           "input_hash": "e3b0c442...b855", "parameters_redacted": true,
           "mitre": {"tactic": "TA0007", "technique": "T1005"}},
  "model": {"id": "claude-3-5-sonnet", "provider": "anthropic"}
}
```

---

## Coverage & Limitations

Agentmetry records agents you wire in — **IDE hooks** or the **MCP proxy**. It is honest about what it cannot see.

| Tier | Setup | Agentmetry coverage |
|------|-------|---------------------|
| **A** | MCP servers wrapped with the audit proxy | **Full tool-call capture** — every `tools/call` + error responses, arg hashes, session correlation |
| **B** | IDE hooks (Cursor, Claude, Codex, Antigravity) | Tool calls (success/failure), approval prompts; approve/deny **inferred** from execution and flagged `inferred:*` |
| **C** | Unmanaged ChatGPT, Cursor with hooks off | **Not visible.** CASB / secure-web-gateway territory |

**Agentmetry is a flight recorder for the agents you govern. It is not a Tier C shadow-AI spy, and it does not replace a CASB.** If your problem is unmanaged copilots, you need network/endpoint policy.

---

## Install & Quick Start

You can run Agentmetry entirely locally. The audit trail never leaves your machine unless you explicitly forward it.

### 1. Prerequisites
- **Python 3.10+**
- **Node.js 18+**

### 2. Core Setup (One-time)
Open a terminal in the root of the repository:

```powershell
# 1. Setup the Python Orchestrator
cd apps\orchestrator
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
cd ..\..

# 2. Local driver config
copy vault\.system\drivers.json.example vault\.system\drivers.json

# 3. Setup the Next.js Dashboard
cd apps\dashboard
npm install
cd ..\..
```

### 3. Boot the Flight Recorder
Launch the orchestrator and the dashboard:

```powershell
scripts\start-dev.bat
```
*Your dashboard is now live at [http://localhost:3000](http://localhost:3000).*

### 4. Wire up your IDEs (Tier B Hooks)
To capture events from Cursor, Claude Code, or Codex, install their lifecycle hooks. **You only need to do this once.**

```powershell
# Install Cursor hooks
powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1

# Install Claude Code hooks
powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
```

*(After installing, fully quit and restart Cursor/Claude for the hooks to load).*

### 5. Verify

```powershell
python scripts\agentmetry_ingest.py selftest
```

Events should appear in the dashboard **Flight Recorder** within a few seconds.

---

## Forwarding to a SIEM

Agentmetry provides a flexible adoption ladder. The SQLite outbox is the **system of record** and never drops events. Forwarders are best-effort.

| Sink | Env |
|------|-----|
| **File (default)** | `BLACKBOX_AUDIT_SINK=file` |
| **Webhook** | `BLACKBOX_AUDIT_SINK=webhook` + `BLACKBOX_AUDIT_WEBHOOK_URL=...` |
| **Elastic ECS** | `BLACKBOX_AUDIT_SINK=elastic` + `BLACKBOX_AUDIT_ELASTIC_URL` + `BLACKBOX_ELASTIC_API_KEY` |
| **Splunk HEC** | `BLACKBOX_AUDIT_SINK=splunk` + `BLACKBOX_AUDIT_SPLUNK_HEC_URL` + `BLACKBOX_SPLUNK_HEC_TOKEN` |

For a free homelab SIEM, start Loki and Grafana:

```powershell
docker compose -f docker-compose.loki.yml up -d
# Grafana → http://localhost:3001
# Explore: {job="agentmetry"} | json
```

---

## CLI Reference

`scripts\blackbox.bat` (or `blackbox` inside the orchestrator venv):

| Command | What it does |
|---------|--------------|
| `blackbox start` / `stop` / `status` | Run the orchestrator detached; check health |
| `blackbox replay <thread_id>` | ASCII audit timeline for one run, from `events.db` |
| `blackbox export --evidence` | Tamper-evident batch pack (JSON + SHA-256) |
| `blackbox verify <evidence.json>` | Recompute the integrity hash on an evidence export |
| `blackbox doctor` | Preflight check for python, paths, etc. |

---

## License

Apache-2.0. Contributions, schema feedback, and detection rules welcome!
