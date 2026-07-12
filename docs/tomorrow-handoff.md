# Tomorrow Handoff — AgentAudit OSS

**Read this first.** Product = **AgentAudit** (local flight recorder). BLACKBOX = engine name only.  
**HEAD:** `82cba0a` on `master` · **299 tests** passing.

| Link | Purpose |
|------|---------|
| [agentaudit-dogfood-checklist.md](./agentaudit-dogfood-checklist.md) | **Pre-Loom validation** — audit_demo + optional Tier B hooks |
| [external-agent-audit.md](./external-agent-audit.md) | Cursor / Claude / Antigravity ingest |
| [agent-audit-event-schema.md](./agent-audit-event-schema.md) | Canonical JSON v1.1 |
| [agentaudit-dashboard-redesign-spec.md](./agentaudit-dashboard-redesign-spec.md) | Dashboard Phase A spec |
| [glm-52-external-agent-audit-results.md](./glm-52-external-agent-audit-results.md) | Tier B feasibility research |

**Strategy:** OSS + LinkedIn + IRT credibility. **Tier C honesty:** unmanaged copilots need CASB — not AgentAudit.

---

## Shipped (launch batch)

| Area | Detail |
|------|--------|
| Schema v1.1 | `initiator`, `gated_action`, external ingest |
| Tier B | hooks, `agentaudit_ingest.py`, MCP proxy, `POST /api/v1/audit/ingest` |
| Dashboard | AgentAudit UI, flight recorder, tool-gate approval, freshness badge |
| README | AgentAudit positioning, Tier B quick start |

---

## Next — operator (in order)

1. `python scripts/agentaudit_ingest.py selftest`
2. Dashboard → `audit_demo` → approve + reject → flight recorder GREEN
3. Restart Cursor → confirm cursor events in tail + freshness badge
4. Record Loom only after checklist GREEN
5. LinkedIn after Loom

---

## Not now

- Inbox / Gmail / customer_reply hero path (skills remain as **examples** only)
- `dogfood-scorecard-v1` (removed — was Path B inbox ritual)
- Schema v1.2, Tier C / CASB claims, new drivers

---

## Key paths

| Task | Path |
|------|------|
| Ingest + tail | `api/routes/audit.py` |
| Hook client | `scripts/agentaudit_ingest.py` |
| Flight recorder UI | `apps/dashboard/components/flight-recorder-panel.tsx` |
| JSONL | `apps/orchestrator/data/audit-forward.jsonl` |

---

## Never commit

`.env`, `vault/.system/drivers.json`, `events.db`, `audit-forward.jsonl`, `edit-log.jsonl`

---

*Updated 2026-07-12 · AgentAudit launch batch pushed*
