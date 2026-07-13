# Agentmetry — Elastic / Kibana detection examples

Team-tier rules for Elasticsearch indices populated by the [Elastic ECS adapter](./elastic-ecs.md).

---

## E1 — Tool denial burst

**Logic:** More than five denied tool outcomes in one minute (any host).

**Kibana rule (ES|QL or threshold):**

```
FROM logs-agentmetry*
| WHERE event.outcome == "denied" AND event.action == "tool_called"
| STATS denial_count = COUNT(*) BY user.id
| WHERE denial_count > 5
```

**Legacy KQL alert:**

```
event.outcome: "denied" and event.action: "tool_called"
```

Threshold: **> 5 events in 1 minute** grouped by `user.id`.

**Triage:** `trace.id` → `blackbox replay <correlation_id>`

---

## E2 — Shell tool success

**Logic:** Successful tool call where service name or tool type indicates shell execution.

```
FROM logs-agentmetry*
| WHERE event.action == "tool_called"
  AND event.outcome == "success"
  AND (service.name == "shell" OR tool.type LIKE "*shell*")
```

**Severity:** High — confirm allowlist and approval chain.

---

## E3 — MCP driver mounted

**Logic:** Configuration change events (driver mount).

```
FROM logs-agentmetry*
| WHERE event.action == "config_change" AND event.outcome == "success"
| KEEP @timestamp, host.name, agentmetry.mcp.server_id, user.id
```

Compare `agentmetry.mcp.server_id` to approved entries in `vault/.system/drivers.json`.

---

## Field reference

| ECS field | Canonical source |
|-----------|------------------|
| `event.action` | `action.type` |
| `event.outcome` | `action.outcome` |
| `trace.id` | `correlation_id` |
| `user.id` | `actor.id` |
| `agentmetry.*` | Full canonical JSON |

See also: [detections-loki.md](./detections-loki.md) for homelab LogQL rules.
