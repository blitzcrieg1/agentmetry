# BLACKBOX — Path B execution pack (Week 2 assets)

**Round 5 · Claude (execution lead) · 2026-07-09 · `master` @ `bf7b717`**
**Companion:** [research doc Parts P + Q](./blackbox-agentic-os-profit-research-2026-07.md) · [horizontal playbook](./blackbox-horizontal-smb-playbook.md) · [operator guide §4](./blackbox-operator-guide.md).
**Scope:** shippable artifacts for Path B (broadened horizontal — comms hero, doc/meeting demo lanes). ≤8 operator hours total Week 2.
**Not in scope:** re-opening Path 1/2/3 ranking; kernel changes; commits.

---

## §1 — Loom script (2:30, comms + doc)

**Setup before you record:**
- Terminal: `scripts\blackbox.bat start` — dashboard on `http://127.0.0.1:8000`
- Screen 1: dashboard Approval Inbox card, empty state
- Screen 2: `vault/00-Inbox/` with one **real anonymized** customer email note and one **real anonymized** PDF (invoice / contract / quote — 1-2 pages, no PII on-screen)
- Screen 3: `vault/10-SOPs/customer-tone.md` open in Obsidian or a text editor
- Camera on, no music, 720p is fine, one take is fine

**Script (talk-track times aim for a slight rush — 2:30 hard cap):**

**(0:00–0:15) Hook — no jargon.**
> *"I built BLACKBOX because I was tired of AI tools that either sent emails I never approved or forgot everything I taught them the next week. Two things — drafts you approve, memory you own. Ninety seconds each. Let me show you."*

**(0:15–0:30) Show the SOP file, plain text.**
> *"This is one of my policies — how I want customer replies to sound. Plain markdown, on my laptop. No cloud account. If I quit BLACKBOX tomorrow, I still own this."*

**(0:30–1:30) Comms flow — the hero surface.**
- Show inbox note in `00-Inbox/`.
- In dashboard left sidebar (**The Armory · Desk**): click the **Customer Reply** card → set **Task input** to `00-Inbox/example-quote-followup.md` (or your inbox note path) → click **Execute**.
- 20-second dead-air ok while it drafts. Fill it with:
  > *"It's reading three of my SOPs — tone, shipping, returns — and drafting a reply against what the customer actually asked. It cannot send. That is on purpose."*
- Draft appears in Approval Inbox. **Edit one real thing** on camera (fix a tone line, add a specific).
- Approve.
- Cut to the archived draft in `30-Archive/drafts/` — hold on it for 2 seconds.
- Cut to `vault/.system/feedback/edit-log.jsonl` growing by one row (open in Obsidian or a text editor).
  > *"Every fix I just made was captured. Next week that pattern feeds a review skill that suggests updating my policies. That's the compounding part."*

**(1:30–2:15) Document tab — one clear scenario (auto-archive, no approval gate today).**
- Drop the PDF into `00-Inbox/`.
- Dashboard → **Document Summarizer** card → Task input = PDF path → **Execute**.
- Wait 15 seconds. Show **Completed** banner (or archived file under `30-Archive/`).
  > *"Same vault ledger. Drop a client PDF — contract, invoice, quote — get a summary you can act on. Comms replies go through the approval inbox; doc summaries auto-archive today — reply drafts from docs still use the comms gate when you run customer_reply next."*

**(2:15–2:30) Close + two honesty flags.**
> *"Today drafts land in a folder on your laptop. Gmail Drafts delivery ships next month. And it's a local install — Python and a config file. That's the wall I'm knocking down over Q3. If you'd try it anyway, DM me. €29 a month when the trial opens."*

**On-screen text overlay for the last 15 seconds:**
> **Local · Own your data · Never auto-sends · Trial opens August 2026 · [contact link]**

**Recording rules:**
- No music, no logo animation, no scripted salesy phrases
- Do NOT say "Agentic OS" once — save that for the README pitch (per Part I)
- Do NOT show any real customer email or invoice content on-screen unredacted — pause and blur if needed
- If the draft is bad in the take, keep rolling and edit it on camera — that IS the demo

---

## §2 — Landing page copy (hero + doc tab + pricing + FAQ)

Copy-paste-ready. Structure assumes a single scroll page (no route). "OS" appears only in the sub-page footer link, never in the hero.

