# Roadmap

Agentmetry is in public alpha. This is where it's going. Nothing here is a
promise with a date — it's the direction, and it's open to contribution. If an
item matters to you, open or upvote an [issue](https://github.com/blitzcrieg1/agentmetry/issues).

## Shipped

- **Capture** — IDE lifecycle hooks (Cursor, Claude Code, Codex, Antigravity) and
  an MCP stdio audit proxy, normalized to canonical schema v1.1.0.
- **MITRE ATT&CK** — per-tool tactic/technique tagging, including credential-access
  (T1552) upgrades when a read touches a key or secret file.
- **Local DLP** — regex engine (AWS keys, GitHub PATs, Slack tokens, bearer
  headers, private keys, US SSN) with a Luhn validator, `log`/`block` modes, and
  scrubbing before storage.
- **Correlated detection** — a sequence-rule engine that fires on patterns a
  single event can't reveal: `credential-exfil`, `approval-denied-then-executed`,
  `encoded-command-download`, `autonomous-unapproved-write`,
  `discovery-then-collect`. Detections stream to the sinks as first-class
  events, not just on query.
- **SIEM forwarding** — file, webhook, Elastic ECS, Splunk HEC, Loki/LogQL, plus
  a Sigma pack and an alert webhook.
- **Dashboard** — live flight recorder, session drill-down, analytics.
- **Evidence** — tamper-evident export packs with SHA-256 integrity hashes.

## Near term

- **More detection rules** — rapid-fire denials, destructive-delete bursts,
  off-hours autonomous activity. Rules are pure functions over a session's
  events (`core/audit/detection/rules.py`); adding one is ~20 lines plus tests.
- **Durable detection state** — live correlation is currently in-memory and
  per-process; make alerting continuity survive a restart.
- **More IDE / agent hosts** — Windsurf, VS Code Copilot.
- **More agent frameworks** — LangChain and AutoGen listeners, following the
  same shape as the [CrewAI adapter](adapters/crewai/).
- **Richer DLP** — source-code and PII heuristics beyond regex; per-rule
  validators.

## Exploring

- **Policy-as-code** — OPA / Rego rules (e.g. "this agent may run `kubectl get`
  but never `kubectl exec`") alongside the regex DLP manifest.
- **MCP transport** — SSE / streamable-HTTP audit proxy in addition to stdio.
- **Threat-intel interop** — STIX/TAXII export of detections.
- **More sinks** — Datadog, New Relic.

## How to help

The best contributions are detection rules, DLP patterns, and SIEM adapters —
each is small, testable, and self-contained. See
[Contributing](CONTRIBUTING.md) and the
[good first issues](https://github.com/blitzcrieg1/agentmetry/issues).
