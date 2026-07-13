# Agentmetry — example Loki / Grafana detections

Canonical events are one JSON object per line. After Alloy's json stage (see `infra/loki/alloy.config`), labels `action_type` and `action_outcome` are available for alert queries.

Create rules in **Grafana → Alerting → Alert rules** with the **Loki** data source.

---

## R1 — Tool denial burst

**Intent:** Possible injection, policy probing, or misconfigured skill allowlist.

**Logic:** Five or more denied tool calls within one minute (any session).

**Severity:** Medium

**LogQL (alert condition):**

```logql
sum(count_over_time({job="agentmetry", action_outcome="denied"} [1m])) >= 5
```

**Example canonical line:**

```json
{
  "action": {"type": "tool_called", "outcome": "denied", "reason": "not_allowed"},
  "tool": {"qualified": "shell.run", "server": "shell"},
  "correlation_id": "thread-abc"
}
```

**Triage:** `blackbox replay thread-abc` — check preceding `approval_request` and skill YAML allowlist.

---

## R2 — Shell / high-risk tool success

**Intent:** Agent executed a privileged tool that passed the allowlist — verify intent.

**Logic:** Successful tool call where qualified name matches shell-family tools.

**Severity:** High

**LogQL:**

```logql
sum(count_over_time(
  {job="agentmetry", action_type="tool_called", action_outcome="success"}
  | json
  | tool_qualified=~".*shell.*|.*powershell.*|.*exec.*"
  [5m]
)) >= 1
```

If `tool_qualified` is not extracted as a label, use line filter:

```logql
sum(count_over_time(
  {job="agentmetry", action_type="tool_called", action_outcome="success"}
  |= "shell"
  [5m]
)) >= 1
```

**Example line:** `tool.qualified` = `shell.run`, `action.outcome` = `success`.

**Triage:** Confirm operator approved the run; check `actor.id` and `correlation_id`.

---

## R3 — MCP driver mounted (supply chain)

**Intent:** New or unexpected MCP server joined the host — possible shadow driver or config drift.

**Logic:** Any successful `config_change` from `driver/mounted`.

**Severity:** Medium

**LogQL:**

```logql
sum(count_over_time({job="agentmetry", action_type="config_change", action_outcome="success"} [15m])) >= 1
```

**Example line:**

```json
{
  "source_topic": "driver/mounted",
  "action": {"type": "config_change", "outcome": "success"},
  "mcp": {"server_id": "search", "tools": ["search.query"]}
}
```

**Triage:** Compare to pinned `vault/.system/drivers.json`; unexpected HTTP/SSE sources warrant investigation (OWASP MCP supply-chain).

---

## Alert notification (homelab)

Grafana → **Contact points** → add Slack, email, or webhook → link to each rule.

For solo use, a **Grafana OnCall** or simple Slack webhook is enough — no enterprise SIEM required.

---

## Roadmap (v1.1)

| Rule | Challenge |
|------|-----------|
| Approval bypass | Needs session-scoped correlation (`approval_request` → `tool_called` on same `correlation_id`) — better suited to recording rules or export + offline Sigma |
| Exfil chain | Sequence of HTTP + file tools — use Loki pattern ingester or Elastic EQL in enterprise adapters |

See also: [agentmetry-event-schema.md](../agentmetry-event-schema.md)
