# External agent audit (Tier B)

Agentmetry records **governed BLACKBOX runs (Tier A)** and **external agents you wire in (Tier B)** into the same `audit-forward.jsonl` flight recorder.

## Architecture

```
Cursor / Claude / Codex / Antigravity / MCP clients
        ↓ hooks or mcp_audit_proxy.py
  scripts/agentmetry_ingest.py
        ↓ POST /api/v1/audit/ingest
  audit-forward.jsonl + SIEM sinks
        ↓
  Dashboard flight recorder (source badges)
```

## Quick start — Cursor (global hooks)

Hooks install to **`~/.cursor/hooks.json`** — every workspace, not just this repo. The orchestrator rewrites them on boot; you can also run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1
```

**One-time:** fully quit Cursor after install so hooks load. Then any project you open logs to Agentmetry when the orchestrator is on `:8000`.

**Requirements:**

1. BLACKBOX running: `scripts\blackbox.bat start` → `:8000`
2. `BLACKBOX_AUDIT_EXPORT_ENABLED=1` (default)
3. Optional: `BLACKBOX_API_KEY` in orchestrator `.env` — hooks send `X-API-Key` via env

Restart Cursor after pulling hooks so they load (Hooks tab in settings). Global hooks live in `%USERPROFILE%\.cursor\hooks.json`.

## Ingest API

```http
POST /api/v1/audit/ingest
Content-Type: application/json
X-API-Key: <optional>

{
  "source_app": "cursor",
  "event_type": "tool_called",
  "correlation_id": "conversation-uuid",
  "session_id": "optional",
  "tool": {
    "qualified": "Shell.run",
    "server": "cursor",
    "arguments": {"command": "pytest -q"}
  }
}
```

`event_type`: `session_start` | `session_end` | `tool_called` | `tool_denied` | `tool_failed` | `approval_request` | `approval_response`

Canonical output adds:

```json
"source": {"tier": "external", "app": "cursor", "adapter": "cursor_hook"}
```

## Claude Code (boot-installed + global)

**Launch-and-forget, like Cursor.** On orchestrator boot, `bootstrap_tier_b_hooks()` **merges** Agentmetry hooks into `~/.claude/settings.json` — every Claude Code project is audited, no per-repo setup. The merge is **non-destructive** (`theme`, `permissions`, `mcpServers`, `env`, and any existing hooks are preserved) and **idempotent** (re-run never duplicates). Never overwrites the file; if it can't parse your settings.json it skips rather than clobber.

Manual install / re-install:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
# then FULLY QUIT and reopen Claude Code so global settings load
```

Events (PascalCase): `SessionStart`, `PreToolUse`, `PostToolUse`, `Notification`, `Stop`. Template: `adapters/claude/settings.agentmetry.json` (nested `event -> [{hooks:[{type,command}]}]` schema).

```powershell
$env:AGENTMETRY_SOURCE_APP="claude"; python scripts/agentmetry_ingest.py selftest   # GREEN
# then run any tool in Claude Code and confirm a real hook fired:
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/audit/tail?sources=claude&limit=10" |
  Select -ExpandProperty events |
  Select timestamp_utc, @{n='adapter';e={$_.source.adapter}}, @{n='tool';e={$_.tool.qualified}}
# success = adapter `claude_hook` with a real tool (not claude_selftest)
```

Honest limits for Claude Tier B: approval *responses* are inferred (ask → tool ran), same as Cursor; Claude hook payloads do **not** carry the model slug, so `model.id` shows the app name, not `claude-sonnet`. A transcript-watcher fallback (`~/.claude/projects/<encoded>/<session>.jsonl`) is **deferred** — hooks already cover every tool call and a watcher would double-log.

## Google Antigravity

Antigravity 2.0 often runs from **`~/.gemini/antigravity/scratch`**, not your repo — project `.agents/hooks.json` is **not** loaded there. Install **global** hooks once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_antigravity_hooks.ps1
# Restart Antigravity
```

That writes `~/.gemini/config/hooks.json` with absolute paths to `agentmetry_ingest.py`. Antigravity 2.0 stdin uses `toolCall.name` + `toolCall.args.CommandLine` (commands captured on **PreToolUse** / `run_command`).

Project-only (when workspace **is** `agentic-os`): merge `adapters/antigravity/hooks.agentmetry.json` into `.agents/hooks.json`.

```powershell
python scripts/agentmetry_ingest.py antigravity hook PreToolUse
$env:AGENTMETRY_SOURCE_APP="antigravity"; python scripts/agentmetry_ingest.py selftest
```

Transcript fallback: `<app_data>/brain/<conversationId>/.system_generated/logs/transcript.jsonl`.

## OpenAI Codex CLI

Project hooks ship in `.codex/hooks.json` (or merge `adapters/codex/hooks.agentmetry.json` into `~/.codex/hooks.json`). Codex uses nested matcher groups — see [OpenAI Codex hooks docs](https://developers.openai.com/codex/hooks).

Events wired: `SessionStart`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`.

```powershell
python scripts/agentmetry_ingest.py codex hook PostToolUse
python scripts/agentmetry_ingest.py selftest
# AGENTMETRY_SOURCE_APP=codex for codex-specific selftest
```

**First run:** Codex requires you to **trust** new hooks — open `/hooks` in the Codex CLI and approve the Agentmetry hook definitions (hash-based trust model). Untrusted hooks are skipped silently.

**Bonus:** Codex hook stdin includes `model` (active model slug) — one of the few Tier B adapters that can populate `model.id` in the canonical event.

**Coverage gaps (honest):** `PreToolUse`/`PostToolUse` may not fire for every tool path (`unified_exec`, some MCP, `WebSearch`) — see OpenAI docs. Audit what you can observe; don't claim full coverage.

