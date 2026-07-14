# ISO/IEC 42001 — Alignment Mapping (Not Certification)

**Honest scope:** Agentmetry provides **evidence hooks** so *you* can run an AI management system. We do not certify your organization.

Export command: `agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD`

---

## Control mapping

| ISO 42001 control | Agentmetry evidence | Substantiation |
|-------------------|-------------------|----------------|
| **A.5.2 AI system life cycle** | `runs[]` + `30-Archive/` closeouts | Each run: skill name, trigger, status, archive path, `sop_version_hash` |
| **A.5.3 Transparency** | `vault/.system/skill-definitions/*.yaml` | Skills are declarative SOPs, not opaque prompts |
| **A.8.2 Logging & monitoring** | `events.db` outbox + `events[]` in export | TOOL_CALLED / TOOL_DENIED with seq + timestamp |
| **A.8.4 Human-in-the-loop** | `approvals[]` + `core/kernel/interrupts.py` | Hard interrupt before finalize on gated skills |
| **A.8.10 Integrity / security** | `meta.integrity_sha256` | SHA-256 over export body; tamper check via `verify_evidence_pack()` |

---

## Export schema fields (v1.1)

| Field | Location | Purpose |
|-------|----------|---------|
| `approval_signature` | `approvals[]` | SHA-256(thread_id \| decided_at \| session_id) |
| `sop_version_hash` | `runs[]` | SHA-256 of skill YAML used |
| `confidence_score` | `approvals[]` | Critic score at HITL gate |
| `provider_metadata` | `meta` | LLM provider + model at export time |
| `tool_allowlist_snapshot` | `meta` | SHA-256 of `drivers.json` at export time |

---

## Operator workflow (weekly governance review)

1. Export evidence for the past 7 days.
2. Check `summary.approvals_granted` vs `summary.approvals_terminated`.
3. Spot-check one `approval` row: draft text matches what you sent.
4. Confirm `tool_denials` = 0 unless you intentionally blocked a driver.
5. File export + one-paragraph review note in `30-Archive/`.

Future: `compliance_digest` skill (Q3) automates steps 2–4 — deferred until email/doc dogfood gate clears.
