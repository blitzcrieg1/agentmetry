# Local LLM forensics on Agentmetry trails

**Context:** [Hugging Face security incident disclosure (July 2026)](https://github.com/huggingface/blog/blob/main/security-incident-july-2026.md)  
**Last updated:** 2026-07-20

---

## Why this document exists

During the July 2026 intrusion, Hugging Face reconstructed a **17,000-event**
attacker log using LLM-driven analysis. Their first attempt used **frontier
models behind commercial APIs**. That failed: safety guardrails blocked requests
containing real exploit payloads, C2 artifacts, and credential material. Forensics
ran instead on **GLM 5.2 self-hosted** — no attacker data left their environment.

HF calls this the **asymmetry problem**: attackers are not bound by usage
policies; defenders doing incident response often are, unless they have a local
model ready *before* the breach.

Agentmetry is built for that gap:

| Asset | Location |
|-------|----------|
| Session tool-call trail | `audit-forward.jsonl` (hash-chained) |
| Structured export | `agentmetry export --evidence --from … --to …` |
| Integrity check | `agentmetry verify --trail` / `agentmetry verify <export.json>` |
| Optional local inference | Ollama (`AGENTMETRY_LLM_PROVIDER=ollama`) |

Nothing in core operation requires sending your trail to a third-party API.

---

## When to use local LLM forensics

Use a self-hosted model when:

- Detections fired (`credential-exfil`, `remote-staging-then-execute`, etc.) and
  you need a **narrative timeline** across hundreds of events in one session.
- You must analyze commands that **hosted APIs will refuse** (shell cradles,
  encoded payloads, live tokens in context).
- Compliance or contract terms **forbid** uploading incident artifacts to
  commercial LLM providers.
- You want to **correlate IoCs** (hosts touched, files read, credentials
  referenced) faster than manual JSONL scrolling.

Agentmetry sequence rules still do the **alerting**. Local LLM analysis is for
**triage depth** after an alert — the same division of labour HF described.

---

## Prerequisites

1. Agentmetry installed and hooks active during the incident window.
2. Trail file or evidence export for the date range.
3. A local model runtime (Ollama recommended) with enough context for chunked
   analysis — 32k+ context preferred for dense sessions.
4. **Rotate any credentials** referenced in the trail before sharing chunks with
   anyone else, even on localhost logs.

---

## Step 1 — Preserve and verify the trail

```powershell
# Verify hash chain (reports legacy unchained prefix lines separately)
agentmetry verify --trail vault/30-Archive/audit-forward.jsonl

# Or export a bounded evidence pack with SHA-256 integrity
agentmetry export --evidence --from 2026-07-18 --to 2026-07-20
agentmetry verify vault/30-Archive/exports/evidence-2026-07-18_to_2026-07-20.json
```

Copy the export to your incident folder (`vault/30-Archive/incidents/`). Treat it
as read-only evidence.

---

## Step 2 — Isolate the session(s)

Find the `correlation_id` from:

- Dashboard **Detections** strip or session search
- JSONL grep: `"correlation_id": "sess-…"`
- API: `GET /api/v1/audit/detections/{correlation_id}`

Extract events for that session only. Order by `timestamp_utc`.

For CLI-oriented workflows, filter the trail:

```powershell
# PowerShell: events for one correlation_id (requires jq or manual filter)
Get-Content vault/30-Archive/audit-forward.jsonl |
  Where-Object { $_ -match '"correlation_id":"sess-exfil-abc"' }
```

---

## Step 3 — Chunk for the model

LLMs hit context limits. Chunk by:

- **One correlation_id per chunk** when possible (Agentmetry's unit of sequence
  detection).
- **~50–100 events** per chunk for very long autonomous runs.
- Include metadata once per chunk: `correlation_id`, `host_id`, detection
  `rule_id`s already fired, time span.

Redact before prompting if the chunk will be archived outside the evidence pack:

- DLP already scrubs many secret patterns at ingest; still assume **live paths
  and hostnames** may be sensitive.
- Do not paste production credentials into prompts — reference `T1552` events by
  file path pattern only.

---

## Step 4 — Prompt template (copy and adapt)

```text
You are an incident responder analyzing a governed AI coding agent session.
The JSON below is a time-ordered list of tool-call audit events from Agentmetry.
Each event may include tool.qualified, tool.command, action.outcome, and
tool.mitre {tactic_id, technique_id}.

Tasks:
1. Reconstruct a timeline in plain language (UTC).
2. List indicators of compromise: remote hosts, files read, cloud APIs invoked.
3. Separate decoy/noise from actions that changed state or reached the network.
4. Map phases: credential access → cloud/cluster use → egress/exfil → persistence.
5. Suggest immediate containment: credentials to rotate, sessions to kill.

Known detections already fired: [paste rule_id list]

Events:
[paste JSON array chunk]
```

Run each chunk; merge timelines manually or ask the model to reconcile overlaps
using shared `event_id`s.

---

## Step 5 — Containment checklist

After analysis, regardless of model output:

- [ ] Rotate tokens for every credential path touched (AWS, GitHub, HF, kube, etc.)
- [ ] Revoke active agent sessions / API keys for the affected operator account
- [ ] Review git remotes pushed to during the window
- [ ] File incident record: [`incident-response-template.md`](incident-response-template.md)
- [ ] Attach evidence export path and detection `correlation_id`s
- [ ] If partner/customer data may be involved, follow your breach notification process

---

## What Agentmetry does *not* replace

This playbook covers **endpoint agent sessions** on machines you instrument.
It does not replace:

- Platform pipeline sandboxing (e.g. dataset `trust_remote_code` workers)
- Kubernetes admission control or cloud IAM review
- Fleet-wide SIEM correlation across thousands of ephemeral sandboxes

Sequence rules (`credential-read-then-cloud-api`, `remote-staging-then-execute`,
`dotfile-read-then-git-push`) alert on **patterns** from the HF disclosure when
they appear in hooked agent sessions. Local LLM forensics helps you **understand
the session** when hosted models refuse to look.

---

## References

- [HF July 2026 security incident disclosure](https://github.com/huggingface/blog/blob/main/security-incident-july-2026.md) — asymmetry problem, 17k-action swarm
- [Agentmetry evidence pack format](../evidence-pack-format.md)
- [Data residency statement](data-residency-statement.md) — Ollama / local-first modes
- [Incident response template](incident-response-template.md)
