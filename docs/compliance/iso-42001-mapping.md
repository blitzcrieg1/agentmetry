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

## Evidence pack sections (schema 2.0)

The pack is built from the canonical audit trail (`audit.db`) — the same events
the dashboard and SIEM sinks see.

| Section | Contents | Governance use |
|---------|----------|----------------|
| `events` | Raw canonical events for the period | Full record; omit with `include_raw_events=False` for a summary-only pack |
| `tool_calls` | Per-call tool, `input_hash`, outcome, MITRE ids, DLP/tool-policy verdicts | What the agents actually did |
| `approvals` | Gates with `decision` and **`inferred`** | Human oversight — see the honesty note below |
| `detections` | Correlated findings with severity and contributing `event_ids` | Observed risk |
| `controls` | DLP + tool-policy **manifest SHA-256 and enforcement modes** | Which controls were in force during the period |
| `meta.trail_chain` | `head_seq`, `head_sha256`, verification result | Binds the pack to a position in the hash chain |
| `meta.integrity_sha256` | Hash over the pack body | `agentmetry verify <export.json>` |

**Read `approvals[].inferred` before citing human oversight.** No IDE reports the
human's click, so most approval responses are *derived* from the event stream and
are marked `inferred: true`. On a typical dogfood month that is the large
majority of gates. Presenting an inferred approval as an observed one would be
the single easiest way to mislead an auditor with this pack.

---

## Operator workflow (weekly governance review)

1. Export evidence for the past 7 days.
2. Review `agentmetry stats --days 7` — events, detections, denials.
3. Triage detections in dashboard; mark false positives in runbook.
4. Confirm tool policy / DLP blocks fired only on intended patterns.
5. File export + one-paragraph review note in your evidence store.

Future: automated compliance digest export — deferred until YAML custom rules land (ROADMAP Phase 2).
