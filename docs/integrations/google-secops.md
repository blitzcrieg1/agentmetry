# Google SecOps (Chronicle)

Agentmetry forwards to Google SecOps as **UDM events**, not as raw logs.

## Why UDM directly, and not a parser

Chronicle offers two ingestion paths. Post raw JSON to `unstructuredlogentries` and let a Config Based Normalization parser turn it into UDM, or post UDM to `udmevents` and skip the parser.

Agentmetry does the second, for maintenance reasons rather than performance ones. A CBN parser is a second implementation of the same mapping: written in a different language, living in your tenant, versioned separately, and updated by somebody who is not us. Every schema change then has to land twice and stay in step, and when the two drift the failure is silent. Events keep arriving and quietly stop populating the fields your detections key on.

Google's own guidance is to send UDM where you can, for the same reason.

## Setup

```ini
AGENTMETRY_AUDIT_SINK=file,chronicle
AGENTMETRY_CHRONICLE_CUSTOMER_ID=<your Chronicle customer id>
AGENTMETRY_CHRONICLE_SERVICE_ACCOUNT=/path/to/ingestion-sa.json
```

The endpoint defaults to the global one and is overridable for a regional tenant:

```ini
AGENTMETRY_CHRONICLE_ENDPOINT=https://malachiteingestion-pa.googleapis.com/v2/udmevents:batchCreate
```

### Credentials, and one thing to know

Two options, and they are not equivalent.

**Service account (recommended).** Needs `google-auth` installed. Tokens refresh automatically, which is the only arrangement suitable for a process that runs for weeks.

```bash
pip install google-auth
```

**Static bearer token.** Needs no extra dependency and **expires**, typically within the hour:

```ini
AGENTMETRY_CHRONICLE_BEARER_TOKEN=ya29....
```

`google-auth` is deliberately not a hard dependency of the open-source core. A single developer recording their own machine should not have to install Google's auth stack to run a local flight recorder. So the static token stays available, and the sink logs a warning at startup saying it will stop working. A forwarder that silently stopped forwarding after fifty minutes would be a worse failure than one that refuses to start.

## How events map

`metadata.event_type` decides which UDM fields Chronicle *requires*, so a mis-declared type is rejected at ingest rather than stored imperfectly. The mapping is conservative for that reason, and for a second one.

| Agentmetry | UDM `event_type` | Notes |
|---|---|---|
| `tool_called` on a shell/exec tool with a command | `PROCESS_LAUNCH` | Command in `target.process.command_line` |
| `tool_called` otherwise | `USER_RESOURCE_ACCESS` | |
| `tool_denied` | `USER_RESOURCE_ACCESS` | `security_result.action = BLOCK` |
| `detection` | `USER_RESOURCE_ACCESS` | `security_result` with `alert_state: ALERTING` |
| `heartbeat` | `STATUS_UPDATE` | The native type for endpoint status reporting |
| `mcp_schema` | `STATUS_UPDATE` | Observed `tools/list` fingerprint; `changed` is a rug-pull candidate, not an alert_state |
| `session_start` / `session_end` | `USER_RESOURCE_ACCESS` | |

**A file read is not mapped to `FILE_READ`, deliberately.** Agentmetry observes an agent's *intent* to read a file at the tool boundary. It is not the kernel's record that a read occurred. Claiming the stronger type would make the two indistinguishable in a UDM search whose entire purpose is telling classes of evidence apart, and it would put agent telemetry in the same bucket as your EDR's file events. Those are different claims and your SOC should be able to separate them.

### Detections arrive as alerts

`security_result` is populated so Chronicle's own alerting works without anyone learning Agentmetry's vocabulary:

```json
"security_result": [{
  "alert_state": "ALERTING",
  "severity": "CRITICAL",
  "rule_name": "Credential exfiltration",
  "rule_id": "credential-exfil",
  "summary": "cursor.Read accessed credentials, then WebFetch egressed.",
  "category_details": ["T1552.004", "T1071.001"]
}]
```

`correlation_id` survives as a searchable label, which is how a responder pivots from one finding to the whole agent session.

