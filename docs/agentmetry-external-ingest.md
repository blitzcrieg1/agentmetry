# External agent audit (Tier B)

Agentmetry records **governed Agentmetry runs (Tier A)** and **external agents you wire in (Tier B)** into the same `audit-forward.jsonl` flight recorder.

## Architecture

```
Claude Code / Cursor / Codex / Antigravity / Qwen Code / Kimi Code / MCP clients
        ↓ hooks or agentmetry mcp-proxy
  scripts/agentmetry_ingest.py
        ↓ POST /api/v1/audit/ingest
  audit-forward.jsonl + SIEM sinks
        ↓
  Dashboard flight recorder (source badges)
```

## Quick start — Claude Code (global hooks)

**Launch-and-forget.** On orchestrator boot, `bootstrap_tier_b_hooks()` **merges** Agentmetry hooks into `~/.claude/settings.json` — every Claude Code project is audited, no per-repo setup. The merge is **non-destructive** (`theme`, `permissions`, `mcpServers`, `env`, and any existing hooks are preserved) and **idempotent** (re-run never duplicates). Never overwrites the file; if it can't parse your settings.json it skips rather than clobber.

Manual install / re-install:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
# then FULLY QUIT and reopen Claude Code so global settings load
```

**One-time:** fully quit Claude Code after install so hooks load. Then any project you open logs to Agentmetry when the orchestrator is on `:8000`.

**Requirements:**

1. Agentmetry running: `scripts\agentmetry.bat start` → `:8000`
2. `AGENTMETRY_AUDIT_EXPORT_ENABLED=1` (default)
3. Optional: `AGENTMETRY_API_KEY` in orchestrator `.env` — hooks send `X-API-Key` via env

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

## Quick start — Cursor (global hooks)

Hooks install to **`~/.cursor/hooks.json`** — every workspace, not just this repo. `agentmetry hooks install` writes them (the orchestrator rewrites them on boot only with `AGENTMETRY_AUTO_INSTALL_HOOKS=1`); on Windows you can also run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1
```

**One-time:** fully quit Cursor after install so hooks load. Then any project you open logs to Agentmetry when the orchestrator is on `:8000`.

Restart Cursor after pulling hooks so they load (Hooks tab in settings). Global hooks live in `%USERPROFILE%\.cursor\hooks.json`.

## Quick start — Qwen Code & Kimi Code (Chinese CLI agents)

Both use the **same hook wire protocol as Claude Code** (JSON on stdin, `PreToolUse` / `PostToolUse`).

| Agent | Install | Config |
|-------|---------|--------|
| Qwen Code | `scripts\install_qwen_hooks.ps1` | `~/.qwen/settings.json` |
| Kimi Code | `scripts\install_kimi_hooks.ps1` | `~/.kimi-code/config.toml` |

Full guide: [`docs/integrations/chinese-agents.md`](integrations/chinese-agents.md)

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

`event_type`: `session_start` | `session_end` | `tool_called` | `tool_denied` | `tool_failed` | `approval_request` | `approval_response` | `hook_remediation`

`hook_remediation` is for a deployment tool that reinstalled hooks, such as an
Intune remediation or a LaunchAgent. It is recorded as `action.type:
config_change` with `source_topic: external/<app>/hook_remediation`, never as a
tool call, so tool-sequence rules do not count it. Only `source_app`,
`outcome`, `reason`, `timestamp_utc`, `adapter` and the initiator fields are
kept; a session id or a tool block is dropped. `outcome` is `success` or
`error`, and any other value is recorded as `error`.

```json
{"event_type": "hook_remediation", "source_app": "agentmetry", "outcome": "success",
 "reason": "intune remediation reinstalled hooks"}
```

A deployment script can check the result with `agentmetry doctor --json`. It
prints `schema`, `version`, `exit_code`, `orchestrator_reachable`,
`hook_profile`, `hooks` (each agent `covered`, `uncovered`, `absent` or
`unknown`), `policy` (`locked`, `pinned`, `rejected`) and `findings`. Test the
fields rather than the sentences in `findings`, which get reworded. `schema`
changes only when a field changes meaning or goes away.

Canonical output adds:

```json
"source": {"tier": "external", "app": "cursor", "adapter": "cursor_hook"}
```

## Google Antigravity

