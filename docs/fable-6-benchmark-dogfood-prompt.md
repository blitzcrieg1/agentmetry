# Fable 6 — World-class benchmark + dogfood scorecard

**Use:** Copy the fenced block below into Claude Fable 5 (read-only assessment — **no code** unless you find a critical bug).

**After Fable:** Copy the `---CURSOR-HANDOFF---` block into Cursor for doc sync only.

**Context date:** 2026-07-09 · master @ `a156e2a`

---

```
# BLACKBOX — Fable 6: World-class benchmark, progress review, dogfood scorecard

You are an **independent product architect** reviewing **BLACKBOX** (Obsidian-Cortex Agentic OS). This is an **assessment + advice session**, not a build session.

**Do NOT:**
- Re-audit or re-litigate kernel architecture (scheduler, bus, IVT, MCP host are DONE)
- Re-open product identity debate (settled below)
- Propose new features beyond what the scorecard/decision tree requires
- Write code unless you find a critical security or data-loss bug

**DO:**
- Compare BLACKBOX honestly to world-class projects in adjacent categories
- Score progress since the July product audit
- Produce actionable operator advice for the next 4 weeks
- Be blunt — operator prefers honest gaps over cheerleading

---

## Repo & environment

- **GitHub:** https://github.com/blitzcrieg1/agentic-os (private) · branch `master` · head **`a156e2a`**
- **Recent commits:**
  - `1d1dede` — Approval Inbox UI, vault-only `customer_reply`, flywheel capture, `sop_drift_review`, SOPs
  - `a156e2a` — Universal webhook ingress (`POST /api/v1/ingress`)
  - `49fc7c9` — Compliance kit, SOP injection, doctor CLI, evidence v1.1
- **Verify:** `cd apps/orchestrator && pip install -e ".[dev]" && pytest -q` (report count)
- **Operator:** Solo dev, Greece/EU, Windows 11, local-first, Gemini BYOK

---

## Read first (mandatory — do not read entire repo)

1. `.cursor/rules/blackbox-handoff.mdc` — file map, what's done vs next
2. `docs/tomorrow-handoff.md` — latest session state
3. `docs/product-audit-2026-07.md` — prior scorecard @ `21da830` (baseline to update from)
4. `docs/fable-5-email-autopilot.md` — email subsystem spec
5. `docs/future-concepts.md` — north star, go/no-go
6. **New since audit (read these):**
   - `apps/orchestrator/core/learning/flywheel.py`
   - `apps/orchestrator/api/routes/ingress.py` + `core/ingress/webhook.py`
   - `vault/.system/skill-definitions/customer_reply.yaml`
   - `vault/.system/skill-definitions/sop_drift_review.yaml`
   - `apps/dashboard/components/mission-control.tsx` + `approval-inbox-card.tsx`
7. Skim: `docs/compliance/README.md`, `vault/.system/GOALS.md`

**Do NOT read:** `node_modules/`, `vault/30-Archive/`, `vault/20-Active-Loops/`, entire `vault/` tree

---

## Settled product identity (do not reopen)

- **What it is:** Governed **draft-only inbox autopilot** + private ledger (vault); compounding SOP memory via flywheel
- **Who it's for first:** Solo K-beauty / DTC boutique owner or 1–5 person document-heavy micro-business
- **UX direction:** Hide Obsidian from SMB — Approval Inbox is operator mode; Dev toggle for graph/terminal
- **Integrations:** Gmail read+draft (optional, local) + **webhook ingress** for long tail — NOT a WooCommerce MCP driver
- **Habit competitor:** Gemini-in-Gmail / Google Workspace AI — NOT n8n or Zapier as primary enemy
- **Gate:** 4 green dogfood weeks before send-after-approve, new drivers, or major features

---

## Proven live vs test-only (operator-reported)

| Item | Status |
|------|--------|
| Vault-only `customer_reply` → approve → `30-Archive/drafts/` | ✅ Live |
| Flywheel capture (edit on approve → `edit-log.jsonl`) | ✅ Live (1 row) |
| Approval Inbox (operator mode default) | ✅ Live |
| `sop_drift_review` | pytest only — not operator-run |
| Webhook ingress | pytest only — not operator-run |
| Gmail `create_draft` on approve | ❌ Not wired (vault-only by design) |

---

## YOUR DELIVERABLE

Write **`docs/fable-6-benchmark-review-2026-07.md`** with these sections:

---

### 1. Executive summary (≤12 bullets)

Where BLACKBOX stands **today** vs the July audit. One sentence on whether the last 5 days of shipping moved the needle on **habit** (not just code).

---

### 2. World-class benchmark matrix

Compare BLACKBOX to **6–8 reference projects** chosen from these categories (pick the most relevant, add 1–2 if justified):

| Category | Reference projects (examples) |
|----------|-------------------------------|
| Orchestration / agent runtime | LangGraph + LangSmith, Temporal, Inngest |
| Integration / automation | n8n, Make.com, Zapier |
| Email / inbox AI | Gemini in Gmail, Superhuman AI, Front AI, Intercom Fin |
| Local-first / personal OS | Open WebUI + Ollama stacks, Rewind, Mem |
| Governed enterprise vertical | Harvey (legal), Glean, Dust.tt |
| HITL / approval workflows | Humanloop, Argilla, Label Studio patterns |

For each reference project, one row:

| Dimension | [Project] | BLACKBOX | Gap | Steal or skip? |
|-----------|-----------|----------|-----|----------------|

Dimensions to score (✅ strong / 🟡 partial / ❌ absent):
- Time-to-first-value (Day 1)
- Governed outbound (approve-before-send)
- Compounding memory (learns from edits)
- Install friction (non-dev can run it?)
- Integration surface (ingress vs native drivers)
- Observability / audit trail
- Reliability / recovery
- Pricing / unit economics story

End with: **"BLACKBOX is closest to [X] but differentiated on [Y]"** — one paragraph.

---

### 3. Progress since July audit (delta scorecard)

Re-score these from `docs/product-audit-2026-07.md` with **July baseline → today → delta**:

| Layer | July % | Today % | Δ | Evidence (file paths) |
|-------|--------|---------|---|------------------------|
| A. Own AOS blueprint (kernel) | ~78 | ? | | |
| B. Stated product vision | ~62 | ? | | |
| C. Industry "true agentic OS" | ~28 | ? | | |
| D. Shippable product (paying stranger) | ~45 | ? | | |
| E. Go/no-go checklist (5 criteria) | 2.5/5 | ?/5 | | |

Add **3 new rows** not in July audit:
- **F. Compounding intelligence (flywheel)** — capture, drift review, SOP patch loop
- **G. SMB-facing UX (Business Mode)** — Approval Inbox vs still-dev-heavy
- **H. Integration strategy (ingress vs drivers)** — webhook maturity

Be honest: kernel % should barely move; product/UX/integration rows should move more if at all.

---

### 4. What moved the needle vs what didn't

**Moved needle (code → operator value):**
- List only items that change **daily habit** or **trust** — not test counts

**Shipped but not yet value:**
- Items built since audit that operator hasn't run live

**Still the bottleneck:**
- One paragraph — is it habit, install, Gmail delivery, content/SOPs, or something else?

---

### 5. Dogfood scorecard v1

Produce **`docs/dogfood-scorecard-v1.md`** content (can be a section here or separate file — operator prefers one doc):

**Week 1–4 operator checklist** (actions, not dev tasks):
- Daily / weekly rituals
- What to measure (`blackbox stats`, edit-log row count, drafts/week)

**Green week criteria:**
- Drafts approved/week
- Flywheel captures/week
- Orphans Monday morning = 0
- Hours saved (self-reported)

**Red week / kill signals:**
- When to STOP building and fix ops
- When vault-only is blocking habit → trigger Gmail re-wire

**Decision tree:**
```
IF [condition] THEN [operator action] ELSE [defer]
```
Cover: Gmail draft delivery, sop_drift_review scheduling, ingress hardening, send-after-approve gate

**Week 4 gate review questions** — what Fable/Cursor should re-assess with real stats

---

### 6. Advice (prioritized, max 15 items)

Split into three buckets:

**A. Operator (you) — this week**
- Max 5 items, ordered, ≤2 sentences each
- Ritual over code

**B. Cursor — next build session (after 4-week gate or blocker)**
- Max 5 items with file paths
- Only if dogfood proves need

**C. Do NOT do (explicit anti-roadmap)**
- Max 5 items — things that feel productive but waste the gate

---

### 7. One-page pitch test

Write a **30-second pitch** for a solo K-beauty shop owner. Then score it:
- Would they understand it without "agentic OS" jargon? (Y/N)
- Would they pay €29/mo before seeing Gmail draft delivery? (Y/N + why)
- What's the single demo moment?

---

### 8. Finish line (revised)

One paragraph: recommended **finish line for September 2026** given current trajectory. Not "general agentic OS" — specific, measurable.

---

## Tone & constraints

- Cite file paths and test counts as evidence
- Percentages are directional, not precise — but must show reasoning
- If you disagree with settled identity above, note it in ≤3 sentences under "Dissent" — do not rewrite the strategy
- **Do not commit** to git

---

## When done — OUTPUT EXACTLY THIS BLOCK

---CURSOR-HANDOFF---
## Continue in Cursor

**Fable completed:** [one sentence]

**Do NOT re-do in Cursor:** [what Fable verified]

### Paste this as your first Cursor message:
```
Sync Fable 6 output into repo:
- Save full report as docs/fable-6-benchmark-review-2026-07.md
- Extract dogfood scorecard to docs/dogfood-scorecard-v1.md if Fable merged them
- Update docs/tomorrow-handoff.md with top 3 operator actions from §6A
- Update product-audit delta row in handoff if scores changed materially
Do not commit unless operator asks.
```

### Optional operator steps (human):
- [ ] Run Week 1 dogfood ritual from scorecard §5
- [ ] Paste §7 pitch to a non-technical friend — note confusion points

### Files Fable created (for review):
- docs/fable-6-benchmark-review-2026-07.md
- docs/dogfood-scorecard-v1.md (if separate)

### Test result:
[N passed] (or "not run")

**If blocked:** [file:line + what operator should do]
---END-CURSOR-HANDOFF---

Session ends after the handoff block. No extra features.
```

---

## Why this prompt (for operator)

| Ask | Included? |
|-----|-----------|
| Architecture re-audit | ❌ — kernel done; delta only |
| Concept re-litigation | ❌ — identity locked in prompt |
| World-class comparison | ✅ — §2 benchmark matrix |
| Progress review | ✅ — §3 delta scorecard |
| Practical advice | ✅ — §6 prioritized buckets |
| Dogfood ritual | ✅ — §5 scorecard |
| Build work | ❌ — hand off to Cursor after gate |

---

*Fable 6 prompt · 2026-07-09 · master `a156e2a`*
