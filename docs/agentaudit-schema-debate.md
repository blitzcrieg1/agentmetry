# AgentAudit — canonical schema debate (v1.0 → v1.1)

**Question:** what do we add to canonical events so AgentAudit is *materially* better than `Get-Content audit-forward.jsonl | Export-Csv`? Grounded in the real normalizer (`core/audit/canonical.py`) at HEAD `c00171b`.

**The CSV strawman is the bar.** Anyone can flatten the JSONL to CSV in one line. So every proposed field must pass one test: **could a CSV of the *current* fields reconstruct this?** If yes, it's not worth a schema bump. If no — because the data isn't captured, or the captured value is misleading — it's a real gap.

---

## Debate

### Round 1 — the gaps, named against code

**Proposer:** Five concrete v1.0 gaps, each with the line that proves it.

1. **Empty `skill_id` on `approval_request`.** `canonical.py:72` reads `payload.get("skill") or payload.get("skill_name")`. The `RUN_WAITING` payload doesn't carry it, so `agent.skill_id = ""` on the *approval* event — the single most important event in the whole product. The HITL gate is the differentiator, and it's the least-labeled row in the stream.

2. **No `pending_tool` on `approval_request`.** `canonical.py:101` only attaches a `tool` block when `tool_qualified` is present, and approval events carry no tool. So an approval reads "a human said yes at 09:14:25" with **no link to what was being approved**. The gate is unmoored from the action it gates.

3. **`actor` is always the human operator.** `canonical.py:85-89` hardcodes `{type:"user", id:operator, role:"operator"}` on *every* event. A cron-triggered or vault-watch autonomous run is stamped with the human's identity. This is **worse than missing** — it's a false attribution an auditor will act on.

4. **`run`/`node` steps not forwarded.** The stream has run lifecycle (`session_start`/`session_end`), tools, approvals, driver mounts — but **not** the intra-run node graph (research→draft→critic→approval). `emit_node` writes to `node-events.jsonl`, a separate file the audit forwarder never touches. You can see *that* a tool was called, not *at which step / toward what sub-goal*.

5. **Outbox fields stripped at the boundary.** `normalize_outbox_row` surfaces a fixed subset (skill, tool, args_hash, reason, driver, tools). Anything else in the payload — input path, trigger source, caller — is silently dropped. There is no field for **why this run started**.

**Skeptic:** Three of these fail the CSV test in the proposer's favor, but let's be honest about two. Gap 4 (node steps) and gap 5 (generic stripped fields) are *scope creep risks*. Forwarding every node event doubles-to-triples event volume and turns the flight recorder into a trace log — which is what Langfuse/OTel already do better. Don't chase parity with tracing tools; that's not the wedge. The wedge is **governed tool-use + approvals**. So node-level forwarding is a P2 "maybe," not a gap to fix.

**Proposer concedes:** Agreed on node granularity — full node forwarding is anti-wedge. But there's a narrow version of gap 5 that is *not* scope creep: a single `initiator`/`trigger` field. That's one field, not a trace.

### Round 2 — what actually defeats the CSV

**Skeptic:** Rank the five by the CSV test, hardest-to-fake first.

- **Gap 3 (actor provenance)** — CSV *cannot* fix this; the value is captured but wrong. An investigator filtering "actions by the human" gets autonomous runs mixed in. **Defeats CSV: totally, and today it actively misleads.**
- **Gap 2 (pending_tool on approval)** — CSV cannot reconstruct the approval→action binding because it isn't in any row. This is the **causality** a flat table structurally can't hold. **Defeats CSV: totally.**
- **Gap 1 (empty skill_id on approval)** — CSV can't populate an empty field. Cheap to fix, high value (labels the pivotal event). **Defeats CSV: yes.**
- **Gap 5-narrow (initiator/trigger)** — "was this run manual, cron, vault-watch, or ingress-webhook?" Not captured anywhere. Every IR review asks it. **Defeats CSV: totally.**
- **Gap 4 (node steps)** — CSV can't add them, but adding them chases the wrong category. **Defeats CSV: yes, but wrong wedge.** Defer.

**Proposer:** Note the overlap — gap 3 (actor) and gap 5-narrow (initiator) are the *same underlying miss*: the schema conflates "who/what initiated this run" with "the machine's operator id." Fix them together: an `initiator` block that says human-vs-autonomous **and** the trigger source, and let `actor` reflect it.

