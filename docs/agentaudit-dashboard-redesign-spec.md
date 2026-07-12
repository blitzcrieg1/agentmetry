# AgentAudit dashboard — deconstruction + redesign spec

**Target:** `apps/dashboard/`. Grounded in the real components at HEAD `c00171b`. Locked: AgentAudit = flight recorder; `audit_demo` default; "BLACKBOX" = engine name only (not the product surface); Tier C honesty; two pipes; no kernel rewrite; no Stripe.

**Confirmed from the 2026-07-12 dogfood:** `audit_demo` is tool-only → approval modal shows an **empty body** and a **placeholder confidence** (the "5%" screenshot). That is a *dashboard* assumption bug (every approval treated as an LLM draft), not a skill bug.

---

## D1 — Executive audit (every UI region)

| Region | Component / location | Current state | Problem | Pri |
|--------|----------------------|---------------|---------|-----|
| Header logo + title | `mission-control.tsx:194-206` | `/blackbox-logo.png`, `<h1>BLACKBOX</h1>`, subtitle "Approval Inbox" | Wrong product branding; "Approval Inbox" is the Path-B frame | **P0** |
| Default skill | `skill-deck.tsx:50-54` | Prefers `gmail_inbox_brief` → `summarize_note` → first | Boots on a Gmail email skill; should boot on `audit_demo` | **P0** |
| Approval modal — body | `approval-inbox-card.tsx:122-137` | Renders `approvalDraft` in a 220px box | Empty for tool-only skills → blank card on camera | **P0** |
| Approval modal — confidence | `approval-inbox-card.tsx:92,115-119` | `{(confidence*100)}% confidence` badge | Meaningless for tool gates → shows 0–5%, looks broken | **P0** |
| Activity feed — tool events | `mission-control.tsx:46` | `if (line.startsWith("🔧"\|"⛔")) continue;` | **Tool calls & denials are explicitly dropped** — the one thing a flight recorder must show | **P0** |
| Live audit event stream | *(does not exist)* | — | No panel shows canonical events (correlation_id, tool.qualified, input_hash) | **P0 (add)** |
| Idle center state | `mission-control.tsx:134-147` | "Inbox zero / Ready for the next customer reply" | Inbox framing | **P1** |
| Completed banner | `mission-control.tsx:163-170` | "Draft approved and archived to vault" | Draft framing | **P1** |
| Approval modal — icon/title | `approval-inbox-card.tsx:105-112` | `Mail` icon, "Draft ready" | Email framing on an audit tool | **P1** |
| Activity "magic" line | `mission-control.tsx:107-118` | "✨ Compounding intelligence" gradient card | Path-B flywheel marketing; off-message for IR | **P1** |
| Right sidebar — Session Telemetry | `telemetry-panel.tsx:60-77` | Input/Output tokens, cost, context window | LLM-centric; irrelevant to the audit story | **P1** |
| Right sidebar — Dogfooding tile | `telemetry-panel.tsx:49` | Path-B "3 skills/week" go/no-go | Dead metric post-pivot | **P1** |
| Right sidebar — Run History | `telemetry-panel.tsx:115` | Generic run list | Should read as the audit log / replay entry point | **P1** |
| Left — "The Armory · Desk" | `skill-deck.tsx:106-108` | Fantasy-console naming | Off-tone for security peers | **P1** |
| Dev mode — vault constellation | `graph-viz/vault-constellation.tsx` (via `graph-visualization.tsx`) | 3D orbit of vault notes | Legacy hero; keep in dev only, demote | **P1** |
| Left — Memory Navigator | `skill-deck.tsx:158`, `memory-navigator.tsx` | Vault file browser | Vault-centric; demote | **P2** |
| Right — Memory Heatmap | `telemetry-panel.tsx:117-138` | Most-accessed vault notes | Vault-centric; demote/remove | **P2** |
| Right — Service status / Recovery / History | `telemetry-panel.tsx:48,80-107,113` | Health, backend stats | Keep, minor relabel | **P2** |
| Dev — agent terminal | `mission-control.tsx:238-267` | Raw line feed | Fine in dev mode | **P2** |

---

## D2 — New IA (flight-recorder hero)

