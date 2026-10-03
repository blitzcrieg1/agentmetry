# Agentmetry: Microsoft Sentinel analytics rules

KQL for events forwarded with the Sentinel sink ([setup](./sentinel.md)), table
`Agentmetry_CL`. Two halves, as for [Splunk](./detections-splunk.md):

1. **The recorder's own detections.** The sequence rules run on the endpoint,
   in the detection engine, and arrive as `ActionType == "detection"` events.
   Sentinel raises incidents from those. It does not re-implement the rules in
   KQL: two implementations of one rule drift, and the engine is the one the
   benchmark corpus scores.
2. **Fleet-side correlations** (S1 to S7) that only a SIEM can do, because they
   need more than one machine or an absence of events.

Not yet run against a live workspace by the maintainers. The queries use only
the columns the setup page declares; treat them as starting points to test
against your own data before enabling them as scheduled rules.

---

## 1. Recorder detections

Every rule the engine ships, with the severity it emits. ATT&CK identifiers
travel on each event (`TacticIds`, `TechniqueIds`); the column below is what
the benchmark corpus emits, for reference only.

| `RuleId` | Severity | Technique(s) |
|---|---|---|
| `approval-denied-then-executed` | critical | (tactic TA0005) |
| `credential-exfil` | critical | T1552.004, T1071.001 |
| `credential-read-then-cloud-api` | critical | T1552.004, T1078 |
| `dotfile-read-then-git-push` | critical | T1552.001, T1567.001 |
| `encoded-command-download` | critical | T1105, T1059.001 |
| `pr-merged-without-review` | critical | T1195.002 |
| `remote-staging-then-execute` | critical | T1105, T1059 |
| `autonomous-unapproved-write` | high | T1565 |
| `destructive-delete-burst` | high | T1485 |
| `session-tool-burst` | high | T1059 |
| `subagent-swarm-burst` | high | T1059 |
| `host-subagent-swarm-burst` | high | T1059 |
| `untrusted-input-then-risky-action` | high | T1071.001 |
| `discovery-then-collect` | medium | T1083, T1005 |
| `off-hours-activity` | medium | from the triggering event |

### A1: Agentmetry detection (critical or high)

```kusto
Agentmetry_CL
| where ActionType == "detection"
| where Severity in ("critical", "high")
// The forwarder is at-least-once: a resent batch repeats an event, never a new finding.
| summarize arg_max(TimeGenerated, *) by EventId
| extend Title = tostring(Event.detection.title)
| project TimeGenerated, HostId, OperatorId, RuleId, Severity, Title,
          Summary = ActionReason, TacticIds, TechniqueIds, CorrelationId
```

Scheduled every 5 minutes over the last 10. Entity mapping: Host = `HostId`,
Account = `OperatorId`. Map the alert severity from `Severity`, and set alert
details from `RuleId` and `Title` so incidents group by rule.

A Sentinel content YAML for it, to import or keep in your detections-as-code repository:

```yaml
id: 49e0084f-9048-47ee-bb5a-d58a5b6be77a
name: Agentmetry - AI coding agent detection (critical/high)
description: A sequence detection from the Agentmetry endpoint recorder.
severity: High
requiredDataConnectors: []
queryFrequency: 5m
queryPeriod: 10m
triggerOperator: gt
triggerThreshold: 0
tactics: [CredentialAccess, Exfiltration, Execution, CommandAndControl, Impact]
query: |
  Agentmetry_CL
  | where ActionType == "detection" and Severity in ("critical", "high")
  | summarize arg_max(TimeGenerated, *) by EventId
  | extend Title = tostring(Event.detection.title)
entityMappings:
  - entityType: Host
    fieldMappings: [{ identifier: HostName, columnName: HostId }]
  - entityType: Account
    fieldMappings: [{ identifier: Name, columnName: OperatorId }]
alertDetailsOverride:
  alertDisplayNameFormat: "Agentmetry: {{Title}}"
  alertSeverityColumnName: Severity
version: 1.0.0
kind: Scheduled
```

(The `id` is a fixed GUID for this template; generate your own if you fork it.)

Triage happens where the finding was raised: a disposition set on the
recorder or the Enterprise console is forwarded too, as
`ActionType == "detection_disposition"`, so a closed finding can close the incident.

---

## 2. Fleet-side correlations

### S1: Tool denial burst

```kusto
Agentmetry_CL
| where ActionType == "tool_called" and ActionOutcome == "denied"
| summarize Denials = count() by OperatorId, HostId, bin(TimeGenerated, 1m)
| where Denials >= 5
```

