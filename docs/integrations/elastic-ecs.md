# Elastic ECS — Agentmetry forwarder

Index governed agent audit events into **Elasticsearch** or **Elastic Cloud** using ECS-shaped documents. Full canonical JSON is nested under `agentmetry.*` for forensics.

**Prerequisite:** [Event schema](../agentmetry-event-schema.md)

---

## Environment

Add to `apps/orchestrator/.env`:

```text
AGENTMETRY_AUDIT_SINK=file,elastic
AGENTMETRY_OPERATOR_ID=dev_01

AGENTMETRY_AUDIT_ELASTIC_URL=https://my-deployment.es.us-central1.gcp.cloud.es.io:443
AGENTMETRY_AUDIT_ELASTIC_INDEX=logs-agentmetry
AGENTMETRY_ELASTIC_API_KEY=base64id:base64key
AGENTMETRY_AUDIT_ELASTIC_VERIFY_TLS=1
```

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENTMETRY_AUDIT_SINK` | Yes | Include `elastic` (e.g. `file,elastic`) |
| `AGENTMETRY_AUDIT_ELASTIC_URL` | Yes | Cluster URL without trailing slash |
| `AGENTMETRY_AUDIT_ELASTIC_INDEX` | No | Default `logs-agentmetry` |
| `AGENTMETRY_ELASTIC_API_KEY` | Yes | Elasticsearch API key (`id:secret`) |
| `AGENTMETRY_AUDIT_ELASTIC_VERIFY_TLS` | No | Set `0` for homelab with self-signed certs |

Restart the orchestrator after changing `.env`.

---

## Create API key (Elastic Cloud / self-hosted)

1. **Stack Management → Security → API keys → Create API key**
2. Name: `agentmetry-forwarder`
3. Role: `editor` on target index, or custom role with `create_doc` on `logs-agentmetry`
4. Copy the encoded key (`id:api_key`) into `AGENTMETRY_ELASTIC_API_KEY`

---

## Index template (recommended)

Create index `logs-agentmetry` with ECS mapping, or use a data stream:

```json
PUT _index_template/logs-agentmetry
{
  "index_patterns": ["logs-agentmetry*"],
  "template": {
    "settings": { "number_of_shards": 1 },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "event.action": { "type": "keyword" },
        "event.outcome": { "type": "keyword" },
        "trace.id": { "type": "keyword" },
        "user.id": { "type": "keyword" },
        "threat.framework": { "type": "keyword" },
        "threat.tactic.id": { "type": "keyword" },
        "threat.tactic.name": { "type": "keyword" },
        "threat.technique.id": { "type": "keyword" },
        "threat.technique.name": { "type": "keyword" },
        "agentmetry": { "type": "object", "enabled": true }
      }
    }
  }
}
```

The `threat.*` fields carry the ATT&CK classification and are what your existing
ATT&CK dashboards, Navigator coverage layers and prebuilt detection content join
on. Map them as `keyword` explicitly: left to dynamic mapping they become
`text` with a `.keyword` subfield, and every aggregation has to remember the
suffix.

They are absent on events Agentmetry did not classify. That is deliberate, not a
gap in the mapping. A coverage panel that counts unclassified calls as covered
is worse than one that shows a smaller number honestly.

`threat.framework` is always `MITRE ATT&CK` on these documents. MITRE ATLAS
techniques, when they ship, will land under `agentmetry.tool.atlas.*` rather than
here, so an aggregation over `threat.technique.id` never mixes taxonomies.

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
  "agentmetry": { "... full canonical event ..." }
}
```

---

## Kibana queries

**All Agentmetry events:**

```
event.action : * and observer.product : "Agentmetry"
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
| TLS errors | `AGENTMETRY_AUDIT_ELASTIC_VERIFY_TLS=0` for lab only |

Local JSONL at `data/audit-forward.jsonl` still writes when `file` is in `AGENTMETRY_AUDIT_SINK`.
