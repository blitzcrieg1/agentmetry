# Agentmetry Compliance Trust-Kit (v1)

**Scope:** Deployer-ready alignment documentation — not legal advice, not certification.

Agentmetry is a **local-first SIEM for AI coding agents**. You (the operator) are the **AI Act deployer** when you use it to monitor developer workstations. This folder maps audit trail, detections, hook-boundary controls, and evidence export to common oversight questions.

## Contents

| File | Purpose |
|------|---------|
| [ai-act-deployer-checklist.md](./ai-act-deployer-checklist.md) | Step-by-step deployer checklist (Art. 9, 10, 12, 14, 52) |
| [iso-42001-mapping.md](./iso-42001-mapping.md) | How `agentmetry export --evidence` maps to ISO 42001 controls |
| [incident-response-template.md](./incident-response-template.md) | Log agent incidents, detections, and tool denials |
| [data-residency-statement.md](./data-residency-statement.md) | Local-first audit data as GDPR + AI Act mitigation |
| [local-llm-forensics.md](./local-llm-forensics.md) | Forensic playbook when commercial APIs refuse incident payloads |

## How to use

1. Run Agentmetry on machines with AI coding agents (hooks + optional MCP proxy).
2. Once per month: `agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD`
3. Store exports in your org evidence store
4. Fill templates in this folder for your firm's risk register / client DPIA pack

## What we do **not** claim

- "EU AI Act compliant" product certification
- ISO 42001 certification for your organization
- Legal suitability for your specific use case — consult qualified counsel
