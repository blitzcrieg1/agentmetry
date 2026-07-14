# EU AI Act — Deployer Checklist (Agentmetry Operator)

**Role mapping:** Agentmetry repo author = **provider** (tool). You, running it on client data = **deployer**.

Use this checklist when a client asks how you govern AI-assisted email, documents, and meeting follow-ups.

---

## Art. 12 — Logging & traceability

| Step | Action | Agentmetry hook |
|------|--------|---------------|
| 1 | Enable the orchestrator for all production skills | `scripts/agentmetry.bat start` |
| 2 | Do not delete `apps/orchestrator/data/events.db` or `runs.jsonl` during an audit window | Immutable outbox + ledger |
| 3 | Export monthly evidence | `agentmetry export --evidence --from … --to …` |
| 4 | Verify integrity | Pack includes `meta.integrity_sha256`; re-run verify in Python or CI |
| 5 | Archive exports | `vault/30-Archive/exports/evidence-*.json` |

**Evidence fields (schema 1.1+):** `events[]`, `runs[]`, `tool_calls[]`, `meta.provider_metadata`, `meta.tool_allowlist_snapshot`.

---

## Art. 14 — Human oversight

| Step | Action | Agentmetry hook |
|------|--------|---------------|
| 1 | Keep `approval_threshold: 1.1` on outbound skills (`customer_reply`, etc.) | Forces HITL gate every run |
| 2 | Resolve approvals only via dashboard / plugin / approved channel | `resolve_approval()` single path |
| 3 | Never enable send-after-approve until your 4-green-week gate clears | Gmail draft-only today |
| 4 | Terminate bad drafts explicitly | Reject → `RUN_TERMINATED` in outbox |
| 5 | Record why you approved | Optional note in Obsidian active loop before approve |

**Evidence fields:** `approvals[]` with `decision`, `draft`, `confidence_score`, `approval_signature`.

---

## Art. 52 — Transparency (user-facing)

| Step | Action | Agentmetry hook |
|------|--------|---------------|
| 1 | Maintain `vault/.system/AGENTS.md` persona | Injected every run |
| 2 | Write SOPs in vault (`10-Knowledge/SOPs/`) | RAG context for reply skills |
| 3 | Tell clients AI assists drafts; you review before send | Process + Gmail draft workflow |
| 4 | Optional footer on outbound mail | Add to your SOP template: *"Draft prepared with local AI assistance; reviewed by [name]."* |

---

## Art. 10 — Data governance (deployer responsibility)

| Step | Action | Agentmetry hook |
|------|--------|---------------|
| 1 | Complete a DPIA for client PII in vault + Gmail | Use [dpia pointer](./data-residency-statement.md) |
| 2 | Prefer local LLM for sensitive matters | `AGENTMETRY_LLM_PROVIDER=ollama` |
| 3 | Restrict drivers | `vault/.system/drivers.json` — disable unused MCP servers |
| 4 | Vault stays on disk you control | No cloud vault sync required |

---

## Art. 9 — Risk management

| Step | Action | Agentmetry hook |
|------|--------|---------------|
| 1 | Maintain a risk register | Copy [incident-response-template.md](./incident-response-template.md) |
| 2 | Tool allowlist enforced at MCP host | `TOOL_DENIED` events in outbox |
| 3 | Write ACL on vault | Orchestrator-only writes to `20-Active-Loops/`, `30-Archive/` |
| 4 | Review weekly stats | `agentmetry stats --days 7` |

---

## Sign-off (operator)

| Field | Value |
|-------|-------|
| Organization | |
| Operator name | |
| Date reviewed | |
| Next review | |
| Counsel consulted? (Y/N) | |
