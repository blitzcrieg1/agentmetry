# Fable 5 — Email Autopilot as First Governed Agent Subsystem

**Audience:** solo operator on Windows 11 · **Scope:** consulting/agency Gmail loop only  
**Kernel:** use as-is (scheduler, bus, MCP host, sandbox, recovery, evidence export)  
**State at writing:** 188 pytest · `customer_reply` + `gmail_inbox_brief` shipped · `resume_orphan` shipped · Gmail driver ships **disabled**

This doc is the implementation-ready spec for living in the email subsystem for 2–4 weeks before any new channels or drivers.

---

## Executive map

| Phase | Goal | Time |
|---|---|---|
| **0** | Vault SOPs + client notes exist | 30 min |
| **1** | Gmail OAuth + driver mounted | 45 min |
| **2** | Read-only dogfood (`gmail_inbox_brief`) | 3–5 days |
| **3** | HITL reply loop (`customer_reply`) | daily |
| **4** | Crash-resume exercised once | 15 min drill |
| **5** | Metrics + evidence export ritual | weekly |

---

## Phase 0 — Vault context (before Gmail)

Create the minimum consulting context the skills actually read via RAG (`run_skill` → `_fetch_skill_context`).

### Files to create

```
vault/
  10-SOPs/
    client-reply.md          # tone, boundaries, escalation
    os-log.md                # weekly one-liner (Friday ritual)
  10-Knowledge/clients/
    acme-corp.md             # one note per active client
    ...
```

### `10-SOPs/client-reply.md` (starter template)

