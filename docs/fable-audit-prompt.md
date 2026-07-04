# Fable audit prompt — status, agentic OS gap, finish line

Copy the fenced block below into Claude Fable (read-only audit preferred; no code unless critical bug found).

---

```
# BLACKBOX — Product audit: where we stand, agentic OS gap, finish line

You are an **independent architect** reviewing **BLACKBOX** (Obsidian-Cortex Agentic OS). This is an **assessment session**, not a build session. Read the repo; run tests; produce a written report the operator can use for the next 3–6 months.

## Repo
- **GitHub:** https://github.com/blitzcrieg1/agentic-os (private) — branch `master`
- **Head:** `21da830` (Phase 2 committed: SMB skills, search driver, plugin v0.1)
- **Prior phases:** `b037156` (plugin v0, recovery, sandbox Tier 1)

## Read first (mandatory)
1. `.cursor/rules/blackbox-handoff.mdc` — kernel map, shipped vs next
2. `docs/future-concepts.md` — north star, go/no-go, driver backlog
3. `docs/implementation-guide.md` — “daily driver” definition
4. `docs/vertical-opportunities.md` + `docs/smb-pain-research.md` — market fit
5. `README.md`, `vault/.system/skill-definitions/`, `vault/.system/drivers.json`
6. `docs/fable-session-notes.md`, `docs/fable-continuation-prompt-v2.md` — recent build history

## Environment (verify, don’t assume)
- Windows 11, local-first, no Docker
- `cd apps/orchestrator && pip install -e ".[dev]" && pytest -q` — expect **129+** passing
- `cd apps/dashboard && npm run build` — should succeed
- Optional: `scripts\blackbox.bat status` if appliance running

## Operator context
- Solo dev, Greece/EU, Windows
- Target wedge: **governed local runtime** for document-heavy micro-business (1–20 staff)
- Reference verticals: agency/consultant (works today), K-beauty e-shop (Gmail+Woo later)
- **Do not commit** unless operator explicitly asks
- Be **honest**, not cheerleading — prior internal estimate: ~78% kernel blueprint, ~62% own product vision, ~28% “industry agentic OS”

---

## Your deliverable

Write **`docs/product-audit-2026-07.md`** (create or overwrite) with these sections:

### 1. Executive summary (≤10 bullets)
Where the project stands in plain language. One recommended “finish line” definition.

### 2. Scorecard (tables + percentages)

Score each **0–100%** with 1–2 sentences evidence (file paths, test counts, live gaps):

**A. Own AOS blueprint** (s1–s5 from handoff)
- Kernel scheduler, event bus/outbox, IVT, MCP drivers, sandbox tiers

**B. Stated product vision** (from future-concepts north star)
- Governed local runtime: vault in → skills → approve → archive out

**C. “True agentic OS” (ambitious bar)**
- Persistent memory, tool ecosystem, autonomous loops, world action (email/web/commerce), multi-agent, recovery, multi-user

**D. Shippable product** (someone else could run it without you)
- Install, Obsidian UX, skill library, integrations, docs, reliability

**E. Go/no-go checklist** (future-concepts §7)
- Mark each criterion: met / partial / not met

### 3. What works today (prove it)
List **concrete flows** that work end-to-end (cite skills, API routes, plugin commands). Note what was **live-tested** vs **test-only**.

### 4. Gap analysis — kernel vs apps vs GTM
| Layer | Done | Missing | Blocks what |
Separate **architecture debt** from **missing integrations** from **empty vault/content**.

### 5. Are we reaching “true agentic OS”?
Answer explicitly:
- **Yes/No/Partially** for three definitions: (1) your blueprint, (2) your north star, (3) market “agentic OS”
- What would falsify “we’re an agentic OS” vs “we’re a governed skill runtime”?

### 6. Finish-the-product roadmap

**Phase A — Daily driver (operator only, 2–4 weeks)**  
No new kernel. Vault content + dogfooding checklist.

**Phase B — Minimum viable product (paying pilot, 6–10 weeks)**  
Ordered engineering list with **acceptance criteria** each:
- Gmail read + draft + approve-send?
- Search driver enabled + supplier_research live?
- Woo read-only?
- Checkpoint resume?
- Batch approve?
- What to **explicitly defer**

**Phase C — Optional “agentic OS” stretch (3–6 months)**  
Only if justified — multi-agent, browser, Tier 2 sandbox, etc.

Each item: **effort (S/M/L)**, **dependency**, **risk**, **file paths to touch**.

### 7. Recommended next 3 commits (if building)
What to build next after this audit — not generic advice; specific modules/skills.

### 8. Risks & honest success odds
| Outcome | 12–24 mo odds | Why |
| e.g. personal daily driver, one SMB pilot, breakout product

### 9. One-page pitch (reuse)
Single sentence + 3 bullets for agency vs K-beauty buyer.

---

## Rules for this audit
- **Read code**, don’t only read docs — spot doc drift (handoff says 123 tests; verify actual count)
- Cite evidence: `path:line` or test names where claims matter
- Distinguish **“kernel done”** from **“product done”** from **“agentic OS done”**
- Do **not** re-architect s1–s4 unless you find a concrete bug — file it separately
- Do **not** build Gmail/Woo in this session unless you find a blocking defect
- If you find stale handoff (e.g. “uncommitted Phase 2”), note it in the report

## Optional live checks
```powershell
pytest -q
npm run build --prefix apps/dashboard
# If running: curl http://127.0.0.1:8000/api/v1/health
# curl http://127.0.0.1:8000/api/v1/skills/
```

Start by reading handoff + running pytest. Deliver **`docs/product-audit-2026-07.md`** as the primary output. Summarize top 5 findings in your final message to the operator.
```

---

*Use after Phase 1 (`b037156`) + Phase 2 (`21da830`). For building, use [fable-continuation-prompt-v2.md](./fable-continuation-prompt-v2.md) instead.*
