# GLM 5.2 — Round 5 Prompt: Post-Implementation Handoff · What's Next?

**Prerequisite:** You have Pass 1 (architecture), Round 2 (viability), Round 3 (local-first 6-month plan), and Round 4 (Daily Stack + compliance Trust-Kit). Paste Round 4 **Executive Verdict** + **§12 Kill triggers** if context is tight.

**How to use:** Paste this entire document into GLM 5.2 with **web search enabled**. Add:

> This is a **post-implementation review**, not a greenfield architecture pass. A solo dev just shipped the Round 4 engineering bundle in Cursor. Your job is **deep research** on what to do next — operator rituals vs code — given what actually landed. Be ruthless about habit over features.

---

## Your role

You are a **regulated-AI product architect + solo-founder operator coach + EU market analyst**.

The operator built **BLACKBOX** — governed local-first agent runtime (Obsidian vault + LangGraph + MCP + HITL + audit outbox + evidence export). Round 4 framed **"The Cycle"** (Morning Brief → Doc Ingestion → Response Wave → Day-Close) and a **compliance Trust-Kit** (docs only, not a compliance kernel).

**Between Round 4 and now, the following was implemented in code** (verify assumptions against this list — do not recommend rebuilding what is done):

---

## Part A — Implementation handoff (what shipped)

### A1. Compliance Trust-Kit (non-code)

| Deliverable | Path | Notes |
|-------------|------|-------|
| AI Act deployer checklist | `docs/compliance/ai-act-deployer-checklist.md` | Art. 12/14/52/10/9 mapped to existing kernel |
| ISO 42001 alignment map | `docs/compliance/iso-42001-mapping.md` | Maps to `blackbox export --evidence` |
| Incident response template | `docs/compliance/incident-response-template.md` | Hallucination / wrong-draft record |
| Data residency statement | `docs/compliance/data-residency-statement.md` | Local-first / Ollama narrative |
| Index | `docs/compliance/README.md` | "Deployer-ready alignment, not legal advice" |

### A2. Daily Stack in vault

- `vault/.system/GOALS.md` updated with success sentence, Mon–Fri loop table, weekly metrics
- Trigger: `inbox-document-summarize.yaml` — PDF/DOCX drop in `00-Inbox/` → `doc_summarize`
- Vault watcher extended for `.pdf` / `.docx` trigger paths (RAG still markdown-only)

### A3. Evidence export v1.1

Schema bumped to **1.1** in `evidence_pack.py`:

| Field | Location |
|-------|----------|
| `approval_signature` | `approvals[]` — SHA-256(thread \| decided_at \| session) |
| `sop_version_hash` | `runs[]` — hash of skill YAML |
| `confidence_score` | `approvals[]` |
| `provider_metadata` | `meta` — LLM provider + model |
| `tool_allowlist_snapshot` | `meta` — SHA-256 of `drivers.json` |

### A4. SOP injection for email

- `_fetch_skill_context()` honors skill YAML `sop_paths` (injected before FTS/RAG)
- `customer_reply.yaml`: `sop_paths` for `10-SOPs/client-reply.md` + `10-Knowledge/SOPs/*.md`
- Client-known path loads **both** client note and reply SOP (not client note as sole SOP)
- Stub: `vault/10-Knowledge/SOPs/customer-reply.md`

### A5. Stale-loop hygiene

- Terminal active-loop notes **>7 days** auto-archive to `30-Archive/active-loops/` on boot
- Config: `BLACKBOX_ACTIVE_LOOP_ARCHIVE_DAYS`, `BLACKBOX_ACTIVE_LOOP_AUTO_ARCHIVE`

### A6. Phase 4-E shadow (disabled)

- `gmail.send_draft` tool exists in `gmail_server.py` — **raises unless** `BLACKBOX_GMAIL_SEND_ENABLED=1`
- Orchestrator injects flag via `settings.gmail_send_enabled` (default **false**)
- MCP host logs `arguments_sha256` + `draft_id` on `gmail.send_draft` TOOL_CALLED events
- **`customer_reply` still uses `create_draft` only** — send not wired into graph

### A7. Portability + doctor

- `vault/.system/drivers.json` committed with portable tokens: `{PYTHON}`, `{ORCHESTRATOR_ROOT}`, `{VAULT_PATH}`
- Resolved at mount via `load_resolved_driver_specs()`
- CLI: **`blackbox doctor`** / **`blackbox doctor --fix`**

### A8. Dashboard UX

- Pending approvals panel: keyboard **`a`** approve checked, **`Shift+a`** approve all, **`r`** reject

### A9. Test status

~**220 passed**, 1 skipped; optional `python-docx` dep may fail one docs test locally.

---

## Part B — What was explicitly NOT built (defer list)

| Item | Round 4 mention | Status |
|------|-----------------|--------|
| `compliance_digest` skill | Q3 | Not built |
| `client_dossier_update` skill | Phase 1 | Not built |
| `contract_triage` skill | Phase 1 | Not built |
| `customer_reply` → `send_draft` graph step | Phase 4-E | Shadow tool only |
| `Relations_Map.csv` | Vault schema | Skipped |
| Telegram channel | — | Disabled by policy |
| Hosted SaaS / Stripe | — | Deferred |
| Batch approve beyond keyboard shortcuts | — | Partial (API existed) |

---

## Part C — Operator state (July 2026)

| Item | Status |
|------|--------|
| Gmail OAuth | Done locally |
| `gmail` driver `enabled: true` | **Local only — not committed** |
| First `gmail_inbox_brief` | Ran once |
| First **`customer_reply` on real thread** | **NOT YET** |
| Morning brief cron | Not confirmed enabled |
| Stale loops in `20-Active-Loops/` | Should shrink after restart (auto-archive) |
| Success gate | **4 consecutive green dogfood weeks** before send-after-approve |

