# Agentmetry event schema (v1.1.0)

Canonical JSON events for governed agent runs. The orchestrator writes these to:

- **SQLite outbox** — `apps/orchestrator/data/events.db` (system of record)
- **JSONL forward file** — `apps/orchestrator/data/audit-forward.jsonl` (SIEM/homelab ingest)

Disable JSONL export: `BLACKBOX_AUDIT_EXPORT_ENABLED=0`

Set operator identity for multi-user SIEM queries: `BLACKBOX_OPERATOR_ID=dev_01`

### Forward sinks

| Env | Default | Description |
|-----|---------|-------------|
| `BLACKBOX_AUDIT_SINK` | `file` | `file` \| `webhook` \| `both` \| `elastic` \| `splunk` \| `all` \| comma-separated |
| `BLACKBOX_AUDIT_EXPORT_PATH` | `data/audit-forward.jsonl` | Append-only canonical JSONL |
| `BLACKBOX_AUDIT_WEBHOOK_URL` | *(empty)* | Generic JSON POST |
| `BLACKBOX_AUDIT_ELASTIC_URL` | *(empty)* | Elasticsearch cluster URL |
| `BLACKBOX_AUDIT_ELASTIC_INDEX` | `logs-agentmetry` | Target index |
| `BLACKBOX_ELASTIC_API_KEY` | *(empty)* | API key `id:secret` |
| `BLACKBOX_AUDIT_SPLUNK_HEC_URL` | *(empty)* | Splunk HEC base URL |
| `BLACKBOX_SPLUNK_HEC_TOKEN` | *(empty)* | HEC token |

Example enterprise multi-sink:

```text
BLACKBOX_AUDIT_SINK=file,elastic,splunk
BLACKBOX_OPERATOR_ID=dev_01
BLACKBOX_AUDIT_ELASTIC_URL=https://elastic.example:9200
BLACKBOX_ELASTIC_API_KEY=id:secret
BLACKBOX_AUDIT_SPLUNK_HEC_URL=https://splunk.example:8088
BLACKBOX_SPLUNK_HEC_TOKEN=...
```

## Bus topic → canonical action

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

`correlation_id` maps to LangGraph `thread_id`. `session_id` is the dashboard/WebSocket session.

### v1.1 additions (additive)

| Field | When present | Purpose |
|-------|--------------|---------|
| `initiator` | All audited run events | Server-derived run origin: `{actor_type, trigger, operator_id}` |
| `gated_action` | `approval_request` | Binds the gate to `{tool, server, input_hash}` |
| `dlp` | `tool_called` (when `outcome` is `denied` or `mode` is `log`) | Records DLP scanner matches: `{rule_id, mode, pattern_type}` |
| `actor.type` | Derived | `user` for human-initiated runs; `agent` for cron/vault/ingress |

`initiator.actor_type` is set at `run_skill` from the call site (`manual`, `cron`, `vault_watch`, `ingress`, …) — never from client headers. `approval_response` events keep the run's `initiator` but set `actor.type=user` (the operator who clicked approve/reject).

**Note on DLP**: When an execution is blocked by the local Regex/YARA scanner, `action.outcome` is set to `denied` and `action.reason` is set to `dlp:<rule_id>`. The specific match data is logged in the `dlp` block.

## Example (`run/tool_called`)

```json
{
  "schema_version": "1.1.0",
  "event_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "seq": 42,
  "session_id": "sess-abc",
  "correlation_id": "thread-8892",
  "timestamp_utc": "2026-07-12T09:14:22.041+00:00",
  "host_id": "dev-laptop",
  "source_topic": "run/tool_called",
  "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "dev_01"},
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success", "reason": ""},
  "agent": {"name": "blackbox", "skill_id": "customer_reply"},
  "tool": {
    "name": "read_file",
    "qualified": "vault_fs.read_file",
    "server": "vault_fs",
    "input_redaction": "hash",
    "input_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "parameters_redacted": true
  },
  "model": {"id": "gemini-2.5-flash-lite", "provider": "gemini"}
}
```

## Example (`run/approval_required` with gate binding)

```json
{
  "schema_version": "1.1.0",
  "correlation_id": "thread-8892",
  "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "dev_01"},
  "action": {"type": "approval_request", "outcome": "pending", "reason": ""},
  "agent": {"name": "blackbox", "skill_id": "audit_demo"},
  "gated_action": {
    "tool": "vault_fs.read_file",
    "server": "vault_fs",
    "input_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
}
```

## Redaction policy

| Field | Default | Notes |
|-------|---------|-------|
| Tool arguments | **HASH** | `arguments_sha256` on bus; `tool.input_hash` in canonical |
| Tool outputs | Not logged on bus v1 | Roadmap |
| Prompts / drafts | Not on tool events | Approval payloads may contain draft text in outbox only |
| `actor.id` | PLAIN | From `BLACKBOX_OPERATOR_ID` or `local` |

## CLI

```powershell
blackbox replay <thread_id>     # ASCII timeline from events.db
blackbox export --evidence ...  # Batch compliance pack (separate format)
```

## SIEM ingest

| Stack | Doc |
|-------|-----|
| **Loki homelab (free)** | [integrations/loki-homelab.md](./integrations/loki-homelab.md) |
| **LogQL detections** | [integrations/detections-loki.md](./integrations/detections-loki.md) |
| **Elastic ECS** | [integrations/elastic-ecs.md](./integrations/elastic-ecs.md) |
| **Elastic detections** | [integrations/detections-elastic.md](./integrations/detections-elastic.md) |
| **Splunk HEC** | [integrations/splunk-hec.md](./integrations/splunk-hec.md) |
| **Splunk detections** | [integrations/detections-splunk.md](./integrations/detections-splunk.md) |

## Limitations (Tier C)

Agentmetry records:

- **Tier A** — agents running through the BLACKBOX governed host
- **Tier B** — external agents you wire in via [`docs/external-agentmetry.md`](./external-agentmetry.md) (Cursor hooks, MCP proxy, ingest API)

It does **not** see unmanaged ChatGPT, Cursor with hooks disabled, or browser copilots without CASB/gateway policy.

### Tier B `source` block (v1.1+)

```json
"source": {"tier": "external", "app": "cursor", "adapter": "cursor_hook"}
```

BLACKBOX-native events use `agent.name: "blackbox"` and omit `source` (implicit Tier A).
