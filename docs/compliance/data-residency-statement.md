# Data Residency & Local-First Statement

**Product:** Agentmetry, local-first sensor for AI coding agents
**Version:** operator-deployed package (public alpha)
**Last updated:** 2026-10-10

---

## Summary

Agentmetry processes audit events **on infrastructure you control**. The JSONL trail, SQLite index, detection checkpoint, and dashboard stay on your machine or your LAN. No multi-tenant cloud backend is required for core operation.

This supports GDPR data-minimization and deployer-side EU AI Act arguments around **data residency** and **human oversight**. It is not a guarantee of compliance.

---

## Data locations

| Data | Default location | Leaves device? |
|------|------------------|----------------|
| Audit JSONL trail | Checkout: `apps/orchestrator/data/audit-forward.jsonl`. Install: the user data directory (`agentmetry doctor` prints it) | Only if *you* configure forwarders |
| Query index | `audit.db` in the same data directory as the trail | No |
| Live detection state | `detection_live.db` in the same data directory as the trail | No |
| Demo MCP config | `vault/.system/drivers.json` | No |
| SIEM forwarders | Elastic, Splunk, Google SecOps, Microsoft Sentinel (not yet run against a live workspace), webhook, CloudEvents. Loki tails the file via Alloy | Your choice |

---

## Forwarding modes

| Sink | Config | Data path |
|------|--------|-----------|
| **File (default)** | `AGENTMETRY_AUDIT_SINK=file` | Local JSONL only |
| **Webhook / Elastic / Splunk / Google SecOps / Sentinel** | See `docs/integrations/` | Your SIEM infrastructure. Sentinel has not yet run against a live workspace |
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