---

## YARA-L rules

### C1 — Any Agentmetry detection at HIGH or above

```yaral
rule agentmetry_high_severity_detection {
  meta:
    author = "Agentmetry"
    description = "A behavioural sequence detection fired at high or critical"
    severity = "HIGH"
  events:
    $e.metadata.vendor_name = "Agentmetry"
    $e.security_result.alert_state = "ALERTING"
    $e.security_result.severity in ("HIGH", "CRITICAL")
    $host = $e.principal.hostname
  match:
    $host over 5m
  condition:
    $e
}
```

### C2 — Recorder degraded (hook removed while the orchestrator runs)

The state a liveness check cannot see: the process is up, the port answers, and the agents on that machine are no longer recorded.

```yaral
rule agentmetry_recorder_degraded {
  meta:
    author = "Agentmetry"
    description = "Recorder attesting that capture is impaired: a hook is missing or events are buffering"
    severity = "MEDIUM"
  events:
    $e.metadata.vendor_name = "Agentmetry"
    $e.metadata.event_type = "STATUS_UPDATE"
    $e.metadata.product_event_type = "heartbeat"
    $e.security_result.rule_id = "agentmetry-recorder-degraded"
    $host = $e.principal.hostname
  match:
    $host over 15m
  condition:
    $e
}
```

### C3 — Recorder silent

Absence, expressed the way YARA-L expresses absence: a reference list of enrolled hosts, and a rule that fires when one of them has no beat in the window.

```yaral
rule agentmetry_recorder_silent {
  meta:
    author = "Agentmetry"
    description = "An enrolled host has emitted no recorder heartbeat for three intervals"
    severity = "HIGH"
  events:
    $host = $enrolled.hostname
    $enrolled.hostname in %agentmetry_enrolled_hosts
    not (
      $beat.metadata.vendor_name = "Agentmetry" and
      $beat.metadata.product_event_type = "heartbeat" and
      $beat.principal.hostname = $host
    )
  match:
    $host over 15m
  condition:
    $enrolled and not $beat
}
```

Populate `%agentmetry_enrolled_hosts` from your asset inventory. Without it the rule can only reason about hosts that beat at least once, so a laptop where the recorder was never installed is invisible to the rule meant to find unmonitored machines.

Three intervals rather than one: the default beat is 300s, and a single missed beat is a restart or a closed laptop. Alerting on that teaches a SOC to close the rule.

### C4 — AI coding agent ran with no recorder behind it

The strongest of the four, because it needs no assumption about whether a machine should be online. Your EDR proves it was in use. Requires EDR process telemetry in the same tenant.

```yaral
rule agentmetry_unhooked_agent_execution {
  meta:
    author = "Agentmetry"
    description = "An AI coding agent process launched on a host with no recorder heartbeat in the same window"
    severity = "HIGH"
  events:
    $ide.metadata.event_type = "PROCESS_LAUNCH"
    re.regex($ide.target.process.file.full_path, `(?i)(claude|cursor)\\.exe$`)
    $host = $ide.principal.hostname
    not (
      $beat.metadata.vendor_name = "Agentmetry" and
      $beat.metadata.product_event_type = "heartbeat" and
      $beat.principal.hostname = $host
    )
  match:
    $host over 1h
  condition:
    $ide and not $beat
}
```

Note the window on `match`. An unbounded correlation lets a single heartbeat from months ago suppress the alert forever, which is the failure mode where the rule looks healthy and detects nothing.

---

## What C2 to C4 do and do not prove

They do not prevent a developer removing a hook. Nothing in user space does, and any vendor claiming otherwise is either shipping a kernel driver or overstating.

What they change is that removal stops being quiet. C2 catches the recorder running while impaired, C3 catches it not running, C4 catches an agent running with nothing behind it. Someone with local admin defeats all three. They cannot defeat all three silently, and silence is what an insider needs.

## Related

- [Splunk equivalents](./detections-splunk.md) (S4 to S6)
- [Portable Sigma rules](./sigma/README.md)
- [Canonical event schema](../agentmetry-event-schema.md)
