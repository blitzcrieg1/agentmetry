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
| **Cl. 10 Improvement (corrective action)** | `dispositions` + `detections[].disposition` | Each finding's decision, decider, timestamp and written justification, recorded as an event on the same hash chain |

---

## Evidence pack sections (schema 2.1)

The pack is built from the canonical audit trail (`audit.db`) — the same events
the dashboard and SIEM sinks see.

| Section | Contents | Governance use |
|---------|----------|----------------|
| `events` | Raw canonical events for the period | Full record; omit with `include_raw_events=False` for a summary-only pack |
| `tool_calls` | Per-call tool, `input_hash`, outcome, MITRE ids, DLP/tool-policy verdicts | What the agents actually did |
| `approvals` | Gates with `decision` and **`inferred`** | Human oversight — see the honesty note below |
| `detections` | Correlated findings with severity, contributing `event_ids`, and the `disposition` in force | Observed risk, and whether anyone acted on it |
| `dispositions` | Triage decisions recorded during the period, oldest first | Corrective action (cl. 10) |
| `summary.detections_untriaged` | Findings with no human decision at all | The honest measure of whether detection is operating as a control |
| `controls` | DLP + tool-policy **manifest SHA-256 and enforcement modes** | Which controls were in force during the period |
| `meta.trail_chain` | `head_seq`, `head_sha256`, verification result | Binds the pack to a position in the hash chain |
| `meta.integrity_sha256` | Hash over the pack body | `agentmetry verify <export.json>` |

**Read `summary.detections_untriaged` before citing detection as a control.** A
detection nobody dispositioned evidences that the system noticed, not that
anyone acted. Closing a finding as a false positive or an accepted risk requires
a written reason: the product refuses the decision without one, because an
unexplained dismissal is the entry an auditor will question first.

**Read `approvals[].inferred` before citing human oversight.** No IDE reports the
human's click, so most approval responses are *derived* from the event stream and
are marked `inferred: true`. On a typical dogfood month that is the large
majority of gates. Presenting an inferred approval as an observed one would be
the single easiest way to mislead an auditor with this pack.

---

## Operator workflow (weekly governance review)

1. Export evidence for the past 7 days.
2. Review `agentmetry stats --days 7` — events, detections, denials.
3. Triage every new detection in the dashboard (Detections -> Triage). Filter to
   **Untriaged only** and drive it to zero. Closing as *false positive* or
   *accepted risk* requires a note; that note is the corrective-action record.
4. Confirm tool policy / DLP blocks fired only on intended patterns.
5. File export + one-paragraph review note in your evidence store.

Run `agentmetry export --compliance-digest --from ... --to ...` for the filing
artifact: it states the untriaged count first, lists every decision made in the
period with its justification, and says plainly when the period evidences
detection rather than prevention.
