# Agentmetry event schema (v1.2.0)

Canonical JSON events for IDE hook capture and MCP audit. The orchestrator writes these to:

- **SQLite index** — `apps/orchestrator/data/audit.db` (query backend)
- **JSONL forward file** — `apps/orchestrator/data/audit-forward.jsonl` (SIEM/homelab ingest)

Disable JSONL export: `AGENTMETRY_AUDIT_EXPORT_ENABLED=0`

Set operator identity for multi-user SIEM queries: `AGENTMETRY_OPERATOR_ID=dev_01`

Set fleet scope for org-level SIEM queries: `AGENTMETRY_FLEET_ID=consulting-pilot`

### Forward sinks

| Env | Default | Description |
|-----|---------|-------------|
| `AGENTMETRY_AUDIT_SINK` | `file` | `file` \| `webhook` \| `both` \| `elastic` \| `splunk` \| `all` \| comma-separated |
| `AGENTMETRY_AUDIT_EXPORT_PATH` | `data/audit-forward.jsonl` | Append-only canonical JSONL |
| `AGENTMETRY_AUDIT_WEBHOOK_URL` | *(empty)* | Generic JSON POST |
| `AGENTMETRY_AUDIT_ELASTIC_URL` | *(empty)* | Elasticsearch cluster URL |
| `AGENTMETRY_AUDIT_ELASTIC_INDEX` | `logs-agentmetry` | Target index |
| `AGENTMETRY_ELASTIC_API_KEY` | *(empty)* | API key `id:secret` |
| `AGENTMETRY_AUDIT_SPLUNK_HEC_URL` | *(empty)* | Splunk HEC base URL |
| `AGENTMETRY_SPLUNK_HEC_TOKEN` | *(empty)* | HEC token |

Example enterprise multi-sink:

```text
AGENTMETRY_AUDIT_SINK=file,elastic,splunk
AGENTMETRY_OPERATOR_ID=dev_01
AGENTMETRY_AUDIT_ELASTIC_URL=https://elastic.example:9200
AGENTMETRY_ELASTIC_API_KEY=id:secret
AGENTMETRY_AUDIT_SPLUNK_HEC_URL=https://splunk.example:8088
AGENTMETRY_SPLUNK_HEC_TOKEN=...
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

`correlation_id` groups events from one agent session (IDE conversation or MCP proxy session). `session_id` is the dashboard/WebSocket session when applicable.

### v1.1 additions (additive)

| Field | When present | Purpose |
|-------|--------------|---------|
| `initiator` | All audited run events | Server-derived run origin: `{actor_type, trigger, operator_id}` |
| `fleet_id` | All canonical events | Org or deployment tag from `AGENTMETRY_FLEET_ID`; empty when unset |
| `gated_action` | `approval_request` | Binds the gate to `{tool, server, input_hash}` |
| `dlp` | `tool_called` (when `outcome` is `denied` or `mode` is `log`) | Records DLP scanner matches: `{rule_id, mode, pattern_type}` |
| `actor.type` | Derived | `user` for human-initiated runs; `agent` for cron/vault/ingress |
| `tool.mitre` | `tool_called` for a tool with an ATT&CK mapping | `{tactic_id, tactic, technique_id, technique}` |
| `tool_policy` | `tool_called` / `approval_request` when an allow/deny rule matches | `{rule_id, action, mode, blocked}` |
| `detection` | `action.type: detection` | Correlated finding: `{rule_id, title, severity, summary, correlation_id, tactic_ids, technique_ids, event_ids, first_seen_utc, last_seen_utc}` |

**Note on MITRE**: the object carries both machine ids and human names. Write SIEM
queries against `tactic_id` / `technique_id`; `tactic` / `technique` are display
labels and their wording can change. There is no single combined field.

**Note on detections**: a firing rule is emitted as its own canonical event with
`action.type: detection`, and `action.outcome` carries the severity, so a SIEM can
alert on `action.type:detection AND action.outcome:critical` without knowing
Agentmetry's rule vocabulary.

`initiator.actor_type` is set at `run_skill` from the call site (`manual`, `cron`, `vault_watch`, `ingress`, …) — never from client headers. `approval_response` events keep the run's `initiator` but set `actor.type=user` (the operator who clicked approve/reject).

**Note on DLP**: When an execution is blocked by the local Regex/YARA scanner, `action.outcome` is set to `denied` and `action.reason` is set to `dlp:<rule_id>`. The specific match data is logged in the `dlp` block.

### v1.2 additions (additive)

| Field | When present | Purpose |
|-------|--------------|---------|
| `detection.atlas` | `action.type: detection`, and only for rules that describe an AI-specific technique | `{framework, tactic_id, tactic, technique_id, technique, atlas_version}` |
| `tool.atlas` | `tool_called` where ATLAS says something ATT&CK cannot | Same shape |
| `mcp_schema.atlas` | `action.type: mcp_schema` with `status: changed` | Same shape |

A 1.1.0 consumer parses a 1.2.0 event and meets one key it does not recognise,
which its JSON parser already handles. Nothing moved, nothing changed meaning,
nothing became required. Consumers pinning the exact string rather than a lower
bound are the only ones that need a change.

## MITRE ATLAS (`atlas`)

ATT&CK describes what the agent did to the host. ATLAS describes what was done
to or through the agent. Both blocks can appear on one event, describing
different things about it.

`cursor.Read` on `~/.aws/credentials` is `T1552.001` whether a human, a script
or an agent did it. An MCP server changing its advertised tool schema between
calls has no honest ATT&CK id at all. That gap is why this block exists.

```json
"atlas": {
  "framework": "MITRE ATLAS",
  "tactic_id": "AML.TA0005",
  "tactic": "Execution",
  "technique_id": "AML.T0051.001",
  "technique": "LLM Prompt Injection: Indirect",
  "atlas_version": "2026.07"
}
```

`atlas_version` is the ATLAS content release the id was resolved against.
ATLAS renumbers between releases, so an id in an old trail is not
re-resolvable without it. Query on `technique_id`; `technique` is a display
label and its wording can change, exactly as with ATT&CK.

### Where the block appears, and where it does not

The block sits beside the thing it labels: inside `detection`, inside `tool`,
inside `mcp_schema`. It is never at the top level.

It is **absent on most events**, and that is the design rather than a gap.
A field carrying the same value everywhere is decoration, not signal. Two
techniques are deliberately never emitted for that reason:

- `AML.T0053 AI Agent Tool Invocation` is true of every event this product
  records, by definition.
- `AML.T0050 Command and Scripting Interpreter` is ATLAS restating `T1059`
  with no agent-specific claim attached.

Exactly one built-in detection rule is mapped:

| Rule | ATLAS | Why |
|------|-------|-----|
| `untrusted-input-then-risky-action` | `AML.T0051.001` LLM Prompt Injection: Indirect | Attacker-authorable content enters the session, then an already-risky action follows. ATLAS describes indirect injection as arriving "via a separate data channel ingested by the LLM". |

Rules such as `credential-exfil` and `destructive-delete-burst` carry no ATLAS
block. They are real and serious and they are host behaviour, which ATT&CK
already covers.

### Analyst overrides

A YAML rule in `agentmetry/policies/detection/manifest.yaml` may declare its
own mapping, which wins over any built-in one:

```yaml
- id: my-custom-rule
  atlas:
    tactic_id: AML.TA0010
    tactic: Exfiltration
    technique_id: AML.T0086
    technique: Exfiltration via AI Agent Tool Invocation
    atlas_version: "2026.07"   # optional; defaults to the shipped pin