### S2: Approval then a shell tool in the same session

```kusto
let approvals = Agentmetry_CL
    | where ActionType == "approval_response"
    | project CorrelationId, ApprovedAt = TimeGenerated;
Agentmetry_CL
| where ActionType == "tool_called" and ActionOutcome == "success"
| where ToolQualified has_any ("shell", "powershell", "Bash")
| join kind=inner approvals on CorrelationId
| where TimeGenerated between (ApprovedAt .. ApprovedAt + 10m)
| project ApprovedAt, TimeGenerated, HostId, OperatorId, CorrelationId, ToolQualified
```

Use `agentmetry replay <CorrelationId>` on the host for the definitive sequence.

### S3: New MCP driver (config change)

```kusto
Agentmetry_CL
| where ActionType == "config_change"
| project TimeGenerated, HostId, OperatorId, ServerId = tostring(Event.mcp.server_id)
```

### S4: Recorder degraded (hook removed while the recorder runs)

```kusto
Agentmetry_CL
| where ActionType == "heartbeat" and ActionOutcome == "degraded"
| summarize arg_max(TimeGenerated, *) by HostId
| project LastBeat = TimeGenerated, HostId, Reason = ActionReason,
          AgentsNotRecorded = Event.heartbeat.hooks_uncovered,
          Unmeasured = Event.heartbeat.hooks_unverified,
          HookProfile = tostring(Event.heartbeat.hook_profile),
          SpoolDepth = toint(Event.heartbeat.spool_depth)
```

Triage from `AgentsNotRecorded`, as in the Splunk notes: it lists only agents
installed on that machine and not recorded. `HookProfile == "service"` is the
MSI rolled out without per-user hook deployment.

### S5: Recorder silent, or never enrolled

Keep the hosts that should report in a watchlist, `AgentmetryExpectedHosts`,
with the host id as its search key.

```kusto
let expected = _GetWatchlist("AgentmetryExpectedHosts") | project HostId = tostring(SearchKey);
let beats = Agentmetry_CL
    | where TimeGenerated > ago(24h) and ActionType == "heartbeat"
    | summarize LastBeat = max(TimeGenerated) by HostId;
expected
| join kind=fullouter beats on HostId
| extend HostId = coalesce(HostId, HostId1)
| extend State = case(isnull(LastBeat), "never enrolled", LastBeat < ago(15m), "silent", "ok")
| where State != "ok"
| project HostId, State, LastBeat
```

Fifteen minutes is three default heartbeat intervals; one missed beat is a
restart or a closed laptop.

### S6: AI coding agent ran with no recorder behind it

Needs Microsoft Defender for Endpoint process telemetry in the same workspace.

```kusto
let beats = Agentmetry_CL
    | where TimeGenerated > ago(1h) and ActionType == "heartbeat"
    | distinct Host = tolower(HostId);
DeviceProcessEvents
| where Timestamp > ago(1h)
| where FileName in~ ("claude.exe", "cursor.exe")
| extend Host = tolower(tostring(split(DeviceName, ".")[0]))
| summarize IdeRuns = count() by Host
| join kind=leftanti beats on Host
| extend Finding = "AI coding agent executed with no recorder heartbeat"
```

Both halves are time-bounded on purpose: an unbounded heartbeat side lets one
old beat suppress the alert forever. `HostId` is the machine name unless
`AGENTMETRY_HOST_ID` overrides it; if you override it, make the `Host`
normalisation above match.

### S7: MCP tool schema changed (rug pull)

```kusto
Agentmetry_CL
| where ActionType == "mcp_schema" and ActionOutcome == "changed"
| project TimeGenerated, HostId,
          ServerId = tostring(Event.mcp_schema.server_id),
          ToolCount = toint(Event.mcp_schema.tool_count),
          Fingerprint = tostring(Event.mcp_schema.fingerprint)
```

Unscheduled until the fleet has a baseline: a vendor adding a tool looks the
same as a poisoned description. What S4 to S7 do and do not prove is written
up in the [Splunk notes](./detections-splunk.md#what-s4-to-s7-do-and-do-not-prove).

---

## Argument fingerprints across a fleet

`ToolInputHash` is HMAC-SHA256 under the fleet key when `AGENTMETRY_HASH_KEY`
is set (`InputRedaction` starts with `hmac`). It matches across every host
sharing the key and nothing else; a query joining two fleets on it finds
nothing, by design.