```markdown
---
tags: [sop, email]
---

# Client reply SOP

## Tone
- Warm, direct, under 150 words
- One clear next step per email
- No signature block (operator adds manually)

## Never commit in email (flag for human)
- Pricing not in thread or client note
- Legal terms, refunds, scope changes
- Promised delivery dates not in vault

## Escalation
- Unknown sender → draft says "I'll confirm internally" + tag urgency
- Angry thread → acknowledge, no defensiveness, offer call

## Client note lookup
- Match sender domain or name to `10-Knowledge/clients/*.md`
```

### `10-Knowledge/clients/acme-corp.md`

```markdown
---
tags: [client]
contact_domains: [acme.com]
---

# Acme Corp

- Primary contact: Jane Doe <jane@acme.com>
- Project: Q3 retainer — weekly status Fridays
- Voice: informal, first names OK
- Do not discuss: competitor X, internal margin
```

RAG picks these up automatically when thread text or `user_input` mentions the client. No code change required.

---

## Phase 1 — Mount Gmail safely (~45 min)

Full detail: [`docs/gmail-driver.md`](gmail-driver.md). Summary with exact commands:

### 1.1 Secrets (never commit)

`apps/orchestrator/.env`:

```env
GMAIL_CLIENT_ID=xxxx.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=xxxx
BLACKBOX_API_KEY=<existing>
# Optional after Phase 4 drill:
# BLACKBOX_AUTO_RESUME=1
```

### 1.2 One-time OAuth

```powershell
cd C:\Users\spiro\Projects\agentic-os\apps\orchestrator
$env:GMAIL_CLIENT_ID = "xxxx.apps.googleusercontent.com"
$env:GMAIL_CLIENT_SECRET = "xxxx"
.\.venv\Scripts\python.exe tools\gmail_server.py --auth
```

Verify: **Windows Credential Manager → Windows Credentials → `blackbox-gmail`**.

### 1.3 Enable driver (local only)

`vault/.system/drivers.json` → `"gmail"` → `"enabled": true` (**do not commit**).

### 1.4 Start + remount

```powershell
cd C:\Users\spiro\Projects\agentic-os
scripts\blackbox.bat start
```

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/drivers/remount `
  -H "X-API-Key: $env:BLACKBOX_API_KEY"
curl http://127.0.0.1:8000/api/v1/drivers/
```

**Expect:** `"gmail": "mounted"` with tools `gmail.list_threads`, `gmail.get_thread`, `gmail.create_draft`.

### 1.5 Guardrails (already enforced — verify mentally)

| Control | Mechanism |
|---|---|
| No send | Server exposes 3 tools; none send |
| Per-skill allowlist | YAML `tools:` on each skill |
| Volume cap | 20 threads/list, 8k body truncation |
| Audit | Every MCP call → bus `run/tool_called` → `data/events.db` |
| Tier 0 | Gmail is read/compose-draft only; no exec tag |

### 1.6 Smoke test (read-only)

Dashboard or Obsidian plugin → run **`gmail_inbox_brief`** with input `morning inbox brief`.

Check:
- Active loop completes → archive note under `30-Archive/`
- Dashboard shows `gmail.list_threads` in tool events
- No errors in `apps/orchestrator/data/logs/orchestrator.log`

### 1.7 Optional cron (week 2+)

When brief habit is stable, enable together with gmail driver:

`vault/.system/trigger-rules/gmail-morning-brief.yaml`:

```yaml
enabled: true   # flip locally only
```

Weekdays 08:00 → autonomous `gmail_inbox_brief`. Keep disabled until Phase 2 read-only dogfood passes.

---

## Phase 2 — Read-only inbox dogfood (3–5 days)

**Ritual (2 min/day):**
1. Run `gmail_inbox_brief` (manual or cron)
2. Open archive output; pick **at most one** thread id for Phase 3
3. Do **not** run `customer_reply` until 3 clean briefs with sensible triage

**Pass criteria:**
- 3 consecutive days without driver mount errors
- Reply queue thread ids are real (spot-check one in Gmail)
- Zero `budget_exceeded` in logs

---

## Phase 3 — Governed reply loop (daily)

### Flow

```
gmail_inbox_brief (read)  →  pick thread_id  →  customer_reply  →  approve  →  Gmail Draft  →  YOU send
```

### Run `customer_reply`

**Input:** Gmail thread id (from brief queue), e.g. `18f3a2b1c4d5e6f7`

**Graph (shipped YAML):**

```
fetch ──► draft ──► critic ──► human_approval ──► deliver ──► finalize
(tool)              │              ▲ checkpoint          (tool)
gmail.get_thread    LLM            interrupt_before      gmail.create_draft
                                       = HITL gate        body={approved_draft}
```

**Structural HITL (not policy promises):**
- `approval_threshold: 1.1` → confidence caps at 1.0 → **every** run stops at gate
- `deliver` is `tool_only_nodes` → no LLM rewrite after approval
- `{approved_draft}` → human edit wins over model draft
- Reject → terminate path → **zero** Gmail writes

### Approve surfaces (no Telegram)

| Surface | Action |
|---|---|
| Next.js dashboard | Pending approvals modal → approve / edit / reject |
| Obsidian plugin v0.2 | Same pending queue over WS |
| CLI | `blackbox pending` (list) — resolve via dashboard/plugin |

After approve: check **Gmail → Drafts** for the reply. **You** click Send. Send-after-approve is Phase 4-E (4 green weeks).

### Daily cap (operator discipline)

- Max **1** `customer_reply` per day during dogfood
- Max **3** approvals resolved per week minimum (metrics gate)
- If thread is sensitive (legal, pricing), reject and handle manually — counts as governance working

---

## Phase 4 — Crash-resume (shipped + email edge cases)

Base implementation: `apps/orchestrator/core/execution/recovery.py` — **`resume_orphan(rel_path)`** already uses `graph.ainvoke(None, config)`.

### 4.1 Classification at boot

`scan_recovery()` → active loops in `20-Active-Loops/`:

| Note status | Live pending thread? | Class | Action |
|---|---|---|---|
| `running` | n/a | **orphan** | `resume_orphan` candidate |
| `awaiting_approval` | missing | **stale_approval** | manual dismiss or re-run skill |
| `awaiting_approval` | present | healthy | skip |
| terminal | — | skip | skip |

Boot warning: `report_recovery_on_startup()` logs count; does not auto-fix unless opted in.

### 4.2 `resume_orphan` decision tree (as implemented)

```python
async def resume_orphan(rel_path: str) -> dict:
    loop = find_orphan(rel_path)  # classification == "orphan"
    if not loop:
        return {"status": "unresumable", "reason": "not a resumable orphan"}

    config = {"configurable": {"thread_id": loop["thread_id"]}}
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        mark_failed(rel_path)
        return {"status": "unresumable", "reason": "no checkpoint"}

    # Case A: paused at approval gate (crash during await)
    if snapshot.next and "human_approval" in snapshot.next:
        _reregister_pending(loop, config, snapshot.values)
        note_status(rel_path, "awaiting_approval")
        return {"status": "resumed_waiting", "thread_id": ...}

    # Case B: graph finished; finalize bookkeeping lost
    if not snapshot.next:
        return await _finalize_execution(...)  # status: resumed_completed

    # Case C: mid-pipeline (fetch/draft/critic/deliver)
    if llm_degraded.active:
        return {"status": "deferred", "reason": "LLM degraded"}

    final_state = await graph.ainvoke(None, config)  # INVARIANT: None, not input
    # ... then gate check again or finalize
```

### 4.3 Email-specific edge cases

| Scenario | Checkpoint `next` | Resume behavior | Operator action |
|---|---|---|---|
| Crash during `fetch` | `["draft"]` | Re-runs from interrupted node; `get_thread` safe (read) | None if resume succeeds |
| Crash during `draft`/`critic` | `["critic"]` or `["human_approval"]` | Re-invokes LLM for interrupted node — **duplicate token spend** | Accept or dismiss if draft looks wrong |
| Crash at approval gate | `["human_approval"]` | **No re-run** — re-register pending with saved draft | Approve in dashboard |
| Approved in UI, crash before `deliver` | `["deliver"]` or `["human_approval"]` with `approved=True` in state | May re-run `create_draft` → **duplicate Gmail draft** | Delete duplicate draft in Gmail (harmless) |
| Partial approval (edited draft, crash) | gate with `modified_input` set | Pending payload includes edited draft | Verify draft text before approve |
| Stale approval (thread cleaned) | note `awaiting_approval`, not in pending | `stale_approval` — not auto-resumed | `blackbox recovery --dismiss-all` or re-run skill |
| Skill YAML changed mid-run | readable checkpoint, old schema | May fail at invoke → `failed` | `mark_failed`, re-run fresh |
| OAuth token expired mid-run | tool error on resume | Run fails → loop `failed` | Re-auth `--auth`, re-run |

**Accepted tradeoff:** duplicate drafts on resume-after-approve > dedup machinery.

### 4.4 Config patterns

`.env`:

```env
# Opt-in: resume up to 3 orphans per boot (skips when LLM degraded)
BLACKBOX_AUTO_RESUME=1
```

Manual:

```powershell
blackbox recovery                          # list orphans + stale
blackbox recovery --resume 20-Active-Loops/2026-07-06-customer_reply-abc123.md
blackbox recovery --dismiss-all            # stale_approval cleanup only when sure
```

API:

```http
GET  /api/v1/skills/recovery
POST /api/v1/skills/recovery/resume  {"path": "20-Active-Loops/..."}
POST /api/v1/skills/recovery/resolve {"path": "...", "action": "mark_failed"|"dismiss"}
```

### 4.5 Drill script (15 min, once)

1. Start `customer_reply` on a test thread
2. Wait until active loop shows `awaiting_approval`
3. `taskkill /F /IM python.exe` (or kill orchestrator only) — simulate hard stop
4. Restart: `scripts\blackbox.bat start`
5. `blackbox recovery` → should show orphan or stale
6. `blackbox recovery --resume <path>` → expect `resumed_waiting`
7. Approve → draft appears in Gmail

Log result in `10-SOPs/os-log.md`.

### 4.6 Future refinement (optional, ~50 LOC)

Not required for dogfood; add if duplicate drafts annoy:

```python
# In deliver tool_only step — email_graph only
if state.get("step_outputs", {}).get("draft_receipt"):
    return {}  # skip second create_draft on resume
```

Store `draft_id` from first `create_draft` response in `step_outputs`.

---

## Phase 5 — Agentic email graph (implementation sketch)

The shipped `customer_reply` uses `graph: pipeline` (linear compiler). For **replanning** without rewriting the kernel, add a small dedicated graph type.

### 5.1 Design choice

| Approach | Effort | Agentic? |
|---|---|---|
| Prompt-only replan in `draft` node | 0 code | Weak — no routing |
| `graph: email_reply` compiler | ~200 LOC | Strong — conditional edges |
| Extend pipeline YAML with `routes:` | ~120 LOC | Medium |

**Recommended:** `graph: email_reply` — one file, one skill, clear boundaries.

### 5.2 Node list

```
                    ┌─────────────────┐
                    │  fetch (tool)   │
                    │ gmail.get_thread│
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ classify_thread │◄── replan #1: unknown sender / multi-client
                    │     (LLM)       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ load_sop   │  │ load_sop   │  │ escalate   │
     │ (tool)     │  │ generic    │  │ (LLM)      │
     │ client note│  │ client-    │  │ no SOP     │
     └─────┬──────┘  │ reply.md   │  └─────┬──────┘
           │         └─────┬──────┘        │
           └───────────────┼───────────────┘
                           ▼
                    ┌─────────────────┐
                    │     draft       │◄── replan #2: if THREAD_STALE → abort
                    │     (LLM)       │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │     critic      │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ human_approval  │◄── interrupt_before
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │ deliver (tool)  │
                    │ create_draft    │
                    └────────┬────────┘
                             ▼
                    ┌─────────────────┐
                    │    finalize     │
                    └─────────────────┘
```

### 5.3 Replanning nodes (minimal set)

#### `classify_thread` (LLM, structured output)

Prompt extracts from `{thread_text}` + RAG `{system_context}`:

```
ROUTE: client_known | client_unknown | thread_stale | needs_escalation
CLIENT_NOTE: relative/path or none
REASON: one line
```

Router function:

```python
def _route_after_classify(state: EmailReplyState) -> str:
    route = _parse_field(state, "ROUTE")
    return {
        "client_known": "load_client_sop",
        "client_unknown": "load_generic_sop",
        "thread_stale": "escalate_draft",      # replan: new messages since fetch
        "needs_escalation": "escalate_draft",
    }.get(route, "load_generic_sop")
```

#### `load_client_sop` (tool-only)

```yaml
node_tools:
  load_client_sop:
    - tool: vault_fs.read_note
      args:
        path: "{client_note_path}"   # from classify output
      output: sop_text
```

If path missing → conditional edge to `load_generic_sop`.

#### `load_generic_sop` (tool-only)

Reads `10-SOPs/client-reply.md` — always available fallback.

#### `escalate_draft` (LLM)

Draft template: acknowledge, flag uncertainty, **no factual claims**, force low confidence. Still goes to HITL — operator decides.

#### `thread_freshness_check` (optional replan #2, before draft)

Compare `fetch` message count / latest timestamp vs classify snapshot. If mismatch:

```
ROUTE: thread_stale → re-enter fetch (max 1 retry via state["replan_count"] < 1)
```

Prevents drafting against stale thread after long approval wait.

### 5.4 State extension

```python
class EmailReplyState(PipelineState):
    replan_count: int
    route: str
    client_note_path: str
    sop_text: str
```

Reuse `PipelineState` fields: `draft`, `approved`, `modified_input`, `step_outputs`, checkpoint keys.

### 5.5 Compiler signature

```python
# apps/orchestrator/core/graphs/email_reply_graph.py

def compile_email_reply_graph(skill_config: dict[str, Any]):
    """Compile customer_reply-style skills with classify + SOP load routing."""
    ...
    return graph.compile(
        checkpointer=get_checkpointer(),
        interrupt_before=["human_approval"],
    )
```

Registry:

```python
# core/graphs/registry.py
_GRAPH_BUILDERS["email_reply"] = compile_email_reply_graph
```

Skill YAML change (when you implement):

```yaml
name: customer_reply
graph: email_reply   # was: pipeline
# ... rest unchanged ...
```

**Migration path:** keep `graph: pipeline` working; switch `customer_reply` only after tests pass.

### 5.6 Interrupt points (checkpoint boundaries)

| Node | Checkpoints? | Interrupt? |
|---|---|---|
| fetch | yes | no |
| classify_thread | yes | no |
| load_*_sop | yes | no |
| draft | yes | no |
| critic | yes | no |
| human_approval | yes | **interrupt_before** |
| deliver | yes | no |
| finalize | yes | no |

Resume semantics identical to pipeline — `resume_orphan` already keys off `"human_approval" in snapshot.next`.

### 5.7 Tests to add (when implementing)

1. `client_known` → loads client note path from classify
2. `client_unknown` → falls back to generic SOP
3. `thread_stale` + `replan_count=0` → re-fetch once
4. `thread_stale` + `replan_count=1` → escalate_draft
5. Resume at gate → no duplicate `get_thread`

---

## Governance spec — email subsystem

### Capability matrix

| Capability | gmail_inbox_brief | customer_reply | Global deny |
|---|---|---|---|
| `gmail.list_threads` | ✅ | ❌ | |
| `gmail.get_thread` | ❌ | ✅ | |
| `gmail.create_draft` | ❌ | ✅ post-HITL only | |
| `gmail.send` | ❌ | ❌ | **not in server** |
| `vault_fs.read_note` | via RAG context | via RAG + optional explicit load | |
| `vault_fs.write_note` | finalize only (archive) | finalize only | |
| `search.*` | ❌ | ❌ | deferred |
| `margin.*` | ❌ | ❌ | |
| `shell` / `fs` MCP | ❌ | ❌ | disabled in drivers.json |

Enforcement layers:
1. **Driver mount** — gmail disabled = tools unavailable
2. **Skill YAML `tools:`** — host rejects non-allowlisted calls
3. **Sandbox tier** — gmail untagged (Tier 0)
4. **Graph** — `deliver` after `interrupt_before` human_approval
5. **Operator** — physical Send in Gmail UI

### Vault ACL (convention + future hardening)

| Path | Read | Write by agent |
|---|---|---|
| `00-Inbox/` | ✅ trigger source | ❌ (operator only) |
| `10-SOPs/` | ✅ RAG | ❌ |
| `10-Knowledge/clients/` | ✅ RAG | ❌ |
| `20-Active-Loops/` | ✅ status | ✅ system managed |
| `30-Archive/` | ✅ | ✅ finalize output only |
| `.system/` | ✅ skill defs | ❌ |

Optional hardening (later): `vault_fs_server.py` path prefix allowlist per skill tag — not needed for solo dogfood.

### HITL rules

| Rule | Enforcement |
|---|---|
| Every outbound draft requires explicit approve | `approval_threshold: 1.1` |
| Human edit overrides model | `{approved_draft}` templating |
| Reject terminates without Gmail write | existing terminate path |
| No auto-send | no send tool exists |
| Approval audit trail | bus events + `runs.jsonl` + active loop frontmatter |

### Audit log sources

| Store | Contents | Retention |
|---|---|---|
| `data/events.db` | bus outbox: tool calls, node events, approvals | local |
| `data/runs.jsonl` | run ledger: skill, cost, status, `triggered_by` | append-only |
| `data/telemetry.db` | aggregated stats | local |
| `20-Active-Loops/` | human-readable run state | until archived |
| `30-Archive/` | finalized outputs | permanent |

### Evidence export (Tier 2 story)

Weekly or on-demand:

```powershell
blackbox export --evidence --from 2026-07-01 --to 2026-07-07
blackbox verify vault/30-Archive/exports/evidence-2026-07-07.json
```

Export includes runs + tool events + SHA-256 integrity hash (`docs/evidence-pack-format.md`). Filter mentally to email skills: `gmail_inbox_brief`, `customer_reply`.

---

## Dogfooding metrics & rituals (4-week gate)

### Weekly thresholds (`blackbox stats --days 7`)

| Metric | Wk 1 | Wk 2 | Wk 3 | Wk 4 | Source |
|---|---|---|---|---|---|
| Distinct successful skills | ≥ 2 | ≥ 3 | ≥ 3 | ≥ 3 | telemetry `dogfooding_met` |
| Email skills completed | ≥ 3 briefs | ≥ 5 briefs | cron on | cron on | runs.jsonl filter |
| `customer_reply` approved | ≥ 1 | ≥ 2 | ≥ 3 | ≥ 3/week | approval events |
| Approval median wait | — | < 48h | < 24h | < 24h | pending timestamps |
| Autonomy share | any | ≥ 40% | ≥ 50% | ≥ 60% | `triggered_by != manual` |
| Orphan loops at Monday | 0 | 0 | 0 | 0 | `blackbox recovery` |
| Spend | < €10/mo | same | same | same | stats total_cost |
| `budget_exceeded` | 0 | 0 | 0 | 0 | logs |

**Unlock Phase 4-E (send-after-approve):** 4 consecutive green weeks on all rows. One red week resets counter.

### Daily ritual (2 min)

1. Glance at `blackbox pending` — resolve anything stale
2. Read today's `gmail_inbox_brief` archive (or trigger manually)
3. At most one `customer_reply` if queue non-empty
4. Send approved drafts in Gmail when ready

### Monday ritual (5 min)

```powershell
blackbox status
blackbox recovery
blackbox stats --days 7
```

- Resume or dismiss orphans
- Target: **zero** orphan/stale items

### Friday ritual (10 min)

```powershell
blackbox stats --days 7
blackbox export --evidence --from <monday> --to <today>
```

One line in `10-SOPs/os-log.md`:

```
2026-07-11 | briefs: 5 | replies approved: 3 | orphans: 0 | spend: €1.20 | dogfooding: MET
```

Run vault skill **`weekly_review`** if configured.

### Monthly

```powershell
blackbox backup
```

Review evidence exports in `30-Archive/exports/`.

### Kill signals (stop and fix, don't add features)

- \>2 orphans/week → crash-resume or stability bug
- Approval wait \> 72h median → HITL UX broken or operator skipping
- Any duplicate draft causing wrong send (operator error) → pause `customer_reply`
- Gmail auth failures \>1/week → fix OAuth before continuing

---

## Implementation checklist (you)

### Operator (this week)

- [x] Create `10-SOPs/client-reply.md` + 2+ client notes
- [ ] Gmail OAuth + enable driver locally
- [ ] 3 clean `gmail_inbox_brief` runs
- [ ] 1 full `customer_reply` → approve → Gmail draft → manual send
- [ ] Crash-resume drill documented in `os-log.md`

### Engineer (when replanning worth it)

- [x] `core/graphs/email_reply_graph.py`
- [x] Register `email_reply` in `registry.py`
- [x] Switch `customer_reply.yaml` to `graph: email_reply`
- [x] 5 tests (routing + interrupt gate)
- [ ] Optional: `draft_id` idempotency on deliver

### Explicitly deferred

- Telegram / email notification channel
- Gmail send tool
- Outlook, CRM, Stripe
- Dashboard redesign
- Team/multi-user ACLs

---

## Quick reference commands

```powershell
# Life cycle
scripts\blackbox.bat start
scripts\blackbox.bat stop

# Drivers
curl http://127.0.0.1:8000/api/v1/drivers/ -H "X-API-Key: $env:BLACKBOX_API_KEY"

# Dogfood
blackbox stats --days 7
blackbox recovery
blackbox recovery --resume 20-Active-Loops/<file>.md
blackbox export --evidence --from 2026-07-01 --to 2026-07-07
blackbox verify vault/30-Archive/exports/<file>.json

# Gmail re-auth
cd apps\orchestrator
.\.venv\Scripts\python.exe tools\gmail_server.py --auth
```

---

*Fable 5 — Email Autopilot spec · 2026-07-06*
