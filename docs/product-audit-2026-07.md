# BLACKBOX Product Audit — July 2026

**Auditor:** Cursor (local repo review)  
**Repo:** `master` @ `21da830`  
**Tests verified:** 129 passed (`pytest -q`, 2026-07-04)  
**Scope:** Architecture, product completeness, “true agentic OS” gap, finish line

---

## 1. Executive summary

- BLACKBOX is a **real, tested governed agent runtime** — not a prototype README. The kernel (scheduler, IVT, event bus, MCP host, budget, recovery) is implemented and covered by **129 pytest** cases plus CI.
- You have crossed from **“kernel demo”** to **“daily-driver candidate”** for a technical solo operator working in Obsidian on document-heavy tasks.
- You are **not** a “true agentic OS” in the industry sense: world action (email send, commerce, calendar) is almost entirely absent; agents do not replan or resume mid-run; there is no multi-agent fleet.
- The honest identity today: **governed skill runtime with vault-native memory** — an **agentic OS kernel (~78%)** with a **thin application layer (~30%)**.
- **Strongest live flows:** inbox drop → auto-summarize; run any of 9 skills from Obsidian; approval-gated outbound drafts archived to vault; crash recovery for stale loops.
- **Weakest links:** no Gmail/Woo; search driver built but disabled; vault business content (SOPs, brand) mostly empty; no proof of weekly dogfooding or external pilot.
- **Doc drift found:** handoff still says 123 tests and “Phase 2 uncommitted”; `implementation-guide.md` §12 still marks Obsidian plugin and recovery as ❌/Partial.
- **Recommended finish line:** *“Governed back-office for 1–20 person document-heavy business — inbox, meetings, drafts, supplier research, approve-before-send email — local-first, one operator.”* Not “general agentic OS.”
- **Next bottleneck is product/content/integrations**, not kernel rewrites.

---

## 2. Scorecard

### A. Own AOS blueprint (s1–s5 + ledger)

| Subsystem | Score | Evidence |
|-----------|-------|----------|
| s1 Kernel scheduler | **95%** | `core/kernel/scheduler.py` — interactive vs background slots, budget admission; tests in `test_kernel_scheduler.py` |
| s2 Event bus + outbox | **90%** | `core/bus/` — durable outbox, WS bridge; `test_event_bus.py` |
| s3 Interrupt Vector Table | **82%** | `core/kernel/interrupts.py` — HITL, budget_defer, llm_degraded, tool_exec; HITL resume on boot; **no mid-run graph resume** (`recovery.py:31-33`) |
| s4 MCP drivers | **58%** | Host + permissions solid (`core/drivers/`); 2 custom servers (`vault_fs`, `search`); only `vault_fs` enabled; Gmail/Woo/browser absent |
| s5 Sandbox | **48%** | Tier 0 deny + Tier 1 allowlisted subprocess (`core/sandbox/tier1.py`); no Tier 2/WSL2; exec shell driver still off |
| Vault as OS ledger | **76%** | Read/write/archive/RAG/triggers; vault-path `.resolve()` fix; business folder model mostly docs-only |
| Skills / user space | **52%** | 9 skills (6 YAML pipeline); SMB pack shipped; no skill marketplace, no auto-skill-gen |
| Surfaces (Obsidian + dashboard + CLI) | **72%** | Plugin v0.1 (4 commands), dashboard + recovery panel, `blackbox` CLI with recovery |

**Weighted blueprint total: ~78%**

---

### B. Stated product vision (north star)

> Governed local agent runtime for document-heavy small businesses — capture in vault, process with skills, approve before outbound, audit everything.

| Wedge stage | Score | Status |
|-------------|-------|--------|
| 1. Admin time back (meetings, inbox, drafts) | **88%** | 9 skills, triggers, plugin, archives |
| 2. Outbound with approval (email, outreach) | **18%** | Drafts in vault + HITL; **no send driver** |
| 3. Research + campaigns (search → vault → email) | **38%** | Search MCP + `supplier_research` tested; driver off; no email leg |
| 4. Deep integrations (Woo, CRM, calendar) | **5%** | Spec only in `future-concepts.md` |

**North-star product vision: ~62%**

---

### C. “True agentic OS” (ambitious industry bar)

| Capability | Required for “OS” label | BLACKBOX |
|------------|-------------------------|----------|
| Persistent memory | Yes | ✅ Vault + Qdrant RAG |
| Tool ecosystem | Broad | 🟡 2 real drivers, 1 live |
| Long-horizon autonomy | Yes | 🟡 Triggers + skills; no replanning |
| World interaction | Email/web/commerce | ❌ Draft-only |
| Multi-agent coordination | Often assumed | ❌ Single graph per run |
| Failure recovery | Resume work | 🟡 Dismiss orphans; no checkpoint resume |
| Multi-user / fleet | Often | ❌ Single operator |
| Self-extension | Optional | ❌ Manual YAML only |

**Industry “true agentic OS”: ~28%**

---

### D. Shippable product (non-dev operator)

