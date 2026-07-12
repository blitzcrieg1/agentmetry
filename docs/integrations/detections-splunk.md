# AgentAudit — Splunk detection examples

Team-tier searches and alert templates for HEC-ingested events. See [Splunk HEC setup](./splunk-hec.md).

---

## S1 — Tool denial burst

**Logic:** Five or more denied tool calls in one minute per actor.

```spl
index=main sourcetype=agentaudit:json action_outcome=denied action_type=tool_called
| stats count as denials by actor_id
| where denials >= 5
```

**Alert:** Scheduled every 1 minute; trigger when `denials >= 5`.

---

## S2 — Approval granted then high-risk tool (same session)

**Logic:** Same `correlation_id` has approval response and subsequent shell tool success within 10 minutes.

```spl
index=main sourcetype=agentaudit:json
| eval cid=coalesce(correlation_id, 'event.correlation_id')
| transaction cid maxspan=10m
| search action_type=approval_response action_type=tool_called action_outcome=success
| search "shell" OR "powershell"
```

Note: `transaction` is approximate; use `blackbox replay` for definitive chain-of-custody.

---

## S3 — New MCP driver (config change)

```spl
index=main sourcetype=agentaudit:json action_type=config_change
| table _time host actor_id event.mcp.server_id
```

**Severity:** Medium — supply-chain / shadow MCP.

---

## Saved search export

Export as **Settings → Searches, reports, and alerts → New alert** for email or webhook notification.

Homelab solo rules: [detections-loki.md](./detections-loki.md)
