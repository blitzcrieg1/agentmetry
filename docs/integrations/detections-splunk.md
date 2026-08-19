# Agentmetry — Splunk detection examples

Team-tier searches and alert templates for HEC-ingested events. See [Splunk HEC setup](./splunk-hec.md).

---

## S1 — Tool denial burst

**Logic:** Five or more denied tool calls in one minute per actor.

```spl
index=main sourcetype=agentmetry:json action_outcome=denied action_type=tool_called
| stats count as denials by actor_id
| where denials >= 5
```

**Alert:** Scheduled every 1 minute; trigger when `denials >= 5`.

---

## S2 — Approval granted then high-risk tool (same session)

**Logic:** Same `correlation_id` has approval response and subsequent shell tool success within 10 minutes.

```spl
index=main sourcetype=agentmetry:json
| eval cid=coalesce(correlation_id, 'event.correlation_id')
| transaction cid maxspan=10m
| search action_type=approval_response action_type=tool_called action_outcome=success
| search "shell" OR "powershell"
```

Note: `transaction` is approximate; use `agentmetry replay` for definitive chain-of-custody.

---

## S3 — New MCP driver (config change)

```spl
index=main sourcetype=agentmetry:json action_type=config_change
| table _time host actor_id event.mcp.server_id
```

**Severity:** Medium — supply-chain / shadow MCP.

---

## S4 — Recorder degraded (hook removed while the orchestrator runs)

**Logic:** The recorder is alive and attesting that capture is impaired.

This is the state a liveness check cannot see: the process is up, the port answers, the dashboard is green, and the agents on that machine are no longer recorded. Deleting `.cursor/hooks.json` produces exactly this.

```spl
index=main sourcetype=agentmetry:json action_type=heartbeat action_outcome=degraded
| spath output=reason      path=action.reason
| spath output=uncovered   path=heartbeat.hooks_uncovered
| spath output=unverified  path=heartbeat.hooks_unverified
| spath output=profile     path=heartbeat.hook_profile
| spath output=spool       path=heartbeat.spool_depth
| stats latest(_time) as last_beat latest(reason) as reason
        latest(uncovered) as agents_not_recorded latest(unverified) as unmeasured
        latest(profile) as hook_profile latest(spool) as spool_depth by host
| convert ctime(last_beat)
```

Only `action_type`, `action_outcome`, `correlation_id` and `actor_id` are promoted to indexed fields by the HEC adapter, so everything else needs `spath`.

Triage from `agents_not_recorded`, not from `heartbeat.hooks.*`. A bool per agent cannot separate a hook that was removed from an IDE that was never installed, and treating those the same is how a rule becomes background noise: a developer who does not use Claude Code used to degrade every beat they ever sent. `hooks_uncovered` lists only agents that are installed on that machine and are not being recorded.

Two other values worth a saved search of their own:

`hook_profile = service` means the recorder is reading a service account's profile rather than a developer's. Hook configuration lives per user, so from there the recorder can see nothing about anybody's coverage. This is the shape a per-machine MSI rollout takes when the hooks were never deployed into user profiles, and it is worth alerting on separately because the fleet looks installed.

`unmeasured` lists agents whose coverage could not be determined, as distinct from determined and found missing. "We could not look" and "we looked and found nothing" are different claims, and collapsing them is how a fleet dashboard turns green over a blind spot. Nothing here counts as coverage, and nothing here raises this alert on its own.

**Alert:** Scheduled hourly. The finding is sustained degradation on a host that was previously healthy.

---

## S5 — Recorder silent (no heartbeat)

**Logic:** No attestation within three intervals. The default beat is 300s, so 15 minutes.

Three intervals rather than one: a single missed beat is a restart, a closed laptop, or a slow drain, and alerting on it teaches the SOC to close this rule.

