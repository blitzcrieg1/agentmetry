# Agentmetry Compliance Trust-Kit (v1)

**Scope:** Deployer-ready alignment documentation. Not legal advice, not certification.

Agentmetry is a **local-first SIEM for AI coding agents**, and it is conventional
software: deterministic sequence rules and regex, no model and no inference. It is
therefore **not itself an AI system** under the Act's definition, and installing it
does not place you under any obligation the Act creates.

The AI systems here are the **coding agents your developers run**. Your organisation
is their deployer, and Agentmetry is one way of exercising oversight over them. This
folder maps audit trail, detections, hook-boundary controls, and evidence export to
the questions that raises.

## Contents

| File | Purpose |
|------|---------|
| [ai-act-deployer-checklist.md](./ai-act-deployer-checklist.md) | Step-by-step deployer checklist (Art. 9, 10, 12, 14, 52) |
| [en-18286-mapping.md](./en-18286-mapping.md) | EN 18286:2026 clause mapping, including the clauses Agentmetry does **not** cover |
| [iso-42001-mapping.md](./iso-42001-mapping.md) | How `agentmetry export --evidence` maps to ISO 42001 controls |
| [incident-response-template.md](./incident-response-template.md) | Log agent incidents, detections, and tool denials |
| [data-residency-statement.md](./data-residency-statement.md) | Local-first audit data as GDPR + AI Act mitigation |
| [local-llm-forensics.md](./local-llm-forensics.md) | Forensic playbook when commercial APIs refuse incident payloads |

## How to use

1. Run Agentmetry on machines with AI coding agents (hooks + optional MCP proxy).
2. Once per month, produce both artifacts, because they have different readers:
   - `agentmetry export --compliance-digest --from … --to …` → Markdown summary a
     governance reviewer files (add `--json` for a machine-readable form)
   - `agentmetry export --evidence --from … --to …` → full pack an incident
     investigator queries
3. Verify: `agentmetry verify <export.json>` and `agentmetry verify --trail <trail.jsonl>`
4. Record the chain head somewhere the audited machine cannot write
5. Store exports in your org evidence store
6. Fill templates in this folder for your firm's risk register / client DPIA pack

## What we do **not** claim

- "EU AI Act compliant" product certification
- ISO 42001 certification for your organization
- Legal suitability for your specific use case; consult qualified counsel
- That your coding agents are in scope of the AI Act's high-risk regime. **They
  almost certainly are not**. Annex III does not cover coding assistants. What
  this kit supports is evidence about your **development lifecycle**, which
  matters when your organisation *builds* AI systems.
- Coverage of agents you have not wired in. Unmanaged browser assistants and
  unhooked IDEs are invisible; absence of an event proves nothing about them.
