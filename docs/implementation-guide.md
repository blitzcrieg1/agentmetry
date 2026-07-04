# BLACKBOX Implementation Guide

**For personal use and small teams**

This guide explains what BLACKBOX is, who it helps, and how to roll it out when the
project reaches its “daily driver” milestone. It is written for operators and
business owners—not only developers.

---

## 1. What BLACKBOX is (in plain language)

BLACKBOX is a **local assistant runtime** that:

- Reads and writes **your notes** (Obsidian vault = your company memory)
- Runs **repeatable workflows** (summarize meetings, triage inbox, draft outreach)
- **Asks before risky steps** (approval gate)
- **Logs everything** (audit trail in the vault and dashboard)
- Works **on your computer**, not as a black-box SaaS chat thread

Think of it as:

| Old way | BLACKBOX way |
|---------|--------------|
| Copy-paste into ChatGPT for every task | Drop a note in a folder → result archived automatically |
| Answers lost in chat history | Results saved as markdown files you can search |
| No limits until the bill surprises you | Daily budget + pause rules for background work |
| “Hope the AI did the right thing” | Approval step for sensitive outputs |

It is **not** a replacement for your CRM, email, or accounting software. It is a
**layer that automates knowledge work** on top of documents you already keep.

---

## 2. Who this is for

### Personal use

- Consultants, founders, researchers, students
- Anyone who lives in notes (meetings, ideas, projects)
- People who want automation **without** sending all company data to random web apps

### Small business (roughly 1–20 people)

- Agencies, studios, professional services
- Teams that run on **documents + email + meetings**, not heavy ERP
- Owners who want to **cut admin time** before hiring another coordinator

### Who it is **not** for (yet)

- Large enterprises needing SSO, SOC2, multi-region fleet management
- Teams that need autonomous browser/email access with no human review
- Organizations that cannot use a cloud LLM API at all (air-gapped) without extra setup

---

## 3. Problems it solves (time and money)

### Time saved

| Task | Manual time | With BLACKBOX (target state) |
|------|-------------|------------------------------|
| Meeting → summary + action items | 15–30 min | ~1 min review of archive |
| Inbox note → classified + next step | 5–10 min | Automatic triage note |
| Weekly review of scattered notes | 1–2 hours | One generated review draft |
| “Find what we decided last month” | 20+ min searching | Search vault + RAG context |

### Cost saved

| Alternative | Typical cost | BLACKBOX |
|-------------|--------------|----------|
| Virtual assistant (part-time) | $500–2,000/mo | Local runtime + API usage |
| Generic AI subscriptions (several seats) | $20–60/user/mo | One API key, shared vault |
| Custom automation consultant | $5k–50k project | YAML skills you own and edit |

**Ongoing cost** is mainly **LLM API usage** (e.g. Google Gemini). On a paid tier,
a small team doing dozens of runs per day is often **tens of dollars per month**, not
hundreds—far below a human hour of admin work.

---

## 4. The mental model (how pieces fit together)

```
You write notes in Obsidian
        ↓
Notes live in folders (Inbox, Projects, Archive)
        ↓
BLACKBOX watches folders + schedules (triggers)
        ↓
Skills run (summarize, triage, outreach draft, etc.)
        ↓
Results saved back to the vault + shown on dashboard
        ↓
You approve or edit only when the gate lights up
```

**Three surfaces:**

1. **Obsidian** — where humans read and write (primary UI when plugin ships)
2. **Vault folders** — the “database” (markdown files, no vendor lock-in)
3. **Dashboard** — mission control (run skills, approve, see history)

---

## 5. Folder layout (your “operating system”)

When fully rolled out, a typical vault looks like:

| Folder | Purpose | Example |
|--------|---------|---------|
| `00-Inbox/` | Drop zone—anything new | Meeting paste, client email summary, idea |
| `10-Projects/` | Active client or internal work | `Client-Alpha/brief.md` |
| `20-Active-Loops/` | *System*—runs in progress | Auto-created; ignore unless troubleshooting |
| `30-Archive/` | *System*—completed agent outputs | `2026-07-03-summarize_meeting-abc123.md` |
| `.system/skill-definitions/` | What agents can do | YAML configs (like recipes) |
| `.system/trigger-rules/` | When agents run automatically | “If inbox `.md` → summarize” |

**Rule for staff:** “If you want the robot to see it, put it in **Inbox** (or tag it).”

---

## 6. Skills you get out of the box (today → near future)

| Skill | What it does | Personal | Small business |
|-------|--------------|----------|----------------|
| **Summarize Note** | Executive summary of any note | Journal, research clips | SOP drafts, briefs |
| **Meeting Summarizer** | Decisions + action items + owners | Personal meetings | Client calls, standups |
| **Inbox Triage** | Category, urgency, suggested action | Email dumps, captures | Support tickets pasted as notes |
| **Lead Gen Outbound** | Draft outreach from vault context | Job search, networking | Sales prospecting (with approval) |
| **Weekly Review** | Priorities from vault activity | Personal planning | Manager weekly sync prep |