```spl
index=main sourcetype=agentmetry:json action_type=heartbeat earliest=-24h
| stats latest(_time) as last_beat by host
| append
    [ | inputlookup agentmetry_expected_hosts.csv
      | eval last_beat=0
      | fields host last_beat ]
| stats max(last_beat) as last_beat by host
| eval gap_minutes = if(last_beat=0, -1, round((now() - last_beat) / 60, 1))
| eval state = case(last_beat=0, "never enrolled", gap_minutes > 15, "silent", 1=1, "ok")
| where state != "ok"
| convert ctime(last_beat)
| sort - gap_minutes
```

**No `join` on purpose.** `join` is capped by the subsearch limit (50k rows by default) and truncates silently on a real fleet, which turns a tamper alert into one that quietly stops firing. `stats` over an appended inventory has no such ceiling.

The `append` of the inventory lookup is what catches a machine that never enrolled. Without it the search can only report hosts that beat at least once, so a laptop where the recorder was never installed is invisible to the rule meant to find unmonitored machines.

---

## S6 — AI coding agent ran with no recorder behind it

**Logic:** EDR saw the IDE execute; no heartbeat arrived from that host in the same window.

The strongest of the three, because it needs no assumption about whether a machine should be online. EDR proves the machine was in use.

```spl
(index=edr process_name IN ("claude.exe","cursor.exe") earliest=-1h)
  OR (index=main sourcetype=agentmetry:json action_type=heartbeat earliest=-1h)
| eval src = if(sourcetype=="agentmetry:json", "beat", "ide")
| stats count(eval(src=="ide")) as ide_runs, count(eval(src=="beat")) as beats by host
| where ide_runs > 0 AND beats = 0
| eval finding="AI coding agent executed with no recorder heartbeat"
```

Note the time bound on **both** halves. An unbounded correlation lets a single heartbeat from six months ago suppress the alert forever, which is the failure mode where the rule looks healthy and detects nothing.

**Requires:** EDR process telemetry in the same SIEM.

---

## S7 — MCP tool schema changed (rug pull)

**Logic:** A `tools/list` fingerprint moved. The configured command in `mcp.json` often did not.

This is not a sequence-engine detection. The recorder hashes observed schemas (via `mcp_audit_proxy`) and emits `action.type=mcp_schema` only when the hash is new or different. Reconnects to an unchanged server are silent. Until a server has been listed through the proxy, `heartbeat.mcp_schema_digest` is empty; that is a gap, not a healthy default.

```spl
index=main sourcetype=agentmetry:json action_type=mcp_schema action_outcome=changed
| spath output=server_id   path=mcp_schema.server_id
| spath output=fingerprint path=mcp_schema.fingerprint
| spath output=tool_count  path=mcp_schema.tool_count
| table _time host server_id tool_count fingerprint
```

Same signal off the heartbeat, which still arrives if the schema event was dropped:

```spl
index=main sourcetype=agentmetry:json action_type=heartbeat
| spath output=cfg    path=heartbeat.mcp_config_digest
| spath output=schema path=heartbeat.mcp_schema_digest
| where schema != ""
| streamstats current=f last(schema) as prev_schema last(cfg) as prev_cfg by host
| where isnotnull(prev_schema) AND prev_schema != "" AND schema != prev_schema AND cfg == prev_cfg
| table _time host prev_schema schema cfg
```

**Alert:** Unscheduled until the fleet has a baseline. A vendor adding a tool looks identical to a poisoned description; treat the hit as an investigation.

---

## What S4 to S7 do and do not prove

They do not prevent a developer removing a hook. Nothing in user space does, and a vendor claiming otherwise is either shipping a kernel driver or overstating.

What they change is that removal stops being quiet. S4 catches the recorder running while impaired, S5 catches it not running, S6 catches an agent running with nothing behind it. S7 catches an MCP server that started telling the model something different. Someone with local admin can stop all of them; they cannot stop all of them *silently*.

---

## Saved search export

Export as **Settings → Searches, reports, and alerts → New alert** for email or webhook notification.

Homelab solo rules: [detections-loki.md](./detections-loki.md)
