# AgentAudit — dogfood checklist

**Run this before recording the Loom (#3) and before writing Sigma rules (#5).** The point is to see the audit trail on *real* traffic so the demo and the detections match live field names — not the schema doc's example values.

**Zero Gemini option:** copy `apps/orchestrator/.env.agentaudit-demo` → `.env` for audit-only dogfood (`BLACKBOX_LLM_PROVIDER=mock`). Tool + approval events are real; draft text is placeholder. Use Gemini or Ollama only for the Loom take — see [dependency audit](./agentaudit-dependency-audit.md).

Time budget: ~20 minutes. One pass. Log the result at the bottom.

---

## 0. Preflight

- ☐ `.env` has `BLACKBOX_OPERATOR_ID` set to a real value (not blank — this becomes `actor.id` in every event)
- ☐ `.env` has `BLACKBOX_AUDIT_EXPORT_ENABLED=1` and `BLACKBOX_AUDIT_SINK=file`
- ☐ `scripts\blackbox.bat doctor` — all green (python, vault, portable `drivers.json`)
- ☐ `scripts\blackbox.bat start` then `scripts\blackbox.bat status` — Gemini up, not degraded

```powershell
# Confirm the audit env actually loaded (should print your operator id + sink)
scripts\blackbox.bat status
```

**Note the starting line count** so you can prove it grew:

```powershell
$before = (Get-Content apps\orchestrator\data\audit-forward.jsonl -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
"audit-forward.jsonl before: $before lines"
```

---

## 1. Generate two runs (one approved, one denied)

You want **both approval outcomes** plus a **tool call** in the log. The `customer_reply` skill forces a human approval on every run (`approval_threshold: 1.1`) and calls `vault_fs.read_note` — so two runs of it, approved once and rejected once, cover the events that matter.

Open the dashboard at `http://127.0.0.1:8000` → **The Armory · Desk**.

- ☐ **Run 1 — approve.** Run `customer_reply` (default input is fine, or any note in `00-Inbox/`). When the approval interrupt appears, **approve** it.
  - Expected events: `run/tool_called` (vault_fs), `run/approval_required`, `run/approval_granted`, `run/completed`.
  - **Note the `thread_id`** shown in the run (you'll replay it).
- ☐ **Run 2 — reject.** Run `customer_reply` again. When the approval interrupt appears, **reject** it.
  - Expected events: `run/tool_called`, `run/approval_required`, `run/approval_denied`.
  - Note this `thread_id` too.

> Optional (nice-to-have, not required): to also see a **`run/tool_denied`** event, run any skill whose YAML `tools:` allowlist does *not* include a tool it tries to call — the governed host blocks it and emits a denial. Skip if you don't have one handy; the two approval runs are enough for a green result.

### Track A vs Track B — which skill to dogfood with

- **Track A — `customer_reply` on mock.** Uses `.env.agentaudit-demo`. Proves the trail (tool + approval events) with zero setup. Good for a quick "is the recorder working" check.
- **Track B — `audit_demo` on Ollama (preferred for the Loom).** Uses `.env.agentaudit-ollama`. A purpose-built, no-cloud, no-PII skill: one tool call + approval, nothing else on screen. This is the cleanest thing to record and the honest air-gapped story. Run it once first to confirm the approval interrupt renders (see the audit_demo risk note in the dependency audit).

---

## 2. Verify the trail

### 2a. Line count grew

```powershell
$after = (Get-Content apps\orchestrator\data\audit-forward.jsonl | Measure-Object -Line).Lines
"audit-forward.jsonl after: $after lines (was $before)"
```

- ☐ `$after` > `$before` by several lines

### 2b. Every line is valid JSON

```powershell
$bad = 0
Get-Content apps\orchestrator\data\audit-forward.jsonl | ForEach-Object {
  try { $null = $_ | ConvertFrom-Json } catch { $bad++; Write-Host "BAD LINE: $_" }
}
"invalid JSON lines: $bad"
```

- ☐ `invalid JSON lines: 0`

### 2c. The events you expect are present with real field values

```powershell
# Show action.type / outcome / tool / actor for the last ~12 events
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

- ☐ At least one row with `type=approval_response`, `outcome=success` (your approve)
- ☐ At least one row with `type=approval_response`, `outcome=denied` (your reject)
- ☐ At least one row with `type=tool_called` and a non-empty `tool` (e.g. `vault_fs.read_note`)
- ☐ `actor` shows your `BLACKBOX_OPERATOR_ID` on every row (not blank, not `local`)
- ☐ `corr` (correlation_id) is populated and matches your run `thread_id`s

### 2d. Tool arg hash is present

```powershell
# input_hash should be a 64-char hex on tool_called events
Get-Content apps\orchestrator\data\audit-forward.jsonl |
  ForEach-Object { $_ | ConvertFrom-Json } |
  Where-Object { $_.action.type -eq 'tool_called' } |
  Select-Object -Last 3 @{n='tool';e={$_.tool.qualified}}, @{n='hash';e={$_.tool.input_hash}}
```

- ☐ `hash` is a 64-char hex string, not empty (this is the redacted arg fingerprint)

### 2e. Replay reconstructs the run

```powershell
scripts\blackbox.bat replay <thread_id_from_run_1>
```

- ☐ Timeline is human-readable, ordered, and shows the tool call + approval for that run
- ☐ The `correlation_id` in the replay matches the JSONL rows for the same run

---

## 3. Optional — Loki homelab (L2), only if demoing it

```powershell
docker compose -f docker-compose.loki.yml up -d
# Wait ~30s, then Grafana → http://localhost:3001  (admin / agentaudit)
# Explore query:
#   {job="agent-audit"} | json
```

- ☐ Grafana + Loki + Alloy come up clean on first try
- ☐ Your two runs appear in Explore, JSON-parsed, fields queryable

> **Kill rule:** if the Loki stack doesn't come up clean in one attempt, **cut it from the Loom.** The `replay` CLI + JSONL is a complete demo on its own. Loki is the "yes it plugs into your SIEM" proof, not the hero.

---

## Green / red summary

**GREEN (proceed to Loom + Sigma):** all of —
- ☐ JSONL line count grew, 0 invalid lines
- ☐ ≥1 `approval_response`/`success` **and** ≥1 `approval_response`/`denied`
- ☐ ≥1 `tool_called` with a non-empty `tool.qualified` and a 64-char `input_hash`
- ☐ `actor.id` = your operator id on every event
- ☐ `replay` shows a readable timeline with matching `correlation_id`

**RED (stop and fix before recording anything):**
- ✗ Empty or missing `audit-forward.jsonl` → check `BLACKBOX_AUDIT_EXPORT_ENABLED=1` and `BLACKBOX_AUDIT_SINK=file`, restart
- ✗ Any invalid JSON line → schema/serialization bug in the sink — fix before Sigma rules are written against it
- ✗ `approval_granted`/`approval_denied` absent after you clicked approve/reject → the approval events aren't wiring into the audit exporter; this is the single most important thing to fix, it's the whole product
- ✗ `input_hash` empty on tool calls → arg hashing not firing in `core/drivers/host.py`
- ✗ `actor.id` blank or `local` → `BLACKBOX_OPERATOR_ID` not loaded

---

## Log template

Append one block per dogfood session. This is the record that says "the schema the Loom and Sigma rules target was observed on real traffic on this date."

```
### Dogfood run — YYYY-MM-DD
- Operator id: <value>
- Skills run: customer_reply (approve), customer_reply (reject)
- thread_ids: <t1>, <t2>
- JSONL: <before> → <after> lines, 0 invalid
- approval_response success/denied: Y / Y
- tool_called present + input_hash 64-hex: Y
- actor.id correct on all events: Y
- replay readable + correlation_id matches: Y
- Loki demoed: Y / N (cut if not clean)
- Result: GREEN / RED
- Notes:
```

---

*Companion to the AgentAudit launch sequence: README (#1) → this checklist (#2) → Loom (#3) → LinkedIn (#4) → Sigma pack (#5) → hash-chain spec (#6). Detection field names in #5 must match what this checklist observed live.*
