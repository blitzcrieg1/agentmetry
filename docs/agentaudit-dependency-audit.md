# AgentAudit — dependency audit (post-pivot)

**What you actually need to run, demo, and dogfood AgentAudit today — vs legacy baggage from the Obsidian back-office vision.** Repo `agentic-os`, HEAD `c00171b`, 257 tests.

**Load-bearing insight (drives everything below):** the audit trail is emitted by the **governed host** — `run/tool_called`, `run/tool_denied`, `run/approval_*`, `driver/mounted` all fire from `core/drivers/host.py` and `core/execution/service.py`, normalized by `core/audit/canonical.py`, forwarded by `core/bus/audit_exporter.py`. **None of that depends on an LLM.** The LLM only drives the *content* nodes (draft/critic/research) inside a skill. So the flight recorder runs even when the LLM is mock, Ollama, or absent — as long as the run reaches tool calls and the approval gate.

---

## 1 — Do I still need Gemini *now*?

| Scenario | Need Gemini? | Why |
|----------|--------------|-----|
| **A) Dogfood audit only** (run skills, verify JSONL/replay) | **No** | Use `BLACKBOX_LLM_PROVIDER=mock` + `BLACKBOX_ALLOW_MOCK=1`. The skill still calls `vault_fs.read_note` (→ `tool_called` event) and still hits the approval gate (→ `approval_granted/denied`). Draft content is a `mock-dry-run` placeholder — irrelevant to the audit trail. Zero cloud calls. |
| **B) Demo Loom** with `customer_reply` | **Recommended (yes)** | The audit events fire either way, but a `mock-dry-run` placeholder draft looks fake on camera. A real draft (Gemini *or* Ollama) makes the demo credible. You already have paid Gemini working (budget 3/100000) — use it; it's the lowest-friction path to a believable draft. |
| **C) Inspect existing trail** (replay/export, no new runs) | **No** | `blackbox replay` and the export read `events.db` only. Pure local read. No LLM, no network. |
| **D) CI / tests** (`pytest`) | **No** | `conftest.py` blanks the key and enforces mock; a real key is never allowed in tests (this was a past quota-burn bug, now guarded). |
| **E) OSS user, flight recorder + Ollama** | **No** | Ollama satisfies the LLM content nodes locally. The whole L0–L4 audit story works with zero cloud. This is the "your data never leaves the box" pitch — keep it true. |

**Recommended default for you (solo, Greece, 15h/week):** **Gemini for the Loom, mock for routine dogfood.** You have Gemini paid + working, so don't add Ollama friction for the one credible-draft demo. But for day-to-day "did the audit trail capture X" checks, run `mock` and spend nothing. Document **Ollama** as the OSS-user path in the README (you don't need it yourself).

> **Practical consequence:** tonight's dogfood does **not** have to spend Gemini. If you want to prove the audit layer on mock and save the real-draft run for the actual Loom take, that's the cleaner split.

---

## 2 — Minimal runtime for the AgentAudit story

### Minimal (audit-first demo)

```
        ┌─────────────────────────────────────────────┐
        │  uvicorn api.main  (single process)          │
        │                                              │
        │   EventBus ─► events.db  (SQLite outbox)     │
        │        │         (system of record)          │
        │        └─► audit_exporter ─► audit-forward.jsonl
        │                                              │
        │   Governed host: 1 MCP driver (vault_fs)     │
        │   Approval gate (HITL)                       │
        │   LLM provider = mock  (or ollama)           │
        └─────────────────────────────────────────────┘
                  │
          blackbox replay <thread_id>   (reads events.db)
```

**Processes that must run:** one — `uvicorn api.main` (via `blackbox start`).
**Env required:** `BLACKBOX_OPERATOR_ID`, `BLACKBOX_AUDIT_EXPORT_ENABLED=1`, `BLACKBOX_AUDIT_SINK=file`, `BLACKBOX_LLM_PROVIDER=mock`, `BLACKBOX_ALLOW_MOCK=1`, `BLACKBOX_VAULT_PATH`.
**Disabled/absent:** Qdrant, PostgreSQL, dashboard, Obsidian app, Gmail, search, Telegram, all cloud LLM.

### Full (current repo, with examples)

```
  Next.js dashboard ──► uvicorn api.main ──► EventBus ─► events.db
   (mission control)         │                    └─► audit sinks (file/webhook/elastic/splunk)
                             │
      MCP drivers: vault_fs, margin, docs [+ gmail/search/shell if enabled]
      LLM: Gemini (cloud)  ──────────────── embeddings ─► Qdrant (semantic RAG)
      Checkpoints/telemetry: SQLite (or PostgreSQL)
      Obsidian vault + plugin (approve UX)
   Separate: docker-compose.loki.yml (Grafana/Loki/Alloy) for L2 SIEM
```

