# Agentmetry Compliance Trust-Kit (v1)

**Scope:** Deployer-ready alignment documentation — not legal advice, not certification.

Agentmetry is a **local-first governed runtime**. You (the operator) are the **AI Act deployer** when you use it for client work. This folder maps existing kernel features — human approval (IVT), event outbox, run ledger, evidence export — to common oversight questions from regulated clients.

## Contents

| File | Purpose |
|------|---------|
| [ai-act-deployer-checklist.md](./ai-act-deployer-checklist.md) | Step-by-step deployer checklist (Art. 12, 14, 52) |
| [iso-42001-mapping.md](./iso-42001-mapping.md) | How `agentmetry export --evidence` maps to ISO 42001 controls |
| [incident-response-template.md](./incident-response-template.md) | Log hallucinations, wrong drafts, or terminated runs |
| [data-residency-statement.md](./data-residency-statement.md) | Local-first / Ollama path as GDPR + AI Act mitigation |

## How to use

1. Run your normal week on Agentmetry (email, docs, meetings).
2. Once per month: `agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD`
3. Store exports in `vault/30-Archive/exports/`
4. Fill templates in this folder for your firm's risk register / client DPIA pack

## What we do **not** claim

- "EU AI Act compliant" product certification
- ISO 42001 certification for your organization
- Legal suitability for your specific use case — consult qualified counsel