```

`technique_id` is validated against `^AML\.T\d{4}(\.\d{3})?$` and
`tactic_id` against `^AML\.TA\d{4}$` when the manifest loads. A malformed id
raises rather than being dropped: a mapping silently discarded for a typo
leaves the rule firing while the analyst believes it is tagged.

### Query patterns

Splunk:

```
index=main sourcetype=agentmetry:json event.detection.atlas.technique_id="AML.T0051.001"
```

Elastic. Note the vendor path: ATLAS ids never enter ECS `threat.*`, because
those fields are ATT&CK-typed and an `AML.T****` there would corrupt any
rollup that groups by technique without filtering on `threat.framework`.

```
FROM logs-agentmetry
| WHERE agentmetry.detection.atlas.technique_id IS NOT NULL
| KEEP @timestamp, host.name, agentmetry.detection.rule_id, agentmetry.detection.atlas.technique_id
```

Every ATLAS-labelled finding, whatever the technique:

```
FROM logs-agentmetry
| WHERE agentmetry.detection.atlas.framework == "MITRE ATLAS"
```

### Out of scope

Two ATLAS tactics are not covered and are not planned here, because they need
signals from inside the model that an endpoint sensor at the tool boundary
does not have:

| Tactic | Why not |
|--------|---------|
| `AML.TA0000` AI Model Access | Requires observing queries to and responses from the model itself. Agentmetry records the tool lifecycle, not inference. |
| `AML.TA0001` AI Attack Staging | Proxy training, adversarial-example crafting and model replication happen off this host, before anything reaches a tool boundary. |

Both were renamed from "ML" to "AI" in current ATLAS, and both are commonly
cited under the wrong ids: `AML.TA0004` is Initial Access and `AML.TA0012` is
Privilege Escalation.

The Cloud Security Alliance's *MITRE ATT&CK and ATLAS Agentic Gap Analysis*
(2026-03-27) argues that ATLAS itself has agentic gaps overlapping the surface
a tool-boundary sensor sees. That cuts both ways: some agent behaviour this
product records has no ATLAS technique either, which is why the block is
absent far more often than it is present.

### Re-resolving the ids

Every id here was resolved **by name** against the canonical source, not from
memory or from secondary write-ups:

```
git clone https://github.com/mitre-atlas/atlas-data
# dist/ATLAS-latest.yaml is a symlink; dist/ATLAS.yaml is a deprecated 5.6.0 snapshot
cat dist/v6/ATLAS-2026.07.yaml
```

Pinned release: **2026.07**, format-version **6.0.0**. Resolving by name is
what catches renumbering. Two examples that a from-memory mapping gets wrong:
`AML.T0054` is *LLM Jailbreak*, not indirect prompt injection; and
`AML.T0099` is *AI Agent Tool Data Poisoning*, a different technique from
*AI Agent Tool Poisoning*, which is `AML.T0110`.

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
  "fleet_id": "consulting-pilot",
  "source_topic": "external/cursor/tool_called",
  "source": {"tier": "external", "app": "cursor", "adapter": "cursor_hook"},
  "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "dev_01"},
  "actor": {"type": "user", "id": "dev_01", "role": "operator"},
  "action": {"type": "tool_called", "outcome": "success", "reason": ""},
  "agent": {"name": "cursor", "skill_id": ""},
  "tool": {
    "name": "run_shell_command",
    "qualified": "shell.run",
    "input_redaction": "hash",
    "input_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "parameters_redacted": true,
    "mitre": {
      "tactic_id": "TA0009",
      "tactic": "Collection",
      "technique_id": "T1005",
      "technique": "Data from Local System"
    }
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
  "agent": {"name": "agentmetry", "skill_id": "audit_demo"},
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
| `actor.id` | PLAIN | From `AGENTMETRY_OPERATOR_ID` or `local` |

## CLI

```powershell
agentmetry replay <thread_id>     # ASCII timeline from events.db
agentmetry export --evidence ...  # Batch compliance pack (separate format)
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

- **Tier A** — agents running through the Agentmetry governed host
- **Tier B** — external agents you wire in via [`docs/external-agentmetry.md`](./external-agentmetry.md) (Cursor hooks, MCP proxy, ingest API)

It does **not** see unmanaged ChatGPT, Cursor with hooks disabled, or browser copilots without CASB/gateway policy.

### Tier B `source` block (v1.1+)

```json
"source": {"tier": "external", "app": "cursor", "adapter": "cursor_hook"}
```

Agentmetry-native events use `agent.name: "agentmetry"` and omit `source` (implicit Tier A).
