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

**Triage:** `trace.id` → `agentmetry replay <correlation_id>`

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

## E4 — Recorder degraded (hook removed while the orchestrator runs)

**Logic:** The recorder is alive and attesting that capture is impaired.

This is the state a liveness check cannot see: the process is up, the port answers, and the agents on that machine are no longer recorded. Deleting `.cursor/hooks.json` produces exactly this.

```
FROM logs-agentmetry*
| WHERE event.action == "heartbeat" AND event.outcome == "degraded"
| KEEP @timestamp, host.name, event.reason,
       agentmetry.heartbeat.hooks_uncovered,
       agentmetry.heartbeat.hooks_unverified,
       agentmetry.heartbeat.hook_profile,
       agentmetry.heartbeat.spool_depth
| SORT @timestamp DESC
```

**Legacy KQL alert:**

```
event.action: "heartbeat" and event.outcome: "degraded"
```

**Triage from `hooks_uncovered`, not from the per-agent booleans.** A bool per agent cannot separate a hook that was removed from an IDE that was never installed, and treating those the same is how a rule becomes background noise. `hooks_uncovered` lists only agents that are present on that machine and are not being recorded.

`hook_profile: "service"` deserves its own rule. It means the recorder is reading a service account's profile rather than a developer's, so it can see nobody's hook configuration at all. On a per-machine MSI rollout that is attested coverage rather than real coverage.

**Severity:** Medium. Sustained degradation on a host that was previously clean is the finding.

---

## E5 — Recorder silent (no heartbeat)

**Logic:** No attestation within three intervals. The default beat is 300s, so 15 minutes.

Three intervals rather than one: a single missed beat is a restart, a closed laptop, or a slow drain, and alerting on that teaches a SOC to close the rule.

```
FROM logs-agentmetry*
| WHERE event.action == "heartbeat" AND @timestamp > NOW() - 24 hours
| STATS last_beat = MAX(@timestamp) BY host.name
| EVAL gap_minutes = DATE_DIFF("minutes", last_beat, NOW())
| WHERE gap_minutes > 15
| SORT gap_minutes DESC
```

**This only sees hosts that beat at least once.** A laptop where the recorder was never installed is invisible to a rule whose whole purpose is finding unmonitored machines. Enrich against your asset inventory to close that: in Kibana, an ES|QL `LOOKUP JOIN` against an enrolled-hosts index, or a Transform that keeps a per-host last-seen document you can compare against.

**Severity:** High once the enrolled list is wired in. Medium without it.

---

## E6 — AI coding agent ran with no recorder behind it

**Logic:** EDR saw the IDE execute; no heartbeat arrived from that host in the same window.

The strongest of these four, because it needs no assumption about whether a machine should be online. Your endpoint telemetry proves it was in use. Requires EDR process events in the same cluster.

```
FROM logs-endpoint*, logs-agentmetry*
| WHERE (event.category == "process" AND process.name IN ("cursor.exe", "claude.exe", "code.exe"))
     OR event.action == "heartbeat"
| EVAL src = CASE(event.action == "heartbeat", "beat", "ide")
| STATS ide_runs = COUNT(CASE(src == "ide", 1, NULL)),
        beats    = COUNT(CASE(src == "beat", 1, NULL))
        BY host.name
| WHERE ide_runs > 0 AND beats == 0
```

Bound the window when you schedule it. An unbounded correlation lets a single heartbeat from months ago suppress the alert forever, which is the failure mode where the rule looks healthy and detects nothing.

**Severity:** High.

---

## E7 — MCP tool schema changed (rug pull)

**Logic:** A `tools/list` fingerprint moved. The configured command in `mcp.json` often did not.

`mcp_config_digest` hashes the configured command line, which catches "somebody added a server" and misses the attack that matters. The payload of a rug pull lives in the tool description the model is handed, and that never appears in the config file. `postmark-mcp` shipped fifteen clean versions before the schema changed.

```
FROM logs-agentmetry*
| WHERE event.action == "mcp_schema" AND event.outcome == "changed"
| KEEP @timestamp, host.name,
       agentmetry.mcp_schema.server_id,
       agentmetry.mcp_schema.fingerprint,
       agentmetry.mcp_schema.tool_count
| SORT @timestamp DESC
```

**The signal is the conjunction:** the schema digest moved while `agentmetry.heartbeat.mcp_config_digest` did not. Config alone never sees it.

**Do not schedule this on day one.** Before a fleet has a baseline every first observation is a change, and a vendor legitimately adding a tool looks identical to a poisoned description. Investigate, do not convict. The digest is also empty until a server has been listed through the audit proxy, which is a gap rather than a healthy default, and the beat reports it as empty rather than as clean.

**Severity:** Medium, and worth a page only once a baseline exists.

---

## Field reference

| ECS field | Canonical source |
|-----------|------------------|
| `event.action` | `action.type` |
| `event.outcome` | `action.outcome` |
| `trace.id` | `correlation_id` |
| `user.id` | `actor.id` |
| `agentmetry.*` | Full canonical JSON |
| `agentmetry.heartbeat.hooks_uncovered` | Agents present on that host whose hook is missing. The incident |
| `agentmetry.heartbeat.hooks_unverified` | Agents whose coverage could not be determined at all |
| `agentmetry.heartbeat.hook_profile` | `user` or `service`. `service` means no developer profile is visible |
| `agentmetry.heartbeat.mcp_schema_digest` | SHA over the observed `tools/list`. Runtime |
| `agentmetry.heartbeat.mcp_config_digest` | SHA over the configured MCP command lines. Inventory |
| `agentmetry.heartbeat.trail_merkle_root` | RFC 6962 commitment that lands off the endpoint |
| `agentmetry.mcp_schema.server_id` | Hashed server name. The name itself never leaves the machine |

See also: [detections-loki.md](./detections-loki.md) for homelab LogQL rules.
