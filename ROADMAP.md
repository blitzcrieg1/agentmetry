# Roadmap

Agentmetry is in **public alpha**, moving toward **beta** as a **local-first mini-SIEM
for AI coding agents**. Nothing here is a promise with a date — it is direction,
grounded in [GLM 5.2 research](docs/glm-52-roadmap-research-prompt-2026-07-16.md)
(July 2026) and operator dogfood.

**Primary persona:** security engineer / DevSecOps who needs tamper-evident agent
tool-use logs and sequence detections without Docker or a cloud ledger.

**Secondary persona:** EU dev shop / compliance-aware deployer (GDPR sovereignty,
EU AI Act record-keeping narrative).

**We will not build in the next 12 weeks:** multi-tenant cloud SaaS, LangGraph
kernel rewrites, email autopilot, or Datadog-scale platform parity.

Open or upvote an [issue](https://github.com/blitzcrieg1/agentmetry/issues) if an
item matters to you.

---

## Shipped

- **Capture** — IDE lifecycle hooks (Cursor, Claude Code, Codex, Antigravity) and
  an MCP stdio audit proxy, normalized to canonical schema v1.1.0.
- **MITRE ATT&CK** — per-tool tactic/technique tagging, including credential-access
  (T1552) upgrades when a read touches a key or secret file.
- **Local DLP** — regex engine (AWS keys, GitHub PATs, Slack tokens, bearer
  headers, private keys, US SSN) with a Luhn validator, `log`/`block` modes, and
  scrubbing before storage at the hook boundary.
- **Correlated detection** — sequence-rule engine: `credential-exfil`,
  `approval-denied-then-executed`, `encoded-command-download`,
  `pr-merged-without-review`, `untrusted-input-then-risky-action`,
  `destructive-delete-burst`, `autonomous-unapproved-write`,
  `discovery-then-collect`, and opt-in `off-hours-activity`. Includes Agent Data
  Injection chains ([arXiv:2607.05120](https://arxiv.org/abs/2607.05120)).
  Detections stream to sinks as first-class events.
- **SIEM forwarding** — file, webhook, Elastic ECS, Splunk HEC, Loki/LogQL, Sigma
  pack, alert webhook.
- **Dashboard Phase 1** — nano-inspired hunt layout: icon rail, detections strip,
  event histogram, split-pane inspector, light/dark mode, CSV/JSONL export, feed
  status in header (`apps/dashboard/`).
- **Evidence** — export packs with SHA-256 integrity hash; `agentmetry verify`
  for evidence JSON.
- **JSONL hash chain** — file sink writes tamper-evident chained envelopes;
  `agentmetry verify --trail <audit-forward.jsonl>` validates the chain (legacy
  unchained prefix lines are reported separately).
- **Ops CLI** — `agentmetry doctor`, `agentmetry stats`, `agentmetry export`.
- **Compliance trust-kit** — [`docs/compliance/`](docs/compliance/) (AI Act
  checklist, ISO mapping, data residency statement).
- **Legal** — Apache 2.0 + CLA workflow (July 2026).
- **Durable live detection state** — SQLite checkpoint for emitted rules and
  session event windows (`core/audit/detection/live_store.py`); survives
  orchestrator restart without re-firing detections.
- **Windows one-flow install** — `scripts/install.ps1` (venv, dashboard deps,
  IDE hooks, doctor).
- **Visual truth** — README, agentmetry.ai, and `docs/assets/demo.gif` match Phase 1
  dashboard and live demo output.

---

## Phase 0 — Beta readiness (weeks 1–2)

Goal: fix trust gaps before calling the product beta-ready.

| Priority | Item | Where | Done when |
|----------|------|-------|-----------|
| P1 | **README scope trim** | `README.md` | SIEM story first; Obsidian/LangGraph runtime under “Advanced” |
| P1 | **Dogfood weekly log** | issue template or operator notes | Events/week, detections/week, false positives, install attempts tracked |

**Phase 0 P0 items are shipped.** Next focus: README scope trim and dogfood logging.

---

## Phase 1 — Trust & demo (weeks 3–6)

| Priority | Item | Where | Done when |
|----------|------|-------|-----------|
| P0 | **Tool allow/deny policy YAML** | alongside existing DLP manifest | Block disallowed shell/MCP before execution (extend hooks, not replace DLP) |
| P1 | **Dogfood metrics in CLI/dashboard** | `agentmetry stats --days 7` surfaced in UI | Operator sees weekly ingest/detection counts without SQL |
| P1 | **Marketing `.gr` / `.ai` alignment** | `ai-audit-watch` | Canonical URL set; EU copy block on `.gr`; no “AI Audit Watch” residue |
| P1 | **More detection rules** | `core/audit/detection/rules.py` | e.g. rapid-fire denials, package-install tampering (~20 lines + tests each) |

---

## Phase 2 — Community & SIEM depth (weeks 7–10)

| Priority | Item | Where | Done when |
|----------|------|-------|-----------|
| P1 | **OTLP export** | `core/audit/` sinks | Forwards to Jaeger / OTel collector |
| P1 | **YAML custom rules** | loader + docs | External contributor adds rule without editing Python core |
| P1 | **Detection benchmark fixtures** | `tests/fixtures/` or `bench/` | CI runs rules against synthetic attack JSONL |
| P2 | **More IDE hosts** | `scripts/` hooks | Windsurf, VS Code Copilot |
| P2 | **Richer DLP** | DLP manifest | Source-code / PII heuristics beyond regex |

---

## Phase 3 — Optional enterprise lane (weeks 11–12)

| Priority | Item | Where | Done when |
|----------|------|-------|-----------|
| P2 | **Cursor hook partner doc** | `docs/` | Third party can forward hook events into Agentmetry JSONL |
| P2 | **Compliance kit v2** | `docs/compliance/` | Hash-chain verify mapped to EU AI Act Art. 12 checklist |
| P2 | **Framework adapters** | `adapters/` | LangChain / AutoGen listeners (CrewAI / OpenSRE pattern) |

---

## Exploring (no dates)

- **Policy-as-code** — OPA / Rego alongside YAML tool policy.
- **MCP transport** — SSE / streamable-HTTP audit proxy in addition to stdio.
- **Threat-intel interop** — STIX/TAXII export of detections.
- **More sinks** — Datadog, New Relic.
- **Repo split** — isolate Obsidian/LangGraph runtime only if GitHub positioning
  stays confused after README trim (not a default week-1 action).

---

## Beta gates (operator)

Declare **beta** only when all are true:

1. **4 consecutive green dogfood weeks** — no orchestrator crashes; detection
   checkpoint survives restarts ([checklist](docs/agentmetry-dogfood-checklist.md)).
2. **`agentmetry doctor` green** on three distinct Windows 11 setups.
3. **`agentmetry verify --trail`** demonstrated in README.
4. **agentmetry.ai hero** matches local Phase 1 dashboard.

**Weekly metrics to log:** events captured, detections fired, false positives,
install success (manual count is fine).

**Design partner / paid pilot:** defer until after beta; inbound EU consultancy
interest only.

---

## Competitive focus (why this order)

Agentmetry wins today on **multi-IDE capture**, **MITRE-mapped sequence
detections**, and **SIEM forwarding without a cloud ledger**. Peers
(AgentLens, mcp-audit, mcp-tap) lead on **install UX**, **HMAC/hash-chain
narrative**, and **OTLP**. The phases above close that gap without abandoning
the local-first wedge.

---

## How to help

Best contributions: **detection rules**, **DLP patterns**, **SIEM adapters**,
**YAML rules** (once loader lands) — each small, testable, self-contained.

See [Contributing](CONTRIBUTING.md) and
[good first issues](https://github.com/blitzcrieg1/agentmetry/issues).
