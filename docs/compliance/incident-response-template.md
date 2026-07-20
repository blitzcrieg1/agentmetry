# AI Incident / Safety Record

Copy this into `vault/30-Archive/incidents/` when something goes wrong with a Agentmetry-assisted workflow.

---

## Incident summary

| Field | Value |
|-------|-------|
| **Incident ID** | INC-YYYY-MM-DD-001 |
| **Date detected** | |
| **Detected by** | Operator / Client / System |
| **Severity** | Low / Medium / High |
| **Status** | Open / Mitigated / Closed |

---

## What happened

Describe the incident in plain language (wrong draft, hallucinated fact, wrong client context, terminated run, etc.).

---

## Affected run(s)

| thread_id | skill | decision | archive_path |
|-----------|-------|----------|--------------|
| | | approved / terminated | |

Pull from dashboard, `runs.jsonl`, or latest `agentmetry export --evidence`.

---

## Root cause (initial)

- [ ] Bad source document / stale vault context
- [ ] Skill SOP gap
- [ ] LLM hallucination
- [ ] Operator approved without reading
- [ ] Driver misconfiguration
- [ ] Other: ___

---

## Immediate actions taken

1. Terminated / did not send draft
2. Notified client (if applicable): Y/N
3. Disabled skill or driver: ___
4. Exported evidence: `evidence-…json` path ___

For **agentic security incidents** (credential chains, staged downloads, autonomous
tool floods), also follow
[`local-llm-forensics.md`](local-llm-forensics.md) — analyze the JSONL trail with
a self-hosted model when commercial APIs refuse incident payloads.

---

## Corrective actions

| Action | Owner | Due |
|--------|-------|-----|
| Update SOP in `10-Knowledge/SOPs/` | | |
| Tighten skill prompt / threshold | | |
| Add vault client link step | | |
| Retrain / brief operator | | |

---

## Sign-off

| Field | Value |
|-------|-------|
| Closed by | |
| Date closed | |
| Evidence pack attached | Y/N |