| Criterion | Score | Notes |
|-----------|-------|-------|
| Install / run | **55%** | `blackbox.bat` exists; still requires Python, `.env`, Gemini key, npm for plugin build |
| Primary UX | **70%** | Obsidian plugin + inbox habit; dashboard for power users |
| Skill library | **50%** | 9 skills; good for agency/consultant demo, thin for K-beauty without drivers |
| Integrations | **20%** | vault_fs only in production |
| Reliability proof | **35%** | Tests + CI; no 30-day operator log |
| Non-technical docs | **65%** | `implementation-guide.md` good but partially stale |

**Shippable product (paying stranger): ~45%**

---

### E. Go/no-go checklist (`future-concepts.md` §7)

| Criterion | Status |
|-----------|--------|
| Obsidian plugin v0 | ✅ **Met** (+ v0.1 picker) |
| Crash recovery UX | ✅ **Met** |
| 3+ skills used weekly by operator | ❌ **Not met** — engineering ready, habit not proven |
| Gmail or search driver MVP stable in CI | ✅ **Partial met** — search mocked in CI; ships `enabled: false`; Gmail not built |
| 30-day pilot without kernel fixes | ❌ **Not met** |

**Go/no-go: 2.5 / 5** — cleared to extend vault skills; **Gmail/Woo still correctly gated** on dogfooding + pilot.

---

## 3. What works today (concrete E2E flows)

| Flow | How | Proof |
|------|-----|-------|
| Inbox → auto summarize | Drop `.md` in `00-Inbox/` → `inbox-note-summarize` trigger | `vault/.system/trigger-rules/inbox-note-summarize.yaml`, `test_triggers.py` |
| Meeting → archive | Tag `meeting` → meeting rule | `inbox-meeting-summarize.yaml` |
| Summarize/triage any note | Dashboard Armory or Obsidian commands | `summarize_note.yaml`, plugin `main.ts` |
| SMB drafts with gate | `client_brief`, `follow_up_draft`, `supplier_intake` | Live-tested Phase 2; approval → `30-Archive/` |
| Pending approval UX | Dashboard, plugin modal, `POST /skills/approve` | `api/routes/skills.py`, `pending` includes draft/confidence |
| Budget / degraded defer | Autonomous runs park in IVT, resume after gate | `test_budget.py`, `test_interrupts.py` |
| Crash cleanup | `blackbox recovery`, dashboard Recovery panel | `core/execution/recovery.py`, `test_recovery.py` |
| Tier 1 exec (when configured) | Approve `TOOL_EXEC_APPROVAL` interrupt | `test_sandbox_tier1.py` |
| Supplier web research | Enable search driver + API key → `supplier_research` | `test_search_driver.py` (mocked); not live by default |

**Live-tested (reported in build sessions):** summarize, follow_up_draft approve loop, supplier_intake, meeting summarize.  
**Test-only unless operator enables:** search driver, Tier 1 git, shell driver.

---

## 4. Gap analysis

### Kernel (low urgency)

| Done | Missing | Blocks |
|------|---------|--------|
| Scheduler, bus, IVT, pipeline graph, budget | Checkpoint resume mid-run | “OS survives kill” narrative |
| MCP host, closed-by-default tools | Driver hot-reload ergonomics | Minor |
| Tier 0+1 sandbox | Tier 2 isolation | Safe shell/git in prod |

### Application layer (high urgency)