Antigravity 2.0 often runs from **`~/.gemini/antigravity/scratch`**, not your repo — project `.agents/hooks.json` is **not** loaded there. Install **global** hooks once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_antigravity_hooks.ps1
# Restart Antigravity
```

That writes `~/.gemini/config/hooks.json` with absolute paths to `agentmetry_ingest.py`. Antigravity 2.0 stdin uses `toolCall.name` + `toolCall.args.CommandLine` (commands captured on **PreToolUse** / `run_command`).

Project-only (when workspace **is** `agentmetry`): merge `adapters/antigravity/hooks.agentmetry.json` into `.agents/hooks.json`.

```powershell
python scripts/agentmetry_ingest.py antigravity hook PreToolUse
$env:AGENTMETRY_SOURCE_APP="antigravity"; python scripts/agentmetry_ingest.py selftest
```

Transcript fallback: `<app_data>/brain/<conversationId>/.system_generated/logs/transcript.jsonl`.

## OpenAI Codex CLI

Install with `agentmetry hooks install --agent codex`, which merges into `~/.codex/hooks.json` with absolute paths and preserves any hooks of your own. `--managed` writes the admin-managed `requirements.toml` instead. From a clone, `scripts/install_codex_hooks.ps1` does the same per-user merge. The template in `adapters/codex/hooks.agentmetry.json` is still there for a manual merge, but its command is relative and only resolves if Codex starts in the repo root. Codex uses nested matcher groups; see [OpenAI Codex hooks docs](https://developers.openai.com/codex/hooks).

Events wired: `SessionStart`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `Stop`.

**Enforcement:** a DLP or tool-policy block is a real deny from **0.9.5**. Earlier releases sent Codex Cursor's `{"permission": "deny"}`, which Codex rejects as an unknown field before running the tool, so on 0.9.4 and earlier a block was recorded as `denied` while the tool ran ([#246](https://github.com/blitzcrieg1/agentmetry/pull/246)). Codex now gets `hookSpecificOutput.permissionDecision: "deny"` with a non-empty reason on `PreToolUse`, and `decision.behavior: "deny"` on `PermissionRequest`. Codex parses `ask` and runs the tool anyway, so a policy ask is enforced as deny.

```powershell
python scripts/agentmetry_ingest.py codex hook PostToolUse
python scripts/agentmetry_ingest.py selftest
# AGENTMETRY_SOURCE_APP=codex for codex-specific selftest
```

**First run:** Codex requires you to **trust** new hooks — open `/hooks` in the Codex CLI and approve the Agentmetry hook definitions (hash-based trust model). Untrusted hooks are skipped silently.

**Bonus:** Codex hook stdin includes `model` (active model slug) — one of the few Tier B adapters that can populate `model.id` in the canonical event.

**Coverage gaps (honest):** per Codex's hooks page (checked 2026-10-13), `PreToolUse` and `PostToolUse` fire for shell, unified exec, `apply_patch`, MCP and other local function tools. Hosted tools such as `WebSearch` run on OpenAI's side and fire neither, so they are not recorded. Codex cloud tasks are not recorded at all; see [agent coverage](agent-coverage.md).

## GitHub Copilot (CLI and VS Code agent mode)

Install with `agentmetry hooks install --agent copilot`. It writes its own file, `~/.copilot/hooks/agentmetry.json` (or `$COPILOT_HOME/hooks/`), in Copilot CLI's version-1 format. Copilot CLI reads it, and so does VS Code agent mode, which accepts that format and reads the same directory. Your own hook files beside it are left alone. `--managed` writes the same document as a CLI policy hook (`/etc/github-copilot/policy.d/`, or `C:\ProgramData\GitHub\Copilot\policy.d\` on Windows), which a user cannot edit or turn off.

Events wired: `sessionStart`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `sessionEnd`, `agentStop`.

**Enforcement:** a DLP or tool-policy block exits with code 2 and the reason on stderr. The two surfaces read different JSON for a decision, and exit code 2 is the one signal both document as a deny. A policy ask is enforced as deny.

**Limits:** VS Code's agent hooks are a preview feature, an organisation can disable them, and `chat.useHooks: false` disables them locally; `agentmetry posture` reports the last one. A machine with only VS Code Copilot may report Copilot as not installed, because the coverage check looks for `~/.copilot`. Neither surface has been run live against this hook yet.

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

RED means the POST failed (orchestrator down / wrong `AGENTMETRY_URL`) or the event never landed (`AGENTMETRY_AUDIT_INGEST_ENABLED=0` / sink off). Set `AGENTMETRY_SOURCE_APP` first to test a specific adapter. Freshness for the dashboard badge: `GET /api/v1/audit/status` returns `last_event_utc` + per-source counts.

## Approvals & enforcement (honest)

Agentmetry's external hooks are **observe-only by default** — they record, they do **not** change the IDE's approval decision. Installing them never auto-approves a tool call the IDE would otherwise prompt you to review.

- **Enforcement is opt-in.** Set `AGENTMETRY_ENFORCE=allow|deny|ask` only if you *want* the hook to emit a decision. Unset (default) = the IDE's own approval flow is untouched.
- **Approval *requests* are observed directly** — an `ask` on a `before*`/`PreToolUse` hook becomes an `approval_request` (pending).
- **Approval *responses* are inferred, not natively reported.** No IDE emits "the human clicked approve." Agentmetry infers it: a tool that *runs* after an `ask` (a matching `tool_called`) yields an `approval_response` marked **`reason: inferred:tool_ran_after_ask`**; an `ask` still pending at session end yields an inferred **denied**. These events are explicitly flagged as inferred — treat them as strong evidence, not a native signal.

**What leaves the hook:** tool arguments are SHA-256 hashed **inside the hook process**; only `input_hash` is POSTed by default. Set `AGENTMETRY_AUDIT_LOG_COMMANDS=1` in `apps/orchestrator/.env` (or `AGENTMETRY_LOG_COMMANDS=1` in the hook environment) to also record **shell command text** (`command` field) for Bash / `run_command` / `shell.run` tools across Claude, Cursor, Codex, and Antigravity — so an investigator can see what actually ran. Inline secrets in the command (bearer tokens, `user:pass@` URLs, `--password`, AWS/OpenAI/GitHub/Slack keys) are **scrubbed to `<redacted>` first**, at both the hook and the server (`core/audit/redaction.py`). Scrubbing is best-effort, not a guarantee — an unusual secret shape may slip through, so treat the local `audit-forward.jsonl` as sensitive and keep it on machines you own. Other args stay hashed.

## MCP proxy (any client)

Wrap MCP server stdio with audit logging:

```powershell
agentmetry mcp-proxy --server vault_fs -- `
  python apps/orchestrator/tools/vault_fs_server.py C:\path\to\vault
```