```
┌─ HEADER ───────────────────────────────────────────────────────────────┐
│ [AgentAudit logo]  AgentAudit            [Sinks: file●]  [Live●]  [Dev] │
│ Flight recorder for governed agents                                     │
├──────────────┬───────────────────────────────────────┬─────────────────┤
│ RUN (left)   │ FLIGHT RECORDER (center, HERO)         │ AUDIT STATUS    │
│              │                                        │ (right)         │
│ audit_demo ▸ │  ┌── Approval Gate (only when paused)─┐│ Events today: N │
│ (default)    │  │ tool-gate OR draft mode (D4)       ││ tool_called: N  │
│              │  └────────────────────────────────────┘│ denied: N       │
│ [other       │                                        │ approvals: N    │
│  skills…]    │  LIVE EVENT STREAM (FlightRecorderPanel)│ ───────────────│
│              │  hh:mm:ss  tool_called  vault_fs.read…  │ Sinks           │
│ Task input   │  hh:mm:ss  approval_req pending         │  file    ●      │
│ [textarea]   │  hh:mm:ss  approval_res denied  ⟵red    │  loki    ○      │
│              │  hh:mm:ss  tool_called  … #a3f1 hash…   │ ───────────────│
│              │  (click a row → full canonical JSON)    │ Run history →   │
│              │                                        │ (replay entry)  │
└──────────────┴───────────────────────────────────────┴─────────────────┘
  Dev mode adds: LangGraph graph-viz + vault constellation + raw terminal
```

