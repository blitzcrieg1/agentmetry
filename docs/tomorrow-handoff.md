# Tomorrow Handoff — AgentAudit OSS (resume 2026-07-12)

**Read this first.** Product identity pivoted from Path B / consumer SaaS to **AgentAudit** — solo-first governed agent flight recorder with SIEM-agnostic forwarders. Implementation **Weeks 1–4 done in repo (uncommitted unless operator asked).**

| Link | Purpose |
|------|---------|
| [agent-audit-event-schema.md](./agent-audit-event-schema.md) | Canonical JSON, env vars, topic mapping |
| [integrations/loki-homelab.md](./integrations/loki-homelab.md) | Free homelab SIEM (Docker) |
| [integrations/elastic-ecs.md](./integrations/elastic-ecs.md) | Enterprise Elastic adapter |
| [integrations/splunk-hec.md](./integrations/splunk-hec.md) | Splunk HEC adapter |
| [glm-52-agentaudit-siem-research-prompt.md](./glm-52-agentaudit-siem-research-prompt.md) | GLM research prompt (already run) |
| [claude-agentaudit-launch-sequence-prompt.md](./claude-agentaudit-launch-sequence-prompt.md) | **Launch drafting** — README → dogfood → Loom → LinkedIn → Sigma (sequenced) |
| [claude-agentaudit-continuation-prompt.md](./claude-agentaudit-continuation-prompt.md) | Broader pivot context + Week 5 tasks |

**Strategy:** **OSS + LinkedIn + IRT credibility** — not Stripe, not buyer Phase 0. Lead with **local flight recorder**; SIEM export optional. **Tier C honesty:** no visibility into unmanaged Cursor/ChatGPT without CASB.

---

## What we built (2026-07-11 sessions — Weeks 1–4)

### Week 1–2 — Core
| Shipped | Path / detail |
|---------|----------------|
| Approval events | `run/approval_granted`, `run/approval_denied` in `service.py` |
| Tool arg hashing | `arguments_sha256` on **all** tool calls + denials (`host.py`) |
| Canonical normalizer | `core/audit/canonical.py` → schema v1.0.0 |
| JSONL forwarder | `core/bus/audit_exporter.py` bus subscriber |
| Replay CLI | `blackbox replay <thread_id>` |
| Config | `BLACKBOX_OPERATOR_ID`, `BLACKBOX_AUDIT_*` in `config.py` |
| Schema doc | `docs/agent-audit-event-schema.md` |

### Week 3 — Homelab + webhook
| Shipped | Path / detail |
|---------|----------------|
| Pluggable sinks | `core/audit/sinks.py` — file, webhook, multi |
| Loki stack | `docker-compose.loki.yml` + `infra/loki/alloy.config` |
| Homelab doc | `docs/integrations/loki-homelab.md` |
| LogQL detections | `docs/integrations/detections-loki.md` (3 rules) |

### Week 4 — Enterprise adapters
| Shipped | Path / detail |
|---------|----------------|
| Elastic ECS | `core/audit/adapters/ecs.py` + `ElasticEcsSink` |
| Splunk HEC | `core/audit/adapters/splunk.py` + `SplunkHecSink` |
| Multi-sink modes | `BLACKBOX_AUDIT_SINK=file,elastic,splunk` or `all` |
| Docs | `elastic-ecs.md`, `splunk-hec.md`, `detections-elastic.md`, `detections-splunk.md` |

### Tests
**257 passed, 2 skipped** (orchestrator) — includes `test_agent_audit.py`, `test_replay.py`, `test_audit_sinks.py`.

---

## Architecture (one line)

```
Skills/MCP → EventBus → outbox (SQLite, never drop)
                      → audit_exporter → file | webhook | Elastic | Splunk
```

- **SoR:** `apps/orchestrator/data/events.db`
- **Forward file:** `apps/orchestrator/data/audit-forward.jsonl`
- **Wire:** `api/main.py` starts `audit_exporter` alongside `outbox_persister`

---

## Env cheat sheet (`apps/orchestrator/.env`)

```text
BLACKBOX_OPERATOR_ID=home-lab
BLACKBOX_AUDIT_EXPORT_ENABLED=1
BLACKBOX_AUDIT_SINK=file                    # file | webhook | both | elastic | splunk | all | comma-separated

# Optional webhook
BLACKBOX_AUDIT_WEBHOOK_URL=http://127.0.0.1:8080/ingest

# Optional Elastic
BLACKBOX_AUDIT_ELASTIC_URL=https://elastic.example:9200
BLACKBOX_AUDIT_ELASTIC_INDEX=logs-agentaudit
BLACKBOX_ELASTIC_API_KEY=id:secret

# Optional Splunk HEC
BLACKBOX_AUDIT_SPLUNK_HEC_URL=https://splunk.example:8088
BLACKBOX_SPLUNK_HEC_TOKEN=...
```

