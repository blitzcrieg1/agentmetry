# Claude — AgentAudit air-gapped path + audit_demo skill (privacy-first OSS)

**Use:** Paste the fenced block below into **Claude** (Opus recommended). Attach `README.md`, `docs/agentaudit-dependency-audit.md`, `docs/agent-audit-event-schema.md`.

**Purpose:** Produce **paste-ready deliverables** for Cursor to apply: Ollama/air-gapped docs, `.env.agentaudit-ollama`, README “Two pipes” section, full **`audit_demo` skill YAML spec**, and updated LinkedIn/Loom guidance — **no kernel rewrites, no BLACKBOX_MINIMAL flag**.

**Context:** Operator accepted proposal: AgentAudit = local chain-of-custody for governed tool-use; **inference (Pipe 1) ≠ audit (Pipe 2)**; cybersecurity OSS must lead with **Ollama + local audit**, not Gemini API.

**Already in repo (HEAD `c00171b`+):** AgentAudit README, Weeks 1–4 audit code, `.env.agentaudit-demo` (mock), dependency audit doc, launch assets (dogfood, Loom, LinkedIn, Sigma).

---

## Copy into Claude

```
# AgentAudit — Air-gapped path + audit_demo skill (deliverables for Cursor)

You are the **operator's technical writing partner + YAML skill designer** for **AgentAudit** on repo `agentic-os` (private GitHub, IRT/security audience).

Your job: produce **complete, paste-ready artifacts** — not strategy debate. Cursor will apply files; operator commits when ready.

---

## Locked decisions (do not re-litigate)

| Decision | Value |
|----------|--------|
| Product | **AgentAudit** — local flight recorder for governed tool-use (Tier A) |
| Path B / inbox hero | **Dead** |
| Privacy story | **Audit stays local**; inference is **operator choice** (Ollama = OSS hero, mock = dev/test, Gemini = optional BYOK) |
| Two pipes | **Pipe 1 inference** (prompts may leave box if cloud LLM) vs **Pipe 2 audit** (events.db + JSONL local by default) |
| No `BLACKBOX_MINIMAL` code flag | Use **committed `.env` profiles** only |
| No kernel rewrite | Do not redesign bus, outbox, MCP host, scheduler |
| Tier C honesty | Unmanaged Cursor/ChatGPT = CASB problem, not this product |
| Repo | **Private** — do not instruct making public |

**Key insight to embed everywhere:** Cybersecurity people care about **chain of custody for tool calls and approvals**, not another chatbot. Cloud API use is a **separate privacy decision** from audit export.

---

## Repo truth (trust this)

### Audit layer (Pipe 2 — the product)
- Events from governed host: `run/tool_called`, `run/tool_denied`, `run/approval_*`, `driver/mounted`
- SoR: `apps/orchestrator/data/events.db`
- Forward: `audit-forward.jsonl` + sinks (file/webhook/elastic/splunk)
- CLI: `blackbox replay <thread_id>`
- Tool args: **hashed** in canonical JSON; prompts not on tool events by default
- Docs: `docs/agent-audit-event-schema.md`, `docs/integrations/*`

### Inference layer (Pipe 1 — operator choice)
- LangGraph pipeline skills call `graph_call_llm` unless node is in `tool_only_nodes`
- Providers: `mock` | `ollama` | `gemini` (see `core/config.py`)
- **`tool_only_nodes`**: step runs MCP tools only, **skips LLM** (see `core/graphs/pipeline_graph.py`)
- Existing profile: `apps/orchestrator/.env.agentaudit-demo` (mock, zero cloud)

### Example skills (legacy demos — not product hero)
- `customer_reply`, `doc_summarize`, `margin_compare`, etc. in `vault/.system/skill-definitions/`
- `margin_compare` runs deterministic tool then LLM to format — tool audit fires **before** LLM

### Tests
- 257 passed, 2 skipped — any new skill must not break pytest (operator runs CI)

---

## Your deliverables (produce ALL in one response, clearly labeled)

### D1 — `apps/orchestrator/.env.agentaudit-ollama` (full file contents)

Profile for **air-gapped / security OSS hero path**:
- `BLACKBOX_LLM_PROVIDER=ollama`
- `BLACKBOX_OLLAMA_BASE_URL`, `BLACKBOX_OLLAMA_MODEL` (sensible defaults: llama3.2, local 11434)
- Audit vars: `BLACKBOX_OPERATOR_ID`, `BLACKBOX_AUDIT_EXPORT_ENABLED=1`, `BLACKBOX_AUDIT_SINK=file`
- `BLACKBOX_VAULT_PATH=../../vault`
- `BLACKBOX_STARTUP_VAULT_INDEX=false` (faster boot for demo)
- **No** `GEMINI_API_KEY`
- Comment block: prerequisites (`ollama pull llama3.2`), privacy note (prompts stay local; audit stays local)

### D2 — README patch: "Two pipes" + air-gapped quick start

Provide **markdown blocks** for Cursor to insert into root `README.md`:

**D2a — New section "Two pipes: inference vs audit"** (~200 words)
- Table: what goes to cloud API vs what stays in events.db/JSONL
- Explicit: Gemini sends **prompts** to Google; **audit export does not**
- Point to Ollama profile for air-gapped

**D2b — Reordered quick starts** (replace or supplement current quick start)
1. **Primary:** Air-gapped (Ollama + audit) — copy `.env.agentaudit-ollama`, start ollama, `blackbox start`, run skill, replay
2. **Secondary:** Dev/test (mock) — `.env.agentaudit-demo`
3. **Tertiary:** Optional Gemini BYOK — one paragraph, not hero

**D2c — One-line privacy callout** near top of README (under tagline)

Do **not** rewrite entire README — only sections to add/replace with clear `<!-- INSERT AFTER ... -->` anchors.

### D3 — `audit_demo` skill (full YAML + design note)

Design a **new skill** `audit_demo` for `vault/.system/skill-definitions/audit_demo.yaml`:

**Requirements:**
- **Zero LLM dependency** for the demo path — use `tool_only_nodes` for all tool steps
- Flow: read a vault note → **human_approval** → finalize/archive
- Tools: `vault_fs.read_note` only (closed allowlist)
- `approval_threshold: 1.1` (force approval every run) OR include `human_approval` in nodes — match existing `customer_reply` pattern
- Sensible `default_input`: e.g. `00-Inbox/audit-demo-note.md`
- Short `description` for dashboard: "AgentAudit demo — tool + approval, no cloud LLM"

Also provide:
- **Content for `vault/00-Inbox/audit-demo-note.md`** (sample note, no PII — 5 lines)
- **Expected audit events** list for operator verification after one approve + one reject run
- **Risk note:** if pipeline compiler requires LLM before approval, say what minimal YAML/compiler assumption is needed — do NOT invent Python changes unless unavoidable; prefer matching existing working skills (`customer_reply` structure)

### D4 — Update `docs/agentaudit-dependency-audit.md`

Add subsection **"Privacy for cybersecurity / IR audience"** (~250 words):
- Pipe 1 vs Pipe 2
- When Ollama vs mock vs Gemini
- What appears in forwarded SIEM (hashed args)
- Link to new profiles and `audit_demo`

Provide full markdown to append (not diff).

### D5 — Update launch copy (light touch)

Revise **only** these if needed for Ollama-first narrative (provide full replacement files or marked sections):

- `docs/agentaudit-dogfood-checklist.md` — add **Track A:** mock; **Track B:** audit_demo + Ollama (preferred for Loom)
- `docs/agentaudit-loom-script.md` — Beat 2/3: mention "local Ollama" instead of implying Gemini; keep Tier C honesty
- `docs/agentaudit-linkedin-post.md` — one sentence: "Run inference locally (Ollama) or BYOK; audit trail stays on your machine"

Do not rewrite from scratch if a short addendum suffices.

### D6 — Cursor handoff block

End with a **single copy-paste block for Cursor** listing:
- Files to create/modify (paths)
- Acceptance criteria (pytest still passes, dogfood steps, no new env flag)
- Suggested commit message (one line)
- **compound preserved?** note (additive skill YAML + docs only)

---

## Constraints

- **Minimize scope** — solo dev 15 h/week; no new Python unless D3 proves impossible without it
- **Do not** recommend ripping out Gmail/Obsidian code — demote in prose only
- **Do not** claim AgentAudit hides prompts from cloud if user chooses Gemini
- **Do not** implement OTel, Chronicle, or export --audit code
- Use **IRT peer tone** in user-facing copy
- Windows paths OK in examples (`scripts\blackbox.bat`) but env profiles use portable `../../vault`

---

## Output format

Use headers:

```
## D1 — .env.agentaudit-ollama
## D2 — README patches
## D3 — audit_demo skill
## D4 — dependency audit addendum
## D5 — launch copy updates
## D6 — Cursor handoff
```

Each deliverable must be **complete and paste-ready** — no "TBD" or "operator fills in."

Begin now.
```

---

## Operator quick-start (paste with the block)

```
Implement deliverables D1–D6 from claude-agentaudit-airgap-prompt.md.
Repo private, HEAD c00171b+. Privacy-first: Ollama + audit_demo hero, mock for dev only.
Apply in Cursor after Claude responds — commit when I say so.
```

---

## After Claude responds

1. Paste Claude output into **Cursor** with: *"Apply D1–D6 exactly as written."*
2. Run `pytest -q` in `apps/orchestrator`
3. Dogfood: `audit_demo` with Ollama profile — approve + reject — verify JSONL
4. Commit when ready (operator asks)

---

*Pairs with [agentaudit-dependency-audit.md](./agentaudit-dependency-audit.md) · [claude-agentaudit-do-everything-prompt.md](./claude-agentaudit-do-everything-prompt.md)*