### Hero

> **Your inbox, drafted by your policies. Never sent without your yes.**
>
> BLACKBOX drafts customer emails, follow-ups, and client updates from your own policies. Every draft waits in an inbox for your yes-or-edit. Every fix you make trains the next draft. Everything stays on your machine.
>
> [Watch the 2-minute demo] [Get the trial invite]

### Subhero (three-icon strip)

- **Local.** Runs on your laptop. Your vault files stay on disk; see FAQ #1 for what each skill run sends to your LLM or Gmail.
- **Never auto-sends.** Every draft is your call. Your policies, your approval, your ledger.
- **Learns from you.** Fix a draft — it remembers. See exactly what it learned in a plain-text file.

### Tab 1 — Comms (hero, expanded by default)

> **Customer replies, quote follow-ups, client updates — drafted for you.**
>
> Drop the email into your inbox folder. BLACKBOX reads your tone, shipping, and returns policies, then drafts a reply. You edit what's wrong and hit approve. The draft goes to your archive; the correction goes to your learning log.
>
> **Who it's for:** solo consultants, agencies, coaches, real estate agents, trades, salons, DTC micro-brands.
>
> **What ships today:** drafts land in your vault archive folder. **Gmail Drafts delivery ships August 2026.**

### Tab 2 — Documents

> **Drop a PDF — get a summary and a reply draft grounded in your SOPs.**
>
> Contracts, invoices, quotes, client memos. BLACKBOX summarizes what matters against the policies you already wrote. **Summaries auto-archive to your vault today**; if you draft a client reply from that summary, it goes through the same approval inbox as comms.
>
> **Who it's for:** solo accountants, small law firms, agencies handling client documents.
>
> **What ships today:** digital PDF and DOCX. Scanned-paper OCR arrives if paying pilots ask for it.

### Pricing (single block, no discount cross-outs)

> **€29 / month — Solo**
> One person. Every skill. BYOK your Gemini or OpenAI key. Cancel anytime.
>
> **€49 / month — Solo Pro**
> Everything in Solo + batch approve (10 drafts in one click) + priority email support.
>
> **Coming Q4 2026 — Firm (2–10 seats)** · Shared policies, per-seat audit trail, GDPR-clean.
>
> 14-day free trial. No credit card at signup. **BYOK model = no LLM markup from us.**

### FAQ × 5 (kill objections in order of frequency)

> **1. Do you send my customer data anywhere?**
> Your vault (policies, archive, edit log) stays on your laptop. When a skill runs, BLACKBOX sends **only the text needed for that task** — typically the inquiry or document plus loaded policy excerpts — to **your chosen LLM** (Gemini API or local Ollama, your key). If you enable Gmail skills, Google’s Gmail API is also called to read threads or write drafts. We do not host your vault in our cloud.

> **2. Can BLACKBOX send emails on my behalf?**
> Not today. Every draft waits for your approval. In Q3 2026 we'll ship optional Gmail Drafts delivery — meaning the approved draft lands in your Gmail Drafts folder for you to review and send by hand. There is no "send after approve" in Year 1.

> **3. What happens if you shut down?**
> Everything you built stays on your laptop. Policies are markdown files. The edit log is a plain-text JSONL. The archive is markdown. You can read all of it in Notepad. Nothing is locked in a proprietary format.

> **4. Is this GDPR / EU AI Act compliant?**
> It's designed to make compliance easier: no data leaves your machine except the specific LLM call you triggered; every AI output is human-reviewed before it goes anywhere; a full audit trail is exportable. See our [EU AI Act one-pager]. **This is not legal advice — your DPO or lawyer signs off, not us.**

> **5. Why isn't this in my browser?**
> Because your customer data would be. Local-first means installing a small runtime (Python + a config file, about 15 minutes). It's not zero-friction. It's a deliberate trade for ownership. If that trade isn't worth it to you, we're honest that this isn't your product.

### Footer

> Built in Greece. Powered by an open [governed local Agentic OS runtime](./architecture). MIT-licensed kernel. [Docs] [Contact] [DPA template] [Twitter/X]

**Copy rules:**
- No "revolutionary," "next-generation," "AI-powered" — banned
- No emojis in body copy
- Every pricing number rounded (€29, €49) — no €28.99
- The word "agent" appears twice max on the page (subhero "learns from you," footer link)

