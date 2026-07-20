# EU AI Act — Deployer Checklist (Agentmetry SIEM)

**Role mapping:** Agentmetry repo author = **provider** (tool). You, running it on
developer workstations = **deployer**.

Use this checklist when a client asks how you govern **AI coding agents**
(Cursor, Claude Code, Codex, MCP tools) — not outbound email automation.

---

## Art. 12 — Logging & traceability

| Step | Action | Agentmetry hook |
|------|--------|-----------------|
| 1 | Run the orchestrator on every machine with AI agents | `scripts/agentmetry.bat start` |
| 2 | Do not delete `audit-forward.jsonl` or `audit.db` during an audit window | JSONL hash chain + SQLite index |
| 3 | Export monthly evidence | `agentmetry export --evidence --from … --to …` |
| 4 | Verify integrity | `agentmetry verify --trail audit-forward.jsonl` |
| 5 | Archive exports | Your org's evidence store (local or SIEM) |

**Evidence fields (schema 1.1+):** `correlation_id`, `host_id`, `tool.input_hash`,
`detection.*`, `dlp.rule_id`, `tool_policy.rule_id`.

---

## Art. 14 — Human oversight

| Step | Action | Agentmetry hook |
|------|--------|-----------------|
| 1 | Enable tool policy **block** mode for destructive patterns | `AGENTMETRY_TOOL_POLICY_MODE=block` |
| 2 | Review detections in dashboard Detections tab | Live + durable in JSONL |
| 3 | Treat hook **deny** as pre-execution control; post-ingest policy as annotation only | See `core/audit/policy.py` |
| 4 | Export correlation packs for incidents | `agentmetry export --evidence` |

---

## Art. 52 — Transparency (user-facing)

| Step | Action | Agentmetry hook |
|------|--------|-----------------|
| 1 | Document which IDEs/agents are monitored | Hook install scripts in `scripts/` |
| 2 | Tell developers tool calls are logged locally | Process + README |
| 3 | Optional: disclose AI assistance in commit messages / PRs | Org policy, not product-enforced |

---

## Art. 10 — Data governance (deployer responsibility)

| Step | Action | Agentmetry hook |
|------|--------|-----------------|
| 1 | Complete a DPIA for developer credentials in audit trails | [data residency statement](./data-residency-statement.md) |
| 2 | Use DLP block mode on pre-hooks for secrets | `AGENTMETRY_DLP_MODE=block` |
| 3 | Restrict MCP servers | `vault/.system/drivers.json` — enable only needed drivers |
| 4 | Audit data stays on disk you control | Local-first by default |

---

## Art. 9 — Risk management

| Step | Action | Agentmetry hook |
|------|--------|-----------------|
| 1 | Maintain a risk register | [incident-response-template.md](./incident-response-template.md) |
| 2 | Tool allow/deny at hook boundary | `policies/tool/manifest.yaml` |
| 3 | Sequence detections for agentic abuse | `core/audit/detection/rules.py` |
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
