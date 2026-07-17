<div align="center">

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo/agentmetry-logo-white.svg">
    <img src="docs/logo/agentmetry-logo-black.svg" alt="Agentmetry" width="360" />
  </picture>
</p>

<h1>Agentmetry: the local flight recorder for AI coding agents</h1>

<p>Records every tool call, denial, and human approval from Cursor, Claude Code, Codex and Antigravity.<br/>
Tags each one with MITRE ATT&CK, correlates sequences into detections, and stores it all in a JSONL trail you own.<br/>
Runs on your machine. Forward to Loki, Elastic, or Splunk only if you want to.</p>

<p align="center">
  <a href="https://github.com/blitzcrieg1/agentmetry/blob/master/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
  <a href="https://github.com/blitzcrieg1/agentmetry"><img src="https://img.shields.io/badge/status-public%20alpha-orange?style=for-the-badge" alt="Project status: public alpha"></a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey?style=for-the-badge" alt="Platform: Windows | Linux">
</p>

<p align="center">
  <a href="#install--quick-start"><strong>Quickstart</strong></a> ·
  <a href="docs/agentmetry-external-ingest.md"><strong>Docs</strong></a> ·
  <a href="docs/agentmetry-event-schema.md"><strong>Schema</strong></a> ·
  <a href="ROADMAP.md"><strong>Roadmap</strong></a> ·
  <a href="#security"><strong>Security</strong></a>
</p>

</div>

<p align="center">
  <img src="docs/assets/dashboard.png" alt="Agentmetry Phase 1 flight recorder: detections strip with CRITICAL credential-exfil alerts, event histogram, live ingest status, and a tool-call feed tagged with MITRE ATT&amp;CK." width="880">
</p>

<p align="center">
  <em>Detections strip, event histogram, and live feed — every tool call tagged with MITRE ATT&amp;CK, with <strong>correlated CRITICAL alerts</strong> when a sequence adds up to an attack.</em>
</p>

---

> 🚧 **Public Alpha**: Core capture, replay, and SIEM forwarding are usable for early exploration. APIs and integration surfaces may evolve rapidly.

---

## Table of Contents