The proxy ships in the package, so this works on a `pip install` or an MSI
host as well as a checkout. `--server` defaults to a name taken from the
command (`npx -y @scope/server-filesystem` becomes `server-filesystem`).
Existing configs that name `apps/orchestrator/tools/mcp_audit_proxy.py` keep
working; that file is now an alias.

Point Claude / Cursor MCP config at the proxy command instead of the raw server.

- **Correlation:** every call in one proxy process shares a per-process session id (override with `AGENTMETRY_CORRELATION_ID`) — not the JSON-RPC request id, which collides across sessions.
- **Args hashed in-proxy:** only `input_hash` is sent; plaintext arguments never leave the proxy.
- **Errors captured:** an MCP error response is matched to its request and logged as `tool_failed`.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTMETRY_URL` | `http://127.0.0.1:8000` | Ingest base URL |
| `AGENTMETRY_SOURCE_APP` | `cursor` | Default source in hook mapper |
| `AGENTMETRY_LOG_COMMANDS` | *(off)* | `1` = store shell command text in audit (also reads `AGENTMETRY_AUDIT_LOG_COMMANDS` from `apps/orchestrator/.env`) |
| `AGENTMETRY_API_KEY` | *(empty)* | Auth header for ingest |
| `AGENTMETRY_AUDIT_INGEST_ENABLED` | `1` | Kill switch |

## Honest limits (Tier C)

- **Works:** Agents you instrument (hooks, MCP proxy, custom scripts) — captures tool calls (success/failure) and approval requests.
- **Inferred, not native:** the human approve/deny *decision* for external agents is inferred from whether the tool ran (see Approvals above). Tier A (governed Agentmetry runs) captures the real grant/deny.
- **Not captured for Tier B:** model/provider id (hook payloads omit it — shown as the app name, not `gpt-4`/`claude-sonnet`), per-approver identity.
- **Does not work:** Silent browser ChatGPT, auto-approve Cursor with hooks disabled, or any agent that never hits your adapter.
- **Not a CASB:** Network-level shadow-AI detection is a different product.

## Disable external ingest

```env
AGENTMETRY_AUDIT_INGEST_ENABLED=0
```

Tier A Agentmetry runs continue; adapters receive HTTP 503.