---

## §3 — Three starter kits (trades / coach / DTC)

Each kit lives under `vault-templates/<vertical>/` and is copy-into-vault-ready. Contents: folder tree, 5–6 SOP stubs (title + 1 line each — full body is operator's real content), one example inbox note, default skills, and a cold-DM variant for Week 3.

### §3.1 — Trades (plumber / electrician / HVAC / handyman)

**Folder tree** (paste into vault):
```
vault-templates/trades/
├── 00-Inbox/
│   └── example-quote-followup.md
├── 10-SOPs/
│   ├── pricing-tiers.md
│   ├── service-window-policy.md
│   ├── warranty-claims.md
│   ├── payment-terms.md
│   ├── customer-tone.md
│   ├── quote-followup-cadence.md
│   ├── shipping-faq.md          # required by customer_reply.yaml — use "N/A trades" or service-area policy
│   └── returns-policy.md        # required by customer_reply.yaml — use warranty/refund cross-ref
└── README.md
```

**SOP stubs (1 line each):**
- `pricing-tiers.md` — Callout, hourly, parts markup, emergency surcharge, when-to-quote-fixed vs T&M.
- `service-window-policy.md` — Same-day vs next-day, weekend rules, minimum visit fee.
- `warranty-claims.md` — What's covered, what isn't, response-time promise.
- `payment-terms.md` — Deposit %, net terms, late fee, accepted methods.
- `customer-tone.md` — Friendly-professional, name usage, apology rules, technical-detail level.
- `quote-followup-cadence.md` — Day 2, Day 5, Day 10 templates from [Jobber's 7 templates](https://www.getjobber.com/academy/quote-follow-up-email-templates/).
- `shipping-faq.md` — **Required by `customer_reply.yaml`.** For trades: "We don't ship product — service area + visit scheduling only" or N/A stub so the skill doesn't 404.
- `returns-policy.md` — **Required by `customer_reply.yaml`.** Cross-reference warranty-claims + payment-terms for deposit/refund rules.

**Example inbox note (`example-quote-followup.md`):**
```markdown
---
from: sarah.k@example.com
subject: Re: bathroom re-plumb quote
received: 2026-07-08
---

Hi — thanks for the quote you sent Monday. My husband and I are
comparing three estimates and yours is the middle one. Can you help
us understand what the €800 difference between yours and the cheaper
one is actually paying for? We want it done right but €800 is a lot.
```

**Default skills:** `customer_reply` (primary), `follow_up_draft` (for Day 5 nudge). Meeting/doc unused.

**Cold-DM variant (Week 3, one line):**
> *"I built a tool that drafts your quote follow-ups from your pricing rules — you approve every send in the evening. Fifteen-minute screen-share? No sales pitch, just show and honest feedback."*

### §3.2 — Coach (executive, life, fitness, business)

**Folder tree:**
```
vault-templates/coach/
├── 00-Inbox/
│   └── example-discovery-call-notes.md
├── 10-SOPs/
│   ├── discovery-call-agenda.md
│   ├── session-prep-template.md
│   ├── session-followup-structure.md
│   ├── program-scope-rules.md
│   ├── coaching-tone.md
│   └── client-boundaries.md
└── README.md
```

**SOP stubs:**
- `discovery-call-agenda.md` — 45-min structure: rapport, goal, obstacle, fit, next-step.
- `session-prep-template.md` — What you send 24h before every paid session.
- `session-followup-structure.md` — Recap + action items + next session hold. Template from [Simply.Coach onboarding guide](https://simply.coach/blog/coachs-guide-to-client-onboarding/).
- `program-scope-rules.md` — What's in-scope vs out-of-scope; when you say no.
- `coaching-tone.md` — Warm, direct, no unsolicited advice, curiosity-first.
- `client-boundaries.md` — Response-time promise, off-hours policy, session cancellation rules.

**Example inbox note (`example-discovery-call-notes.md`):**
```markdown
---
call: Discovery — Alex M.
date: 2026-07-08
duration: 42 min
---

Alex is a Series B engineering director. Wants exec-coaching for
next-level leadership — running a team of 40 across 3 timezones.
Main pain: 60-hour weeks, feels reactive, no strategic time.
Tried: therapy (helped personal, not work), one-off leadership book.
Budget: mentioned $500-800/mo without prompting.
Concern: doesn't want "guru energy." Wants tactical.
Next: I promised to send a recap + program outline by Friday.
```

**Default skills:** `summarize_meeting` (primary demo — call notes → recap + action list), `customer_reply` (for the Friday follow-up email).

**Cold-DM variant:**
> *"I built a tool that turns your call notes into a client recap + action list — you approve before anything gets sent. Especially useful if you run 3+ discovery calls a week. Quick demo, no pitch?"*

### §3.3 — DTC micro-brand (K-beauty, skincare, apparel, home)

**Folder tree:**
```
vault-templates/dtc/
├── 00-Inbox/
│   └── example-wismo-inquiry.md
├── 10-SOPs/
│   ├── shipping-faq.md
│   ├── returns-policy.md
│   ├── product-catalog-facts.md
│   ├── wholesale-terms.md
│   ├── customer-tone.md
│   └── review-response-tone.md
└── README.md
```

**SOP stubs:**
- `shipping-faq.md` — Cutoff times, carriers, EU delivery windows, tracking policy, "where is my order?" default response.
- `returns-policy.md` — Window, condition, restocking, damaged-on-arrival, non-returnable categories.
- `product-catalog-facts.md` — Ingredients / materials / claims / country of origin — the facts you can cite in a reply.
- `wholesale-terms.md` — MOQ, pricing tiers, payment terms, dropship policy.
- `customer-tone.md` — Warm but professional; brand voice specifics; emoji policy.
- `review-response-tone.md` — 5-star, 3-star, 1-star response templates.

**Example inbox note (`example-wismo-inquiry.md`):**
```markdown
---
from: maria.r@example.com
subject: Order #10847 — still no tracking?
received: 2026-07-08
---

Hi, I ordered the vitamin C serum on July 3rd and I still don't
have a tracking number. Is my order actually shipped? Can you
please check? I bought it for a friend's birthday on Saturday
so I'm getting nervous.
```

**Default skills:** `customer_reply` (primary — WISMO). Optionally `doc_summarize` for wholesaler quote PDFs.

**Cold-DM variant:**
> *"I built a tool that drafts your 'where is my order?' replies from your shipping and returns policies — you approve every one in a batch each evening. If WISMO eats your afternoons, worth 15 min?"*

**All three kits:** README.md is one paragraph pointing back to `docs/blackbox-operator-guide.md` §4 with the vertical example substituted in.

---

## §4 — Signal log template + Week 4 tally rule

Add `vault/10-SOPs/signal-log.md` (one file, updated as prospects appear). Not a spreadsheet — same file lives next to `os-log.md` for one-glance review.

### Template

```markdown
# BLACKBOX signal log — 2026-Q3

Format: `YYYY-MM-DD · source · vertical · surface · skill_used · blocked_by · verdict`

**Verdict grammar:** either `pay €X if Y ships` or `no — reason` or `pending`.

## Week 3 — cold-DM screen-shares

2026-07-2X · LinkedIn DM · trades · comms · customer_reply · Gmail Drafts · pay €29 if Gmail Drafts ships
2026-07-2X · LinkedIn DM · coach · meeting · summarize_meeting · nothing (paste transcript worked) · pay €29 today (SIGNED)
2026-07-2X · Reddit DM · accountant · doc · doc_summarize · compliance-export button + DPA template · pay €149 if both ship
2026-07-2X · warm intro · agency · comms · customer_reply · batch approve · no — team of 6, needs shared vault
2026-07-2X · IndieHackers · photographer · comms · customer_reply · Instagram DM · pending — wants IG integration
```

### Week 4 tally rule (Cursor P.2 verbatim, adopted)

- Count **verdict lines matching `pay €X if Y ships` on the same surface**.
- **≥2 of 3** prospects on one surface = that surface wins → **Bucket B item #1 swaps** to that surface's unblock (Gmail Drafts / compliance-export / paste-transcript ergonomics).
- **Doc-surface + scanned PDF:** if ≥2 doc verdicts cite `blocked_by: scanned PDF`, **OCR (~2–3 dev-days) replaces compliance-export as #1** for that sprint; compliance-export stays #1 if blockers are audit/export/DPA only (Cursor Part S accepts R.2).
- 1–1–1 or fewer than 2 on any single surface → **default to Gmail Drafts** (Cursor P.2.1 guardrail).
- **Any prospect offering money before Week 4 close pre-empts the tally.** Signed pilot beats spreadsheet (Cursor P.2.3 override).
- Items #2 (Stripe) and #3 (`doctor --wizard`) do not swap — they fix install for every surface (Cursor P.2.2).

### One line to add to `os-log.md` on Friday of Week 4:

```
Week 4 close · signal count: comms=X doc=Y meeting=Z · winner: [surface or "tie → Gmail Drafts"] · Bucket B #1 = [swap]
```

---

## §5 — EU AI Act one-pager (marketing copy + honest disclaimer)

Save as `docs/marketing/eu-ai-act-blackbox.md`. Print-friendly (one page). Link from landing FAQ #4.

### On-page content

> # BLACKBOX and the EU AI Act
> **What changes on August 2 2026, and why local + approve-before-send is the safer place to stand.**
>
> ---
>
> **The confirmed August 2, 2026 deadline** is for the **AI Act Article 50 transparency obligations** — the rules requiring providers to disclose when a user is interacting with AI, mark AI-generated content, and label deepfakes. This deadline stands ([artificialintelligenceact.eu implementation timeline](https://artificialintelligenceact.eu/implementation-timeline/); [Holland & Knight 2026 analysis](https://www.hklaw.com/en/insights/publications/2026/04/us-companies-face-eu-ai-acts-possible-august-2026-compliance-deadline)).
>
> **The high-risk AI system obligations have been formally postponed to December 2, 2027** for stand-alone Annex III systems (and August 2, 2028 for Annex I product-embedded AI) via the Digital Omnibus, Council adoption June 29, 2026 ([Latham & Watkins update](https://www.lw.com/en/insights/ai-act-update-eu-resolves-to-change-rules-and-extend-deadlines); [Gibson Dunn Omnibus analysis](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)). **Footnote:** providers of generative AI already on the market before August 2, 2026 get until **December 2, 2026** for Article 50(2) machine-readable content marking — Article 50 disclosure duties still apply from August 2, 2026.
>
> **SME carve-outs are real and expanded.** The simplified compliance framework extends to companies with up to 750 employees and €150M in annual revenue — reduced fines, regulatory sandbox access, and standardized documentation templates.
>
> ## Why BLACKBOX's shape makes the AI Act easier, not harder
>
> - **Transparency (Article 50):** Every BLACKBOX draft is explicitly presented to you as AI-generated before you approve. Your customer never receives AI-generated content you didn't consciously send.
> - **Human oversight:** BLACKBOX's forced approval gate is not a UX choice — it's an architectural rule. Every outbound artifact is a human decision on the record.
> - **Audit trail:** Your vault is a full ledger of every skill run, every approval, every edit. Exportable as plain markdown. Regulator-legible without conversion.
> - **Data minimization (GDPR alignment):** Customer data lives on your laptop, not in a vendor cloud. LLM calls send the specific task text only — never the whole customer record.
>
> ## What this one-pager is not
>
> - **This is not legal advice.** BLACKBOX is a builder, not a law firm. Your DPO, lawyer, or accountant signs off on your specific compliance posture — not us.
> - **This is not a compliance certification.** No product can certify you. Compliance is a process; BLACKBOX is one tool that makes several parts of that process easier.
> - **This is not a substitute for a DPIA.** For high-risk use cases, you still need a Data Protection Impact Assessment under GDPR Article 35 and a Fundamental Rights Impact Assessment under AI Act Article 27.
>
> ## Two-line takeaway
>
> If you were planning to deploy an AI drafting tool for customer communications in 2026, BLACKBOX's local-first + forced-approval + owned-ledger shape lets you say **yes to Article 50 transparency on day one** without a cloud vendor DPIA. That is not a legal opinion; it is an architectural statement.
>
> ---
>
> *One-pager v1 · 2026-07-09. Deadlines verified against the Digital Omnibus agreement of June 29, 2026 ([Latham & Watkins](https://www.lw.com/en/insights/ai-act-update-eu-resolves-to-change-rules-and-extend-deadlines)). Update when the AI Act Service Desk publishes the amended Regulation in the Official Journal.*

**Copy rules for this page:**
- Never write "GDPR compliant" without a qualifier — write "GDPR-aligned" or "designed to make GDPR easier"
- Never write "certified" or "guaranteed"
- Always cite the deadline source when a date appears
- The last sentence of every marketing paragraph should be defensible under cross-examination

---

## §6 — Week 2 day-by-day (Mon–Fri, ≤8 operator hours total)

Sequenced so no single day exceeds 2 hours. All dogfood runs happen in whatever normal work-inbox time the operator has anyway.

### Monday (2026-07-13) — 1.5h

- **0.5h** — Day 1 ritual per [operator guide §4](./blackbox-operator-guide.md) if not already done Friday: one real `customer_reply`, honest edit, approve, verify edit-log grew.
- **0.5h** — Create `vault/10-SOPs/os-log.md` with the Week 1 template header + Monday's row.
- **0.5h** — Create `vault/10-SOPs/signal-log.md` from §4 template (empty rows).

### Tuesday (2026-07-14) — 2h

- **2h** — Write §3.1 (trades) starter kit content into `vault-templates/trades/`. Real SOP body text for pricing-tiers, service-window, warranty, payment-terms. Steal from [Jobber](https://www.getjobber.com/academy/quote-follow-up-email-templates/) and [Housecall Pro](https://www.housecallpro.com/resources/how-to-follow-up-on-quote/) — do not invent from scratch.

### Wednesday (2026-07-15) — 1.5h

- **0.5h** — Run one non-email skill on real content: `doc_summarize` on a real PDF sitting in a Downloads folder (invoice, contract, quote) OR `summarize_meeting` on real call notes.
- **1h** — Write §3.2 (coach) starter kit. Steal from [Simply.Coach](https://simply.coach/blog/coachs-guide-to-client-onboarding/) and [ContentSparks](https://contentsparks.com/email-templates-for-coaches-and-consultants/).

### Thursday (2026-07-16) — 1.5h

- **1h** — Write §3.3 (DTC) starter kit. Pull shipping/returns copy from an existing store you admire; adapt.
- **0.5h** — Draft the landing page copy from §2 into `docs/marketing/landing-page-v1.md` (do NOT publish yet — Week 3 sign-off after DMs land).

### Friday (2026-07-17) — 1.5h

- **0.5h** — Write §5 EU one-pager into `docs/marketing/eu-ai-act-blackbox.md`. Verify both deadline citations still hold before publishing anywhere.
- **0.5h** — Record §1 Loom take 1. If it's bad, do NOT re-record until Monday.
- **0.5h** — Friday `os-log.md` close: `blackbox stats --days 7`, count edit-log rows, first line of "what did I learn." No `sop_drift_review` this week — Week 3 minimum for that (need ≥3 edit-log rows).

**Total: 8h across Mon–Fri.** If a day slips, the fungible items are the second Loom take and the DTC kit — never the daily ritual, never the signal log.

**What Week 2 does NOT include:**
- Any Bucket B code (Gmail Drafts, Stripe, wizard — all post-gate)
- Cold-DMs — those are Week 3, after the assets exist
- Publishing the landing page — it stays in `docs/marketing/` as markdown until Week 3 DMs surface real objections
- Recording the Loom more than twice — perfection kills shipping

---

## Handoff to Cursor (Round 5)

Cursor reads this pack + Part R in the research doc, then in Round 6:
1. Reviews §1 Loom script for accuracy against actual dashboard behavior at `bf7b717`
2. Reviews §2 landing copy for over-promise (especially FAQ #1 "nothing leaves" — verify against actual gmail/LLM call boundaries)
3. Reviews §3 kits for skill-YAML compatibility (do the skills actually read those SOP paths?)
4. Verifies §5 EU AI Act deadlines against the Official Journal publication when it lands (Digital Omnibus was agreed June 29, 2026; the amended Regulation publishes shortly after)
5. Any Part R red-line disagreements

---

*Path B execution pack v1 · 2026-07-09 · Week 2 assets only. Week 3 = cold-DMs; Week 4 = signal tally; Bucket B #1 = swap or default per §4 rule. Do not commit until Cursor Round 6 clears.*
