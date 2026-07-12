# External agent audit (Tier B)

AgentAudit records **governed BLACKBOX runs (Tier A)** and **external agents you wire in (Tier B)** into the same `audit-forward.jsonl` flight recorder.

## Architecture

```
Cursor / Claude / Antigravity / MCP clients
        ↓ hooks or mcp_audit_proxy.py
  scripts/agentaudit_ingest.py
        ↓ POST /api/v1/audit/ingest
  audit-forward.jsonl + SIEM sinks
        ↓
  Dashboard flight recorder (source badges)
```

## Quick start — Cursor (project hooks)

Hooks ship in `.cursor/hooks.json`. They call `scripts/agentaudit_ingest.py` on tool and session events.

**Requirements:**

1. BLACKBOX running: `scripts\blackbox.bat start` → `:8000`
2. `BLACKBOX_AUDIT_EXPORT_ENABLED=1` (default)
3. Optional: `BLACKBOX_API_KEY` in orchestrator `.env` — hooks send `X-API-Key` via env

Restart Cursor after pulling hooks so they load (Hooks tab in settings).

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

## Claude Code / desktop

Merge `adapters/claude/settings.agentaudit.json` into `~/.claude/settings.json` (or project settings). Uses PascalCase events: `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, `Notification`.

```powershell
python scripts/agentaudit_ingest.py claude hook PreToolUse
```

Supplement: tail transcript JSONL at `~/.claude/projects/<encoded-path>/<session-id>.jsonl` for full chain-of-custody if a hook is missed.

## Google Antigravity

Merge `adapters/antigravity/hooks.agentaudit.json` into workspace `.agents/hooks.json` or `~/.gemini/config/`. Uses camelCase stdin (`conversationId`, `toolName`, `toolInput`).

```powershell
python scripts/agentaudit_ingest.py antigravity hook PostToolUse
```

Transcript fallback: `<app_data>/brain/<conversationId>/.system_generated/logs/transcript.jsonl`.

## Cursor (expanded — GLM research validated)

Project hooks in `.cursor/hooks.json` now include **before** and **after** gating events:

- `beforeShellExecution` / `beforeMCPExecution` / `preToolUse` → `approval_request` (allow/deny/ask)
- `afterShellExecution` / `afterMCPExecution` / `postToolUse` → `tool_called`
- `sessionStart` / `sessionEnd` / `stop`

**Windows:** ingest reads `sys.stdin.buffer` (UTF-8 corruption workaround). Invoke via `python.exe` directly — avoid PATH `bash` → WSL.

Research reference: [`docs/glm-52-external-agent-audit-results.md`](./glm-52-external-agent-audit-results.md) (full GLM deliverable).

## Verify hooks actually work (do this before trusting the trail)

Hooks fail **silently** if `python` isn't on the IDE's PATH or the orchestrator is down — you'd believe you're being audited when you're not. Confirm the round-trip:

```powershell
# with the orchestrator running (:8000):
python scripts/agentaudit_ingest.py selftest
#   AgentAudit hooks: GREEN — synthetic event round-tripped for source 'cursor'.
```

RED means the POST failed (orchestrator down / wrong `AGENTAUDIT_URL`) or the event never landed (`BLACKBOX_AUDIT_INGEST_ENABLED=0` / sink off). Set `AGENTAUDIT_SOURCE_APP` first to test a specific adapter. Freshness for the dashboard badge: `GET /api/v1/audit/status` returns `last_event_utc` + per-source counts.

## Approvals & enforcement (honest)

AgentAudit's external hooks are **observe-only by default** — they record, they do **not** change the IDE's approval decision. Installing them never auto-approves a tool call the IDE would otherwise prompt you to review.

- **Enforcement is opt-in.** Set `AGENTAUDIT_ENFORCE=allow|deny|ask` only if you *want* the hook to emit a decision. Unset (default) = the IDE's own approval flow is untouched.
- **Approval *requests* are observed directly** — an `ask` on a `before*`/`PreToolUse` hook becomes an `approval_request` (pending).
- **Approval *responses* are inferred, not natively reported.** No IDE emits "the human clicked approve." AgentAudit infers it: a tool that *runs* after an `ask` (a matching `tool_called`) yields an `approval_response` marked **`reason: inferred:tool_ran_after_ask`**; an `ask` still pending at session end yields an inferred **denied**. These events are explicitly flagged as inferred — treat them as strong evidence, not a native signal.

**What leaves the hook:** tool arguments are SHA-256 hashed **inside the hook process**; only `input_hash` is POSTed to the orchestrator. Plaintext arguments do not cross the wire from the hook. (The raw `/api/v1/audit/ingest` API still accepts `arguments` for manual `send` use and hashes them server-side.)

## MCP proxy (any client)

Wrap MCP server stdio with audit logging:

```powershell
python apps/orchestrator/tools/mcp_audit_proxy.py --server vault_fs -- `
  python apps/orchestrator/tools/vault_fs_server.py C:\path\to\vault
```

Point Cursor/Claude MCP config at the proxy command instead of the raw server.

- **Correlation:** every call in one proxy process shares a per-process session id (override with `AGENTAUDIT_CORRELATION_ID`) — not the JSON-RPC request id, which collides across sessions.
- **Args hashed in-proxy:** only `input_hash` is sent; plaintext arguments never leave the proxy.
- **Errors captured:** an MCP error response is matched to its request and logged as `tool_failed`.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTAUDIT_URL` | `http://127.0.0.1:8000` | Ingest base URL |
| `AGENTAUDIT_SOURCE_APP` | `cursor` | Default source in hook mapper |
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
