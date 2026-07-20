# Data Residency & Local-First Statement

**Product:** Agentmetry — local-first SIEM for AI coding agents  
**Version:** operator-deployed appliance  
**Last updated:** 2026-07-20

---

## Summary

Agentmetry processes audit events **on infrastructure you control**. The JSONL trail, SQLite index, detection checkpoint, and dashboard stay on your machine or your LAN. No multi-tenant cloud backend is required for core operation.

This supports GDPR data-minimization and deployer-side EU AI Act arguments around **data residency** and **human oversight** — not a guarantee of compliance.

---

## Data locations

| Data | Default location | Leaves device? |
|------|------------------|----------------|
| Audit JSONL trail | `apps/orchestrator/data/audit-forward.jsonl` | Only if *you* configure forwarders |
| Query index | `apps/orchestrator/data/audit.db` | No |
| Live detection state | `apps/orchestrator/data/detection_live.db` | No |
| Demo MCP config | `vault/.system/drivers.json` | No |
| SIEM forwarders | Elastic / Splunk / webhook / Loki | Your choice |

---

## Forwarding modes

| Sink | Config | Data path |
|------|--------|-----------|
| **File (default)** | `AGENTMETRY_AUDIT_SINK=file` | Local JSONL only |
| **Webhook / Elastic / Splunk** | See `docs/integrations/` | Your SIEM infrastructure |
| **Loki homelab** | `docker-compose.loki.yml` | Your Grafana stack |

**Recommendation for regulated environments:** keep file sink as system of record; forward redacted copies to corporate SIEM when contract allows.

---

## DPIA pointer (operator task)

When using Agentmetry on developer machines that handle client credentials:

1. List processing purposes (AI agent tool-use monitoring, incident response).
2. Document legal basis and retention (JSONL + export archives).
3. Record subprocessors (only if you enable cloud SIEM forwarders).
4. Describe HITL controls (tool policy block mode, detection review workflow).
5. Attach monthly `agentmetry export --evidence` as technical annex.

Use your jurisdiction's DPIA template — this document is input, not a completed DPIA.

---

## Contact

Operator-maintained deployment. For the open-source project: see repo README.
