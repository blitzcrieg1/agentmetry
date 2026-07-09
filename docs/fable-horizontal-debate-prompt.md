# Claude debate prompt — Horizontal SMB vs narrow ICP

**Use:** Copy the fenced block into Claude (**Opus 4.8** recommended for debate quality; 4.7 if quota-tight).  
**Goal:** Structured argument on strategy — not another benchmark, not code.  
**Output:** `docs/blackbox-strategy-debate-2026-07.md` with both sides, rebuttals, and a **single recommended path** for the next 4 weeks.

**Read first (you):** [blackbox-horizontal-smb-playbook.md](./blackbox-horizontal-smb-playbook.md) · [fable-7-progress-rating-2026-07-09.md](./fable-7-progress-rating-2026-07-09.md)

---

```
# BLACKBOX — Strategy debate: horizontal SMB vs narrow ICP

You are moderating a **structured debate** between two strategic positions for BLACKBOX. Your job is to argue **both sides fairly**, steel-man the opposition, then deliver a **verdict the operator can act on Monday morning**.

This is **not** a build session. No code. No new feature list beyond what the debaters cite. No third benchmark scorecard.

## Operator context (fixed facts)

- **Repo:** `master` @ `bf7b717`+ · governed draft-only inbox autopilot · local-first · build freeze until 4 green dogfood weeks
- **Habit evidence:** 1 edit-log row · no `os-log.md` · 0 ritual days · tier 1.5
- **Product evidence:** 6/7 universal SMB workflows shipped as skills; flywheel capture live; Approval Inbox live; install is dev-grade
- **Docs in tension:**
  - `docs/blackbox-horizontal-smb-playbook.md` — horizontal governance layer, ten vertical starter kits, Mailchimp pattern, Week 3 three screen-shares
  - `docs/fable-7-progress-rating-2026-07-09.md` — habit 12/100, narrow dogfood, moratorium on assessment until Week 2 Friday
  - `docs/blackbox-operator-guide.md` — Day 1 = one real customer_reply on operator's inbox
- **Cursor's opinion (include as Position B ammunition, do not treat as gospel):**
  - Horizontal architecture claim is **true**; Mailchimp-style starter kits fit the vault model
  - Mailchimp analogy **oversells TTFV** until install/demo exists
  - §8 three-conversation test is the **best part** of the horizontal playbook
  - "Ten verticals" is marketing breadth; **three kits + three screen-shares** is enough validation
  - Fable 7 and horizontal playbook **can coexist**: horizontal product, narrow proof week 1
  - Instagram driver / wizard in playbook §7 should **not** ship before Week 3 green signal

## Read first (mandatory — closed list)

1. `docs/blackbox-horizontal-smb-playbook.md` — full doc
2. `docs/fable-7-progress-rating-2026-07-09.md` — full doc
3. `docs/dogfood-scorecard-v1.md`
4. `docs/blackbox-operator-guide.md` — skim §0, §4, §11 only
5. `docs/fable-6-benchmark-review-2026-07.md` — skim §2 competitive matrix only

Do NOT re-read kernel code or explore the repo beyond these files.

---

## Debate motion

**"BLACKBOX should lead GTM as a horizontal SMB governance layer (starter kits per vertical) starting now — not as a narrow vertical product (e.g. K-beauty / DTC only) until habit is proven."**

---

## Format — deliver `docs/blackbox-strategy-debate-2026-07.md`

### Part 1 — Opening statements (600 words max each side)

**Position A — Horizontal now** (steel-man the playbook)
- Mailchimp / QuickBooks / Shopify pattern
- Seven universal workflows, six shipped
- Three defensible wedges vs Vellum/Lindy/MailMaestro (HITL, vault, flywheel)
- Week 2–3 validation plan (starter kits + screen-shares) as cheap falsification

**Position B — Narrow first** (steel-man Fable 7 + Cursor pushback)
- Habit is 12/100; strategy docs don't move the grade
- Install friction makes horizontal pitch fail at first demo
- Gemini-in-Gmail wins convenience; horizontal TAM doesn't matter if one owner won't pay
- Assessment/strategy competing with ritual (Fable 6+7+playbook same day)

### Part 2 — Cross-examination (3 rounds)

For each round, write **Question → Answer → Rebuttal** for both sides.

| Round | Topic |
|-------|--------|
| **R1** | **ICP & pitch:** Can a trades owner and a coach both understand the product in 30 seconds without vertical-specific demo? |
| **R2** | **Proof:** What counts as evidence in Week 1–4 — edit-log rows, os-log, screen-shares, or starter kit count? |
| **R3** | **Build freeze:** What is allowed during the gate (SOP kits, copy rename, Loom) vs forbidden (Instagram driver, wizard, rebrand)? |

### Part 3 — Strongest objections each side must concede

List **3 concessions** Position A must make honestly, and **3 concessions** Position B must make honestly. No "both sides have merit" mush — name the tradeoff.

### Part 4 — Synthesis verdict (operator-facing)

Answer these decisively:

1. **Primary ICP sentence** for the next 90 days (one sentence, no jargon)
2. **Horizontal or narrow for GTM copy?** (pick one as *lead*; other as secondary)
3. **Week 1–4 calendar** — one row per week: operator actions only, max 5 bullets total across 4 weeks
4. **Kill criterion:** what observation in Week 3 **retreats** to single-vertical?
5. **Moratorium:** what docs/sessions are banned until when?
6. **The one thing the operator must NOT do this week** (single sentence)

### Part 5 — Dissent appendix (optional)

If you genuinely cannot pick a winner, write **Option 1 / Option 2** with a **decision trigger** ("If X by Friday, choose Option 1"). Max 200 words.

---

## Debate rules

- Cite playbook § numbers and Fable 7 sections when claiming facts
- Distinguish **architecture** (what the product is) from **GTM** (how you sell it) from **habit** (what the operator does tomorrow)
- Do not invent market stats not in the playbook sources
- Do not propose VPS, Woo driver, or send-after-approve
- Tone: sharp, respectful, operator is solo dev with finite hours — every paragraph should respect that constraint
- Length target: **2,500–3,500 words** total

## Do NOT

- Write code or YAML skills
- Re-score Fable 7 percentages
- Add an 11th vertical
- Recommend "do both fully" without a strict time budget

---

## When done — OUTPUT EXACTLY THIS BLOCK

---CURSOR-HANDOFF---
## Continue in Cursor

**Claude completed:** [one sentence — who won the debate or what the decision trigger is]

### Paste this as your first Cursor message:
```
Review docs/blackbox-strategy-debate-2026-07.md.
If verdict aligns with operator guide Week 1: add one "Strategy" paragraph to docs/tomorrow-handoff.md (5 lines max) — no rewrite of operator guide.
If verdict changes Week 2–3 plan: update docs/blackbox-horizontal-smb-playbook.md §8 or §11 TL;DR only.
Do not commit unless operator asks.
```

### Operator steps:
- [ ] Read Part 4 verdict only (~5 min)
- [ ] Tomorrow: execute Week 1 from operator guide regardless of debate outcome

**If blocked:** [note]
---END-CURSOR-HANDOFF---

Session ends after the handoff block.
```

---

## How to use the debate output

| If verdict says… | You do… |
|------------------|---------|
| **Horizontal lead** | Week 2: three starter kits; keep Day 1 on your inbox |
| **Narrow lead** | Pick one vertical from playbook §4; ignore other nine until green weeks |
| **Split (architecture horizontal, GTM narrow)** | Pitch "inbox autopilot for [coach/agency]"; product stays universal |

**Do not run this debate until tomorrow evening** if you haven't done operator guide §4 yet — the debate assumes Day 1 is done or scheduled.

---

*Debate prompt v1 · 2026-07-09 · companion to horizontal playbook + Fable 7*