**Skeptic:** Then the P0 clusters into exactly two edits, both on events that already flow:
- **Enrich the approval event** (gaps 1 + 2): put `skill_id` and `pending_tool` on `RUN_WAITING`.
- **Fix provenance** (gaps 3 + 5-narrow): add `initiator` {actor_type: human|autonomous, trigger: manual|cron|vault_watch|ingress}, and stop hardcoding actor.

### Round 3 — cost and blast radius

**Skeptic:** Is this ~2 days? Blast radius check.

- **Approval enrichment:** the skill name and the last pending tool are known at the point `RUN_WAITING` is published (the run paused *because* of the gate; the thread's last `tool_called` is in the outbox). Populate two payload fields at the publish site + read them in `canonical.py`. Additive. ~half a day + tests.
- **Initiator/trigger:** the run's origin is known at `run_skill` entry (manual API call vs vault-watcher vs cron vs ingress route — these are *different call sites*). Thread a `trigger`/`initiator` through the run context into the `RUN_STARTED` payload and every event's actor derivation. This is the bigger one — touching the run-context plumbing — but it's additive and the call sites already differ. ~1 day + tests.

**Proposer:** Both are pure additions to the canonical event — no field renamed or removed, so **red-line #4 (additive-only schema) holds**, version bumps `1.0.0 → 1.1.0`. Total ≈ 1.5–2 days. Fits P0.

**Skeptic:** One guardrail — `initiator.actor_type` must derive from the *run's* origin, not a client-supplied header, or an autonomous run could spoof "human." Derive server-side at the call site. Agreed → P0.

**Debate resolved.** P0 = enrich the approval event + fix initiator provenance. P1 = tool-output hash + SOP/code version stamp. P2 = narrow node-step forwarding *only if* IR users ask. Full node trace = never (wrong wedge).

---

## D1 — Gap ledger

| # | Gap | Evidence (canonical.py) | Defeats CSV? | Severity |
|---|-----|-------------------------|--------------|----------|
| 1 | Empty `skill_id` on approval_request | `:72` reads skill from payload that lacks it | Yes — can't fill empty | High (pivotal event unlabeled) |
| 2 | No `pending_tool` on approval | `:101` tool block only on tool events | Yes — causality not in any row | High (gate unmoored from action) |
| 3 | `actor` always human operator | `:85-89` hardcoded | **Yes — value is wrong, not absent** | **Critical (misleads auditor)** |
| 4 | Node steps not forwarded | `emit_node` → separate `node-events.jsonl` | Yes, but wrong wedge | Low (defer — anti-scope) |
| 5 | No initiator/trigger source | not captured; stripped at `normalize_outbox_row` | Yes — not in any row | High (every IR review asks) |

---

## D2 — Proposed v1.1 additions (additive only)

```jsonc
// on approval_request (RUN_WAITING) — gaps 1 + 2
"agent": { "name": "blackbox", "skill_id": "audit_demo" },   // now populated
"gated_action": {                                            // NEW
  "tool": "vault_fs.read_note",                              // the tool the run paused before/after
  "server": "vault_fs",
  "input_hash": "a3f1c9…b855",                               // reuse arguments_sha256
  "input_ref": "00-Inbox/audit-demo-note.md"                 // user_input, if non-sensitive; else omit
},

// on ALL events — gaps 3 + 5
"initiator": {                                               // NEW
  "actor_type": "human",            // human | autonomous
  "trigger": "manual",              // manual | cron | vault_watch | ingress
  "operator_id": "spiro"            // the machine/operator identity, always present
},
"actor": {
  "type": "user",                   // "user" for human, "agent" for autonomous — derived, not hardcoded
  "id": "spiro",
  "role": "operator"
}
```

| Field | Source | Why it beats CSV | Cost |
|-------|--------|------------------|------|
| `agent.skill_id` on approval | run context at RUN_WAITING publish | Labels the pivotal event | XS |
| `gated_action` on approval | thread's pending tool at pause | Binds approval → action (causality) | S |
| `initiator.actor_type` | run origin (call site), server-derived | human vs autonomous — the #1 IR question | M |
| `initiator.trigger` | run origin | manual/cron/vault/ingress provenance | M |
| `actor.type` derived | from `initiator.actor_type` | stops false human attribution | XS (once initiator exists) |

**P1 (next):** `tool.output_hash` (roadmap in schema doc), `agent.code_version` + `sop_version_hash` at action time (evidence export already computes SOP hashes — surface them live). **P2:** narrow node-step events, `parent_event_id` causal graph.

---

## D3 — Why this is materially better than CSV

A CSV of v1.0 answers *"what events happened, in order."* An investigation needs three things a flat table of the current fields **cannot** provide:

1. **Attribution you can trust.** "Show me everything the *human* did" — v1.0 answers this *wrong* (everything is the human). v1.1 `initiator.actor_type` makes the human/autonomous split real. **No CSV of v1.0 can recover this; the source value is false.**
2. **Chain of custody on the gate.** "This tool ran — did a human approve *this specific action*?" v1.1 binds `approval_response` → `gated_action` (same tool, same `input_hash`). A CSV has an approval row and a tool row with a shared `correlation_id`, but nothing says the approval was *for that tool* rather than a different one in the same run. v1.1 makes the binding explicit. **Causality is structurally absent from the flat table.**
3. **Provenance of initiation.** "Did someone start this, or did it fire on a schedule at 02:00?" — the exact 2am question the LinkedIn hook poses. v1.0 has no field for it. v1.1 `initiator.trigger` answers it. **Not in any current row.**

That's the pitch: **AgentAudit isn't a CSV of events — it's an evidentiary record where the pivotal event (the approval) is fully labeled and bound to the action it gated, and every action is honestly attributed to human or machine.** A CSV export is a *feature* of AgentAudit (it's just JSONL), not a substitute for it.

