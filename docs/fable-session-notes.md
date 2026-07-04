# Fable session notes — 2026-07-04

Built P0-A, P0-B, and P1 from [fable-continuation-prompt.md](./fable-continuation-prompt.md). **Not committed** — operator reviews in Cursor first.

## Verify (Windows)

```powershell
# Orchestrator tests (123 expected)
cd apps\orchestrator
pip install -e ".[dev]"
pytest -q

# Plugin
cd ..\obsidian-plugin
npm install
npm run deploy
# Obsidian → enable BLACKBOX → Summarize active note → check vault\30-Archive\

# Recovery (after a stale loop exists, or after --dismiss-all cleared them)
scripts\blackbox.bat start
blackbox recovery
blackbox recovery --dismiss-all   # needs API key if set

# Dashboard
cd apps\dashboard
npm run build
```

## What shipped

### P0-A — Obsidian plugin v0

- **Path:** `apps/obsidian-plugin/`
- Status bar, summarize/triage commands, pending-approval modal with draft/confidence
- API gap closed: `GET /skills/pending` now returns `draft` + `confidence` from IVT payload
- Deploy: `npm run deploy` → `vault/.obsidian/plugins/blackbox/` (gitignored)

### P0-B — Crash recovery UX

- **Path:** `core/execution/recovery.py`
- `GET /api/v1/skills/recovery`, `POST /api/v1/skills/recovery/resolve`
- CLI: `blackbox recovery [--dismiss-all]`
- Dashboard: `RecoveryPanel` on telemetry page
- Startup warning via `report_recovery_on_startup()` in `recover_interrupts()`

### Vault-path bug (critical)

**Symptom:** 32 stale `20-Active-Loops/` notes with `status: running` forever.

**Cause:** `BLACKBOX_VAULT_PATH=../../vault` produced loop paths containing `..`. `resolve_active_loop`'s traversal guard rejected them silently — successful runs never updated loop status.

**Fix:** `ObsidianClient` and `VaultWatcher` resolve vault path to absolute at init. Regression test in `tests/test_recovery.py`.

### P1 — Sandbox Tier 1

- **Path:** `core/sandbox/tier1.py`
- Allowlisted binaries (default `git`), cwd jailed to vault, scrubbed env, timeout, no shell
- `POST /api/v1/skills/interrupts/{id}/approve|deny` for `TOOL_EXEC_APPROVAL`
- Requires skill YAML `sandbox_tier: 1`
- Tests: `tests/test_sandbox_tier1.py`

## Suggested commits (when operator asks)

1. **API + pending payload** — `skills.py`, `pending_store.py`, `interrupts.py` (draft/confidence, exec approve routes)
2. **Vault path fix + recovery** — `obsidian_client.py`, `vault_watcher.py`, `recovery.py`, CLI, dashboard panel, tests
3. **Sandbox Tier 1** — `core/sandbox/`, `host.py`, `spec.py`, `config.py`, tests
4. **Plugin + docs** — `apps/obsidian-plugin/`, handoff, README, this file

Do **not** commit: `vault/.obsidian/`, `vault/00-Inbox/test2.md`, `node_modules/`, built `main.js` in plugin source (deploy artifact lives in vault only).

## Next work (post-P0/P1)

- More YAML skills (`tools:` / `node_tools:`)
- Gmail / search drivers (see `future-concepts.md` go/no-go)
- Mid-run checkpoint **resume** (recovery today only classifies/dismisses orphans)
- Obsidian plugin v0.1: WebSocket run status, batch approve
