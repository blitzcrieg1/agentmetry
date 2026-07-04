# Fable ↔ Cursor synergy prompt

**Use:** Start every Fable (Opus 4.8) session with the block below.  
**Replace:** `[TASK]` with one focused job.  
**After Fable:** Copy the **Cursor handoff block** from Fable’s final message into a **new Cursor chat** (Composer/fast).

---

## Copy into Fable (master prompt)

```
# BLACKBOX — Fable build session (hand off to Cursor when done)

You are the **heavy builder** for BLACKBOX. **Cursor** is the **cheap finisher** (docs, commits, lint, small fixes, dogfooding checks). Your job is to complete ONE scoped task, then **stop** and hand off — do not keep building.

## Two-tool workflow

| Fable (you) | Cursor (operator pastes your handoff) |
|-------------|----------------------------------------|
| Multi-file features, new modules, tests | Doc sync, handoff updates, commit/push |
| API + orchestrator + dashboard in one task | `.cursorignore`, rule splits, one-line fixes |
| Architecture when file map isn’t enough | Run pytest locally, paste results back to you if needed |
| **Stop when acceptance passes** | Continue from your handoff block |

**Token rules (mandatory):**
- Read **only** files listed in [TASK] + `.cursor/rules/blackbox-handoff.mdc` file map — no kernel re-exploration
- Do **not** read entire directories, `node_modules`, `vault/30-Archive/`, `vault/20-Active-Loops/`
- Do **not** run broad codebase searches; use handoff paths
- One pytest at end (`cd apps/orchestrator && pytest -q`) — not repeated mid-task
- **Do not commit** unless [TASK] explicitly says commit
- **Do not** start Phase 4 (Gmail/Woo/resume) unless [TASK] says so

## Project snapshot (2026-07-04)
- Repo: agentic-os, branch `master`, head `3ca4faa+`
- **137 pytest**, 1 skipped, CI green
- Kernel **done** — scheduler, bus, IVT, MCP host, sandbox Tier 1, recovery, batch approve
- 9 skills, plugin v0.2, `GET /api/v1/runs/stats`, search driver (ships disabled)
- Go/no-go: dogfooding + search live once = **operator**, not you
- Audit: `docs/product-audit-2026-07.md`

## Ground rules
- Windows 11, local-first, one process (`scripts\blackbox.bat start`)
- MCP replaces tools, not LangGraph graphs
- Match existing conventions; minimal diff

---

## YOUR TASK (single scope)

[TASK]

---

## Acceptance (you must verify before handoff)
- [ ] `pytest -q` passes (report count)
- [ ] If UI touched: `npm run build` in `apps/dashboard` OR `npm run typecheck` in `apps/obsidian-plugin`
- [ ] No unrelated refactors
- [ ] List every file changed (path only)

---

## When done — OUTPUT EXACTLY THIS BLOCK (operator copies to Cursor)

Your final message **must** end with this fenced block filled in:

---CURSOR-HANDOFF---
## Continue in Cursor

**Fable completed:** [one sentence what shipped]

**Do NOT re-do in Cursor:** [what Fable already verified]

### Paste this as your first Cursor message:
```
[Paste-ready short prompt for Cursor — specific files, exact next steps, 5-15 lines max]
```

### Optional operator steps (human, not Cursor):
- [ ] …

### Files changed (for commit review):
- path/to/file

### Test result:
`137 passed` (or actual count)

### Commit suggestion (if operator wants git):
`type: one-line message`

**If blocked:** [only if you could not finish — file:line + what Cursor should do]
---END-CURSOR-HANDOFF---

Do not add more features after the handoff block. Session ends there.
```

---

## Example tasks (swap into [TASK])

### Example A — Gmail draft-only scaffold (Phase 4, when unlocked)
```
Build Gmail MCP read + create_draft only (no send): tools/gmail_server.py, drivers.json example (enabled: false), mocked tests. Skill stub optional. Out of scope: OAuth UI wizard — document env vars in docs/gmail-driver.md.
```

### Example B — Handoff/doc sync only (prefer Cursor — use Fable only if large)
```
Skip — give this to Cursor directly: sync handoff test count, commit product-audit doc, fix implementation-guide §12.
```

### Example C — Operator asked you to split cursor rules (token save)
```
Split .cursor/rules/blackbox-handoff.mdc: alwaysApply ≤50 lines pointer + glob-scoped rules for orchestrator/, dashboard/, docs/. No code changes.
```

---

## Paste into Cursor (after Fable)

When Fable ends with `---CURSOR-HANDOFF---`, copy **only** the inner ``` block into a **new Cursor chat** (Composer 2 or default Agent — not Opus).

Cursor’s job in that chat:
1. Execute the pasted prompt (small scope)
2. Commit/push **only if you ask**
3. Not re-run full Fable-scale exploration

---

## Role cheat sheet (for you)

| Need | Tool |
|------|------|
| New driver, skill pack, batch API | **Fable** with this prompt |
| Commit, README, handoff sync, lint | **Cursor** from handoff |
| “Where do I stand?” / audit | **Cursor** (or paste audit doc) |
| Real weekly usage, search live | **You** in Obsidian/terminal |
| 4-week dogfooding | **You** — `blackbox stats --days 7` |

---

*Synergy prompt v1 — 2026-07-04*