- [Why Agentmetry?](#why-agentmetry)
- [Install & Quick Start](#install--quick-start)
- [How Agentmetry Works](#how-agentmetry-works)
- [Coverage & Limitations](#coverage--limitations)
- [Capabilities & Integrations](#capabilities--integrations)
- [Behavioral Detection Engine](#behavioral-detection-engine)
- [Data Loss Prevention (DLP)](#data-loss-prevention-dlp)
- [Dashboard](#dashboard)
- [Forwarding to a SIEM](#forwarding-to-a-siem)
- [CLI Reference](#cli-reference)
- [Advanced — governed runtime (optional)](#advanced--governed-runtime-optional)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

---

## Why Agentmetry?

When an autonomous agent runs a tool, most stacks keep nothing you could hand to an incident responder. Logs show a process; they do not show **intent**, **session boundaries**, or **what the human approved**.

Agentmetry is the open-source **endpoint flight recorder** for AI agents — built to run entirely on your machine, with optional forwarding to the SIEM you already operate.

> an immutable, operator-owned audit trail for governed AI agents — capturing tool execution at the IDE lifecycle boundary and the MCP wire, not in a vendor cloud

We do that by:

- **Intercepting** agent tool calls through IDE lifecycle hooks (Cursor, Claude Code, Codex, Antigravity) and an MCP stdio audit proxy
- **Normalizing** every event into a canonical schema v1.1.0 with MITRE ATT&CK enrichment and SHA-256 argument hashing
- **Detecting** correlated behavioral sequences a single event cannot reveal (credential exfil, guardrail bypass, download cradles, agent data injection, recon-then-grab)
- **Blocking** secrets and PII at the hook boundary with a local regex DLP engine (`log` or `block` mode)
- **Forwarding** the same JSONL trail to Loki, Elastic ECS, Splunk HEC, or a generic webhook — without making the cloud the system of record

**Agentmetry is not a CASB or shadow-AI spy.** It records the agents you wire in. If your problem is unmanaged ChatGPT in the browser, you need network/endpoint policy — not a flight recorder.

---

## Install & Quick Start

Agentmetry runs fully locally. The audit trail never leaves your machine unless you explicitly forward it.

### See it catch something first (30 seconds)

No server, no API key, no config. Clone and run:

```bash
git clone https://github.com/blitzcrieg1/agentmetry.git && cd agentmetry
pip install -r apps/orchestrator/requirements.txt
python scripts/demo.py
```

It replays an agent session through the real ingest API: the agent reads an SSH
private key, runs a command containing an AWS key, then fetches a URL. Agentmetry
tags each call with MITRE ATT&CK, catches the AWS key with DLP (storing the rule,
never the value), and then — without being asked — **correlates the key read with
the network call and fires a `CRITICAL` credential-exfil detection.**

<p align="center">
  <img src="docs/assets/demo.gif" alt="Terminal replay: an agent reads an SSH private key and an AWS key, then fetches a URL; Agentmetry tags each call with MITRE ATT&CK, flags the AWS key with DLP without storing it, and fires a CRITICAL credential-exfil detection." width="760">
</p>

No single one of those events is an alert. The sequence is. That is the whole
product in one screen.

### See the dashboard with a story in it

```bash
python scripts/demo_dashboard.py            # seeds 7 sessions + 5 detections, serves http://127.0.0.1:8010/
python scripts/demo_dashboard.py --live     # ...and streams synthetic agent traffic in real time
```

One command seeds a realistic demo trail and serves the dashboard locally — no
API key, no cloud. The detections strip surfaces CRITICAL findings; the feed
shows approval gates, tool calls, and inline detection events:

<p align="center">
  <img src="docs/assets/dashboard-detection.png" alt="Agentmetry flight recorder with DETECTIONS strip showing CRITICAL credential-exfil alerts and the event feed highlighting detection rows, SSH key reads, and network egress." width="900">
</p>

See the [dashboard tour](docs/dashboard-tour.md) for what each view shows and how
to read it.

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 18+ (dashboard only) |

### Windows one-flow install

From a fresh clone on Windows 11:

```powershell
git clone https://github.com/blitzcrieg1/agentmetry.git
cd agentmetry
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
scripts\start-dev.bat
```

`install.ps1` creates the orchestrator venv, installs Python + dashboard deps, copies `.env.example`, wires Cursor and Claude hooks, and runs `agentmetry doctor`. Skip hooks with `-SkipHooks`; orchestrator-only with `-SkipDashboard`.

### Manual install

```powershell
git clone https://github.com/blitzcrieg1/agentmetry.git
cd agentmetry

# Python orchestrator
cd apps\orchestrator
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
cd ..\..

# Next.js dashboard
cd apps\dashboard
npm install
cd ..\..
```

### 2. Boot the flight recorder

```powershell
scripts\start-dev.bat
```

Dashboard → [http://localhost:3000](http://localhost:3000) · Orchestrator API → [http://localhost:8000](http://localhost:8000)

### 3. Wire your IDEs (one-time)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
```

Fully quit and restart Cursor / Claude Code so hooks load.

### 4. Verify

```powershell
python scripts\agentmetry_ingest.py selftest
```

Events should appear in the dashboard **Flight Recorder** within a few seconds.

When an agent runs a tool, Agentmetry automatically:

1. **Intercepts** the lifecycle hook or MCP `tools/call` before arguments leave the hook process
2. **Hashes** tool arguments (SHA-256) and scrubs inline secrets in command strings
3. **Enriches** each event with MITRE tactic/technique mappings and session correlation
4. **Stores** canonical JSONL locally (`audit-forward.jsonl`) — the system of record for the hook path; each new line is hash-chained for tamper detection
5. **Detects** multi-step behavioral patterns across the session timeline
6. **Forwards** to your SIEM sinks and alert webhook (optional, best-effort)

Verify the local trail after capture:

```powershell
agentmetry verify --trail apps\orchestrator\data\audit-forward.jsonl
```

**What the chain does and does not prove.** Verification catches in-place edits, inserted or reordered lines, and forged appends, and it cross-checks the `.chain` sidecar to catch a truncated file. It cannot, by itself, prove the newest lines were not deleted along with the sidecar: any actor with full write access to the trail can also rewrite the sidecar. For that, `verify` prints the current chain head (sequence number plus SHA-256). Record it somewhere the audited agent cannot write (a git commit, a note, a password manager entry) and compare on the next verify.

---

## How Agentmetry Works

### Architecture

```mermaid
flowchart TB
  subgraph Capture["Capture Layer (Tier A + B)"]
    HOOKS["IDE Lifecycle Hooks<br/>Cursor · Claude · Codex · Antigravity"]
    PROXY["MCP Audit Proxy<br/>mcp_audit_proxy.py"]
  end

  subgraph Gate["Local Security Gate"]
    DLP["DLP Scanner<br/>regex rules"]
    HASH["Arg Hash + Secret Scrub"]
  end

  subgraph Core["Orchestrator :8000"]
    INGEST["POST /api/v1/audit/ingest"]
    CANON["Canonical Schema v1.1.0<br/>MITRE enrichment"]
    DETECT["Sequence Detection Engine"]
    TRAILDB[("SQLite trail index<br/>audit.db")]
  end

  subgraph Output["Outputs"]
    JSONL["audit-forward.jsonl"]
    DASH["Dashboard<br/>Flight Recorder + Analytics"]
    SIEM["Loki · Elastic · Splunk · Webhook"]
  end

  HOOKS --> DLP
  PROXY --> DLP
  DLP -->|allow| HASH
  DLP -->|deny| INGEST
  HASH --> INGEST
  INGEST --> CANON
  CANON --> TRAILDB
  CANON --> JSONL
  CANON --> DETECT
  JSONL --> DASH
  JSONL --> SIEM
```

### Capture paths

```mermaid
flowchart LR
  subgraph TierB["Tier B — IDE Hooks"]
    C["Cursor"]
    CL["Claude Code"]
    AG["Antigravity"]
    CX["Codex"]
  end

  subgraph TierA["Tier A — MCP Proxy"]
    MCP["Any MCP Client"]
    WRAP["Audit Proxy wraps server command"]
  end

  INGEST["agentmetry_ingest.py → /audit/ingest"]

  C --> INGEST
  CL --> INGEST
  AG --> INGEST
  CX --> INGEST
  MCP --> WRAP --> INGEST
```

| Component | Path | Role |
|-----------|------|------|
| **Hook client** | `scripts/agentmetry_ingest.py` | Maps IDE lifecycle events to canonical payloads; hashes args in-process |
| **MCP proxy** | `apps/orchestrator/tools/mcp_audit_proxy.py` | Wraps any stdio MCP server; logs every `tools/call` + errors |
| **Ingest API** | `core/audit/ingest.py` | Normalizes payloads, infers approvals (`inferred:*`), writes sinks |
| **DLP engine** | `core/audit/dlp/` | Regex scan of tool arguments (validators, e.g. Luhn); block or log before execution |
| **Detection engine** | `core/audit/detection/` | Correlated sequence rules over a session's event timeline |
| **Sinks** | `core/audit/sinks.py` | File, webhook, Elastic ECS, Splunk HEC |
| **Replay** | `core/audit/replay.py` | ASCII timeline reconstruction from the local outbox |

### The canonical event

Every run emits typed, SIEM-ready JSON. A single `tool_called` line:

```json
{
  "schema_version": "1.1.0",
  "correlation_id": "thread-8892",
  "timestamp_utc": "2026-07-12T09:14:22.041+00:00",
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success"},
  "agent": {"name": "cursor", "skill_id": ""},
  "tool": {
    "qualified": "vault_fs.read_file",
    "server": "vault_fs",
    "input_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "parameters_redacted": true,
    "mitre": {"tactic": "Collection (TA0009)", "technique": "Data from Local System (T1005)"}
  },
  "model": {"id": "claude-3-5-sonnet", "provider": "anthropic"}
}
```

Full schema → [docs/agentmetry-event-schema.md](docs/agentmetry-event-schema.md)

---

## Coverage & Limitations

Agentmetry records agents you wire in — **IDE hooks** or the **MCP proxy**. It is honest about what it cannot see.

| Tier | Setup | Agentmetry coverage |
|------|-------|---------------------|
| **A** | MCP servers wrapped with the audit proxy | **Full tool-call capture** — every `tools/call` + error responses, arg hashes, session correlation |
| **B** | IDE hooks (Cursor, Claude, Codex, Antigravity) | Tool calls (success/failure), approval prompts; approve/deny **inferred** from execution and flagged `inferred:*` |
| **C** | Unmanaged ChatGPT, Cursor with hooks off | **Not visible.** CASB / secure-web-gateway territory |

---

## Capabilities & Integrations

| | |
| --- | --- |
| 🎥 **Flight Recorder** | Live audit tail with dynamic columns, drag-and-drop layout, CSV export, and session drill-down |
| 📊 **Analytics & Process Tree** | Session-level charts, MITRE tactic breakdown, horizontal React Flow timeline |
| 🔍 **Behavioral Detection** | Correlated sequence rules: credential exfil, guardrail bypass, download cradles, agent data injection, supply-chain merges |
| 🛡️ **Local DLP** | Regex scanner blocks AWS keys, GitHub tokens, Slack tokens, and PII before tool execution |
| 🎯 **MITRE ATT&CK mapping** | Per-tool tactic/technique tags on every canonical event |
| 🔐 **Argument hashing** | SHA-256 of tool args by default — plaintext never crosses the wire from hooks |
| 📡 **SIEM-native export** | Elastic ECS, Splunk HEC, Loki/LogQL, generic webhook, alert webhook on denials |
| 🔁 **Replay & evidence** | ASCII session timeline + tamper-evident evidence pack export |
| 👥 **Multi-IDE support** | Cursor, Claude Code, Codex, Antigravity — global hook install scripts |

### Integrations

| Category | Supported today | Roadmap |
| -------- | --------------- | ------- |
| **IDE / Agent hosts** | Cursor · Claude Code · Codex · Antigravity | Windsurf · VS Code Copilot |
| **Agent frameworks** | [CrewAI](adapters/crewai/) · [OpenSRE](adapters/opensre/) | LangChain · AutoGen |
| **MCP transport** | Stdio audit proxy (wrap any MCP server command) | SSE / streamable HTTP proxy |
| **Observability / SIEM** | Loki · Grafana · Elastic ECS · Splunk HEC · generic webhook | Datadog · New Relic |
| **Detection formats** | In-engine sequence rules · LogQL · Elastic · Splunk · [Sigma pack](docs/integrations/sigma/README.md) | STIX/TAXII export |
| **Policy engines** | Regex DLP manifest (`policies/dlp/`) | OPA / Rego policy-as-code |
| **Compliance docs** | [ISO 42001 mapping](docs/compliance/iso-42001-mapping.md) · [AI Act checklist](docs/compliance/ai-act-deployer-checklist.md) | SOC 2 evidence templates |

Agentmetry is community-built. Browse [open issues](https://github.com/blitzcrieg1/agentmetry/issues) or the [roadmap](ROADMAP.md).

---

## Behavioral Detection Engine

Per-event MITRE tags say *what* a single tool call is. The detection engine says what a **sequence** of calls means — the signal an EDR cannot see because it never had the agent's session boundary.

Rules run **as events arrive**. A firing rule is emitted once per session as a first-class canonical event (`action.type: detection`, `action.outcome: <severity>`) down the same sinks as everything else — so it reaches your SIEM, your alert webhook, and the live feed without anyone opening a dashboard. The same findings are recomputed from the trail on `GET /audit/detections/{correlation_id}`.

> **Alpha limitation.** Live detection checkpoint state persists in SQLite across orchestrator restarts (emitted rules and session windows are not re-fired). Detection state is still per-process and not shared across multiple orchestrator instances. The JSONL trail stays authoritative — every detection can be recomputed on query via `GET /audit/detections/{correlation_id}`.

```mermaid
sequenceDiagram
  participant IDE as IDE / MCP Proxy
  participant IN as Ingest API
  participant DB as JSONL Outbox
  participant ENG as Detection Engine
  participant API as GET /audit/detections/{id}

  IDE->>IN: tool_called / approval_response / session_end
  IN->>DB: append canonical event
  Note over ENG: Rules run over time-ordered session events
  ENG->>ENG: credential-exfil
  ENG->>ENG: approval-denied-then-executed
  ENG->>ENG: encoded-command-download
  ENG->>ENG: pr-merged-without-review
  ENG->>ENG: untrusted-input-then-risky-action
  ENG->>ENG: destructive-delete-burst
  ENG->>ENG: autonomous-unapproved-write
  ENG->>ENG: discovery-then-collect
  API->>DB: load events for correlation_id
  API->>ENG: run_detections(events)
  ENG-->>API: ranked Detection list
```

| Rule ID | Severity | Pattern |
| ------- | -------- | ------- |
| `credential-exfil` | critical | Credential access (T1552) → network egress (TA0011) |
| `approval-denied-then-executed` | critical | Human denied a gated tool → same tool executed successfully later |
| `encoded-command-download` | critical | Remote code fetched and executed: a raw-IP download, or a fetch piped into an interpreter (`curl … \| bash`). T1105, plus T1027 when base64-encoded |
| `pr-merged-without-review` | critical | A pull request merged with no preceding read of its diff (T1195.002) |
| `autonomous-unapproved-write` | high | Autonomous agent writes/deletes with no prior human approval |
| `untrusted-input-then-risky-action` | high | Session ingested externally-authored content (a GitHub issue, a fetched page) → then performed a risky action |
| `destructive-delete-burst` | high | 5+ deletions in one session, by technique or command (`rm -rf`) |
| `discovery-then-collect` | medium | Filesystem recon burst (TA0007) → data collection |
| `off-hours-activity` | medium | Unscheduled autonomous impact action outside business hours. **Opt-in** (`AGENTMETRY_DETECT_OFF_HOURS=1`) with an operator-set window; scheduled jobs excluded |

Query detections for a session:

```http
GET /api/v1/audit/detections/{correlation_id}
X-API-Key: <optional>
```

### Agent Data Injection

[*Agent Data Injection Attacks are Realistic Threats to AI Agents*](https://arxiv.org/abs/2607.05120)
(Choi et al., July 2026) demonstrates remote code execution and supply-chain
compromise against **Claude Code, Codex, Gemini CLI and Antigravity**. ADI hides
malicious data inside content an agent already trusts, such as a GitHub issue
comment carrying forged author metadata, so the agent runs an attacker's command
believing it came from a maintainer.

The paper tested model hardening, input guardrails, alignment output guardrails,
plan-then-execute, sandboxing and dual-LLM. All of them fail on ADI, for a
reason worth quoting:

> ADI "corrupts only the data the agent acts on, leaving the agent's task
> aligned with the user prompt."

Nothing about the request looks wrong. The agent is doing what you asked. When
the prompt looks clean and the guardrails pass, the agent's **behaviour** is the
only evidence left, which is the layer Agentmetry works at. Both published
chains are sequences of tool calls, and both are detected:

| Paper | Chain | Fires |
|-------|-------|-------|
| §4.2 RCE via origin injection | `gh issue view` → attacker's command | `encoded-command-download` + `untrusted-input-then-risky-action` |
| §4.3 Supply chain via tool-response injection | `gh pr view` → merge, diff never read | `pr-merged-without-review` |

**To be clear about the boundary: Agentmetry does not prevent ADI, and nothing
here should be read as claiming otherwise.** Prevention requires isolating
trusted from untrusted data inside the agent, which is the paper's own
conclusion and is not something a recorder can do. We detect the consequence.

---

## Data Loss Prevention (DLP)

Agentmetry ships a local regex DLP engine that scans tool arguments **before** they are executed or logged. When a match fires in `block` mode, the hook denies execution and emits a `tool_denied` event.

```mermaid
flowchart LR
  HOOK["Pre-tool hook"] --> SCAN["DLP Scanner<br/>policies/dlp/manifest.yaml"]
  SCAN -->|match + block| DENY["tool_denied<br/>reason: dlp:rule_id"]
  SCAN -->|pass| EXEC["Tool executes + audit log"]
  SCAN -->|match + log| WARN["Audit + allow<br/>(observe mode)"]
```

| Env | Default | Description |
| --- | ------- | ----------- |
| `AGENTMETRY_DLP_MODE` | `log` | `log` · `block` · `disable` |
| `AGENTMETRY_DLP_PII` | `1` | Enable PII rules (SSN, etc.) |
| `AGENTMETRY_DLP_RULES_PATH` | `policies/dlp/manifest.yaml` | Custom rule manifest |

Rules cover AWS keys, GitHub PATs, Slack tokens, bearer headers, private keys, and US SSN patterns. Add custom regex rules without touching Python — drop entries into the manifest.

### Tool allow/deny policy

Structural tool policy runs **before** DLP at the hook boundary. Deny rules match tool names (glob) and optional shell command regex.

| Env | Default | Description |
| --- | ------- | ----------- |
| `AGENTMETRY_TOOL_POLICY_MODE` | `log` | `log` · `block` · `disable` |
| `AGENTMETRY_TOOL_POLICY_PATH` | `policies/tool/manifest.yaml` | Custom allow/deny manifest |

In `block` mode, a matching deny rule returns `permission: deny` to the IDE hook (same path as DLP block).

---

## Dashboard

The Next.js dashboard at `:3000` gives SOC analysts a live view of agent activity:

| View | Features |
| ---- | -------- |
| **Flight Recorder** | Real-time event tail, detections strip, event histogram, color-coded source badges (Cursor, Claude, Codex, Antigravity), outcome filters, split-pane inspector, CSV/JSONL export |
| **Column manager** | Drag-and-drop column layout featuring built-in fields for model, skill, host, MCP server, and failure reasons — reorder or hide via the Columns settings panel |
| **Analytics** | Outcome distribution, MITRE tactic chart, session ID search |
| **Process Tree** | Horizontal React Flow timeline of events within a selected session |

Dark mode supported with theme toggle. Logo and panels adapt automatically.

---

## Forwarding to a SIEM

For agents captured via IDE hooks (the common case), the canonical JSONL trail is the **system of record**; `audit.db` indexes the same events for fast dashboard queries. Forwarders are best-effort.

| Sink | Env |
|------|-----|
| **File (default)** | `AGENTMETRY_AUDIT_SINK=file` — hash-chained JSONL (`agentmetry verify --trail`) |
| **Webhook** | `AGENTMETRY_AUDIT_SINK=webhook` + `AGENTMETRY_AUDIT_WEBHOOK_URL=...` |
| **Elastic ECS** | `AGENTMETRY_AUDIT_SINK=elastic` + `AGENTMETRY_AUDIT_ELASTIC_URL` + `AGENTMETRY_ELASTIC_API_KEY` |
| **Splunk HEC** | `AGENTMETRY_AUDIT_SINK=splunk` + `AGENTMETRY_AUDIT_SPLUNK_HEC_URL` + `AGENTMETRY_SPLUNK_HEC_TOKEN` |
| **Alert webhook** | `AGENTMETRY_AUDIT_ALERT_WEBHOOK_URL=...` (fires on denied/error outcomes) |


Homelab SIEM with Loki + Grafana:

```powershell
docker compose -f docker-compose.loki.yml up -d
# Grafana → http://localhost:3001
# Explore: {job="agentmetry"} | json
```

Integration guides → [docs/integrations/](docs/integrations/)

---

## CLI Reference

`scripts\agentmetry.bat` (or `python -m cli` inside the orchestrator venv):

| Command | What it does |
|---------|--------------|
| `scripts\install.ps1` | Windows one-flow: venv, dashboard deps, IDE hooks, doctor |
| `agentmetry start` / `stop` / `status` | Run the orchestrator detached; check health |
| `agentmetry replay <thread_id>` | ASCII audit timeline for one run, from `events.db` |
| `agentmetry export --evidence` | Tamper-evident batch pack (JSON + SHA-256) |
| `agentmetry verify <evidence.json>` | Recompute the integrity hash on an evidence export |
| `agentmetry verify --trail <audit-forward.jsonl>` | Verify JSONL hash chain (tamper detection on file sink) |
| `agentmetry doctor` | Preflight check for python, paths, etc. |

`scripts\agentmetry.bat` remains as a legacy alias.

---

## Advanced — governed runtime (optional)

The README above describes the **SIEM flight recorder** (hooks → JSONL → dashboard). The same repo also ships an optional **Obsidian + LangGraph** skill runtime with vault-defined skills and approval gates — useful for governed demos, not required for IDE hook capture.

See **[docs/advanced-governed-runtime.md](docs/advanced-governed-runtime.md)** for when to use hook JSONL vs vault skills, and how to avoid mixing compliance narratives.

---

## Contributing

Agentmetry welcomes contributions across detection rules, DLP patterns, SIEM adapters, and dashboard UX.

| Area | Start here |
| ---- | ---------- |
| Hook adapters | [docs/agentmetry-external-ingest.md](docs/agentmetry-external-ingest.md) |
| Framework adapters | [adapters/crewai/](adapters/crewai/) |
| Event schema | [docs/agentmetry-event-schema.md](docs/agentmetry-event-schema.md) |
| Detection rules | `apps/orchestrator/core/audit/detection/rules.py` |
| DLP rules | `policies/dlp/manifest.yaml` |
| Sigma pack | [docs/integrations/sigma/README.md](docs/integrations/sigma/README.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |

Run tests before opening a PR — see [CONTRIBUTING.md](CONTRIBUTING.md). **All PRs require a signed [CLA](CLA.md)** (v1.0).

---

## Security

Agentmetry is designed for security-sensitive environments:

- **Local-first** — audit data stays on your machine unless you configure forwarders
- **Argument hashing by default** — plaintext tool args never leave the hook process
- **Optional API key** — protect ingest/tail/export endpoints with `AGENTMETRY_API_KEY`
- **DLP blocking** — stop secrets and PII from reaching tool execution boundaries
- **Tamper-evident exports** — evidence packs include SHA-256 integrity hashes

Report vulnerabilities via GitHub Issues with the `security` label, or open a private security advisory on the repository.

Compliance docs → [docs/compliance/](docs/compliance/)

---

## License

Apache-2.0 — Copyright 2026 blitzcrieg1. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Contributors sign the [Individual CLA (v1.0)](CLA.md); companies use [CCLA.md](CCLA.md).
Trademark policy: [TRADEMARK.md](TRADEMARK.md). Commercial intent (non-binding):
[COMMERCIAL.md](COMMERCIAL.md).

---

## Maintainer

Built and maintained by Ioannis L. — connect on [LinkedIn](https://www.linkedin.com/in/ioannis-l-074439194/).
