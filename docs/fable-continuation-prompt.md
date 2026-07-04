# Fable continuation prompt — P0/P1 build

Copy everything inside the fenced block below into Claude Fable (or paste as the first message in a Fable session with repo access).

---

```
# BLACKBOX — Continue building (Obsidian plugin · crash recovery · sandbox Tier 1)

You are continuing work on **BLACKBOX** (Obsidian-Cortex Agentic OS), a local-first governed agent runtime. The kernel, drivers (MCP), inbox autonomy, budget/defer, and 111 pytest tests are **shipped**. Do not re-architect s1–s4. Your job is the **next three roadmap items** in priority order.

## Read first (repo)
- `.cursor/rules/blackbox-handoff.mdc` — ground truth, file map, API refs
- `docs/tomorrow-handoff.md` — session state (2026-07-03)
- `docs/future-concepts.md` §2.2 — acceptance intent for these three items

## Environment (non-negotiable)
- **Windows 11**, solo dev, **local only** — no Docker, no cloud deploy
- Run: `scripts\blackbox.bat start` → orchestrator + dashboard on `:8000`
- Vault at `vault/`; skills in `vault/.system/skill-definitions/`
- LLM: Gemini (`gemini-2.5-flash-lite`, paid tier in `apps/orchestrator/.env`)
- **Minimize scope** — match existing conventions; no unrelated refactors
- **Do not commit** unless the operator explicitly asks
- Tests: `cd apps/orchestrator && pytest -q` — must stay green (111+)

## Ground rules (do not violate)
- Kernel + user space stay in **one process** (`apps/orchestrator/`)
- MCP replaces tools, not LangGraph graphs — keep `core/graphs/registry.py`
- Skills opt into tools via YAML `tools:` / `node_tools:` (closed by default)
- Mutating API routes use `X-API-Key` when `BLACKBOX_API_KEY` is set (`core/auth.py`)
- Do not rebuild: scheduler, outbox, IVT defer/resume, vault watcher, budget ledger, vault_fs driver

## Priority order — ship in sequence

### P0-A — Obsidian plugin v0
**Why:** Daily-driver UX; run skills from the note you're editing without opening the dashboard.

**Scope (v0 only — no settings UI sprawl):**
1. New package: `apps/obsidian-plugin/` (standard Obsidian Community Plugin scaffold: TypeScript, esbuild or obsidian-sample-plugin layout)
2. **Status bar item:** poll `GET http://127.0.0.1:8000/api/v1/health` every 30s — show `ok` / `degraded` / `offline`
3. **Command palette:**
   - "BLACKBOX: Summarize active note" → `POST /api/v1/skills/execute` with `skill_name: summarize_note`, `user_input: <vault-relative path of active file>`, `session_id: obsidian-<note-basename>`
   - "BLACKBOX: Triage active note" → same pattern with `inbox_triage`
4. **Settings tab (minimal):** orchestrator URL (default `http://127.0.0.1:8000`), optional API key
5. **Pending approvals:** command "BLACKBOX: Show pending approvals" — `GET /api/v1/skills/pending` → simple modal listing thread_id + skill; approve/deny via `POST /api/v1/skills/approve` `{ thread_id, approved, modified_input? }`
6. Map vault path: plugin setting `vaultPath` must match BLACKBOX `BLACKBOX_VAULT_PATH` (document in plugin README)

**API contracts (existing — do not break):**
```typescript
// POST /api/v1/skills/execute
{ skill_name: string, user_input: string, session_id: string }
// POST /api/v1/skills/approve
{ thread_id: string, approved: boolean, modified_input?: string }
// GET /api/v1/skills/pending → { pending: [{ thread_id, skill_name, session_id, vector }] }
// GET /api/v1/health → budget, degraded, drivers, etc.
```

**Acceptance:**
- With BLACKBOX running, open a note in Obsidian, run Summarize → archive appears under `vault/30-Archive/` within ~10s
- Status bar reflects health; offline shows clear message (no silent fail)
- README in `apps/obsidian-plugin/README.md` with dev load instructions (load unpacked from `.obsidian/plugins/blackbox/`)

**Out of scope for v0:** WebSocket live board, skill editor, batch approve, mobile

---

### P0-B — Crash recovery UX
**Why:** After kill/restart, `20-Active-Loops/` notes with `status: running` and orphan IVT rows confuse the operator.

