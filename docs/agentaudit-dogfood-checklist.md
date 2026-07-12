# AgentAudit — validation checklist

**Run this before recording the Loom and before writing Sigma rules.** Confirm the audit trail on real traffic so the demo and detections match live field names — not the schema doc's example values.

**Zero-cloud profile:** copy `apps/orchestrator/.env.agentaudit-demo` → `.env` (`BLACKBOX_LLM_PROVIDER=mock`). Tool + approval events are real; no cloud keys required.

Time budget: ~20 minutes.

---

## 0. Preflight

- ☐ `.env` has `BLACKBOX_OPERATOR_ID` set (becomes `actor.id` in every event)
- ☐ `.env` has `BLACKBOX_AUDIT_EXPORT_ENABLED=1` and `BLACKBOX_AUDIT_SINK=file`
- ☐ `scripts\blackbox.bat doctor` — all green
- ☐ `scripts\blackbox.bat start` then hard-refresh dashboard at `http://127.0.0.1:8000`

```powershell
python scripts/agentaudit_ingest.py selftest   # Tier B round-trip (optional but recommended)
$before = (Get-Content apps\orchestrator\data\audit-forward.jsonl -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
"audit-forward.jsonl before: $before lines"
```

---

## 1. Tier A — `audit_demo` (approve + reject)

The default dashboard skill. One governed tool call + approval gate — no inbox, no Gmail, no LLM draft required on mock profile.

Open dashboard → **Run** → **AgentAudit Demo**.

- ☐ **Run 1 — approve.** Tool gate shows `vault_fs.read_note` + args hash (no empty box, no confidence %). Approve.
  - Expected: `tool_called`, `approval_request`, `approval_response`/`success`, `session_end`
  - Note `thread_id`
- ☐ **Run 2 — reject.** Run again, reject at the gate.
  - Expected: `tool_called`, `approval_request`, `approval_response`/`denied`

Flight recorder (center panel) should list events with `correlation_id` and truncated `input_hash`.

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
  $env:AGENTAUDIT_SOURCE_APP = $src
  python scripts/agentaudit_ingest.py selftest
}
Remove-Item Env:\AGENTAUDIT_SOURCE_APP -ErrorAction SilentlyContinue
```

**Real hooks** (Loom gate — need `*_hook`, not `*_selftest`):

- ☐ **Cursor** — restart Cursor → run a shell command in this repo
- ☐ **Claude Code** — restart Claude / open this repo → run any tool (Read, Bash, MCP)
- ☐ **Codex CLI** — `/hooks` trust AgentAudit → run one Bash command
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

Full adapter guide: [`external-agent-audit.md`](./external-agent-audit.md).

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

- ☐ ≥1 `approval_response` / `success` and ≥1 / `denied`
- ☐ ≥1 `tool_called` with `tool.qualified` and 64-char `input_hash`
- ☐ `actor.id` = your operator id

### 3c. Replay

```powershell
scripts\blackbox.bat replay <thread_id_from_run_1>
```

- ☐ Readable timeline; `correlation_id` matches JSONL

---

## 4. Optional — Loki homelab (L2)

Only if demoing SIEM export. **Kill rule:** if stack doesn't come up in one attempt, cut from Loom — JSONL + replay is enough.

---

## Green / red

**GREEN:** JSONL grew · valid JSON · approve + deny approval events · tool_called + hash · actor.id set · replay OK · (Tier B) cursor event if claiming external ingest

**RED:** missing JSONL · broken approval wiring · empty `input_hash` · blank `actor.id` · hooks claimed but no cursor events after selftest passes

---

## Log template

```
### Validation — YYYY-MM-DD
- Operator id:
- Tier A thread_ids: <approve>, <reject>
- Tier B cursor events: Y / N
- JSONL: <before> → <after>, 0 invalid
- Result: GREEN / RED
```

---

### Validation — 2026-07-12 (GREEN — Tier A)

- Operator id: `home-lab`
- Profile: `.env.agentaudit-demo`
- Skills: `audit_demo` approve + reject
- thread_ids: `e4808307-…`, `a0822c37-…`
- JSONL: 89 → 103 lines, 0 invalid
- Result: **GREEN**

---

*Companion: README → this checklist → Loom → LinkedIn → Sigma pack.*
