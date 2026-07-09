# BLACKBOX — Horizontal SMB playbook

**Position change:** BLACKBOX is not a K-beauty product. It never was. K-beauty was one operator's dogfood, not the ICP. The ICP is **any owner-operator small business that lives in an inbox** — with policies to enforce, drafts to write, and no tolerance for a bot that sends the wrong thing.

**Why this changes now:** The narrow-ICP orthodoxy (Fable 7, GLM 5.2) is defensible advice for a moonshot AI product with a domain-specific model. It is the wrong advice for a horizontal governance layer. The horizontal SMB SaaS graveyard is real, but so is the horizontal SMB SaaS Hall of Fame: **Mailchimp (~$800M revenue before Intuit's $12B acquisition), QuickBooks, Shopify — all sold from day one to "the generalist running their own shop, not a procurement committee and not a specialist team"** ([Proof Dept, Six GTM Motions of B2B SaaS](https://www.proofdept.com/insights/six-gtm-motions-of-b2b-saas)). The pattern that wins isn't "pick one vertical." It's **one horizontal primitive + per-vertical starter kits**.

This doc replaces "K-beauty owner" with "SMB owner-operator" everywhere and grounds the pivot in real workflows, real templates, and real competitive product data — not theory.

---

## 1. The horizontal primitive (one sentence)

**BLACKBOX drafts anything you type repeatedly — from your own policies — waits for your yes, and gets smarter every time you fix it, all on your machine.**

That primitive doesn't care whether you sell serums, houses, haircuts, or hours. It cares whether you (a) write similar messages more than once a week, (b) have implicit or explicit rules about how those messages should read, and (c) don't want a machine sending on your behalf without your review. **Every SMB owner-operator meets those three conditions.**

---

## 2. Why this pain is universal (real numbers)

The market data is unambiguous: SMB owners drown in inbox-shaped work regardless of vertical.

- **2.6 hours per day (28% of the workweek)** managing email; only 10% of it is business-critical ([Mailbird, Email Management for Small Business Owners, 2026](https://www.getmailbird.com/email-management-small-business-guide/)).
- **36% of the average entrepreneur's workweek** is administrative tasks, dominated by unscheduled communications ([Agility PR, Time Management Survey](https://www.agilitypr.com/pr-news/pr-news-trends/time-management-new-survey-reveals-biz-owners-spending-time-theyd-rather-spend/)).
- **68.1% of solopreneur time on daily operations vs 31.9% "on the business"** — inbox work is exactly what's eating strategic time ([Mailbird](https://www.getmailbird.com/email-management-small-business-guide/)).
- **Automation saves 5–15 hours per week; well-optimized systems save 20+ hours** — an addressable prize that translates to €29/mo at any conservative hourly rate.
- **"More time" is the SMB's #1 stated need** ([Small Business Expo](https://www.thesmallbusinessexpo.com/blog/small-business-more-time/)).
- **The typical AI-using SMB runs 5 different AI tools** across content, service, scheduling, and automation — fueling demand for one assistant that shares context ([Missive, 8 best AI email assistants 2026](https://missiveapp.com/blog/ai-email-assistant)).

**Read that last one again.** The competitive opening isn't "AI email doesn't exist yet." It's "SMB owners are stitching five tools that don't talk to each other." BLACKBOX's edit-log flywheel + vault ledger is a **memory layer** those five tools structurally can't share.

---

## 3. The seven universal SMB workflows

Every SMB owner-operator does these, regardless of vertical. This is the horizontal skill library.

| # | Workflow | What it looks like | Existing BLACKBOX skill | Fit |
|---|---|---|---|---|
| 1 | **Customer/client inquiry reply** | "Do you ship to X? Can you fit me in Tuesday? What's your price?" | `customer_reply` | ✅ Shipped |
| 2 | **Lead/quote follow-up** | "Just checking in on the quote I sent you last week…" | `follow_up_draft` | ✅ Shipped |
| 3 | **Onboarding new customer/client** | Welcome, intake form, first-session prep, kickoff | (needs `client_onboarding_reply`) | ⚠️ Skill-YAML only |
| 4 | **Meeting/call → action items** | Notes in, decisions + owners + dates out | `summarize_meeting` | ✅ Shipped |
| 5 | **Weekly review / status update** | "Here's what I did this week" for you or a client | `weekly_review` | ✅ Shipped |
| 6 | **Document intake summary** | Contract, quote, PDF, docx dropped → key facts extracted | `doc_summarize` (docs driver) | ✅ Shipped |
| 7 | **Complaint / refund / dispute** | Sensitive, policy-heavy, high-stakes — the HITL is doing real work here | (needs `dispute_reply` variant, or use `customer_reply` with dispute SOPs) | ⚠️ SOP work |

**Every SMB reuses at least five of these seven weekly.** That's the horizontal bet: the skill library barely changes across verticals. What changes is the SOPs.

---

## 4. Ten vertical playbooks — real workflows, cited templates

Each row proves the same architectural point: **the emails per vertical are canonical, few, and templated by third parties already.** BLACKBOX's job is to run those templates against your specific policies with a HITL gate. The vertical is a **SOP starter kit + a channel map**, not a code fork.

### 4.1 Trades — plumber / electrician / HVAC / handyman

- **Top email types:** quote sent, quote follow-up ("need help finalizing your HVAC quote?"), appointment confirmation, post-service check-in, invoice + payment reminder.
- **Public templates exist:** [Jobber's 7 quote follow-up templates](https://www.getjobber.com/academy/quote-follow-up-email-templates/), [Plumber & HVAC SEO's follow-up scripts](https://www.plumberseo.net/email-scripts-for-excellent-customer-follow-up/), [VisibleFeedback's HVAC templates for repairs/installs/tune-ups](https://visiblefeedback.com/insights/hvac/hvac-follow-up-templates-texts-emails-repairs-installs-tune-ups/).
- **BLACKBOX SOPs:** `pricing-tiers.md`, `service-window-policy.md`, `warranty-claims.md`, `payment-terms.md`.
- **Channel:** email + SMS (Housecall Pro data: 24–48h follow-up wins residential jobs).
- **HITL matters because:** quote numbers are wrong = money lost.
- **Vertical competitor:** [Jobber](https://www.getjobber.com/), [Housecall Pro](https://www.housecallpro.com/) — full-stack ~$50–200/mo. BLACKBOX at €29 is the "I don't want a whole FSM system, I want my email drafted correctly" wedge.

### 4.2 Solo coach / consultant

- **Top email types:** discovery-call intake, welcome, session prep, session follow-up, program milestone, invoice.
- **Public templates:** [Simply.Coach onboarding guide](https://simply.coach/blog/coachs-guide-to-client-onboarding/), [ContentSparks' 9 email templates for coaches & consultants](https://contentsparks.com/email-templates-for-coaches-and-consultants/), [HelloBonsai's 7 coaching email templates 2026](https://www.hellobonsai.com/blog/coaching-email-template).
- **BLACKBOX SOPs:** `coaching-tone.md`, `program-scope.md`, `discovery-call-agenda.md`, `session-followup-structure.md`.
- **Channel:** email + occasional Calendly integration.
- **HITL matters because:** wrong tone with a client kills the relationship; wrong scope-of-work commit is a legal problem.
- **Vertical competitor:** [Practice.do](https://practice.do/), [Paperbell](https://paperbell.com/), [HoneyBook](https://www.honeybook.com/) — full CRM/coaching platforms $30–60/mo. BLACKBOX wedge: solo coaches who already live in Gmail and want drafting + memory, not another platform to migrate to.

### 4.3 Small marketing / design / dev agency (1–5 people)

- **Top email types:** proposal follow-up, client status update, scope-change confirmation, invoice reminder, hand-off summary.
- **BLACKBOX SOPs:** `pricing-per-scope.md`, `weekly-status-template.md`, `late-payment-escalation.md`, `voice-guide.md`.
- **Channel:** email + Slack + occasional Basecamp/Notion.
- **HITL matters because:** every retainer client thinks they're the only one — the tone-and-content mismatch is what kills accounts.
- **Vertical competitor:** [HubSpot](https://www.hubspot.com/) (CRM tier), [Notion AI](https://www.notion.so/), [ClickUp AI]. BLACKBOX wedge: agencies who want per-client SOPs (voice, scope, cadence) enforced automatically at draft time — a memory shape none of the above ship.

### 4.4 Real estate agent (solo or 2–3 team)

- **Top email types:** new-lead first contact, property inquiry response, showing confirmation, offer follow-up, closing checklist, past-client anniversary touch.
- **Public templates:** [Luxury Presence 33 templates 2026](https://www.luxurypresence.com/blogs/real-estate-email-templates/), [myRealPage 7 templates](https://myrealpage.com/blog/real-estate-email-templates/), [Contempo Themes 10 templates](https://contempothemes.com/10-real-estate-email-templates-for-agents/).
- **BLACKBOX SOPs:** `disclosure-policy.md`, `showing-scheduling.md`, `offer-response-tone.md`, `local-market-facts.md`.
- **Channel:** email + SMS heavy.
- **HITL matters because:** real estate is heavily regulated; auto-sent claims about a property are a lawsuit.
- **Vertical competitor:** [Follow Up Boss](https://www.followupboss.com/), [kvCORE](https://insiderealestate.com/kvcore/) — CRM-heavy, $60–500/mo. BLACKBOX wedge: solo agent who wants tone-matched drafts, not a CRM migration.

### 4.5 Salon / spa / independent practitioner

- **Top email types:** booking confirmation, appointment reminder, rebooking prompt, product recommendation follow-up, cancellation reschedule.
- **Public templates:** [Mailsoftly spa/salon templates](https://mailsoftly.com/email-templates/small-business-email-templates/spa-salon-email), [PosterMyWall salon email designs](https://www.postermywall.com/index.php/email/templates/spa-email-templates/all/all), [Vondy's salon appointment email template](https://www.vondy.com/salon-appointment-email-template--SSnK8pzi).
- **BLACKBOX SOPs:** `booking-policy.md`, `cancellation-window.md`, `product-cross-sell.md`, `retention-tone.md`.
- **Channel:** SMS-first, email secondary.
- **HITL matters because:** double-booking and wrong-service confirmations bleed revenue.
- **Vertical competitor:** [Vagaro](https://www.vagaro.com/), [Mindbody](https://www.mindbodyonline.com/) — full booking systems. BLACKBOX wedge: independents who use paper/Google Calendar + Gmail and don't want a booking platform.

### 4.6 Restaurant / small hospitality

- **Top email types:** reservation confirmation, private-event inquiry, catering quote, review response, vendor/supplier reply.
- **BLACKBOX SOPs:** `event-package-pricing.md`, `dietary-accommodation.md`, `review-response-tone.md`.
- **Channel:** email + Google review responses + occasional Instagram DM.
- **HITL matters because:** committing to allergens/dietary the kitchen can't actually handle is a health-safety event.
- **Vertical competitor:** [Toast](https://pos.toasttab.com/), [OpenTable](https://www.opentable.com/) — POS-plus. BLACKBOX wedge: back-of-house owner comms, not customer-facing bookings.

### 4.7 Solo lawyer / accountant / bookkeeper (from Fable 7 — still strongest architectural fit)

- **Top email types:** client intake, document request, engagement letter draft, matter update, invoice + reminder, tax-season repetition.
- **BLACKBOX SOPs:** `engagement-scope.md`, `privilege-language.md`, `deadline-tracking.md`, `client-communication-cadence.md`.
- **Channel:** email dominates (regulated industry, paper trail matters).
- **HITL matters because:** Air Canada precedent applies with 10× force — auto-sent legal/tax advice is malpractice.
- **Vertical competitor:** [Clio](https://www.clio.com/), [MyCase](https://www.mycase.com/) — legal practice management $50–150/mo. BLACKBOX wedge: solo practitioner drafting layer *inside* Gmail, not another portal.

### 4.8 E-commerce / DTC boutique (not just K-beauty — apparel, home, food, jewelry)

- **Top email types:** WISMO ("where is my order?"), return/exchange, product question, wholesaler inquiry, review response.
- **Data point:** WISMO is **40–60% of ecommerce support** at ~$5/ticket (Fable 7 §5). Universal across DTC verticals.
- **BLACKBOX SOPs:** `shipping-faq.md`, `returns-policy.md`, `product-catalog-facts.md`, `wholesale-terms.md`.
- **Channel:** email + Instagram DM (US/global) or Instagram + Viber (Greece specifically — Fable 7 §3).
- **HITL matters because:** wrong shipping/return commitments = chargebacks.
- **Vertical competitor:** [Gorgias](https://www.gorgias.com/) (17K+ brands, ~$60–360/mo), [Re:amaze](https://www.reamaze.com/), [Klaviyo Service](https://www.klaviyo.com/). BLACKBOX wedge: solo/micro-DTC who can't justify Gorgias's floor and lives in Gmail + Shopify admin.

### 4.9 Healthcare private practice (therapist / dietitian / chiro / small clinic)

- **Top email types:** intake response, appointment confirmation, insurance question, cancellation policy enforcement, referral coordination.
- **BLACKBOX SOPs:** `intake-scope.md`, `HIPAA-language.md` (US) / `GDPR-language.md` (EU), `no-show-policy.md`.
- **Channel:** email + patient portal.
- **HITL matters because:** anything approaching medical advice via auto-send is a licensing risk.
- **Vertical competitor:** [SimplePractice](https://www.simplepractice.com/), [Jane](https://jane.app/) — practice management $50–100/mo. BLACKBOX wedge: pre-portal inbound, admin overflow, referral coordination — the stuff practice-mgmt tools don't automate.

### 4.10 Photographer / videographer / event creative

- **Top email types:** inquiry response with pricing, contract send, shot-list confirmation, timeline coordination, delivery + gallery access, testimonial request.
- **BLACKBOX SOPs:** `package-pricing.md`, `usage-rights.md`, `turnaround-policy.md`, `delivery-tone.md`.
- **Channel:** email + Instagram DM for inbound leads.
- **HITL matters because:** commit to the wrong deliverable date and you kill your reputation.
- **Vertical competitor:** [HoneyBook](https://www.honeybook.com/), [Dubsado](https://www.dubsado.com/), [Studio Ninja](https://www.studioninja.co/) — creative-business platforms $20–70/mo. BLACKBOX wedge: solo creative who wants inbox drafting + memory, not another CRM.

---

**Pattern across all ten verticals:** each has 5–8 canonical email types, 3–6 policy documents, and one or two dominant channels (usually email + one messenger). The architectural cost of adding a new vertical to BLACKBOX is **zero code** — it is a **SOP starter kit** and a channel toggle. That is what makes horizontal viable.

---

## 5. What horizontal SMB winners actually did (playbook)

The horizontal SMB SaaS Hall of Fame validates a specific pattern. Copy it.

- **Mailchimp** launched in 2001 targeting freelancers and small businesses with freemium; bootstrapped to $800M+ revenue before Intuit's $12B acquisition. **Never picked one vertical** — sold "email marketing" as a horizontal utility ([Proof Dept](https://www.proofdept.com/insights/six-gtm-motions-of-b2b-saas)).
- **QuickBooks** sold accounting-as-utility to every SMB with a bank account. Vertical specialization came from third-party accountants, not the product.
- **Shopify** sold "an online store" to anyone selling anything.
- **HubSpot's SMB scaling learnings:** ACV $300–$3K, volume is the game, product-led acquisition ([Operator's Blog](https://operator.blog/2023/03/20/smb-saas-at-scale-founder-learnings-from-hubspot/)).

**What they had in common:**
1. **One horizontal primitive** ("send email to your list," "keep books," "sell online").
2. **Product-led onboarding** — the owner-operator set it up themselves in <60 minutes.
3. **Vertical starter templates** — Mailchimp shipped industry-specific email designs, QuickBooks shipped chart-of-accounts templates by industry. **The verticalization was in the *content*, not the *code*.**
4. **Freemium or generous trial** to remove the ICP-picking problem before you have data.
5. **Community + templates** as distribution — every vertical had a template gallery.

**BLACKBOX translation:**
1. **Primitive:** governed draft-anything with edit-flywheel.
2. **Onboarding:** the guide's Day-1 flow must complete in <60 min for a non-dev.
3. **Vertical starter kits:** ship `vault-templates/trades/`, `vault-templates/coach/`, `vault-templates/real-estate/`, `vault-templates/salon/`, `vault-templates/agency/`, `vault-templates/legal/`, `vault-templates/dtc/`, `vault-templates/healthcare/`, `vault-templates/restaurant/`, `vault-templates/creative/` — each with pre-seeded SOPs and one example inquiry.
4. **Trial not freemium:** Fable 7 established freemium is structurally hostile to BYOK. A 14-day trial with pre-seeded vertical template is the horizontal-safe version.
5. **Distribution:** the ten starter kits *are* the distribution — each is content marketing to that vertical.

---

## 6. Competitive read — the horizontal AI email assistant field is real (and beatable)

BLACKBOX is not the first attempt at horizontal SMB AI email. Read the incumbents honestly ([Missive](https://missiveapp.com/blog/ai-email-assistant), [Gmelius](https://gmelius.com/blog/best-ai-assistants-for-email), [Vellum](https://www.vellum.ai/blog/best-ai-assistant-for-small-business), [Revo](https://www.revo.ai/blog/comparison/best-ai-email-tool-for-small-businesses-a-2026-guide)):

| Product | Positioning | Where BLACKBOX wins | Where BLACKBOX loses |
|---|---|---|---|
| **Vellum** ([source](https://www.vellum.ai/blog/best-ai-assistant-for-small-business)) | "Personal AI assistant that runs on your device or cloud, remembers how your business works, handles email/scheduling/follow-ups across tools" | Owned vault + edit-log flywheel + audit trail; forced HITL gate | TTFV, cross-tool integrations already shipped |
| **Lindy AI** | Workflow automation with AI agents; lead follow-up + customer replies as repeatable flows | Local-first, no per-agent config for owner-operators | Deep integration graph; enterprise polish |
| **MailMaestro** | AI copilot inside Outlook and Gmail — drafts, responds, summarises, understands thread context | HITL-as-legal-protection (Air Canada); compounding SOP memory | Zero-install-in-place-of-email; Outlook coverage |
| **Missive** | Team-inbox + AI rules; 845 G2 reviews at 4.7 | Solo owner-operator focus (Missive is team-shaped) | Multi-channel breadth already shipped |
| **Spark** | Cross-platform email client with AI, low price | Vault ledger + edit flywheel (Spark has neither) | Native mobile/desktop client; polish |
| **Alfred** ([source](https://get-alfred.ai/blog/best-ai-email-assistants)) | Inbox triage AI | Draft-anything, not just triage; compliance story | Triage UX polish |

**Where BLACKBOX honestly differentiates (three things, all defensible):**
1. **Forced HITL gate with legal framing (Air Canada precedent).** No horizontal competitor markets this. It's a five-word wedge for any regulated persona.
2. **Owned markdown vault ledger.** Every competitor keeps memory in *their* cloud. BLACKBOX keeps it in *your* Obsidian folder. The vault survives the vendor. That is a sale to anyone burned by SaaS deprecation (Rewind users, anyone).
3. **Edit-log flywheel → SOP drift review.** Every competitor either has no memory (Spark, MailMaestro) or opaque memory (Vellum, Lindy). BLACKBOX's memory is a JSONL file the owner can read, edit, and delete. Compounding intelligence you can inspect is a genuinely novel primitive (Fable 7 §2 called this out as [NO DATA] in the competitive set — no one else ships it).

**Where BLACKBOX honestly loses today (fix or acknowledge):**
- **Install friction.** Every competitor is a browser tab or an Outlook add-in. BLACKBOX is Python + npm + `.env` + OAuth. This is the horizontal thesis's #1 blocker.
- **Multi-channel.** SMB owner support is not email-only — Klaviyo, Front Prime, Gorgias all bundle SMS/WhatsApp/Instagram. Solo email is a viable *wedge* but not a complete horizontal SMB story.
- **Zero-install trial.** No paid stranger can experience BLACKBOX in 5 minutes today.

---

## 7. What BLACKBOX needs to change to actually serve horizontal SMB

Small list, ordered by revenue impact per dev-hour. **None of these are new skills** — they are packaging, onboarding, and one-channel additions.

### 7.1 Ten vertical starter kits (highest leverage, lowest code)

Ship `vault-templates/<vertical>/` with:
- Pre-seeded SOPs (5–8 markdown files per vertical using the public template citations in §4)
- One example inquiry note in `00-Inbox/`
- Skill-picker default: `customer_reply`, `follow_up_draft`, `client_onboarding_reply`

**Effort:** 1 day per vertical of writing + citation, entirely operator-side (this doc has the URLs). **Zero code.** This is the horizontal onboarding play copied straight from Mailchimp.

### 7.2 A "pick your business" onboarding wizard

- Dashboard first-run prompts: "What kind of small business do you run?" → picks a starter kit → copies SOPs into vault → seeds `customer_reply` with your defaults.
- Reduces Day-1 time-to-first-draft from 30 min (guide §4) to <10 min.
- **Effort:** 2–3 days (dashboard component + copy-templates script).

### 7.3 Zero-install browsable trial

Even a *pre-generated demo vault + a live dashboard on your own domain* would let a stranger click through the Approval Inbox with fake data. Not a full SaaS; a demo you can send a link to.
- **Effort:** 3–4 days (deploy dashboard behind a domain with a read-only fake vault). No hosting of user data — the trial is *your* dogfood vault, made public.
- Alternative: a 2-minute Loom video walking through §4 of the operator guide. Ship this **this week**.

### 7.4 One additional channel — Instagram DM

- Ubiquitous across DTC, salon, restaurant, real estate, coach, photographer, healthcare inbound.
- Instagram Graph API + Messenger Platform read+draft is a comparable-effort driver to gmail (already built).
- **Do NOT add WhatsApp first** for Greece-based dogfood (Fable 7 §3 established Viber, not WhatsApp). For non-Greek SMBs, WhatsApp is second priority after Instagram.
- **Effort:** 5–7 days (driver + skill wiring + auth flow).

### 7.5 Rename the operator experience

The dashboard says "orchestrator," "graph," "vault." That's dev vocabulary. The owner-operator sees:
- "Approval Inbox" ✅ (already right)
- "Your policies" (instead of "SOPs")
- "Learning log" (instead of "edit-log.jsonl")
- "Weekly review" (instead of "sop_drift_review")

**Effort:** half a day of copywriting + a config file.

### 7.6 Optional: browser-based install path (deferred, high-value)

A single-installer .exe or a Docker Desktop image would remove the Python+npm wall entirely. This is a Week 6+ decision after horizontal dogfood proves demand.

---

## 8. The horizontal dogfood test (4 weeks, no code changes)

Fable 7 said the moratorium holds until Week 2 Friday. This test respects it AND directly answers the horizontal question.

**Week 1 (starting tomorrow):** operator dogfoods `customer_reply` on his own inbox as planned. Same as guide §4.

**Week 2:** operator writes **three vertical starter kits by hand** — pick three maximally different: e.g. `trades/`, `coach/`, `dtc/`. Each is SOPs + one example inquiry. Under 4 hours per kit if you use the cited public templates in §4.

**Week 3:** operator finds **three real SMB owner-operators** across those three verticals (not K-beauty — deliberately different). Cold-DM ask: *"Would you spend 30 minutes on a call and 20 minutes trying a private AI email drafter for [your business]? I'll set it up on my machine and drive; you tell me if the draft is any good."* Screen-share sessions, one per vertical.

**Green horizontal signal:** at least 2 of 3 respond with "yes, that draft is roughly what I would have written — I'd have edited X." **Red horizontal signal:** every vertical needs a fundamentally different skill or the policies don't map. If red, retreat to the strongest single vertical from the three.

**Week 4:** based on Week 3 signal, either
- (green) build the pick-a-business wizard + ship the 10 starter kits, or
- (red) pick the winning vertical, ship that starter kit deeply, revisit horizontal in 2 months.

**This test costs 0 lines of code and 3 real conversations.** It is exactly the conversation-shaped input Fable 7 said was missing.

---

## 9. Pricing that fits horizontal SMB

From Fable 7 §7 (do not re-litigate):
- **Do not do freemium.** ChartMogul/SaaSfactor: freemium is structurally hostile to BYOK agents.
- **14-day free trial** (Agent23 model) with vertical starter kit pre-seeded.
- **One tier at €29/mo** (Superhuman-anchored, ~€2–10 BYOK COGS). Horizontal winners kept pricing simple; QuickBooks and Mailchimp added tiers *after* volume.
- **Optional €499 one-time setup** for verticals with high install friction (legal, healthcare) where you (the operator) do OAuth + SOP customization + first-week hand-holding in a screen-share. Under-served per Fable 7 §7. Cap at 5 setup customers in Month 1 so it doesn't eat the dogfood budget.

---

## 10. Anti-goals — what NOT to do while going horizontal

1. **Do not build per-vertical skills.** The seven universal skills cover >90% of every vertical's inbox. Each starter kit is SOPs, not code. This is the whole point.
2. **Do not add multi-channel before Instagram works cleanly.** WhatsApp, Viber, SMS, Messenger, Discord — pick one, prove it, then add the next. Feature-count is a horizontal SMB death spiral (Rabbit R1, Humane — Fable 7 §7 graveyard).
3. **Do not rebrand.** "BLACKBOX" is fine; add a horizontal tagline like *"Your inbox, drafted by your policies. Never sent without your yes."* Rebranding is a Week 12+ conversation.
4. **Do not chase the Vellum / Lindy feature list.** They ship breadth; BLACKBOX ships defensibility (HITL as law, vault as memory, flywheel as compounding). Compete on those three, not on integration count.
5. **Do not accept every SMB persona equally in the first paying cohort.** Even horizontal Mailchimp had a most-eager segment (email marketers) that funded the horizontal build-out. From the §4 table, the three strongest architectural fits are **legal/accounting/bookkeeping**, **agency/consultant**, and **coach** — all email-dominant, all HITL-sensitive, all vault-friendly. **Bias the first paying cohort toward those three** while shipping starter kits for all ten.
6. **Do not throw away the K-beauty work.** Retail DTC is a legitimate vertical in the starter-kit set (§4.8). It's just no longer the *only* target.
7. **Do not extend the gate.** Four green dogfood weeks was the gate before this pivot; it stays the gate after. Going horizontal is a positioning change, not a feature explosion. The moratorium and build freeze from Fable 7 still hold.

---

## 11. TL;DR for the operator (bookmark this)

- **BLACKBOX is a horizontal governance layer**, not a vertical product. K-beauty was one dogfood, not the ICP.
- **Universal SMB pain:** 2.6h/day on email, 36% of workweek on admin, "more time" is the #1 stated need.
- **Universal SMB workflow:** seven repeated email/doc types cover every vertical's inbox. **BLACKBOX already ships six of them.**
- **Horizontal winners** (Mailchimp / QuickBooks / Shopify) verticalized through *content* (starter kits, templates), not *code*.
- **Defensible against Vellum/Lindy/MailMaestro/Missive on three things:** forced HITL with legal framing, owned markdown vault, inspectable edit-log flywheel. No horizontal competitor ships any of the three.
- **This week's action doesn't change:** finish Day 1, run three real customer_reply cycles, log the row.
- **Week 2 action:** write three vertical starter kits from the §4 citations (trades, coach, DTC — 4 hours each).
- **Week 3 action:** three cold-DM screen-share sessions across those three verticals. Green = at least 2/3 recognize their own inbox in the draft.
- **Fastest revenue per dev-hour:** ten starter kits (§7.1) + rename operator vocabulary (§7.5). Zero new code.
- **Next channel (after Instagram):** WhatsApp globally; Viber only for Greek-market pilots.

---

## Sources

- [Mailbird — Email Management for Small Business Owners 2026](https://www.getmailbird.com/email-management-small-business-guide/)
- [Agility PR — Time Management New Survey](https://www.agilitypr.com/pr-news/pr-news-trends/time-management-new-survey-reveals-biz-owners-spending-time-theyd-rather-spend/)
- [Small Business Expo — "More Time" as top need](https://www.thesmallbusinessexpo.com/blog/small-business-more-time/)
- [Missive — 8 best AI email assistants 2026](https://missiveapp.com/blog/ai-email-assistant)
- [Gmelius — 15 Best AI Email Assistants for Productivity 2026](https://gmelius.com/blog/best-ai-assistants-for-email)
- [Vellum — 10 Best AI Assistants for Small Business 2026](https://www.vellum.ai/blog/best-ai-assistant-for-small-business)
- [Revo — Best AI Email Tool for Small Businesses 2026](https://www.revo.ai/blog/comparison/best-ai-email-tool-for-small-businesses-a-2026-guide)
- [Alfred — Best AI Email Assistant 2026](https://get-alfred.ai/blog/best-ai-email-assistants)
- [Proof Dept — Six GTM Motions of B2B SaaS (horizontal vs vertical)](https://www.proofdept.com/insights/six-gtm-motions-of-b2b-saas)
- [Operator's Blog — SMB SaaS at Scale, Founder Learnings from HubSpot](https://operator.blog/2023/03/20/smb-saas-at-scale-founder-learnings-from-hubspot/)
- [FLG Partners — Horizontal vs Vertical SaaS Business Models](https://flgpartners.com/saas-industry-centric-business-models-horizontal-vertical/)
- [Jobber — 7 quote follow-up email templates](https://www.getjobber.com/academy/quote-follow-up-email-templates/)
- [Plumber & HVAC SEO — email scripts for excellent customer follow-up](https://www.plumberseo.net/email-scripts-for-excellent-customer-follow-up/)
- [VisibleFeedback — HVAC follow-up templates for repairs/installs/tune-ups](https://visiblefeedback.com/insights/hvac/hvac-follow-up-templates-texts-emails-repairs-installs-tune-ups/)
- [Housecall Pro — how to follow up on a quote](https://www.housecallpro.com/resources/how-to-follow-up-on-quote/)
- [Simply.Coach — coach's guide to client onboarding](https://simply.coach/blog/coachs-guide-to-client-onboarding/)
- [ContentSparks — 9 email templates for coaches and consultants](https://contentsparks.com/email-templates-for-coaches-and-consultants/)
- [HelloBonsai — 7 best coaching email templates 2026](https://www.hellobonsai.com/blog/coaching-email-template)
- [Luxury Presence — 33 real estate email templates 2026](https://www.luxurypresence.com/blogs/real-estate-email-templates/)
- [myRealPage — 7 real estate email templates 2026](https://myrealpage.com/blog/real-estate-email-templates/)
- [Contempo Themes — 10 real estate email templates for agents](https://contempothemes.com/10-real-estate-email-templates-for-agents/)
- [Mailsoftly — spa/salon email templates](https://mailsoftly.com/email-templates/small-business-email-templates/spa-salon-email)
- [PosterMyWall — salon and spa email templates](https://www.postermywall.com/index.php/email/templates/spa-email-templates/all/all)
- [Vondy — salon appointment email template](https://www.vondy.com/salon-appointment-email-template--SSnK8pzi)
- [LocaliQ — 34 free small business email templates](https://localiq.com/blog/small-business-email-examples-and-templates/)

---

*Horizontal SMB playbook v1 · 2026-07-09 · `master` @ `bf7b717` · Companion to `fable-7-progress-rating-2026-07-09.md` (which recommended narrow-ICP; this doc explicitly diverges after operator direction and grounds the divergence in horizontal-winner evidence).*