| Done | Missing | Blocks |
|------|---------|--------|
| vault_fs, search (off) | Gmail read/draft/send | Outbound wedge (#2) |
| 9 skills | `customer_reply` with order context | K-beauty Phase B |
| Plugin v0.1 | Batch approve, WS live board | High-volume email shops |

### Vault content (operator urgency)

| Done | Missing | Blocks |
|------|---------|--------|
| Samples in `00-Inbox/` | `10-SOPs/`, `10-Brand/`, supplier tables | RAG quality for SMB skills |
| `10-Knowledge/` stubs | Real brand voice, EU claims rules | Client-facing draft quality |

### GTM (business urgency)

| Done | Missing | Blocks |
|------|---------|--------|
| Vertical research docs | Pilot customer, 30-day log | Revenue, product validation |
| Honest positioning | Installer / one-click for non-devs | Stranger adoption |

---

## 5. Are we reaching “true agentic OS”?

| Definition | Verdict | Explanation |
|------------|---------|-------------|
| **(1) Your AOS blueprint** | **Partially yes (~78%)** | Kernel subsystems s1–s3 are production-quality; s4–s5 need breadth and Tier 2 |
| **(2) Your north star** | **Partially yes (~62%)** | Vault-in → approve → archive works; outbound and commerce legs missing |
| **(3) Market “agentic OS”** | **No (~28%)** | Cannot read email, act on web, or run business ops without manual paste |

**What you actually built:** A **governed agent runtime (kernel)** with **Obsidian as the system of record** — closer to *“launchd + auditd for LLM skills”* than to *“Windows for agents.”*

**Falsifiers:** If a buyer expects autonomous email/calendar/CRM without paste-and-approve, you are **not** an agentic OS to them. If a buyer expects **repeatable governed procedures on notes they own**, you **are** the product.

---

## 6. Finish-the-product roadmap

### Phase A — Daily driver (2–4 weeks, **no kernel work**)

**Goal:** Prove 3+ skills weekly; fill vault.

| Task | Acceptance |
|------|------------|
| Create `10-SOPs/customer-tone.md`, `10-SOPs/supplier-intake-rules.md` | Referenced in skill system prompts or RAG tags |
| Weekly habit: inbox triage + one approval skill | Log in `vault/.system/run-log.md` or personal journal |
| `blackbox recovery --dismiss-all` once | Clean `20-Active-Loops/` |
| Enable search + one live `supplier_research` run | Archive with web sources cited |

**Effort:** operator time only.

---

### Phase B — MVP for paying pilot (6–10 weeks engineering)

Ordered by leverage for agency + K-beauty:

| # | Item | Effort | Depends on | Acceptance | Defer? |
|---|------|--------|------------|------------|--------|
| 1 | **Gmail read + draft** (no send) | **L** | OAuth app | Skill reads thread ID; draft saved to vault | — |
| 2 | **Gmail send after approve** | **M** | #1 | `customer_reply` archives + sends on approve | — |
| 3 | **Search driver on by default** (when key set) | **S** | SERPER/TAVILY key | Health shows search mounted | — |
| 4 | **`customer_reply` skill** | **M** | #1, vault SOPs | Paste or thread → draft → approve | — |
| 5 | **WooCommerce read-only** | **M** | REST keys | Order context injected into reply draft | After #1 |
| 6 | **Checkpoint resume** | **L** | LangGraph checkpointer | Kill mid-run → restart → resume same thread | Can defer to Phase C |
| 7 | **Batch approve UI** | **M** | — | Approve 5 pending HITL in one action | Can defer |
| 8 | **Plugin v0.2 WS status** | **S** | existing WS | Status bar live during run | Nice-to-have |

**Explicitly defer:** browser RPA, multi-agent planner/executor, Tier 2 sandbox, Woo write, CRM, calendar, multi-tenant sync.

**Files likely touched:** `tools/gmail_server.py`, `vault/.system/drivers.json`, new skill YAMLs, `api/routes/skills.py` (batch approve), `apps/obsidian-plugin/src/main.ts`.

---

### Phase C — “Agentic OS stretch” (3–6 months, optional)

Only if Phase B pilot succeeds:

- Multi-agent graphs (research agent → writer agent → critic)
- Browser MCP (last resort)
- Tier 2 sandbox (WSL2 jail)
- Webhook ingress (Woo → inbox note)
- Syncthing multi-user vault doc + conflict rules

---

## 7. Recommended next 3 commits

1. **`docs: sync stale guides`** — Fix `implementation-guide.md` §12, handoff test count (129), Phase 2 committed status. *Files:* handoff, implementation-guide.

2. **Gmail driver scaffold (read-only)** — `tools/gmail_server.py`, OAuth token via `env_allow`, `gmail.read_thread` + `gmail.create_draft`; driver off by default; mocked tests. *Pattern:* `search_server.py`, `test_search_driver.py`.

3. **`customer_reply` pipeline skill** — vault SOP + optional gmail read; human_approval; archive draft. *Pattern:* `follow_up_draft.yaml`.

---

## 8. Risks & success odds (12–24 months, solo dev)

| Outcome | Odds | Why |
|---------|------|-----|
| **Personal daily driver** | **65–70%** | Stack works; needs habit + vault content |
| **One SMB pilot (agency or K-beauty Phase A)** | **20–30%** | Needs Gmail + 30 days operator time + one willing shop |
| **Breakout product / revenue scale** | **<5%** | Crowded AI market; narrow wedge; solo GTM |
| **Kernel regression / rewrite** | **Low** | 129 tests, stable architecture |

**Top risks:** OAuth/Gmail maintenance burden; operator never dogfoods; building Woo before email; positioning as “agentic OS” vs “governed back-office.”

---

## 9. One-page pitch

**One sentence:**  
*BLACKBOX reads your business notes and email, runs approved checklists, drafts replies and research, and never sends anything without your OK — everything filed in Obsidian you own.*

**Agency buyer (works today):**
- Meeting notes → client brief + follow-up draft in one click from Obsidian
- Approval gate on anything client-facing
- Audit trail in markdown, not lost chat threads

**K-beauty buyer (Phase A today, Phase B with Gmail):**
- Paste supplier quote → structured intake table in vault
- Customer email paste → triage + reply draft against your SOPs
- Phase B: Gmail + Woo context → approve → send

---

## Appendix: doc drift to fix

| Doc | Issue |
|-----|-------|
| `.cursor/rules/blackbox-handoff.mdc:191` | Says 123 tests; actual **129** |
| `.cursor/rules/blackbox-handoff.mdc:142` | Says Phase 2 “uncommitted”; **committed** `206b7d2`–`21da830` |
| `docs/implementation-guide.md:341-344` | Obsidian ❌, recovery Partial, 5 skills — **outdated** |
| `docs/fable-session-notes.md:3` | Says “Not committed” — **outdated** |

---

*Generated 2026-07-04 — local repo audit, pytest 129 passed.*
