# Loki homelab — Agentmetry + free SIEM-lite

Tail `audit-forward.jsonl` into **Grafana Loki** for solo/homelab monitoring. No cloud account required.

**Prerequisite:** [Agentmetry event schema](../agentmetry-event-schema.md) — orchestrator running with `AGENTMETRY_AUDIT_EXPORT_ENABLED=1` (default).

---

## Quick start (~20 minutes)

### 1 — Run Agentmetry and generate events

```powershell
scripts\agentmetry.bat start
# Run any skill from the dashboard or Obsidian plugin
```

Confirm JSONL is growing:

```powershell
Get-Content apps\orchestrator\data\audit-forward.jsonl -Tail 3
```

Optional identity for SIEM queries:

```powershell
# apps/orchestrator/.env
AGENTMETRY_OPERATOR_ID=home-lab
```

### 2 — Start the Loki stack

From repo root:

```powershell
docker compose -f docker-compose.loki.yml up -d
```

Services:

| Service | URL | Notes |
|---------|-----|-------|
| Grafana | http://localhost:3001 | admin / `agentmetry` |
| Loki | http://localhost:3100 | API only |
| Alloy | http://localhost:12345 | Tails JSONL → Loki |

Alloy mounts `apps/orchestrator/data/audit-forward.jsonl` read-only (see `infra/loki/alloy.config`).

### 3 — Add Loki data source in Grafana

1. Open http://localhost:3001 → **Connections** → **Data sources** → **Add data source**
2. Choose **Loki**
3. URL: `http://loki:3100` (Docker network name)
4. **Save & test**

### 4 — Explore logs

**Explore** → Loki → query:

```logql
{job="agentmetry"}
```

Parse JSON fields:

```logql
{job="agentmetry"} | json | action_outcome="denied"
```

Filter by operator:

```logql
{job="agentmetry"} | json | actor_id="home-lab"
```

Replay a single run in Agentmetry (local, no Loki needed):

```powershell
agentmetry replay <thread_id>
```

---

## Example dashboard panels

**Events over time**

```logql
sum(count_over_time({job="agentmetry"} [5m]))
```

**Denials by tool**

```logql
sum by (tool_qualified) (count_over_time({job="agentmetry", action_outcome="denied"} | json [1h]))
```

**Approvals pending vs granted** (from labels after Alloy json stage)

```logql
sum(count_over_time({job="agentmetry", action_type="approval_request"} [24h]))
```

---

## Detection rules (LogQL alerts)

Full rule definitions: [detections-loki.md](./detections-loki.md)

Create in Grafana → **Alerting** → **Alert rules** → Loki data source.

| Rule | Severity |
|------|----------|
| Tool denial burst (5+ in 1 min) | Medium |
| Shell tool invoked successfully | High |
| MCP driver mounted (config_change) | Medium |

---

## Webhook sink (optional — skip Loki file tail)

Push canonical JSON directly to any HTTP collector (n8n, Vector, Logstash, custom):

```powershell
# apps/orchestrator/.env
AGENTMETRY_AUDIT_SINK=both
AGENTMETRY_AUDIT_WEBHOOK_URL=http://127.0.0.1:8080/ingest
```

`both` = append JSONL **and** POST each event. Use `webhook` for HTTP-only.

---

## Vector snippet (alternative to Alloy)

If you prefer [Vector](https://vector.dev) instead of Alloy:

```toml
[sources.agent_audit]
type = "file"
include = ["apps/orchestrator/data/audit-forward.jsonl"]
read_from = "end"

[transforms.parse]
type = "remap"
inputs = ["agent_audit"]
source = '''
. = parse_json!(.message)
.action_type = .action.type
.action_outcome = .action.outcome
'''

[sinks.loki]
type = "loki"
inputs = ["parse"]
endpoint = "http://localhost:3100"
encoding.codec = "json"
labels.job = "agentmetry"
```

---

## Fluent Bit snippet

```ini
[INPUT]
    Name              tail
    Path              apps/orchestrator/data/audit-forward.jsonl
    Parser            json
    Tag               agent.audit

[OUTPUT]
    Name              loki
    Match             agent.audit
    Host              127.0.0.1
    Port              3100
    Labels            job=agentmetry
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Empty Loki | Run a skill first; confirm JSONL exists and is non-empty |
| Alloy not shipping | `docker compose -f docker-compose.loki.yml logs alloy` |
| Grafana can't reach Loki | Use `http://loki:3100` inside Grafana, not localhost |
| Port 3001 in use | Change `3001:3000` in `docker-compose.loki.yml` |

---

## Limitations

- **Tier A only** — events from agents running through Agentmetry. See schema doc Tier C note.
- LogQL correlates poorly across long sessions for “approval bypass” — use `agentmetry replay <thread_id>` for chain-of-custody until recording rules land in v1.1.