### `AGENTAUDIT_DEMO=1` — build it or document it?

**Document it. Do not build a mode.** A `BLACKBOX_MINIMAL`/`AGENTAUDIT_DEMO` flag is another code path that needs test coverage (your 257 tests would need minimal-mode variants), another branch to keep green, for a solo dev at 15h/week. A committed **`.env.agentaudit-demo` profile** (Profile A below) + a README paragraph achieves the identical outcome with zero code and zero maintenance. Ship the profile, skip the flag. Revisit only if OSS users file issues asking "how do I run just the recorder" more than a couple times.

---

## 3 — Dependency tier table

| Dependency | Used for | Tier | Notes |
|------------|----------|------|-------|
| **SQLite** | Outbox (SoR), checkpoints, telemetry, budget, embed cache | **Essential** | The audit trail *is* `events.db`. Non-negotiable. |
| **LangGraph + MCP** | Governed execution + tool host | **Essential** | Every audit event originates here. |
| **Vault directory** (`vault/`) | Skill YAML, SOPs, archive, tool target | **Essential (runtime)** | The *folder* is required; **Obsidian the app is not** (see below). |
| **Python stack** (FastAPI/httpx/pydantic) | Orchestrator | **Essential** | `pyproject.toml`. |
| **Gemini API** | LLM content nodes | **Recommended** | Needed for realistic draft in the Loom; replaceable by Ollama/mock for audit. Not required by the recorder. |
| **Ollama** | Local LLM alternative | **Recommended (OSS story)** | The "no cloud" path for OSS users; optional for you. |
| **Next.js dashboard** | Approval UX, telemetry | **Recommended (demo)** | Great on camera; approvals also work via API/plugin. Optional for headless audit. |
| **`docker-compose.loki.yml`** | Homelab SIEM (L2) | **Optional** | Only for the "plugs into a SIEM" demo beat. Cut if it doesn't come up clean. |
| **Qdrant** | Semantic RAG | **Optional** | Degrades to FTS5 + in-memory. Irrelevant to audit. |
| **PostgreSQL** | Checkpoints/telemetry at scale | **Optional** | SQLite is the default and is enough. |
| **Elastic / Splunk env** | Enterprise sinks (L4) | **Optional** | Only when `BLACKBOX_AUDIT_SINK` includes them. |
| **Obsidian app + plugin** | Approve UX in Obsidian | **Legacy / demote** | Dashboard covers approvals. Keep plugin in `apps/` but demote in docs; not part of the AgentAudit story. |
| **Gmail OAuth** | `customer_reply` email demo | **Legacy / demote** | Example-only. Dogfood/demo with `vault_fs` tool calls instead — no Gmail needed. |
| **Main `docker-compose.yml`** (Qdrant/PG/Ollama/dashboard) | Full stack convenience | **Legacy / demote** | Not needed for audit. The *Loki* compose is the only one the AgentAudit story references. |
| **Search API keys** (Serper/Tavily) | `kbeauty_*`/`supplier_research` skills | **Remove candidate (future)** | Path B vertical residue. Keep skills as examples; drop from any AgentAudit doc. |
| **Telegram** | Channel adapter | **Remove candidate (future)** | Ships disabled, zero relevance to a flight recorder. Candidate to move to `examples/` or delete. |

---

## 4 — Three `.env` profiles

### Profile A — "Audit dogfood" (you, tonight — zero cloud spend)

```text
# --- audit layer (the product) ---
BLACKBOX_OPERATOR_ID=home-lab
BLACKBOX_AUDIT_EXPORT_ENABLED=1
BLACKBOX_AUDIT_SINK=file
# BLACKBOX_AUDIT_EXPORT_PATH defaults to data/audit-forward.jsonl

# --- runtime, no cloud ---
BLACKBOX_LLM_PROVIDER=mock
BLACKBOX_ALLOW_MOCK=1
BLACKBOX_VAULT_PATH=../../vault
BLACKBOX_STARTUP_VAULT_INDEX=false

# No GEMINI_API_KEY needed. Dashboard optional (approve via http://127.0.0.1:8000).
# Committed profile: apps/orchestrator/.env.agentaudit-demo
```
Generates real `tool_called` + `approval_*` audit events with a placeholder draft. Verify JSONL/replay with no Gemini calls.

### Profile B — "Loom demo" (credible draft on camera)

