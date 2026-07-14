# Agentmetry — validation checklist

**Run this before recording the Loom and before writing Sigma rules.** Confirm the audit trail on real traffic so the demo and detections match live field names — not the schema doc's example values.

**Zero-cloud profile:** copy `apps/orchestrator/.env.agentmetry-demo` → `.env`. The recorder needs no LLM and no cloud keys — events come from your IDE hooks and the MCP proxy.

Time budget: ~20 minutes.

---

## 0. Preflight

- ☐ `.env` has `AGENTMETRY_OPERATOR_ID` set (becomes `actor.id` in every event)
- ☐ `.env` has `AGENTMETRY_AUDIT_EXPORT_ENABLED=1` and `AGENTMETRY_AUDIT_SINK=file`
- ☐ `scripts\agentmetry.bat doctor` — all green
- ☐ `scripts\agentmetry.bat start` then hard-refresh dashboard at `http://127.0.0.1:8000`

```powershell
python scripts/agentmetry_ingest.py selftest   # Tier B round-trip (optional but recommended)
$before = (Get-Content apps\orchestrator\data\audit-forward.jsonl -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
"audit-forward.jsonl before: $before lines"
```

---

## 1. Tier A — MCP proxy (`mcp_audit_proxy.py`)

Wrap any stdio MCP server with the audit proxy — every `tools/call` is recorded with a stable session correlation id and an in-proxy argument hash. Simplest check uses the bundled `vault_fs` server:

```powershell
# Point an MCP client (e.g. Cursor's MCP config) at the proxy instead of the raw server:
python apps/orchestrator/tools/mcp_audit_proxy.py --server vault_fs -- `
  python apps/orchestrator/tools/vault_fs_server.py .\vault
```

Then trigger one MCP tool call from the client and verify:

- ☐ A `tool_called` event lands with `source.app: mcp_proxy` (`adapter: mcp_audit_proxy`)
- ☐ `correlation_id` is the per-proxy session id (**not** a bare JSON-RPC id like `"1"`)
- ☐ `tool.input_hash` is a 64-char hex; no plaintext `arguments` in the event
- ☐ (If the server errors) a matching `tool_failed` event appears

Flight recorder (center panel) should list the events with `correlation_id` and truncated `input_hash`.

---

## 2. Tier B — all IDE adapters (Cursor, Claude, Codex, Antigravity)

Project hooks ship in-repo:

| Platform | Path |
|----------|------|
| Cursor | `.cursor/hooks.json` |
| Claude Code | `.claude/settings.json` |
| Codex CLI | `.codex/hooks.json` |
| Antigravity | `.agents/hooks.json` |

**Selftest** (each source — expect GREEN):

```powershell
foreach ($src in @("cursor","claude","codex","antigravity")) {
  $env:AGENTMETRY_SOURCE_APP = $src
  python scripts/agentmetry_ingest.py selftest
}
Remove-Item Env:\AGENTMETRY_SOURCE_APP -ErrorAction SilentlyContinue
```

**Real hooks** (Loom gate — need `*_hook`, not `*_selftest`):

- ☐ **Cursor** — restart Cursor → run a shell command in this repo
- ☐ **Claude Code** — restart Claude / open this repo → run any tool (Read, Bash, MCP)
- ☐ **Codex CLI** — `/hooks` trust Agentmetry → run one Bash command
- ☐ **Antigravity** — open workspace → run one tool (`run_command`, etc.)

```powershell
function Show-Tail($src) {
  Write-Host "`n=== $src ===" -ForegroundColor Cyan
  Invoke-RestMethod "http://127.0.0.1:8000/api/v1/audit/tail?sources=$src&limit=5" |
    ForEach-Object { $_.events } |
    Select-Object timestamp_utc, @{n='adapter';e={$_.source.adapter}}, @{n='tool';e={$_.tool.qualified}}
}
Show-Tail cursor; Show-Tail claude; Show-Tail codex; Show-Tail antigravity
```

- ☐ Freshness badge shows dots for sources you exercised
- ☐ Kill-test: stop orchestrator → hook silent-fails, IDE unharmed

Full adapter guide: [`external-agentmetry.md`](./external-agentmetry.md).

---

## 3. Verify the trail

### 3a. Line count grew

```powershell
$after = (Get-Content apps\orchestrator\data\audit-forward.jsonl | Measure-Object -Line).Lines
"audit-forward.jsonl after: $after lines (was $before)"
```

- ☐ `$after` > `$before`

### 3b. Valid JSON + expected events

```powershell
Get-Content apps\orchestrator\data\audit-forward.jsonl -Tail 12 |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Select-Object `
    @{n='corr';e={$_.correlation_id}}, `
    @{n='type';e={$_.action.type}}, `
    @{n='outcome';e={$_.action.outcome}}, `
    @{n='tool';e={$_.tool.qualified}}, `
    @{n='actor';e={$_.actor.id}} |
  Format-Table -AutoSize
```

- ☐ ≥1 `approval_request` (from an IDE permission prompt) and, after the tool runs, an `approval_response` flagged `inferred:*`
- ☐ ≥1 `tool_called` with `tool.qualified` and 64-char `input_hash`
- ☐ `actor.id` = your operator id

### 3c. Replay

```powershell
scripts\agentmetry.bat replay <correlation_id_from_3b>
```

- ☐ Readable timeline; `correlation_id` matches JSONL

---

## 4. Optional — Loki homelab (L2)

Only if demoing SIEM export. **Kill rule:** if stack doesn't come up in one attempt, cut from Loom — JSONL + replay is enough.

---

## Green / red

**GREEN:** JSONL grew · valid JSON · approval_request + inferred approval_response present · tool_called + hash · actor.id set · replay OK · (Tier B) cursor event if claiming external ingest

**RED:** missing JSONL · empty `input_hash` · blank `actor.id` · hooks claimed but no cursor events after selftest passes

---

## Log template

```
### Validation — YYYY-MM-DD
- Operator id:
- Tier A (MCP proxy) events: Y / N
- Tier B cursor/claude events: Y / N
- JSONL: <before> → <after>, 0 invalid
- Result: GREEN / RED
```

---

### Validation — 2026-07-12 (GREEN — legacy Tier A, pre-pivot)

*Recorded against the since-removed `audit_demo` skill runner; kept as a historical record. New validations use the MCP-proxy Tier A check above.*

- Operator id: `home-lab`
- Profile: `.env.agentmetry-demo`
- thread_ids: `e4808307-…`, `a0822c37-…`
- JSONL: 89 → 103 lines, 0 invalid
- Result: **GREEN**

---

*Companion: README → this checklist → Loom → LinkedIn → Sigma pack.*
