# Claude prompt — Comprehensive operator getting-started guide

**Use:** Copy the fenced block into Claude (**Opus 4.7**, read-only doc session).  
**Goal:** One guide the operator can follow tomorrow morning to **actually use** BLACKBOX — not architecture, not assessment.  
**After Claude:** Paste `---CURSOR-HANDOFF---` into Cursor to sync the file and fix stale doc links.

---

```
# BLACKBOX — Write the operator getting-started guide (make it actually work)

You are a **technical writer + operator coach** for BLACKBOX. Write a **comprehensive, step-by-step guide** so a solo Windows user can go from zero (or partial setup) to **first real customer_reply with flywheel capture** in one day.

This is a **documentation session only** — no code, no repo changes, no commits.

## Audience

- Solo dev / micro-business owner (K-beauty / DTC or consulting email)
- **Windows 11**, local-first, Greece/EU
- Has the repo cloned; may already have Gemini key + blackbox running — guide must handle **both fresh install and resume**
- **Not** a developer onboarding doc — minimize kernel/LangGraph jargon; use plain language

## Repo context (2026-07-09)

- **Branch:** `master` @ `bf7b717`
- **Identity:** Draft-only inbox autopilot · vault ledger · forced approval · flywheel (edit → SOP patch)
- **Primary UI for dogfood:** **Approval Inbox** on dashboard (`http://127.0.0.1:8000`) — operator mode default; Obsidian is optional power-user surface
- **Primary skill to prove:** `customer_reply` (vault-only today — drafts land in `30-Archive/drafts/`, not Gmail yet)
- **Build freeze:** ritual over features; guide must not promise send-after-approve or new drivers

## Read first (mandatory — closed list)

1. `docs/tomorrow-handoff.md` — current state, top 3 operator actions
2. `docs/dogfood-scorecard-v1.md` — daily/Friday rituals
3. `docs/personal-step-by-step.md` — reuse what’s still accurate; **flag and replace stale bits** (test counts, old flows)
4. `docs/implementation-guide.md` — plain-language framing only
5. `docs/gmail-driver.md` — optional Gmail path (local enable, never commit drivers.json flip)
6. `docs/blackbox-how-it-works.html` — flow diagram concepts
7. `.cursor/rules/blackbox-handoff.mdc` — file map, commands
8. `vault/.system/skill-definitions/customer_reply.yaml` — what the skill actually does
9. Skim: `apps/orchestrator/.env.example`, `scripts/blackbox.bat` (help text if readable)

**Do NOT:** re-explore kernel, read `vault/30-Archive/`, or write another benchmark/rating doc.

## Deliverable

Write **`docs/blackbox-operator-guide.md`** with these sections (use checkboxes ☐ throughout):

---

### 0. What you’re building (60 seconds)
- One paragraph: vault in → skill drafts → **you approve** → archive + flywheel
- What “success” looks like after Day 1 (one approved draft + optional edit-log row)
- What BLACKBOX is **not** (not auto-send Gmail, not n8n)

### 1. Prerequisites checklist
- Windows, Python 3.11+, Node 18+ (for dashboard build), Git
- Google AI Studio Gemini key
- Optional: Gmail OAuth creds, `BLACKBOX_API_KEY` for ingress
- Disk paths: recommend **absolute** `BLACKBOX_VAULT_PATH` (example: `C:/Users/.../vault`)

### 2. One-time install (fresh machine)
Numbered steps with **exact PowerShell commands**:
- Clone / pull
- `.env` from `.env.example` — every required var explained in one line
- `pip install -e ".[dev]"` + optional `python-docx`, `pypdf`
- `blackbox doctor` — what green looks like; common fixes (`--fix` for path tokens)
- Dashboard build + `blackbox start` → `:8000`
- Optional: Obsidian plugin deploy + vault folder open
- Optional: Gmail driver local enable (explicit: **do not commit** `drivers.json`)
- **Verify:** `blackbox status`, open dashboard, expect operator mode / Approval Inbox

### 3. “Already partially set up?” (resume path)
- 5-minute checklist if orchestrator was running before
- How to tell you’re ready vs need Part 2

### 4. Day 1 — First real win (≤30 min) ⭐ most important section
Step-by-step with **two input paths**:

**Path A — Vault note (simplest, no Gmail):**
- Create/paste customer inquiry in `vault/00-Inbox/` or use sample `sample-shipping-complaint.md`
- Run `customer_reply` from dashboard Armory or API
- Open **Approval Inbox** — read draft
- **Edit** the draft (this triggers flywheel — explain why edits matter)
- Approve → confirm file in `vault/30-Archive/drafts/`
- Verify flywheel: `vault/.system/feedback/edit-log.jsonl` grew by 1 row

**Path B — Gmail (optional, if driver enabled locally):**
- Point to `docs/gmail-driver.md` for OAuth
- How to get thread ID → run skill — note vault-only archive today (Gmail draft delivery is Week 2+ ops fix)

Include **copy-paste commands** where helpful (PowerShell).

### 5. Daily ritual (Mon–Fri, ≤20 min)
Condense from dogfood scorecard — checkbox list, not essay.

### 6. Friday ritual (≤30 min)
- `blackbox stats --days 7`
- Create/maintain `vault/10-SOPs/os-log.md` (provide **template table** for first row)
- First `sop_drift_review` walkthrough (input `20`, approve patch in `10-SOPs/Learnings/`)

### 7. Optional: webhook ingress (one-time smoke test)
- Set `BLACKBOX_API_KEY`
- PowerShell `Invoke-RestMethod` block from tomorrow-handoff
- What success looks like (inbox note + skill run queued)

### 8. SOPs you should edit before Week 2
List the live files and what each controls:
- `customer-tone.md`, `shipping-faq.md`, `returns-policy.md`
- One paragraph on why bad SOPs = bad drafts

### 9. Troubleshooting (decision tree)
Format as **Symptom → Check → Fix**:
- `blackbox status` not ok / Gemini degraded
- Skill stuck / waiting_for_input / orphans → `blackbox recovery`
- Empty or nonsense draft → SOP paths, vault path wrong
- Suite red locally → gmail test vs docx skip vs doctor
- Draft in vault but “I work in Gmail” → red-week trigger (explain, don’t implement)

### 10. What to do after Week 1
- Green week thresholds (one table)
- When Gmail re-wire is allowed
- **Moratorium:** no more assessment sessions until Week 2 Friday
- Link to `docs/dogfood-scorecard-v1.md` for full gate

### Appendix A — Command cheat sheet
All commands on one page.

### Appendix B — Key paths
Table: vault folders, config files, what never to commit.

### Appendix C — Glossary (max 10 terms)
Approval Inbox, flywheel, skill, vault, ingress, HITL, etc. — one line each, no jargon stack.

---

## Writing rules

- **Actionable:** every section ends with “you should now see…” or a checkbox
- **Honest:** call out vault-only draft delivery; don’t oversell Gmail integration
- **Windows-only** commands (PowerShell, `scripts\blackbox.bat`)
- **No filler** — operator has 30 minutes tomorrow at 08:00
- Update stale numbers from old docs (tests ~238+, not 159)
- Use mermaid **only once** if it clarifies the Day 1 flow (optional)
- Length target: **2,500–4,000 words** — comprehensive but scannable (H2/H3, tables, checklists)

## Do NOT include

- Kernel architecture deep dive
- New feature proposals
- Another world-class benchmark
- Telegram, Woo drivers, send-after-approve setup

## When done — OUTPUT EXACTLY THIS BLOCK

---CURSOR-HANDOFF---
## Continue in Cursor

**Claude completed:** [one sentence]

### Paste this as your first Cursor message:
```
Save docs/blackbox-operator-guide.md (review Claude output on disk).
Cross-link from docs/tomorrow-handoff.md and README.md (one line each).
Flag stale sections in docs/personal-step-by-step.md at top ("superseded by operator guide" + link) — do not rewrite the whole file unless operator asks.
Do not commit unless operator asks.
```

### Optional operator steps:
- [ ] Follow §4 Day 1 tomorrow 08:00
- [ ] Create os-log.md from guide template

**If blocked:** [note]
---END-CURSOR-HANDOFF---

Session ends after the handoff block.
```

---

## Why this prompt (for you)

| Need | This prompt |
|------|-------------|
| Assessment / rating | ❌ Fable 7 moratorium |
| Build new features | ❌ build freeze |
| **Actually use it tomorrow** | ✅ §4 Day 1 + troubleshooting |
| PowerPoint / visual | Already have `docs/blackbox-how-it-works.html` — guide links to it |

**Model:** Opus **4.7** (long doc, closed file list). **4.8** only if Day 1 section comes back vague.

---

*Operator guide prompt · 2026-07-09 · master `bf7b717`*