**Mode A success sentence (unchanged):** Four consecutive green weeks, ≥3 hrs/week saved, product success optional.

---

## Part D — Architectural truth (still do not ignore)

| Capability | Status |
|------------|--------|
| Kernel (scheduler, bus, IVT, MCP host, budget, recovery) | **DONE — no rewrite** |
| LLM providers | `gemini` \| `ollama` \| `mock` — pluggable |
| Enabled drivers in repo | vault_fs, margin, docs |
| Real competitor for habit | **Gemini-in-Gmail**, not n8n |
| Moat hypothesis | Sovereignty + governance-by-construction + vault SOPs + evidence export |
| Compliance positioning | "Deployer-ready alignment" — **never** "EU AI Act compliant product" |

---

## Part E — Your research mission (deep dive)

Search the web (2025–2026 sources). This pass is **"what next after the build sprint"** — not another architecture review.

### E1. Validate the implementation sprint

1. Did the team build the **right** things given Round 4 priorities? Score each shipped item **1–10** for impact on **daily habit formation** (not feature count).
2. What shipped items are **premature** (engineering ahead of first real `customer_reply`)?
3. What critical gaps remain that **block the first green dogfood week**?

### E2. The next 4 weeks — operator vs code split

Produce a **week-by-week table** (Week 1–4) with:

| Column | Content |
|--------|---------|
| Operator ritual | Concrete actions (skills, times, metrics logged) |
| Code (if any) | Max **one** small item per week or "none" |
| Success metric | Measurable pass/fail for that week |
| Kill signal | What would make you stop |

**Hard constraint:** No new skills, drivers, or kernel changes unless a week fails its metric twice.

### E3. Research: post-Gmail loops that compound (2026–2027)

Given **`doc_summarize` trigger + SOP injection + compliance docs** now exist:

1. Re-rank Round 4's expansion loops for **Q3 2026** (not 2030 horizon — nearer term).
2. Which **single** non-email loop should prove value **after** email dogfood starts — meeting→draft, doc→client dossier, or weekly governance digest?
3. Search: what are EU boutique firms (1–20 people) actually **buying** in 2026 for "governed AI" — evidence packs, local LLM, or workflow automation?

### E4. Compliance Trust-Kit — market signal or distraction?

1. Is `docs/compliance/` sufficient as a **sales artifact** for privacy-first boutiques, or does it need one **demo export walkthrough** (video/script)?
2. Does ISO 42001 **alignment mapping** help close deals at this stage, or should compliance stay internal until 10+ paying users?
3. Any **2026 regulatory changes** (EU AI Act enforcement dates, UK equivalent) that change the "Sovereign Office" pitch?

### E5. Competitive re-check (90 days post-Round 2)

Search current state of:

- Gemini in Gmail / Google Workspace AI for **solo operators**
- Local-first agent stacks (Ollama + n8n, Open WebUI, etc.)
- "Governed agent" / HITL products targeting EU SMB

**Deliverable:** Updated competitor table + one paragraph on whether BLACKBOX's moat ** strengthened or weakened** after this implementation sprint.

### E6. Revised kill / pivot triggers

Update Round 4 §12 with **specific dates** (today ≈ July 7, 2026):

| Trigger | Original | Revise? |
|---------|----------|---------|
| No measurable time saved | Month 3 | |
| Zero non-founder installs | Month 6 | |
| Wrong-send incident | Any | Now that send_draft shadow exists |

Should **`customer_reply` never running by Week 2** be an explicit kill sub-trigger?

---

## Part F — Required output format

### 1. Executive verdict (≤150 words)

Ship sprint: right/wrong/mixed? **Single next focus** for the operator this week.

### 2. Implementation scorecard

| Shipped item | Habit impact (1–10) | Premature? (Y/N) | Keep / revert / iterate |

### 3. Four-week operator plan (table)

Week 1–4 with rituals, optional code, metrics, kill signals.

### 4. One expansion loop recommendation (post-email)

Name, why now, max effort (days), dependency on green weeks.

### 5. Compliance: sell now or defer?

Three bullets with evidence from web search.

### 6. Competitor delta (since Round 2)

Table + moat paragraph.

### 7. Top 5 actions — **Monday morning only**

Number them. Split **Operator (3 max)** vs **Code (2 max)**. No more than 2 code items.

### 8. Research prompts for Round 6 (if needed)

If you cannot conclude without primary user interviews or pricing tests, list **exactly 3 questions** to ask the operator — not generic advice.

---

## Part G — Anti-patterns (do not)

- Do not recommend rebuilding scheduler, bus, IVT, MCP host, or evidence export kernel
- Do not recommend 3 new YAML skills in the next 4 weeks
- Do not recommend enabling `send_draft` before 4 green weeks
- Do not recommend Telegram, Stripe, CRM, multi-agent, or hosted SaaS
- Do not say "EU AI Act compliant" — use deployer-ready alignment language
- Do not ignore that **first real customer_reply** is still the critical path

---

## Part H — Context snippets (paste if room)

```
Repo: github.com/blitzcrieg1/agentic-os · branch master
Run: scripts\blackbox.bat start → :8000
Tests: ~220 passed
Skills: 14 YAML in vault/.system/skill-definitions/
Daily Stack: 08:00 gmail_inbox_brief · day doc_summarize · 14:00 customer_reply · 17:00 meeting/day-close
Compliance: docs/compliance/ + blackbox export --evidence v1.1
Send: draft-only; send_draft shadow disabled until BLACKBOX_GMAIL_SEND_ENABLED=1
Doctor: blackbox doctor --fix for portable drivers.json
```

---

*End of Round 5 prompt — post-implementation handoff · what's next · July 2026*