**Principles:**
- **Center is the flight recorder**, always visible — the live canonical event stream. The approval gate appears *inside* it when a run pauses, not as the whole center.
- **Right sidebar becomes audit-centric:** event counts (tool_called / denied / approvals), sink status (file/loki/elastic/splunk ● on/○ off), and a link into Run History framed as "replay". Drop tokens/cost/context-window from the default (move to Dev).
- **Left stays the runner**, default skill `audit_demo`, renamed from "The Armory".
- **Vault constellation + graph-viz + terminal live in Dev mode only** (already the case for graph-viz/terminal; move constellation there too if it isn't).

---

## D3 — Copy deck (old → new)

| Location | Old | New |
|----------|-----|-----|
| `mission-control.tsx:204` | `BLACKBOX` (h1) | `AgentAudit` |
| `mission-control.tsx:205` | `Approval Inbox` | `Flight recorder for governed agents` |
| `mission-control.tsx:196-198` | `blackbox-logo.png` / alt "BLACKBOX" | `agentaudit-logo.png` / alt "AgentAudit" (or text mark) |
| `mission-control.tsx:140` | `Inbox zero` | `No active run` |
| `mission-control.tsx:141-144` | "Ready for the next customer reply. Pick a skill from the armory… drafts land here for approval." | "No agent activity right now. Run a skill from the left — every tool call and approval is recorded here." |
| `mission-control.tsx:154` | `Working on it` | `Run in progress` |
| `mission-control.tsx:167` | `Draft approved and archived to vault` | `Run approved — recorded to the audit trail` |
| `mission-control.tsx:62` | `Draft ready for your review` | `Approval required — decision will be recorded` |
| `mission-control.tsx:65-66` | "Approved and archived to vault" / "Completed and archived to vault" | "Approved — recorded" / "Completed — recorded" |
| `mission-control.tsx:116` | `Compounding intelligence` | *(remove the magic card entirely, or)* `Recorded` |
| `mission-control.tsx:244` | `agent terminal` | `agent terminal` *(keep — dev only)* |
| `skill-deck.tsx:107` | `The Armory · Desk` | `Skills` |
| `skill-deck.tsx:116` | "Describe what the agent should do…" | "Input for the selected skill (e.g. a note path)" |
| `approval-inbox-card.tsx:110` | `Draft ready` | draft-mode: `Draft ready` · tool-gate: `Tool call awaiting approval` |
| `approval-inbox-card.tsx:105-107` | `Mail` icon | draft-mode: `Mail` · tool-gate: `ShieldCheck` / `Terminal` |
| `telemetry-panel.tsx:52` | `Session Telemetry` | `Session` *(and move token/cost rows to Dev)* |

**Global rule:** the word "draft" only appears in draft-mode approvals. Everywhere else the verb is **"recorded"** / **"audit trail"**, never "archived to vault".

---

## D4 — Approval Gate redesign (two modes)

The gate must stop assuming every approval is an LLM draft. Branch on an `approval_kind` from the payload (see D6).

### Mode A — `draft` (LLM skills: customer_reply, summarize_note…)
- Keep current UI: draft body (editable), confidence badge, edit/approve/reject.
- Unchanged behavior.

### Mode B — `tool_gate` (tool-only skills: audit_demo, and any run pausing on a pending tool)
- **Header:** icon `ShieldCheck` (not `Mail`), title "Tool call awaiting approval", subtitle = skill label.
- **Body (replaces the empty draft box):** the pending action, rendered from `pending_tool`:
  ```
  Tool     vault_fs.read_note
  Server   vault_fs
  Args     redacted · sha256 a3f1c9…b855   [copy]
  Input    00-Inbox/audit-demo-note.md      (from user_input, if present)
  ```
- **No confidence badge.** Confidence is meaningless for a policy gate; hide it entirely in this mode (do not render 0%).
- **No edit button** (there's no draft to edit); keep **Approve** / **Reject**, same `a`/`r` shortcuts.
- **Footer line:** "Your decision is recorded as an approval event." (reinforces the product).

### Detection logic (frontend)
```
kind = payload.approval_kind
     ?? (payload.pending_tool ? "tool_gate"
        : (approvalDraft?.trim() ? "draft" : "tool_gate"))
```
Fallback covers old payloads: empty draft ⇒ tool_gate, so the empty-card bug can't recur even before the backend ships `approval_kind`.

### Fixes this closes
- ✗ Empty approval body on `audit_demo` → now shows the gated tool call.
- ✗ "5% confidence" → confidence hidden in tool_gate mode.
- ✗ Email framing → ShieldCheck + "recorded" language.

---

## D5 — `FlightRecorderPanel` spec (new component)

**File:** `apps/dashboard/components/flight-recorder-panel.tsx`. This is the center hero.

**Data:** initial `GET /api/v1/audit/tail?limit=50` (D6), then append live via the existing WS stream (subscribe to tool/approval/driver events already flowing through `use-websocket`). Keep a ring buffer of ~200 rows client-side.

**Row (one canonical event):**
```
09:14:22  ⬤ tool_called   vault_fs.read_note   #8892   a3f1c9…   ▸
09:14:25  ⬤ approval_req   pending              #8892             ▸
09:14:31  ⬤ approval_res   denied               #8892             ▸   (red)
```
- **Time** — `timestamp_utc` local hh:mm:ss.
- **Outcome dot** — success=emerald, denied=red, pending=amber, error=red.
- **Type** — `action.type` (tool_called / approval_response / config_change).
- **Detail** — `tool.qualified` for tool events; `action.outcome` for approvals; `mcp.server_id` for config_change.
- **corr** — short `correlation_id` (last 4), click-to-copy full.
- **hash** — truncated `tool.input_hash` (first 6), monospace, click-to-copy full; empty for non-tool events.
- **▸ expand** — row expands to full canonical JSON (read-only, syntax-dim).

**Controls:** filter chips (All · Tools · Approvals · Denials · Config), a "correlation_id" filter (click a corr to isolate a run), and a "Copy JSONL" button (exports the visible rows). Empty state: "No events yet. Run a skill — tool calls and approvals appear here as they happen."

**Explicitly not:** tokens, cost, latency, draft text. This panel is Pipe 2 only.

---

## D6 — Minimal backend API (additive, read-only + one payload field)

Two small changes. Both additive — no schema break, no kernel rewrite.

### 6a — `GET /api/v1/audit/tail?limit=N` (new route)
- **File:** `apps/orchestrator/api/routes/audit.py` (new), registered in `api/main.py`.
- **Behavior:** read the last `N` (default 50, cap 500) lines of `BLACKBOX_AUDIT_EXPORT_PATH` (`data/audit-forward.jsonl`), parse each as canonical JSON, return `{"events": [...]}` newest-last. If the file is absent/empty, return `{"events": []}`. Open, read-only.
- **Why file not events.db:** the JSONL is already the canonical, redacted, forwarder-shaped record — exactly what the panel renders. No new query layer.
- **Auth:** open (same as other GET telemetry routes).
- **Guard:** path comes from config, not the client — no traversal surface.

### 6b — Richer `approval_required` payload
- **File:** `apps/orchestrator/api/routes/skills.py` (~lines 60-65, where `draft`/`confidence` are set).
- **Add fields (keep existing):**
  ```python
  "approval_kind": "draft" if payload.get("draft") else "tool_gate",
  "pending_tool": payload.get("pending_tool"),   # {"qualified","server","input_hash"} or None
  ```
- `pending_tool` is populated from the last `tool_called` event on the thread when the run pauses with no draft. If wiring that through the pipeline is non-trivial, ship `approval_kind` alone first — the frontend fallback (D4) already infers `tool_gate` from an empty draft, so the empty-card bug is fixed with **zero backend change**; `pending_tool` just makes Mode B richer.
- **No change** to the canonical audit schema, the approval gate contract, or `approval_threshold`. These are response-DTO fields only.

---

## D7 — Phased plan

### Phase A — Loom-ready (P0 only, ~half a day)
The minimum so the demo doesn't show a broken/empty/mis-branded screen.
1. **Branding:** header → "AgentAudit" + "Flight recorder for governed agents"; swap/blank the logo (`mission-control.tsx`).
2. **Default skill → `audit_demo`** (`skill-deck.tsx:50-54`).
3. **Approval tool-gate mode** (D4 Mode B + the frontend fallback) — kills the empty body and the fake confidence with no backend dependency.
4. **Show tool events in the feed:** delete the `continue` at `mission-control.tsx:46`; give 🔧/⛔ lines a tone in `parseActivityFeed` (tool=neutral/info, denied=warn).
5. **`FlightRecorderPanel` (minimal)** + `GET /api/v1/audit/tail` — even a static tail (no live WS yet) makes the center the hero.

### Phase B — On-message (P1, ~1 day)
6. Copy deck (D3) applied throughout.
7. Right sidebar → audit-centric (event counts + sink status); move tokens/cost/context to Dev.
8. Remove/relabel Dogfooding tile and the "Compounding intelligence" magic card.
9. WS live-append into FlightRecorderPanel; filter chips.
10. Rename "The Armory · Desk" → "Skills"; move vault constellation to Dev-only.

### Phase C — Cleanup (P2, later)
11. Demote Memory Navigator + Memory Heatmap (vault surfaces) behind Dev or remove.
12. `pending_tool` backend wiring (D6b full).
13. Run History reframed as the replay/audit-log entry point.

**Loom can record after Phase A.** Everything else is polish.

---

## D8 — Cursor handoff

```
Redesign apps/dashboard/ from inbox autopilot to AgentAudit flight recorder. Additive + refactor only — no kernel changes, no schema changes. Phase A first (Loom-ready). Operator commits when ready; show git status + diff and wait for confirm.

## Phase A files to change (P0)
- apps/dashboard/components/mission-control.tsx
    - header: "BLACKBOX"→"AgentAudit", subtitle→"Flight recorder for governed agents", logo swap/blank (line 194-206)
    - parseActivityFeed: REMOVE the `if (line.startsWith("🔧"||"⛔")) continue;` at line 46; give tool lines a tone
    - idle/completed copy per D3
- apps/dashboard/components/skill-deck.tsx
    - default skill preference (line 50-54): prefer "audit_demo" first
- apps/dashboard/components/approval-inbox-card.tsx
    - implement D4 two-mode gate; frontend fallback: empty draft ⇒ tool_gate; hide confidence in tool_gate; ShieldCheck icon + "Tool call awaiting approval"
- apps/dashboard/components/flight-recorder-panel.tsx  (NEW, D5) — start with static tail
- apps/orchestrator/api/routes/audit.py  (NEW, D6a) — GET /api/v1/audit/tail?limit=N, register in api/main.py

## Phase A acceptance
1. Dashboard header reads AgentAudit; no "BLACKBOX" user-facing string except an optional "engine: BLACKBOX" footnote.
2. Fresh load selects audit_demo, not gmail_inbox_brief.
3. Running audit_demo → approval modal shows the gated tool call (vault_fs.read_note + args hash), NO confidence %, NO empty box.
4. Activity feed shows tool_called / tool_denied lines (no longer dropped).
5. FlightRecorderPanel lists recent canonical events from /api/v1/audit/tail with correlation_id + input_hash visible.
6. `cd apps/orchestrator && python -m pytest -q` still 257 passed / 2 skipped (audit.py is read-only, no test breakage; add a small test for the tail route if quick).
7. `cd apps/dashboard && npm run build` passes (static export clean).

## Do NOT
- Touch core/audit/*, the approval gate contract, approval_threshold, canonical schema, or the outbox.
- Add tokens/cost/draft to FlightRecorderPanel (Pipe 2 only).
- Rename the repo or the BLACKBOX engine internals — only the product-facing UI strings.

## Suggested commit (Phase A)
Reframe dashboard as AgentAudit flight recorder: audit_demo default, tool-gate approval, live event panel

## compound preserved? yes
UI + one read-only GET route + two additive response fields. No change to canonical schema, approval gate, outbox, or edit-log. Approval still requires explicit human grant (approval_threshold unchanged).
```

---

*Companion: [dependency audit](./agentaudit-dependency-audit.md) (two-pipe model) · [dogfood checklist](./agentaudit-dogfood-checklist.md) · [Loom script](./agentaudit-loom-script.md) (records against this redesigned UI). Record the Loom only after Phase A ships.*
