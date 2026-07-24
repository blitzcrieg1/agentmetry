# EN 18286:2026 — Where Agentmetry Fits (and Where It Does Not)

**EN 18286** is the European AI quality-management standard published by CEN in
July 2026. Annex ZA maps its requirements to **EU AI Act Articles 11, 17 and 72**;
once cited in the Official Journal, conformity confers a **presumption of
conformity with Art. 17**.

**Honest scope:** Agentmetry is an evidence source for a small number of clauses.
It is not a QMS, and no tool can make you conformant. This page exists to say
precisely which clauses it touches — and the longer list it does not.

---

## The framing that matters

A developer using Cursor is **not** operating a high-risk AI system. Annex III
does not cover coding assistants, and anyone selling you "AI Act compliance for
your coding agents" is selling you a regulation that does not apply.

The real position is narrower and defensible:

> If your organisation **builds** AI systems, then AI coding agents are now part
> of your **development lifecycle** — and EN 18286 cl. 6, ISO/IEC 5338 and
> ISO/IEC 42001 all require you to control and evidence that lifecycle.

Agentmetry produces process evidence for that development activity. It says
nothing about the AI system you ship.

---

## Clauses Agentmetry provides evidence for

| Clause | Requirement | Agentmetry evidence | Command |
|--------|-------------|---------------------|---------|
| **cl. 5** Product Realization — record-keeping | Technical records covering development activity | Canonical trail: every captured agent tool call with `input_hash`, MITRE ids, session boundaries | `agentmetry export --evidence` |
| **cl. 6** Operation & Control — change control | Controlled, recorded changes across the lifecycle | Which agent changed what, under which policy configuration; `controls` section records DLP + tool-policy manifest hashes and modes in force | `evidence.controls` |
| **cl. 6** Operation & Control — post-market surveillance | Monitoring plan with incident capability | Detections streamed as first-class events; hash-chained trail supports reconstruction inside Art. 73 windows | [local-llm-forensics.md](local-llm-forensics.md) |
| **cl. 7** Performance Evaluation | Periodic review with real inputs | Weekly metrics: events, detections by rule/severity, denials, DLP hits | `agentmetry stats --days 7` |
| **cl. 8** Improvement | Corrective action driven by findings | Detection triage workflow; rule and manifest changes are themselves version-controlled and hashed into the pack | `evidence.detections` |

**Cross-reference:** EU AI Act Art. 12 (record-keeping), Art. 15 (cybersecurity of
the development chain), Art. 17 (QMS), Art. 72 (post-market monitoring). See the
[deployer checklist](ai-act-deployer-checklist.md).

---

## Clauses Agentmetry does NOT help with

Stated plainly, because a mapping with no gaps is not credible.

| Clause | Why not |
|--------|---------|
| **cl. 1–2** General & documentation requirements | Organisational scope, QMS documentation structure — a management task, not a telemetry one |
| **cl. 3** Management responsibility | Leadership accountability, quality policy, role assignment |
| **cl. 4** Planning & support | Competence, training, awareness, resourcing |
| **cl. 5** Data governance & technical documentation *of the AI system* | Agentmetry records the **development process**, not your training data, model cards, or system documentation |
| **cl. 5** Risk management *of the AI system* | Detections are observed-risk telemetry about agent behaviour; they are not an Art. 9 risk management system |
| **cl. 6** Supplier management | No vendor assessment capability |
| **Annex A** Affected-person engagement | Entirely outside a developer-tool boundary |
| **Conformity assessment / certification** | Agentmetry is not a notified body and produces no conformity evidence for the AI system itself |

Additionally: **Agentmetry sees only the agents you wire in.** Unmanaged browser
assistants and unhooked IDEs are invisible. Absence of an event is not evidence
that nothing happened.

---

## Relationship to the ISO standards

| Standard | Role | Agentmetry |
|----------|------|------------|
| **EN 18286** | European QMS, presumption of conformity with AI Act Art. 17 | Record-keeping + operation/control evidence (this page) |
| **ISO/IEC 42001** | Certifiable AI management system | Annex A control evidence — [mapping](iso-42001-mapping.md) |
| **ISO/IEC 23894** | AI risk management guidance (imported by 42001) | Detections as risk-monitoring input to your register |
| **ISO/IEC 5338** | AI system life cycle processes | Operation & monitoring phase evidence |

**Important:** ISO/IEC 42001 conformity alone does **not** satisfy EN 18286.
Annex D links the two, but they are complementary, not substitutable. If you are
already 42001-certified, EN 18286 is an additional step, not a re-badge.

---

## Suggested audit workflow

1. Export monthly: `agentmetry export --evidence --from … --to …`
2. Verify the pack: `agentmetry verify <export.json>`
3. Verify the chain it points at: `agentmetry verify --trail <audit-forward.jsonl>` — compare `meta.trail_chain.head_sha256` in the pack against the current chain head
4. Record the chain head somewhere the audited machine cannot write. A local hash chain proves in-place edits and reordering; it cannot prove the file was not truncated. This step is what closes that gap
5. Review `summary.detections_by_severity` and file the triage outcome
6. Confirm `controls` shows the enforcement modes you intended for the period

---

*Not legal advice. Map requirements to your risk classification with qualified
counsel.*
