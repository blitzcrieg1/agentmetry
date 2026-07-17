# Advanced — governed agent runtime (optional)

Most Agentmetry users only need the **SIEM flight recorder**:

- IDE hooks (Cursor, Claude Code, Codex, Antigravity) or the MCP audit proxy
- Canonical JSONL trail + dashboard + optional SIEM forwarders

This path does **not** require Obsidian, vault skills, or LangGraph.

---

## What the governed runtime adds

The same orchestrator (`apps/orchestrator/`) can also run **vault-defined skills** with human approval gates, semantic memory, and LangGraph checkpoints. That is the original “Blackbox” operator loop:

| Piece | Path |
|-------|------|
| Skill definitions | `vault/.system/skill-definitions/*.yaml` |
| Vault I/O | `core/memory/obsidian_client.py` |
| Execution | `core/execution/service.py` → `run_skill()` |
| Run outbox | `data/events.db` (orchestrator-native runs, not hook JSONL) |
| Obsidian plugin | `apps/obsidian-plugin/` |

Hook-captured events (Tier B) land in **`audit-forward.jsonl`** and **`audit.db`** (query index). Governed skill runs additionally emit to the LangGraph outbox for replay and approval UX inside Obsidian.

---

## When to use which trail

| Use case | System of record | Dashboard |
|----------|------------------|-----------|
| IDE agent dogfood (SIEM) | `audit-forward.jsonl` + hash chain | Flight Recorder tail |
| Governed vault skill | `events.db` + vault markdown | Plugin + `agentmetry replay` |

Do not mix them for compliance narrative: external IDE capture is the product’s primary beta story.

---

## Boot (optional)

```powershell
scripts\agentmetry.bat start
# Obsidian: enable the Agentmetry plugin and open the vault at ./vault
```

See `vault/.system/AGENTS.md` and `.cursor/rules/blackbox-orchestrator.mdc` for skill authoring. **Not required** for hook-only SIEM deployments.
