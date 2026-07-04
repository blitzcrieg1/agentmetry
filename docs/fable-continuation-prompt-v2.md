# Fable continuation prompt — Phase 2 (post P0/P1)

Copy the fenced block below into Claude Fable.

---

```
# BLACKBOX — Phase 2: YAML skills + search driver + plugin v0.1

You are continuing **BLACKBOX** (Obsidian-Cortex Agentic OS). Phase 1 is **shipped and committed** (`b037156` on `master`):

- ✅ Obsidian plugin v0 (`apps/obsidian-plugin/`)
- ✅ Crash recovery UX (`core/execution/recovery.py`, dashboard Recovery panel, `blackbox recovery`)
- ✅ Sandbox Tier 1 (`core/sandbox/tier1.py`, exec interrupt approve/deny)
- ✅ Vault-path fix (relative `BLACKBOX_VAULT_PATH` no longer orphans active-loop notes)
- ✅ **123 pytest** passing

Do **not** re-implement Phase 1. Read `.cursor/rules/blackbox-handoff.mdc` and `docs/fable-session-notes.md` first.

## Environment
- Windows 11, local only, no Docker
- Run: `scripts\blackbox.bat start` → `:8000`
- Vault: `vault/`; only enabled driver today: `vault_fs` (read-only)
- LLM: `gemini-2.5-flash-lite`, paid tier in `apps/orchestrator/.env`
- Tests: `cd apps/orchestrator && pip install -e ".[dev]" && pytest -q` — must stay **123+**
- **Do not commit** unless operator explicitly asks
- Minimize scope; match existing patterns

## Go/no-go (from `docs/future-concepts.md`)
Plugin + recovery are done. **Gmail/Woo still deferred** until operator dogfoods 3+ skills weekly.
**Search MCP is OK** as first external driver (read-only, no OAuth circus).

---

## Priority order — ship in sequence

### P2-A — YAML skill pack (vault-only, no new drivers)

Add **2–3 pipeline skills** using existing `vault_fs.read_note` + RAG context. Zero new Python graphs.

**Target skills** (pick all three; copy patterns from `summarize_note.yaml` / `inbox_triage.yaml`):

| Skill | Purpose | Trigger idea |
|-------|---------|--------------|
| `supplier_intake` | Triage pasted supplier email/quote → structured table (vendor, MOQ, lead time, red flags) | manual + optional inbox tag `#supplier` |
| `client_brief` | Turn meeting/inbox note into client-facing brief draft (sections: context, deliverables, open questions) | manual |
| `follow_up_draft` | From a note tagged `#follow-up`, draft a short check-in email body (vault-only; no send) | manual |

**Each skill must:**
- `graph: pipeline` with `tools: [vault_fs.read_note]`
- `node_tools:` read `{user_input}` path
- `human_approval` node on anything client/supplier-facing (draft step → approval → finalize archive)
- `max_cost_per_run` ≤ 0.15
- Appear in dashboard Armory + Obsidian plugin (automatic if registered)

**Vault helpers (optional, small):**
- Sample notes in `vault/00-Inbox/` for smoke test (UTF-8 via `Set-Content -Encoding utf8`)
- SOP stub in `vault/10-SOPs/supplier-intake.md` referenced in system_prompt

**Acceptance:**
- Each skill runs live from dashboard and Obsidian "Summarize"-style command (add plugin commands if needed)
- Archive lands in `30-Archive/` with approval gate working on `client_brief` / `follow_up_draft`
- pytest: add `tests/test_skill_yaml.py` or extend existing registry test — all 5+ skills load without error

---

### P2-B — Search MCP driver MVP (read-only)

**Why:** Enables supplier/lead research without browser RPA. First step toward K-beauty / wholesale vertical.

**Implement:**
1. New MCP server or thin wrapper: `apps/orchestrator/tools/search_server.py` (FastMCP, like `vault_fs_server.py`)
   - Tool: `search.web` — `{ query, num_results?: 5 }` → markdown table of title, url, snippet
   - Backend: **Serper** (`SERPER_API_KEY`) or **Tavily** (`TAVILY_API_KEY`) — config via `env_allow` in drivers.json, never in skill YAML
2. Register in `vault/.system/drivers.json` — `enabled: false` by default; example entry documented
3. Skill `supplier_research` (pipeline):
   - `tools: [search.web, vault_fs.read_note]` (optional read brand SOP from vault)
   - nodes: research → synthesize → human_approval → finalize
   - Writes competitor/supplier research table to archive
4. Tests: mock HTTP in `tests/test_search_driver.py` — no live API key required in CI
5. Update `docs/future-concepts.md` go/no-go: check "Gmail or search driver MVP stable in CI" when green

**Out of scope:** Gmail, Woo, auto-send, browser automation

**Acceptance:**
- With `SERPER_API_KEY` in driver env + driver enabled, `supplier_research` runs and archives
- Without key: graceful error, no crash
- Driver mount failure doesn't block boot (existing pattern)

---

### P2-C — Obsidian plugin v0.1 (polish)

Extend `apps/obsidian-plugin/src/main.ts`:

1. **Run feedback:** after execute, show Notice with thread_id + link hint ("check 30-Archive")
2. **WebSocket hook (optional if time):** subscribe to existing dashboard WS (`/api/v1/events` or bus bridge) — status bar shows "running summarize_note…" during active run
3. **Command:** "BLACKBOX: Run skill on active note…" — SuggestModal over `GET /api/v1/skills/` skill list (not hardcoded summarize/triage only)
4. Rebuild + `npm run deploy`; update `apps/obsidian-plugin/README.md`

**Acceptance:** Generic skill picker works; operator sees run started/completed feedback without opening dashboard

---

## File map (start here)
| Task | Path |
|------|------|
| Skill YAML | `vault/.system/skill-definitions/` |
| Pipeline engine | `core/graphs/pipeline_graph.py` |
| Skill registry | `core/graphs/registry.py` |
| Drivers | `core/drivers/`, `vault/.system/drivers.json`, `tools/vault_fs_server.py` (template) |
| Execute | `core/execution/service.py` |
| Plugin | `apps/obsidian-plugin/src/main.ts` |
| Triggers | `vault/.system/trigger-rules/` (optional new rules) |

## Do NOT build this session
- Gmail OAuth / send
- WooCommerce REST
- Kernel scheduler / budget changes
- Sandbox Tier 2 / Docker
- Mid-run checkpoint resume (future P3)

## Deliverables
1. Code + tests for P2-A, then P2-B, then P2-C
2. Brief `docs/fable-session-notes.md` append (date, what shipped, verify commands)
3. Handoff update in `.cursor/rules/blackbox-handoff.mdc` (skill count, search driver, next work)

## Verify (Windows)
```powershell
cd apps\orchestrator && pip install -e ".[dev]" && pytest -q
scripts\blackbox.bat start
# Dashboard Armory → run supplier_intake on 00-Inbox/sample
# Obsidian → BLACKBOX: Run skill on active note
cd apps\obsidian-plugin && npm run deploy
```

Start with **P2-A YAML skills**. Proceed to P2-B and P2-C without asking when acceptance passes. Report blockers with file:line evidence.
```

---

*Previous prompt: [fable-continuation-prompt.md](./fable-continuation-prompt.md) (Phase 1 — completed 2026-07-04).*