```text
# audit layer
BLACKBOX_OPERATOR_ID=home-lab
BLACKBOX_AUDIT_EXPORT_ENABLED=1
BLACKBOX_AUDIT_SINK=file

# real draft content — pick ONE:
BLACKBOX_LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
# --- or fully local ---
# BLACKBOX_LLM_PROVIDER=ollama

BLACKBOX_VAULT_PATH=../../vault
# Dashboard ON for the approval-click beat. Loki optional.
```

### Profile C — "Enterprise SIEM" (OSS user forwarding to Elastic + Splunk)

```text
BLACKBOX_OPERATOR_ID=soc-host-01
BLACKBOX_AUDIT_EXPORT_ENABLED=1
BLACKBOX_AUDIT_SINK=file,elastic,splunk

BLACKBOX_AUDIT_ELASTIC_URL=https://elastic.internal:9200
BLACKBOX_AUDIT_ELASTIC_INDEX=logs-agentaudit
BLACKBOX_ELASTIC_API_KEY=id:secret
BLACKBOX_AUDIT_SPLUNK_HEC_URL=https://splunk.internal:8088
BLACKBOX_SPLUNK_HEC_TOKEN=<hec-token>

BLACKBOX_LLM_PROVIDER=ollama       # or gemini; content provider is the user's call
BLACKBOX_VAULT_PATH=/opt/agentaudit/vault
```
`file` stays in the sink list so the local outbox/JSONL remains the system of record even when forwarding — matches the "outbox never drops, forwarders best-effort" invariant.

---

## Bottom line

- **You do not need Gemini to dogfood the audit layer tonight** — Profile A, mock provider, zero spend. Save Gemini for the one Loom take that needs a real draft (Profile B).
- **Essentials are tiny:** SQLite + LangGraph/MCP + the `vault/` folder + Python. Everything else is Recommended, Optional, or Legacy.
- **Don't build a minimal mode** — ship the `.env.agentaudit-demo` profile (Profile A) and a README line. Zero code, matches the shipping discipline.
- **Demote in docs, don't rip out code:** Obsidian app/plugin, Gmail, main docker-compose, search/Telegram are Path-B residue. Move their mentions to an "examples/legacy" framing; deletion is a future cleanup, not a launch blocker.

*Companion: [README](../README.md) · [dogfood checklist](./agentaudit-dogfood-checklist.md) · [event schema](./agent-audit-event-schema.md) · [`.env.agentaudit-demo`](../apps/orchestrator/.env.agentaudit-demo) · [`.env.agentaudit-ollama`](../apps/orchestrator/.env.agentaudit-ollama).*

---

## Privacy for a cybersecurity / IR audience

Security people don't want another chatbot — they want **chain of custody for tool calls and approvals**. AgentAudit is built around that, and it keeps two data paths deliberately separate:

- **Pipe 1 — inference.** The prompt sent to an LLM to draft/critique. Goes wherever your provider is: **local** with Ollama (`.env.agentaudit-ollama`) or **mock** (`.env.agentaudit-demo`), or **cloud** if you choose Gemini BYOK. Your call, per environment.
- **Pipe 2 — audit.** Tool calls, denials, approvals, driver mounts → `events.db` + `audit-forward.jsonl`. **Local by default.** Nothing forwards off-box unless you set a webhook/Elastic/Splunk sink.

**When to use which inference provider:**

| Provider | Use when | Prompts leave box? |
|----------|----------|--------------------|
| **Ollama** | Air-gapped demo, regulated data, "nothing leaves the machine" pitch | No |
| **mock** | CI, routine audit dogfood, proving the trail with zero setup | No (no real inference) |
| **Gemini** | You want a realistic draft on camera and accept cloud inference | **Yes — prompts go to Google** |

**What lands in a forwarded SIEM (Pipe 2):** the canonical event — `action.type`, `action.outcome`, `tool.qualified`, `tool.server`, `correlation_id`, `actor.id`, and a **SHA-256 hash of the tool arguments** (`tool.input_hash`). **Never the raw arguments, never the prompt.** So forwarding your audit trail to a shared Splunk does not leak customer content — it leaks the *shape* of what the agent did, which is exactly what an investigator needs.

**The honest line for the audience:** AgentAudit does not hide your prompts from a cloud provider if *you* choose one — that's your inference decision. What it guarantees is that the *record of what the agent did* is yours, local, and hashed. See [`.env.agentaudit-ollama`](../apps/orchestrator/.env.agentaudit-ollama) for the fully-local path and the `audit_demo` skill for a no-LLM tool+approval demo.