---

## D4 — P0 / P1 / P2 cut (P0 ≈ 2 days)

### P0 — ~2 days, additive, ship for v1.1
| Task | Files | Effort |
|------|-------|--------|
| Populate `skill_id` on RUN_WAITING payload | publish site in `core/execution/service.py`; read stays `canonical.py:72` | XS |
| Add `gated_action` to RUN_WAITING payload + normalize | service.py (pause site) + `canonical.py` (new block, guarded by presence) | S |
| Add `initiator` {actor_type, trigger, operator_id}; derive `actor.type` | run-context origin at `run_skill` call sites (manual/cron/vault/ingress) → RUN_STARTED payload + `canonical.py` actor derivation | M |
| Bump `SCHEMA_VERSION` → `1.1.0`; update `docs/agent-audit-event-schema.md` | `canonical.py:25`, schema doc | XS |
| Tests: approval event has non-empty skill_id + gated_action; autonomous run stamps actor_type=autonomous | `test_agent_audit.py` | S |

### P1 — after launch
- `tool.output_hash` (schema doc already flags outputs as roadmap).
- `agent.code_version` + `sop_version_hash` live (reuse evidence-export hashing).

### P2 — only if IR users ask
- Narrow node-step events (not full trace).
- `parent_event_id` causal linkage across events.

### Never
- Full node/LLM trace forwarding — that's Langfuse/OTel's job, and chasing it dilutes the governed-tool-use wedge.

---

## D5 — Migration & compatibility

- **Additive only.** No field renamed or removed → **red-line #4 preserved**. Existing sinks (Loki/Elastic/Splunk), the Sigma pack, and the `export --audit` spec keep working; they just gain optional fields.
- **Version:** `1.0.0 → 1.1.0`. Consumers pin `schema_version` major; minor is backward-compatible by contract.
- **Sigma impact:** the R-rules gain a *better* option — the approval-bypass rule (previously "roadmap, needs sequence correlation") becomes writable once `gated_action.input_hash` on the approval can be matched to the `tool.input_hash` on the tool call. Note it in `docs/integrations/sigma/README.md` but don't rewrite rules until dogfooded.
- **Spoofing guard:** `initiator.actor_type` MUST be derived server-side from the run's call site, never from a client header — else an autonomous run could claim "human." Add a test asserting an ingress-triggered run stamps `autonomous`.
- **Acceptance tests:** (1) approval_request has non-empty `agent.skill_id`; (2) approval_request carries `gated_action` with a 64-hex `input_hash`; (3) a vault-watch/cron run stamps `initiator.actor_type=autonomous` and `actor.type=agent`; (4) a dashboard-run stamps `human`/`user`; (5) `schema_version=1.1.0`; (6) old-shape events (no initiator) still parse — forward-compat.
- **compound preserved? yes** — additive canonical fields, no gate/outbox/edit-log change. Approval still requires explicit human grant.

---

## If we only ship ONE thing

**If we only ship ONE thing, ship `initiator` (human-vs-autonomous + trigger source) — because it's the only gap where v1.0 doesn't just omit the answer, it records a *false* one (`actor` is always the human), and "did a person do this or did the agent do it on its own at 2am?" is the first question every incident responder asks and the exact question the product's own hook promises to answer.**
