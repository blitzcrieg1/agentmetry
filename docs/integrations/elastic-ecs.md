# Elastic ECS — AgentAudit forwarder

Index governed agent audit events into **Elasticsearch** or **Elastic Cloud** using ECS-shaped documents. Full canonical JSON is nested under `agentaudit.*` for forensics.

**Prerequisite:** [Event schema](../agent-audit-event-schema.md)

---

## Environment

Add to `apps/orchestrator/.env`:

```text
BLACKBOX_AUDIT_SINK=file,elastic
BLACKBOX_OPERATOR_ID=dev_01

BLACKBOX_AUDIT_ELASTIC_URL=https://my-deployment.es.us-central1.gcp.cloud.es.io:443
BLACKBOX_AUDIT_ELASTIC_INDEX=logs-agentaudit
BLACKBOX_ELASTIC_API_KEY=base64id:base64key
BLACKBOX_AUDIT_ELASTIC_VERIFY_TLS=1
```

| Variable | Required | Description |
|----------|----------|-------------|
| `BLACKBOX_AUDIT_SINK` | Yes | Include `elastic` (e.g. `file,elastic`) |
| `BLACKBOX_AUDIT_ELASTIC_URL` | Yes | Cluster URL without trailing slash |
| `BLACKBOX_AUDIT_ELASTIC_INDEX` | No | Default `logs-agentaudit` |
| `BLACKBOX_ELASTIC_API_KEY` | Yes | Elasticsearch API key (`id:secret`) |
| `BLACKBOX_AUDIT_ELASTIC_VERIFY_TLS` | No | Set `0` for homelab with self-signed certs |

Restart the orchestrator after changing `.env`.

---

## Create API key (Elastic Cloud / self-hosted)

1. **Stack Management → Security → API keys → Create API key**
2. Name: `agentaudit-forwarder`
3. Role: `editor` on target index, or custom role with `create_doc` on `logs-agentaudit`
4. Copy the encoded key (`id:api_key`) into `BLACKBOX_ELASTIC_API_KEY`

---

## Index template (recommended)

Create index `logs-agentaudit` with ECS mapping, or use a data stream:

```json
PUT _index_template/logs-agentaudit
{
  "index_patterns": ["logs-agentaudit*"],
  "template": {
    "settings": { "number_of_shards": 1 },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "event.action": { "type": "keyword" },
        "event.outcome": { "type": "keyword" },
        "trace.id": { "type": "keyword" },
        "user.id": { "type": "keyword" },
        "agentaudit": { "type": "object", "enabled": true }
      }
    }
  }
}
```

---

## Example indexed document

After a denied tool call, Elasticsearch receives:

```json
{
  "@timestamp": "2026-07-12T09:14:22.041Z",
  "event": {
    "id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "kind": "event",
    "category": ["process"],
    "action": "tool_called",
    "outcome": "denied",
    "reason": "not_allowed",
    "sequence": 42
  },
  "host": { "name": "dev-laptop" },
  "user": { "id": "dev_01", "roles": ["operator"] },
  "trace": { "id": "thread-8892" },
  "tool": { "name": "run", "type": "shell.run" },
  "service": { "name": "shell" },
  "agentaudit": { "... full canonical event ..." }
}
```

---

## Kibana queries

**All AgentAudit events:**

```
event.action : * and observer.product : "AgentAudit"
```

**Denied tools in last hour:**

```
event.outcome : "denied" and event.action : "tool_called"
```

**One run by correlation id:**

```
trace.id : "thread-8892"
```

Detections: [detections-elastic.md](./detections-elastic.md)

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `401 Unauthorized` | Regenerate API key; check `id:secret` format |
| `403 forbidden` | Grant `create_doc` on index |
| `index_not_found_exception` | Create index or enable auto-create |
| TLS errors | `BLACKBOX_AUDIT_ELASTIC_VERIFY_TLS=0` for lab only |

Local JSONL at `data/audit-forward.jsonl` still writes when `file` is in `BLACKBOX_AUDIT_SINK`.