**Near future** (on the roadmap): Obsidian plugin (run from active note), more YAML
skills without coding, safe shell/git drivers for small ops tasks.

---

## 7. Personal implementation (step by step)

### Phase A — Setup (day 1)

1. Install **Obsidian** (free) and create or open a vault.
2. Install **BLACKBOX** on one always-on PC (or laptop that stays on during work).
3. Point BLACKBOX at that vault path.
4. Add your **LLM API key** (Gemini or similar).
5. Run `blackbox install` so it starts when you log in.
6. Open dashboard once to confirm **System Status: ok**.

### Phase B — Learn one workflow (week 1)

Start with **one habit only**:

**Meeting notes → summary**

1. After a call, paste notes into `00-Inbox/meeting-YYYY-MM-DD.md`
2. Add frontmatter: `tags: [meeting]`
3. Wait ~30 seconds (or run Meeting Summarizer manually from dashboard)
4. Open the new file in `30-Archive/`
5. Copy action items into your task app if needed

Do not enable five automations at once. One loop, daily, until trusted.

### Phase C — Add autonomy (week 2–3)

- Enable **inbox trigger** so drops in `00-Inbox/` auto-summarize.
- Set **budget reserve** so background runs pause before they eat your manual quota.
- Check **Interrupts · Gate** once a day—clear or resume deferred work.

### Phase D — Personal knowledge base (month 1)

- Move stable reference material into tagged folders (`reference`, `project-x`).
- Skills use **RAG** to pull relevant context—not just the one file you dropped.
- Run **Weekly Review** every Sunday; edit the archive output into your plan.

### What “done” feels like personally

You stop opening a chat tab for “summarize this.” You **drop, archive, skim**.
Your history is **files you own**, searchable in Obsidian forever.

---

## 8. Small business implementation (step by step)

### Before you start: pick one pain point

Do not deploy “AI for everything.” Pick **one expensive admin loop**, for example:

- Client meeting → internal summary + tasks
- Inbound lead notes → triage + draft reply
- Weekly status from scattered docs → one manager brief

Everything else waits until that loop saves measurable hours.

### Roles (even in a 5-person shop)

| Role | Responsibility |
|------|----------------|
| **Owner / ops lead** | Chooses workflows, sets budget limits, approves sensitive skills |
| **Vault keeper** (often same person) | Folder conventions, tags, who may edit `.system/` rules |
| **Staff** | Drop notes in Inbox, review archives, never bypass approval on outbound |
| **Technical contact** (can be outsourced) | Updates BLACKBOX, API keys, backups |

You do **not** need a full-time engineer. You need **one person who can follow a checklist** and a developer on call for upgrades.

### Phase 1 — Pilot (2 weeks, 2–3 users)

1. **One shared vault** on a network drive *or* synced folder (Syncthing, iCloud, etc.).
2. **One machine** runs BLACKBOX (mini PC or always-on office desktop).
3. **Pilot workflows only**—e.g. meeting summarize + inbox triage.
4. **No outbound email automation** until approval flow is trusted.
5. Measure: minutes saved per meeting, errors, how often humans re-edit archives.

**Success metric:** Pilot users prefer archive output to doing it manually ≥ 80% of the time.

### Phase 2 — Team conventions (week 3–4)

Document internally (one page):

- Naming: `YYYY-MM-DD-client-topic.md`
- Tags: `meeting`, `client`, `inbox`, `confidential`
- What must **never** go in the vault (passwords, raw payment cards)
- When to use **manual Run** vs waiting for automation

Turn on **API key auth** on BLACKBOX if dashboard is reachable on the office LAN.

### Phase 3 — Controlled expansion (month 2)

Add skills one at a time:

1. Weekly review for managers
2. Lead gen drafts (**human approval required**—already built for `lead_gen`)
3. Custom YAML skills for your SOPs (no Python needed)

Add **backup schedule**: `blackbox backup` weekly; store zip off-machine.

### Phase 4 — Cost governance

- Set **daily API budget** in config aligned to your Google/Mistral dashboard.
- Use a **cheaper model** for triage, **stronger model** for client-facing drafts.
- Review **telemetry** monthly: cost per skill, failure rate, success rate.

### Compliance basics (small business)

- LLM provider terms: confirm client data policy (Google AI Studio / Vertex / etc.).
- Keep **human approval** on anything customer-facing or legally sensitive.
- Audit trail = `30-Archive/` + run history on dashboard—keep backups.
- GDPR-style deletion: remove notes from vault + reindex; you control the files.

---

## 9. Day-in-the-life examples

### Example A — Solo consultant

| Time | Action |
|------|--------|
| 9:00 | Client call; rough notes in Obsidian inbox |
| 9:05 | BLACKBOX archives summary + action items |
| 9:07 | Consultant edits archive, sends follow-up email manually |
| Friday | Weekly Review skill produces next-week priorities |