**Current behavior (extend, don't replace):**
- `ObsidianClient.write_active_loop()` / `resolve_active_loop()` — `core/memory/obsidian_client.py`
- `recover_interrupts()` on startup reloads HITL + deferred budget/degraded — `core/execution/service.py`
- `write_crash_report()` writes to `30-Archive/` on user terminate — `obsidian_client.py`
- **Gap:** stale active-loop files + failed mid-run threads are not surfaced or cleaned

**Implement:**
1. **Startup scan** (in `recover_interrupts()` or adjacent): find all `vault/20-Active-Loops/*.md` where frontmatter `status == "running"`. For each, check LangGraph checkpointer / `pending_threads` / IVT — classify as:
   - `recoverable_hitl` — thread still in pending store
   - `orphan_loop` — note says running but no live thread
   - `failed` — associated RUN_FAILED or checkpointer dead
2. **API:** `GET /api/v1/skills/recovery` → `{ stale_loops: [...], orphan_count, recoverable: [...] }`
3. **API:** `POST /api/v1/skills/recovery/resolve` `{ paths: string[], action: "mark_failed" | "dismiss" }` — updates frontmatter to `status: failed|dismissed`, optional crash report note
4. **Dashboard panel** (small): "Recovery" section on existing skills/interrupts page — list stale loops, one-click dismiss
5. **CLI:** `blackbox recovery` — print stale count + `--dismiss-all` flag (add to `apps/orchestrator/cli/`)

**Acceptance:**
- Kill orchestrator mid-run → restart → recovery endpoint lists the stale loop; dismiss clears it without manual vault edit
- pytest covers scan + resolve (use temp vault fixture pattern from `tests/test_approval_flow.py`)
- No false dismiss of genuinely pending HITL threads

---

### P1 — Sandbox Tier 1 (restricted subprocess)
**Why:** Unlock `tags: ["exec"]` drivers (future shell/git) with governance instead of hard deny.

**Current (Tier 0):** `core/drivers/permissions.py` — any exec-tagged tool → `ToolExecApprovalRequired` → IVT `TOOL_EXEC_APPROVAL` → deny. Host: `core/drivers/host.py`.

**Implement Tier 1 minimally:**
1. New module `core/sandbox/tier1.py`:
   - Allowlist commands (config: `BLACKBOX_SANDBOX_TIER1_COMMANDS=git,python` or YAML in `vault/.system/sandbox-tier1.yaml`)
   - Run subprocess with: cwd jailed to vault or temp dir, timeout, no shell=True, env stripped except explicit allowlist
   - Capture stdout/stderr; max output size cap
2. Change flow in `host.call_tool()`: when `ToolExecApprovalRequired` would fire, if driver is Tier-1-eligible AND skill has `sandbox_tier: 1` in YAML AND user pre-approved via new interrupt approve path → execute via tier1 runner instead of deny
3. **API:** extend `POST /api/v1/skills/approve` OR add `POST /api/v1/skills/approve-tool-exec` for `InterruptVector.TOOL_EXEC_APPROVAL` rows (list via existing `GET /api/v1/skills/interrupts`)
4. **Proof driver:** optional read-only `git` MCP wrapper or inline `vault_git` tool that runs `git status` / `git diff` in vault (exec-tagged, Tier 1 only) — enable in test only
5. Tests in `tests/test_sandbox_tier1.py`: command allowlist, timeout, path jail, deny unknown binary

**Acceptance:**
- Exec-tagged tool without approval → still denied (Tier 0 behavior preserved)
- Approve TOOL_EXEC interrupt → Tier 1 runs allowed command → result returned to pipeline; audit event on bus
- Disallowed command (e.g. `rm`) never runs even after approval

**Out of scope:** Docker/E2B, full shell REPL, network from sandbox

---

## File map (start here — do not re-explore kernel)
| Task | Path |
|------|------|
| Execute skill | `core/execution/service.py` → `run_skill()` |
| API routes | `api/routes/skills.py` |
| Active loops | `core/memory/obsidian_client.py` |
| Interrupts | `core/kernel/interrupts.py` |
| Tool host | `core/drivers/host.py`, `core/drivers/permissions.py` |
| Dashboard | `apps/dashboard/` — add Recovery panel near interrupts |
| CLI | `apps/orchestrator/cli/__init__.py` |

## Deliverables per phase
1. Working code + tests for P0-A, then P0-B, then P1
2. Short update to `.cursor/rules/blackbox-handoff.mdc` (status + new paths)
3. Brief `docs/fable-session-notes.md` entry: what shipped, how to verify on Windows

## Verification script (run after each phase)
```powershell
scripts\blackbox.bat start
cd apps\orchestrator && pytest -q
# P0-A: Obsidian → Summarize active note → check vault\30-Archive\
# P0-B: start run → taskkill /F orchestrator → restart → blackbox recovery
# P1: pytest tests/test_sandbox_tier1.py
```

## What NOT to build this session
- Gmail, WooCommerce, search MCP drivers (`docs/future-concepts.md` deferred until go/no-go)
- New YAML business skills beyond what's needed for plugin smoke test
- Kernel scheduler / token changes
- Logo / dashboard cosmetic work

Start with **P0-A Obsidian plugin v0**. When v0 acceptance passes, proceed to P0-B without asking. Report blockers with file:line evidence.
```

---

## Usage notes

- **Token-light:** If Fable quota is tight, send only P0-A first; add P0-B and P1 in follow-up sessions.
- **Repo access:** Fable needs the full `agentic-os` repo (private GitHub or local sync).
- **After Fable finishes:** Operator reviews in Cursor; commit only when ready.

*Created 2026-07-04 from handoff + roadmap priorities.*
