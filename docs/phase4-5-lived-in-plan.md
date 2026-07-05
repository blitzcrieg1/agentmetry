# Phase 4–5: from test harness to lived-in governed agent OS

**State at writing:** 167 pytest, 1 skipped · Gmail driver (read+draft, disabled) ·
margin driver (enabled) · checkpoint resume shipped · `customer_reply` +
`gmail_inbox_brief` skills shipped.

Four deliverables: turn drivers on, one governed end-to-end workflow,
crash-resume, and metrics/rituals that prove the OS is *used*.

---

## 1. Turn the world on (operator, ~45 min, no code)

### Serper search (10 min)
1. Key from serper.dev → `apps/orchestrator/.env`: `SERPER_API_KEY=...`
2. `vault/.system/drivers.json` → `"search"` → `"enabled": true` (never commit)
3. Restart or `POST /api/v1/drivers/remount`
4. Verify `GET /api/v1/drivers/` → `search: mounted`
5. Prove live once: `kbeauty_trend_research` or `supplier_research`

### Gmail (30 min — `docs/gmail-driver.md`)
1. GCP: Gmail API + OAuth consent (External, self as test user) + Desktop client
2. `.env`: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`
3. `.\.venv\Scripts\python.exe tools\gmail_server.py --auth` → token to Credential Manager
4. `drivers.json` → `"gmail"` → `"enabled": true` → remount
5. Optionally flip `vault/.system/trigger-rules/gmail-morning-brief.yaml` to
   `enabled: true` for the weekday 08:00 inbox brief

Guardrails already enforced: no send tool exists in the server; 20-thread cap;
8k body truncation; per-skill tool allowlists; every call audited on the bus.

---

## 2. The governed workflow: inbox triage + reply drafting

### `gmail_inbox_brief` (read-only, cron-able)
`scan` (tool: `gmail.list_threads`) → LLM triage → prioritized reply queue in
`30-Archive/`. Cron rule ships **disabled**, weekdays 08:00 when enabled.

### `customer_reply` (thread → draft → HITL → Gmail draft)

```
fetch ─► draft ─► critic ─► human_approval ─► deliver ─► finalize
(tool-only)                 ▲ checkpoint      (tool-only:
 gmail.get_thread           interrupt_before   gmail.create_draft
                            = approval gate)   with {approved_draft})
```

Governance properties (structural, not promises):
- `approval_threshold: 1.1` — confidence caps at 1.0, so **every** run pauses
  at the gate. Nothing touches Gmail (even Drafts) without an explicit yes.
- `deliver` is a **tool-only node** (new compiler feature): no LLM call, and it
  never overwrites the approved text.
- `{approved_draft}` templating (new): post-approval tools receive
  `modified_input or draft` — the human's edit wins.
- Reject = existing terminate path; zero Gmail writes.

Daily UX: morning brief lands in archive → pick a thread id → run
`customer_reply` from the Obsidian skill picker → approve/edit in the modal →
draft appears in Gmail Drafts → **you** press send. Send-after-approve is
Phase 4-E, gated on 4 green weeks (see §4).

Known edge: a crash between approval and deliver can, on resume, produce a
duplicate Gmail draft. Harmless; accepted instead of dedup machinery.

---

## 3. Crash-resume (shipped)

`recover_pending_threads()` already survived restarts for approval-waiting
threads. The gap was **orphans** (`status: running` after a hard kill) — they
could only be dismissed while their checkpoint sat in `checkpoints.db`.

### `resume_orphan(rel_path)` — `core/execution/recovery.py`
Classifies the orphan's checkpoint and acts:

| Checkpoint state | Action |
|---|---|
| No checkpoint | mark failed (`unresumable`) |
| Paused at `human_approval` | re-register in pending queue — no re-run (`resumed_waiting`) |
| Graph finished, bookkeeping lost | replay closeout only (`resumed_completed`) |
| Genuinely mid-run | `graph.ainvoke(None, config)` under an AUTONOMOUS scheduler slot, then finalize or land at the gate |

**The invariant:** resume passes `None`, never the original state — same
pattern the approval path uses. Re-passing input would restart from the entry
node (double LLM spend, duplicate tool calls). Regression-tested.

Surfaces:
- `POST /api/v1/skills/recovery/resume {"path": ...}`
- `blackbox recovery --resume <path>`
- Boot auto-resume, opt-in: `BLACKBOX_AUTO_RESUME=1` (cap 3/boot, skipped when
  LLM degraded)

Edge cases: the interrupted node re-runs from its start (reads are safe;
`create_draft` may duplicate — accepted). Cost resumes from checkpointed value,
so `max_cost_per_run` still applies across the crash. Unreadable/stale-schema
checkpoints fail closed to `mark_failed`.

---

## 4. Metrics + rituals ("lived-in" gates)

Weekly, from `blackbox stats --days 7` (+ `runs.jsonl` for `triggered_by`):

| Metric | Threshold |
|---|---|
| Distinct skills with completed runs | ≥ 3 |
| Autonomy share (`triggered_by != manual`) | ≥ 40% wk 2 → ≥ 60% wk 4 |
| Approvals resolved | ≥ 3/week, median wait < 24h |
| Spend | < €10/mo, zero `budget_exceeded` |

Rituals:
- **Daily (2 min):** everything enters via `00-Inbox/`; clear approvals; read
  the morning brief; at most one `customer_reply`.
- **Friday (10 min):** stats → one line in `10-SOPs/os-log.md`; run `weekly_review`.
- **Monday (5 min):** `blackbox status` + recovery panel; resume or fail
  orphans. Zero-orphan weeks are the reliability signal.
- **Monthly:** `blackbox backup`.

**Unlock rule:** 4 consecutive green weeks → Phase 4-E (approve-then-send).
Any red week resets the counter. Until then drafts-in-Gmail is the ceiling.

---

## Shipped in this phase (code)

| Change | Where |
|---|---|
| `{approved_draft}` templating for post-approval tools | `core/graphs/pipeline_graph.py` |
| `tool_only_nodes` (tools without LLM, draft preserved) | `core/graphs/pipeline_graph.py` |
| `customer_reply`, `gmail_inbox_brief` skills | `vault/.system/skill-definitions/` |
| `gmail-morning-brief` cron rule (disabled) | `vault/.system/trigger-rules/` |
| `resume_orphan` + `resume_orphans_on_startup` | `core/execution/recovery.py` |
| `POST /api/v1/skills/recovery/resume` | `api/routes/skills.py` |
| `blackbox recovery --resume <path>` | `cli/__init__.py` |
| `BLACKBOX_AUTO_RESUME` boot hook | `core/execution/service.py` |
| 8 new tests (resume semantics, tool-only, approved_draft) | `tests/` |

**Not built (deliberately):** Gmail send, browser scraping, Woo, installer,
kernel changes.

---

*Phase 4–5 plan — 2026-07-05*