**Saved:** ~25 min/day of formatting and “what did we agree?”

### Example B — 8-person agency

| Time | Action |
|------|--------|
| After each client call | Account lead drops notes in shared Inbox |
| Automatic | Meeting Summarizer → Archive tagged by client |
| PM | Skims archives Monday AM instead of reading raw notes |
| Sales | Pastes prospect research in Inbox → triage + draft (approval before send) |

**Saved:** 3–5 hours/week of PM + sales admin across the team.

### Example C — What goes wrong (and how the system handles it)

| Situation | BLACKBOX behavior |
|-----------|-------------------|
| API rate limit | Pauses (degraded mode), retries; you wait or upgrade tier |
| Daily budget low | Background runs **defer** to Gate; manual runs still work |
| Bad summary | You edit archive; fix prompts in skill YAML once |
| Risky tool (future shell) | **Approval interrupt**—nothing runs until you click approve |

---

## 10. Cost and hardware checklist

### Hardware (small business)

| Item | Recommendation |
|------|----------------|
| BLACKBOX host | Mini PC or spare desktop, 16 GB RAM, SSD |
| Uptime | Same network as staff; UPS optional |
| Obsidian | Free on each user machine |
| Backup | External drive or cloud zip of vault + `blackbox backup` |

### Software/API (monthly, indicative)

| Item | Personal | Small team |
|------|----------|------------|
| Obsidian | Free | Free |
| LLM API (Gemini paid tier) | $5–20 | $20–100 (usage-dependent) |
| BLACKBOX software | Free (self-hosted) | Free (self-hosted) |
| Optional: Qdrant/Postgres | Not required | Optional at scale |

Compare to **one hour** of admin salary saved per week—the API line item is usually negligible.

---

## 11. Rollout checklist (printable)

### Personal — “go live”

- [ ] Vault path configured and backed up
- [ ] `blackbox start` / autostart working
- [ ] One skill tested end-to-end (meeting or summarize)
- [ ] Inbox trigger enabled OR manual habit established
- [ ] Know where archives appear (`30-Archive/`)
- [ ] API budget set on provider + BLACKBOX

### Small business — “pilot live”

- [ ] One pain point chosen and documented
- [ ] 2–3 pilot users trained (Inbox + tags only)
- [ ] Shared vault sync tested (no conflict surprises)
- [ ] Approval required on outbound/customer-facing skills
- [ ] Weekly backup tested restore once
- [ ] Internal one-page policy (what goes in vault)
- [ ] Success metrics defined (hours saved, edit rate)

---

## 12. What “done” means vs today

| Capability | Today | Target “daily driver” |
|------------|-------|-------------------------|
| Run skills from dashboard | ✅ | ✅ |
| Auto-run on inbox drop | ✅ | ✅ |
| Meeting → archive | ✅ | ✅ |
| Budget / defer / resume | ✅ | ✅ |
| Run from Obsidian | ✅ | ✅ Plugin v0.1 |
| Crash recovery UX | ✅ | ✅ Clear stale loops |
| Safe write tools (git, shell) | Tier 1 gated | ✅ Sandboxed Tier 1 |
| 10+ business skills | 9 | ✅ YAML library (growing) |
| Non-technical skill editor | YAML (light) | ✅ Templates + docs |

You can **start personal and pilot SMB use today** on summarize/triage/meeting flows.
The guide above describes **full** rollout once Obsidian plugin and sandbox catch up.

---

## 13. How to explain BLACKBOX to non-technical stakeholders

**Elevator pitch:**

> “We keep our work in notes. BLACKBOX is a local robot that reads those notes,
> runs approved checklists on them, and saves the results back—like a junior
> admin who never forgets to file things. It asks before anything risky, and
> we own all the files.”

**What to emphasize:**

- **You own the data** (markdown on your disk)
- **Predictable cost** (API meter + budget gates)
- **Audit trail** (archives + run history)
- **Not magic**—works best on structured habits (Inbox, tags, meetings)

**What not to promise:**

- Fully autonomous company management
- Zero errors without human review
- Replacement of specialized software (CRM, accounting)

---

## 14. Getting help and next steps

| Need | Resource |
|------|----------|
| Technical setup | `README.md`, `scripts/blackbox.bat` |
| Developer handoff | `.cursor/rules/blackbox-handoff.mdc` |
| Add a skill (no code) | `README.md` → “Adding a New Skill” |
| This guide | `docs/implementation-guide.md` |

**Suggested first conversation with a implementer:**

1. Which single workflow costs the most hours per week?
2. Where do notes live today (Obsidian, Word, Notion export)?
3. Who approves customer-facing text?
4. What is the monthly budget for API usage?

Answer those four questions and you have a **90-minute deployment plan**, not a six-month IT project.

---

*Last updated: July 2026 — aligned to BLACKBOX master branch (kernel, drivers, inbox autonomy, paid-tier Gemini support).*