## Cursor (expanded — GLM research validated)

Project hooks in `.cursor/hooks.json` now include **before** and **after** gating events:

- `beforeShellExecution` / `beforeMCPExecution` / `preToolUse` → `approval_request` (allow/deny/ask)
- `afterShellExecution` / `afterMCPExecution` / `postToolUse` → `tool_called`
- `sessionStart` / `sessionEnd` / `stop`

**Windows:** hooks must invoke `python.exe` **directly** (no `.cmd` wrapper — batch files drop stdin). Reinstall: `scripts\install_cursor_hooks.ps1`. Ingest tries UTF-8, UTF-16-LE, and BOM variants on stdin.

Research reference: [`docs/glm-52-external-agentmetry-results.md`](./glm-52-external-agentmetry-results.md) (full GLM deliverable).

## Verify hooks actually work (do this before trusting the trail)

Hooks fail **silently** if `python` isn't on the IDE's PATH or the orchestrator is down — you'd believe you're being audited when you're not. Confirm the round-trip:

```powershell
# with the orchestrator running (:8000):
python scripts/agentmetry_ingest.py selftest
#   Agentmetry hooks: GREEN — synthetic event round-tripped for source 'cursor'.
```

RED means the POST failed (orchestrator down / wrong `AGENTMETRY_URL`) or the event never landed (`BLACKBOX_AUDIT_INGEST_ENABLED=0` / sink off). Set `AGENTMETRY_SOURCE_APP` first to test a specific adapter. Freshness for the dashboard badge: `GET /api/v1/audit/status` returns `last_event_utc` + per-source counts.

## Approvals & enforcement (honest)

Agentmetry's external hooks are **observe-only by default** — they record, they do **not** change the IDE's approval decision. Installing them never auto-approves a tool call the IDE would otherwise prompt you to review.

- **Enforcement is opt-in.** Set `AGENTMETRY_ENFORCE=allow|deny|ask` only if you *want* the hook to emit a decision. Unset (default) = the IDE's own approval flow is untouched.
- **Approval *requests* are observed directly** — an `ask` on a `before*`/`PreToolUse` hook becomes an `approval_request` (pending).
- **Approval *responses* are inferred, not natively reported.** No IDE emits "the human clicked approve." Agentmetry infers it: a tool that *runs* after an `ask` (a matching `tool_called`) yields an `approval_response` marked **`reason: inferred:tool_ran_after_ask`**; an `ask` still pending at session end yields an inferred **denied**. These events are explicitly flagged as inferred — treat them as strong evidence, not a native signal.

**What leaves the hook:** tool arguments are SHA-256 hashed **inside the hook process**; only `input_hash` is POSTed by default. Set `BLACKBOX_AUDIT_LOG_COMMANDS=1` in `apps/orchestrator/.env` (or `AGENTMETRY_LOG_COMMANDS=1` in the hook environment) to also record **shell command text** (`command` field) for Bash / `run_command` / `shell.run` tools across Cursor, Claude, Codex, and Antigravity — so an investigator can see what actually ran. Inline secrets in the command (bearer tokens, `user:pass@` URLs, `--password`, AWS/OpenAI/GitHub/Slack keys) are **scrubbed to `<redacted>` first**, at both the hook and the server (`core/audit/redaction.py`). Scrubbing is best-effort, not a guarantee — an unusual secret shape may slip through, so treat the local `audit-forward.jsonl` as sensitive and keep it on machines you own. Other args stay hashed.

## MCP proxy (any client)

Wrap MCP server stdio with audit logging:

```powershell
python apps/orchestrator/tools/mcp_audit_proxy.py --server vault_fs -- `
  python apps/orchestrator/tools/vault_fs_server.py C:\path\to\vault
```

Point Cursor/Claude MCP config at the proxy command instead of the raw server.

- **Correlation:** every call in one proxy process shares a per-process session id (override with `AGENTMETRY_CORRELATION_ID`) — not the JSON-RPC request id, which collides across sessions.
- **Args hashed in-proxy:** only `input_hash` is sent; plaintext arguments never leave the proxy.
- **Errors captured:** an MCP error response is matched to its request and logged as `tool_failed`.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTMETRY_URL` | `http://127.0.0.1:8000` | Ingest base URL |
| `AGENTMETRY_SOURCE_APP` | `cursor` | Default source in hook mapper |
| `AGENTMETRY_LOG_COMMANDS` | *(off)* | `1` = store shell command text in audit (also reads `BLACKBOX_AUDIT_LOG_COMMANDS` from `apps/orchestrator/.env`) |
| `BLACKBOX_API_KEY` | *(empty)* | Auth header for ingest |
| `BLACKBOX_AUDIT_INGEST_ENABLED` | `1` | Kill switch |

## Honest limits (Tier C)

- **Works:** Agents you instrument (hooks, MCP proxy, custom scripts) — captures tool calls (success/failure) and approval requests.
- **Inferred, not native:** the human approve/deny *decision* for external agents is inferred from whether the tool ran (see Approvals above). Tier A (governed BLACKBOX runs) captures the real grant/deny.
- **Not captured for Tier B:** model/provider id (hook payloads omit it — shown as the app name, not `gpt-4`/`claude-sonnet`), per-approver identity.
- **Does not work:** Silent browser ChatGPT, auto-approve Cursor with hooks disabled, or any agent that never hits your adapter.
- **Not a CASB:** Network-level shadow-AI detection is a different product.

## Disable external ingest

```env
BLACKBOX_AUDIT_INGEST_ENABLED=0
```

Tier A BLACKBOX runs continue; adapters receive HTTP 503.
