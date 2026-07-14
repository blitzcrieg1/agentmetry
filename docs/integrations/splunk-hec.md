# Splunk HEC — Agentmetry forwarder

POST canonical agent audit events to **Splunk HTTP Event Collector** (HEC). Works with Splunk Enterprise, Splunk Cloud, and **Splunk Free** (500 MB/day — more than enough for solo agent volume).

**Prerequisite:** [Event schema](../agentmetry-event-schema.md)

---

## Environment

```text
AGENTMETRY_AUDIT_SINK=file,splunk
AGENTMETRY_OPERATOR_ID=dev_01

AGENTMETRY_AUDIT_SPLUNK_HEC_URL=https://127.0.0.1:8088
AGENTMETRY_SPLUNK_HEC_TOKEN=your-hec-token
AGENTMETRY_AUDIT_SPLUNK_INDEX=main
AGENTMETRY_AUDIT_SPLUNK_SOURCETYPE=agentmetry:json
AGENTMETRY_AUDIT_SPLUNK_VERIFY_TLS=0
```

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENTMETRY_AUDIT_SINK` | Yes | Include `splunk` |
| `AGENTMETRY_AUDIT_SPLUNK_HEC_URL` | Yes | HEC base, e.g. `https://splunk:8088` |
| `AGENTMETRY_SPLUNK_HEC_TOKEN` | Yes | HEC token |
| `AGENTMETRY_AUDIT_SPLUNK_INDEX` | No | Default `main` |
| `AGENTMETRY_AUDIT_SPLUNK_SOURCETYPE` | No | Default `agentmetry:json` |

URL may be `https://host:8088` or full `.../services/collector/event` — both work.

---

## Enable HEC (Splunk)

1. **Settings → Data inputs → HTTP Event Collector → New Token**
2. Name: `agentmetry`
3. Source type: `agentmetry:json` (or accept automatic JSON)
4. Index: `main` (or dedicated `agentmetry`)
5. Copy token → `AGENTMETRY_SPLUNK_HEC_TOKEN`

---

## Example HEC payload

```json
{
  "time": 1752306862.041,
  "host": "dev-laptop",
  "source": "Agentmetry",
  "sourcetype": "agentmetry:json",
  "index": "main",
  "fields": {
    "action_type": "tool_called",
    "action_outcome": "denied",
    "correlation_id": "thread-abc",
    "actor_id": "dev_01"
  },
  "event": {
    "schema_version": "1.0.0",
    "action": { "type": "tool_called", "outcome": "denied", "reason": "not_allowed" },
    "tool": { "qualified": "shell.run" }
  }
}
```

---

## Splunk searches

**All events:**

```spl
index=main sourcetype=agentmetry:json
```

**Denials:**

```spl
index=main sourcetype=agentmetry:json action_outcome=denied
```

**Replay correlation id locally:**

```powershell
agentmetry replay thread-abc
```

Detections: [detections-splunk.md](./detections-splunk.md)

---

## Combined sinks

```text
AGENTMETRY_AUDIT_SINK=file,elastic,splunk
```

Or `AGENTMETRY_AUDIT_SINK=all` with Elastic + Splunk + webhook env vars set.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `401` / data not indexed | Check HEC token and index allow-list on token |
| SSL errors on homelab | `AGENTMETRY_AUDIT_SPLUNK_VERIFY_TLS=0` |
| Wrong index | Token may restrict indexes — match `AGENTMETRY_AUDIT_SPLUNK_INDEX` |
