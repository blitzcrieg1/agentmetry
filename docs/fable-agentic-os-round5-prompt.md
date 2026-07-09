# BLACKBOX × Claude — Round 5: Path B execution pack + final stress-test

**Use:** Paste the fenced block below into Claude (Opus + Web Search optional for pricing/competitor checks). **After Claude delivers,** paste the Cursor handoff into Cursor for Part S review (repo alignment + file placement).

**Context:** Rounds 1–4 complete. `docs/blackbox-agentic-os-profit-research-2026-07.md` has Parts A–Q. **Decision locked: Path B** (comms hero + doc/meeting demo lanes). Cursor amended Bucket B swap rule (≥2/3 threshold, Stripe+wizard fixed #2–#3, doc= compliance-export not OCR, meeting= paste-transcript first). **Moratorium:** no new strategy rounds until Week 4 verdict or €500 MRR unless operator explicitly requests Round 6.

**This round is execution, not more paths.**

---

## Copy into Claude

```
# BLACKBOX — Round 5: Path B execution pack (Bucket A deliverables + stress-test)

You are **execution lead + final devil's advocate** in a multi-round debate with **Cursor** (repo builder). Strategy debate is **substantially complete** — Path **B** chosen (Part Q). Cursor's Part P amended Bucket B mechanics. Your job: **ship operator-ready Bucket A assets** Claude can paste/use this week, plus one short stress-test of whether Path B survives contact with real copy.

**Do not reopen Path 1/2/3 ranking or invent Path F.** Debate only if an execution choice contradicts Parts P–Q — then flag it in Part R §1, don't rewrite the strategy doc.

## Operator intent

1. **Turn Part Q into shippable artifacts** — starter kit outlines, landing copy, Loom script, cold-DMs, signal log template, EU one-pager (marketing-safe, not legal advice).
2. **Stay grounded** — reference real skills (`customer_reply`, `doc_summarize`, `summarize_meeting`), real vault paths (`vault/10-SOPs/`, `00-Inbox/`), build freeze (Bucket A = writing only).
3. **Breadth without blur** — comms hero; doc tab 2; meeting in demo only; **never market Surface 4 (research)**.
4. **Greece/EU operator** — pricing in €; EU AI Act/GDPR as copy wedge where honest; English-first landing OK (Path B, not D-only).
5. **Solo dev 15 hrs/week** — deliverables must be completable in **≤8 hours operator time** total across Week 2.

## Mandatory reads (trust repo facts — do not re-audit kernel)

1. `docs/blackbox-agentic-os-profit-research-2026-07.md` — **Parts P, Q, L.2, O (Option B), M.5**
2. `docs/blackbox-horizontal-smb-playbook.md` — §4.1 trades, §4.2 coach, §4.8 DTC + §3 seven workflows
3. `docs/blackbox-operator-guide.md` — §4 Day 1 ritual
4. `docs/dogfood-scorecard-v1.md` — green week criteria
5. `.cursor/rules/blackbox-handoff.mdc`

## Repo facts (unchanged)

- Path B; Week 1: operator guide §4 + os-log row 1 + one non-email skill
- Bucket B post-gate: #1 swaps on Week 4 verdict; #2 Stripe; #3 doctor --wizard always
- Gmail Drafts default if tie; compliance-export if doc wins; paste-transcript meeting path if meeting wins
- 15 skills; doc_summarize + docs driver shipped; habit 12/100; ~238 tests

## Optional web research (max 3 searches — only if needed for pricing anchors)

1. Superhuman / Missive / MailMaestro solo pricing (€29 anchor validation)
2. EU AI Act Aug 2026 SME messaging — verify one date for one-pager footnote
3. One competitor for doc intake (Gavel, Harvey solo, or EU accounting tool) — price anchor for tab 2 only

## Deliverable — create NEW file + append summary to research doc

### Primary output: `docs/blackbox-path-b-execution-pack-2026-07.md`

Write this as a **standalone operator playbook** (~2,500–3,500 words). Structure:

#### §1 — Loom script (2:30 total)
- 0:00–1:30 comms flow (quote follow-up or customer inquiry → approve)
- 1:30–2:30 doc drop (PDF → summary → draft → approve)
- Speaker notes + on-screen actions (Obsidian vs dashboard vs vault paths)
- **Honesty callouts** where Gmail Drafts not wired yet — what to say on screen-share

#### §2 — Landing page copy (one page, ready to paste)
- Hero (comms — no "Agentic OS" in hero)
- Tab 2 / section: document intake (one paragraph + 3 bullets)
- Subhead: governance + local-first + EU-friendly (one line, not legal advice)
- Pricing block: €29 / €49 / trial terms (14-day, BYOK, match Part Q)
- FAQ: 5 questions (install, data ownership, Gmail, EU AI Act, who is this for)
- Footer: privacy/DPA pointer (draft one-liner)

#### §3 — Three starter kits (outlines + seed content)

For each vertical (**trades, coach, DTC**), deliver:

| Item | Content |
|------|---------|
| Folder path | `vault-templates/<vertical>/` suggested tree |
| 5–6 SOP filenames | with 3–5 bullet policy stubs each (operator fills later) |
| 1 example `00-Inbox/` note | realistic paste-in inquiry (trades quote, coach discovery, DTC WISMO) |
| Default skills | which 2–3 skills to run first |
| Cold-DM variant | 2 sentences + subject line |

Do **not** write all ten verticals — only the three Week 2 kits.

#### §4 — Signal log template
- Markdown table or CSV header: `{date, surface, vertical, skill_used, blocked_by, verdict, pay_if_ships}`
- 3 example rows (one per Week 3 lane)
- Week 4 tally instructions (≥2/3 rule from Part P)

#### §5 — EU AI Act one-pager (marketing)
- 1 page max: what BLACKBOX does, HITL, local vault, audit trail, SME carve-out mention
- **Disclaimer:** not legal advice; consult qualified counsel
- Greek operator may use EN; optional 3-line EL summary at bottom

#### §6 — Week 2 day-by-day (Mon–Fri)
- 5 days × ≤3 bullets; respect 15 hrs/week; Day 1 = ritual first
- Map each day to §1–§5 deliverables

### Secondary output: append to `docs/blackbox-agentic-os-profit-research-2026-07.md`

#### Part R — Final stress-test (~600 words)

1. **Path B under real copy** — does the landing page accidentally promise Gmail Drafts, OCR, or audio? List every over-promise and fix wording.
2. **Cursor Part P amendments** — agree or challenge: Stripe+#3 fixed, ≥2/3 threshold, doc=compliance-export not OCR, meeting=paste-transcript.
3. **Compound bet check** — do any §1–§6 deliverables tempt kernel changes this week? Flag red lines.
4. **Kill criteria for Path B** — if Week 4 tally fails, what's the fallback (A? C? extend dogfood?) — one paragraph, forced choice.
5. **Debate closed?** Yes/no + what single metric reopens strategy (from Part Q).

#### Part S placeholder — "Cursor review pending"
One line only: Cursor validates file paths, skill names, and honesty flags in execution pack.

## Rules

- Create `docs/blackbox-path-b-execution-pack-2026-07.md` as primary artifact
- Append Parts R + S stub to research doc; do not overwrite A–Q
- No git commit
- No kernel/code suggestions except pre-authorized Gmail Drafts mention
- Force tradeoffs; no fluff
- Total new content: ~3,000–4,000 words across both files

## When done — OUTPUT EXACTLY

---CURSOR-HANDOFF---
## Continue in Cursor

**Claude completed:** [one sentence — execution pack path + debate closed Y/N]

### Paste this as your first Cursor message:
```
Read docs/blackbox-path-b-execution-pack-2026-07.md and Part R of docs/blackbox-agentic-os-profit-research-2026-07.md.

Replace Part S stub with Cursor review (~400 words):
- Repo alignment: skill names, vault paths, drivers.json — flag mismatches
- Honesty flags: anything that over-promises vs bf7b717 reality
- File placement: suggest where vault-templates/ should live if not in repo yet
- Week 2 priority order if operator only has 5 hours not 8

Do not commit unless operator asks. Update tomorrow-handoff.md ONLY if Day 1 ritual text changes.
```

**Files created/updated:**
- docs/blackbox-path-b-execution-pack-2026-07.md (new)
- docs/blackbox-agentic-os-profit-research-2026-07.md (Parts R + S stub)

**If blocked:** [note]
---END-CURSOR-HANDOFF---
```

---

## After Claude — paste into Cursor

See handoff block above, or ask Cursor to review execution pack + complete Part S.

---

## Operator quick reference (Path B — no need to paste)

| Week | Focus |
|------|--------|
| Week 1 | Day 1 ritual + os-log + one non-email skill |
| Week 2 | Execution pack §1–§6 (Claude Round 5 output) |
| Week 3 | 3 cold-DM lanes + screen-shares + signal log |
| Week 4 | Tally → Bucket B #1; then Stripe, wizard |

**Stop:** Surface 4 marketing, new strategy sessions, Bucket B code during gate (except Gmail Drafts if paying pilot).

---

*Round 5 prompt · 2026-07-09 · execution pack · debate moratorium until Week 4*
