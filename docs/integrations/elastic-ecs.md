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
techniques land under `agentmetry.tool.atlas.*` and never here, so an
aggregation over `threat.technique.id` cannot mix taxonomies.

## MITRE ATLAS (`agentmetry.tool.atlas.*`)

ATT&CK describes what the agent did to the host. ATLAS describes what was done
to or through the agent, which is the half ATT&CK has no id for. Both blocks can
be present on one event, describing different things about it.

| field | example |
| --- | --- |
| `agentmetry.tool.atlas.framework` | `MITRE ATLAS` |
| `agentmetry.tool.atlas.tactic_id` | `AML.TA0013` |
| `agentmetry.tool.atlas.tactic` | `Credential Access` |
| `agentmetry.tool.atlas.technique_id` | `AML.T0098` |
| `agentmetry.tool.atlas.technique` | `AI Agent Tool Credential Harvesting` |

The block is absent on most events, deliberately. It appears only where ATLAS
adds a claim ATT&CK cannot make: that an AI agent's tool was the instrument.
A shell command is tagged `T1059.004` and carries no ATLAS label, because
`AML.T0050` is ATLAS restating the same thing with nothing agent-specific
attached. `AML.T0053 AI Agent Tool Invocation` is true of every event this
product records and is never emitted for the same reason.

The rug-pull signal carries its own label on the `mcp_schema` event rather than
on a tool call:

```json
"mcp_schema": {
  "status": "changed",
  "atlas": {
    "framework": "MITRE ATLAS",
    "tactic_id": "AML.TA0007",
    "tactic": "Defense Evasion",
    "technique_id": "AML.T0109",
    "technique": "AI Supply Chain Rug Pull"
  }
}
```

Only a schema that moved is the technique. A first sighting (`new`) and a quiet
reconnect (`same`) carry no label, because tagging either would put a Defense
Evasion finding on installing a tool.

Ids are from ATLAS content release `2026.07`, format-version `6.0.0`. Note that
the widely-linked `dist/ATLAS.yaml` in the ATLAS data repository is a deprecated
`5.6.0` snapshot; these came from `dist/v6/`.

To query ATLAS in Elastic, filter the vendor path directly:

```
FROM logs-agentmetry
| WHERE agentmetry.tool.atlas.technique_id == "AML.T0098"
| KEEP @timestamp, host.name, user.id, agentmetry.tool.qualified
```

Map those as keywords too if you intend to aggregate on them, for the same
reason as `threat.*` above:

```json
"agentmetry.tool.atlas.technique_id": { "type": "keyword" },
"agentmetry.tool.atlas.tactic_id":    { "type": "keyword" }
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
