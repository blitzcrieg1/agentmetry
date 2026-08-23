# Agentmetry — Sigma detection pack

Portable [Sigma](https://sigmahq.io/) rules for Agentmetry canonical events, ported from the Loki/LogQL examples in [`../detections-loki.md`](../detections-loki.md). Use these to generate backend-specific queries for Elastic, Splunk, Loki, or any Sigma target instead of hand-writing per-SIEM.

| Rule | File | Severity | Intent |
|------|------|----------|--------|
| Tool denial burst | `agentmetry_tool_denial_burst.yml` | medium | Injection / policy probing / misconfigured allowlist |
| High-risk tool success | `agentmetry_highrisk_tool_success.yml` | high | Shell/exec-family tool passed the allowlist |
| MCP driver mounted | `agentmetry_mcp_driver_mounted.yml` | medium | New/unexpected MCP server joined the host (supply chain) |
| Risk accepted disposition | `agentmetry_disposition_risk_accepted.yml` | medium | Operator closed a detection as accepted risk |
| Critical detection left untriaged | `agentmetry_critical_detection_untriaged.yml` | medium | Nobody answered a CRITICAL finding. Health metric for the deployment, not the agent. Needs a backend anti-join; tested SPL, ES\|QL and LogQL are in the rule file |
| Recorder degraded | `agentmetry_recorder_degraded.yml` | medium | Recorder alive and attesting that capture is impaired: an IDE hook removed, or events buffering instead of reaching the trail. The state a liveness check cannot see |
| Recorder silent | `agentmetry_recorder_silent.yml` | informational | The heartbeat itself. Not a finding alone; the correlation notes in the file carry the absence check, including a machine that never enrolled |
| MCP tool schema changed | `agentmetry_mcp_schema_changed.yml` | medium | `tools/list` fingerprint moved. Rug pull / tool poisoning. Config digest may be unchanged; that conjunction is in the rule file |

---

## The sequence detections (generated)

The table above covers the recorder's **own health**: is it alive, is coverage
intact, did an MCP schema move, is anybody triaging. Useful, and none of it is
the product.

`agentmetry_rule_*.yml` covers the fifteen **sequence detections**, which are
what a SOC actually routes on. One file per rule, matching the detection event
in the trail:

```yaml
detection:
  selection:
    action.type: detection
    detection.rule_id: credential-exfil
  condition: selection
level: critical
tags:
  - attack.ta0006
  - attack.ta0011
  - attack.t1071.001
  - attack.t1552.004
```

Sixteen files for fifteen rules. `encoded-command-download` is deliberately two
detections: `critical` for remote code fetched and executed, `low` for local
content piped into an interpreter, where `rules.py` says the low one exists "so
it stops drowning the criticals". A single Sigma `level` would either page on
the quiet variant or stay silent on the loud one, so each gets a rule and the
selection pins `action.outcome`.

### Do not hand-edit these

They are produced by `apps/orchestrator/tools/generate_sigma_pack.py`, which
replays the benchmark corpus through the real rule engine and reads the
severities and MITRE ids off the `Detection` objects it emits. Editing a level
here creates a claim that disagrees with the code, and the code is what fires.

```bash
cd apps/orchestrator
.venv/Scripts/python.exe tools/generate_sigma_pack.py
```

Rerunning is idempotent: the rule UUIDs are derived from the rule id rather than
generated, so a consumer who pinned one keeps working.

`tests/test_sigma_pack.py` fails if a rule is added without a Sigma rule, if a
Sigma rule survives a deleted rule, or if a severity here disagrees with the
engine. Two of the fifteen (`host-subagent-swarm-burst`, `off-hours-activity`)
have no corpus case and carry an explicit entry in the generator, which is
tracked in [issue #36](https://github.com/blitzcrieg1/agentmetry/issues/36).

## Field mapping — read before deploying

Sigma rules reference the **canonical schema** ([`../../agentmetry-event-schema.md`](../../agentmetry-event-schema.md)) using dotted JSON paths (`action.type`, `tool.qualified`). **Field names differ by the sink you forward to** — you must supply the right Sigma processing pipeline for your backend, or adjust the field names:

| Sink | How fields appear | Notes |
|------|-------------------|-------|
| **Raw JSONL** (`audit-forward.jsonl`) | Nested: `action.type`, `action.outcome`, `tool.qualified` | The rules below are written against this — the source of truth |
| **Loki via Alloy** | Flattened labels: `action_type`, `action_outcome` (see `infra/loki/alloy.config`); other fields via `| json` | Map `action.type → action_type`, `action.outcome → action_outcome` in a pipeline |
| **Elastic ECS** (`adapters/ecs.py`) | Remapped toward ECS | Verify how `ecs.py` names `action.type`/`tool.qualified` before deploying — likely custom `agentmetry.*` fields alongside `event.action`/`event.outcome` |
| **Splunk HEC** (`adapters/splunk.py`) | Depends on sourcetype extraction | Verify extracted field names in your Splunk props/transforms |

> **`[verify against live JSONL]`** markers in each rule flag a field whose exact name/nesting you should confirm against your own `audit-forward.jsonl` (run the [dogfood checklist](../../agentmetry-dogfood-checklist.md) first) before trusting the rule in production. The canonical doc is authoritative for the raw JSONL; adapters may rename.

## Generating backend queries

```bash
pip install sigma-cli
# Loki
sigma convert -t loki -p loki_promtail agentmetry_tool_denial_burst.yml
# Elastic (adjust pipeline to match ecs.py field names)
sigma convert -t esql agentmetry_highrisk_tool_success.yml
# Splunk
sigma convert -t splunk agentmetry_mcp_driver_mounted.yml
```

## Coverage honesty (Tier A/B/C)

These rules detect what Agentmetry records — agents running **through the governed host**. They do **not** see unmanaged ChatGPT/Cursor/browser copilots (Tier C); that needs a CASB/secure-web-gateway, not a Sigma rule here. See the coverage section of the root README.

## Not yet covered (roadmap)

- **Approval bypass** — `approval_request` with no matching `approval_response` before a `tool_called` on the same `correlation_id`. Needs sequence correlation; better as a Sigma correlation rule once field mapping is verified live, or offline against the evidence export.
- **Exfil chain** — HTTP tool followed by file/read tools on one `correlation_id`. Sequence rule, v1.1.