---

## Tomorrow — start here (pick one)

### Track A — Dogfood + demo (recommended)

1. `scripts\blackbox.bat start` → run any skill with tool use
2. `Get-Content apps\orchestrator\data\audit-forward.jsonl -Tail 5`
3. `blackbox replay <thread_id>` from dashboard/logs
4. Optional homelab: `docker compose -f docker-compose.loki.yml up -d` → Grafana http://localhost:3001 (admin / `agentaudit`)

### Track B — Week 5 code (next build slice)

1. **AAT hash-chain export** — optional SHA-256 chain on `blackbox export --audit` (v1.1)
2. **HTML timeline export** — IR narrative from replay module
3. **Sigma detection pack** — `docs/integrations/sigma/` or separate repo stub
4. **README reposition** — AgentAudit hero; Obsidian/email → `examples/`

### Track C — LinkedIn / OSS launch prep

1. 60s Loom: deny → approve → JSONL line → Loki Explore
2. README limitations paragraph (Tier C) — copy in GLM Part K
3. License decision: **Apache-2.0** (GLM recommendation)
4. Do **not** overclaim CASB coverage

---

## Not built yet (defer)

| Item | Notes |
|------|-------|
| Per-event hash chain in outbox | Pack-level SHA-256 only today |
| OTel logs exporter | v2 |
| GCP Logging → Chronicle adapter | v1.1 docs-only OK first |
| MCP schema pinning + SIEM alert | v1.1 |
| `blackbox export --audit` CLI flag | Week 5 |
| Passive Cursor/Copilot monitoring | Rejected scope |
| Stripe / consumer SaaS | Rejected for v1 |

---

## Decisions locked (do not re-litigate)

| Decision | Value |
|----------|--------|
| Product identity | **AgentAudit** — flight recorder + SIEM-ready, not Langfuse clone |
| Launch order | Solo replay/JSONL first → Loki homelab → enterprise adapters |
| SIEM scope | **Vendor-neutral** — Elastic, Splunk, Loki, webhook; Google = one adapter row |
| Tier C | README must say unmanaged copilots need CASB/gateway |
| Compound bet | Outbox never drops; forwarders best-effort |
| License (pending commit) | Apache-2.0 recommended |
| Email/inbox hero | **Deprioritized** — skills remain as examples |
| Commit policy | **Only when operator asks** |

---

## Key file map

| Task | Path |
|------|------|
| Canonical schema | `core/audit/canonical.py` |
| Sinks | `core/audit/sinks.py` |
| Elastic / Splunk map | `core/audit/adapters/ecs.py`, `splunk.py` |
| Bus forwarder | `core/bus/audit_exporter.py` |
| Replay | `core/audit/replay.py`, CLI `blackbox replay` |
| Tool audit | `core/drivers/host.py` |
| Approvals | `core/execution/service.py` → `resolve_approval()` |
| Loki compose | `docker-compose.loki.yml`, `infra/loki/alloy.config` |

---

## Operator state (local — never commit)

| Item | Location |
|------|----------|
| Secrets | `apps/orchestrator/.env` |
| Gmail enabled | `vault/.system/drivers.json` |
| Audit JSONL | `apps/orchestrator/data/audit-forward.jsonl` |
| Outbox | `apps/orchestrator/data/events.db` |

---

## Resume prompt for Cursor

```
Continue AgentAudit from docs/tomorrow-handoff.md.
Weeks 1–4 implemented: canonical schema, replay CLI, JSONL/webhook/Elastic/Splunk sinks, Loki homelab compose + docs. 257 tests pass.
Next: Week 5 (AAT hash-chain export, HTML timeline, Sigma pack, README reposition) OR dogfood Loki stack + LinkedIn demo.
Do not commit unless I ask. Tier C honesty in any public README.
```

---

## Resume prompt for Claude

**Launch assets (recommended):** Paste [`claude-agentaudit-launch-sequence-prompt.md`](./claude-agentaudit-launch-sequence-prompt.md) — start with **#1 README reposition** unless dogfood done and you want Loom/Sigma.

**Broader context:** [`claude-agentaudit-continuation-prompt.md`](./claude-agentaudit-continuation-prompt.md) + attach `tomorrow-handoff.md`.

- **GLM verdict:** Go — solo-first flight recorder + reference IR data model; not full governance platform
- **Default homelab SIEM:** Grafana Loki + Alloy
- **Enterprise default adapters:** Elastic ECS, Splunk HEC (now shipped)
- **Devil's advocate conceded:** SQLite OK if JSONL + hash export is the IR artifact

---

*Updated 2026-07-11 night · AgentAudit Weeks 1–4 complete in working tree · uncommitted*
