# ISO/IEC 42001 — Alignment Mapping (Not Certification)

**Honest scope:** Agentmetry provides **evidence hooks** so *you* can run an AI management system. We do not certify your organization.

Export command: `agentmetry export --evidence --from YYYY-MM-DD --to YYYY-MM-DD`

---

## Control mapping

| ISO 42001 control | Agentmetry evidence | Substantiation |
|-------------------|-------------------|----------------|
| **A.5.2 AI system life cycle** | Audit JSONL + correlation exports | Session boundaries via `correlation_id` / `host_id` |
| **A.5.3 Transparency** | Canonical schema + MITRE tags | Tool calls mapped to ATT&CK tactics/techniques |
| **A.8.2 Logging & monitoring** | `audit.db` + `audit-forward.jsonl` | `tool_called` / `detection` events with timestamps |
| **A.8.4 Human-in-the-loop** | Tool policy + DLP block at hook boundary | Pre-execution deny on configured rules |
| **A.8.10 Integrity / security** | JSONL hash chain + `meta.integrity_sha256` on evidence packs | `agentmetry verify --trail` |

---

## Export schema fields (v1.1)

| Field | Location | Purpose |
|-------|----------|---------|
| `correlation_id` | All session events | Groups one agent conversation |
| `host_id` | All events | Workstation identity |
| `tool.input_hash` | Tool events | Tamper-evident args without plaintext |
| `detection.*` | Detection events | Correlated rule findings |
| `tool_allowlist_snapshot` | `meta` | SHA-256 of `drivers.json` at export time |

---

## Operator workflow (weekly governance review)

1. Export evidence for the past 7 days.
2. Review `agentmetry stats --days 7` — events, detections, denials.
3. Triage detections in dashboard; mark false positives in runbook.
4. Confirm tool policy / DLP blocks fired only on intended patterns.
5. File export + one-paragraph review note in your evidence store.

Future: automated compliance digest export — deferred until YAML custom rules land (ROADMAP Phase 2).
