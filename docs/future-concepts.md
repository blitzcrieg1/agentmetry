# BLACKBOX — Future Concepts Backlog

Ideas captured from product research, SMB pain mapping, and vertical examples
(K-beauty e-shop, WooCommerce, Gmail). **Implement when the core kernel and
daily-driver UX are stable** — not before Obsidian plugin, crash recovery, and
Tier B drivers are proven.

Status key: **💡 concept** · **📋 spec-ready** · **🔨 partial** · **✅ shipped**

Related docs:

- [implementation-guide.md](./implementation-guide.md) — rollout for personal/SMB
- [smb-pain-research.md](./smb-pain-research.md) — pain × fit matrix

---

## 1. North-star positioning

**One sentence:**

> Governed local agent runtime for document-heavy small businesses — capture in
> vault, process with skills, approve before outbound, audit everything.

**Not:** generic chat, full ERP, RPA clicking Windows, ad platform replacement.

**Wedge order:**

1. Admin time back (meetings, inbox, drafts) — **✅ mostly shipped**
2. Outbound with approval (email, outreach) — **💡 needs drivers**
3. Research + campaigns (search → vault → email) — **💡**
4. Deep integrations (Woo, CRM, calendar) — **💡**

---

## 2. Platform capabilities (horizontal)

### 2.1 MCP drivers to build

| Driver | Purpose | Priority | Notes |
|--------|---------|----------|-------|
| **gmail** | Read threads, create draft, send after approval | P1 | OAuth; `env_allow` for tokens; prefer draft-first |
| **search** | Serper / Tavily / Google CSE | P1 | Supplier & lead research without browser RPA |
| **woocommerce** | REST read orders/products/stock; optional write with gate | P1 | API keys in driver env only |
| **smtp** | Generic send for non-Gmail | P2 | Fallback |
| **calendar** | Follow-up scheduling | P3 | Google Calendar |
| **shell** (Tier 1 sandbox) | File ops, scripts | P3 | Unlock exec-tagged tools safely |
| **browser** | Last resort | P4 | High risk; prefer search API |

Config pattern: `vault/.system/drivers.json` + skill `tools:` allowlist (existing).

### 2.2 Kernel / UX gaps

| Item | Why | Priority |
|------|-----|----------|
| Obsidian plugin v0 | Status bar, summarize active note, approve via API | P0 |
| Crash recovery UX | Stale `20-Active-Loops/`, `RUN_FAILED` IVT vector | P0 |
| Sandbox Tier 1 | Subprocess jail for shell/write tools | P1 |
| Batch approval UI | Approve 10 emails / outreach rows at once | P1 |
| Model routing | Cheap model triage, strong model for client-facing | P2 |
| Per-tenant vault sync | Shared vault for 2–10 staff (Syncthing doc) | P2 |
| Webhook ingress | Woo → vault note on new order (optional) | P3 |

### 2.3 Skills library (YAML-first)

| Skill | Graph | Depends on |
|-------|-------|------------|
| `customer_reply` | pipeline | gmail + woo + vault SOPs |
| `supplier_outreach` | pipeline | search + gmail + vault templates |
| `supplier_intake` | pipeline | vault_fs (triage supplier paste) |
| `rfq_responder` | pipeline | vault price sheets + gmail draft |
| `marketing_batch` | pipeline | vault brand tags |
| `follow_up_cron` | trigger + pipeline | vault tags + gmail |
| `stuck_orders_digest` | cron + pipeline | woo read |
| `low_stock_digest` | cron + pipeline | woo read |
| `influencer_outreach` | lead_gen variant | gmail + approval |

---

## 3. SMB vertical playbooks

### 3.1 Generic small business (1–20 staff)

**Top pains (2026 survey-backed):** time, marketing content, follow-ups, lead research.

**Today:** meeting summarize, inbox triage, weekly review, lead_gen drafts.

**Future:** email send, search leads, cron follow-ups, batch marketing from brand vault.

See [smb-pain-research.md](./smb-pain-research.md).

### 3.2 K-beauty e-shop — Greece → EU (reference customer)

**Stack:** WooCommerce, Gmail, possibly Obsidian for internal notes.

**Vault layout (concept):**

```
00-Inbox/           customer/supplier paste or auto-ingest
10-Brand/           voice, EU claims rules, “safe wording”
10-Products/        SKU, INCI, positioning, margin notes
10-Suppliers/       KR/EU wholesalers, MOQ, COA, contacts
10-SOPs/            shipping EU, returns, authenticity FAQ
10-Campaigns/       drops, influencers
30-Archive/         agent outputs
```

**Workflows:**

| Workflow | Phase | Systems |
|----------|-------|---------|
| Paste customer email → triage + reply draft | A (now) | Inbox + vault SOPs |
| Gmail unread → draft with Woo order context | B | gmail + woo + approval |
| Korean/EU wholesaler search → vault table | B | search MCP |
| Bulk pricing inquiry emails | B | gmail + supplier_outreach + batch approve |
| Stuck orders / low stock daily note | B | woo cron |
| Product copy GR/EN from INCI | A (now) | summarize + brand vault |
| Influencer / B2B outreach | A/B | lead_gen + gmail |

**Explicit non-goals:** replace Woo checkout, payments, shipping labels, Meta ads.

**Compliance notes:** GDPR on vault copies of mail; human approve customer-facing
claims (EU cosmetics).

### 3.3 Agency / professional services

Meeting → archive, client email triage, weekly brief, proposal drafts from RAG.

### 3.4 B2B sales / distribution

Research → structured leads → outreach → follow-up cron (same as supplier_outreach).

---

## 4. Integration architecture (Woo + Gmail)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ WooCommerce │     │   BLACKBOX   │     │    Gmail    │
│  (orders)   │◄───►│ vault+skills │◄───►│  (customers)│
└─────────────┘     │  + drivers   │     └─────────────┘
                    └──────┬───────┘
                           │
                    Dashboard Gate
                    (approve send)
```

**Phase A — no API:** forward/copy email → `00-Inbox/`; manual Woo lookup.

**Phase B — drivers:** skills pull order + thread; draft; approve; send; archive.

**Suggested build order:** gmail read+draft → woo read → `customer_reply` skill →
gmail send with gate → supplier_outreach.

---

## 5. “Real agent” examples (deferred)

These require search + email + governance — **not** chat replacement.

| Example | Steps |
|---------|--------|
| EU Korean wholesalers for K-beauty | search → extract table → email template → approve → send → log |
| Weekly competitor price scan | search or paste → diff note in vault |
| AR payment chasers | woo overdue + gmail draft (no auto-debit) |
| Re-order from supplier when stock low | woo threshold → supplier email draft |

---

## 6. Chat vs BLACKBOX (reminder for GTM)

| Chat | BLACKBOX |
|------|----------|
| One-off | Repeatable skill + trigger |
| Thread memory | Vault files + RAG |
| No audit | Archive + run history |
| No team ledger | Shared vault |
| Manual send | Approve → send driver |

Use chat for exploration; use BLACKBOX for **operations**.

---

## 7. Go / no-go criteria (“good point”)

Start implementing §2–§5 when **all** are true:

- [ ] Obsidian plugin v0 shipped (or equivalent zero-friction run-from-note)
- [ ] Crash recovery UX acceptable (no confusing stale loops)
- [ ] At least 3 production skills used weekly by operator (dogfooding)
- [ ] Gmail or search driver MVP stable in CI
- [ ] One pilot SMB (or vertical self-test) ran 30 days without manual kernel fixes

Until then: extend **vault skills + triggers** only; defer Woo/Gmail drivers.

---

## 8. Cost / GTM snippets (reuse in pitches)

- Recover **2–3 owner hours/week** → pays for API tier.
- Part-time admin **$800–1,500/mo** vs BLACKBOX **~$20–100/mo** API + self-host.
- K-beauty pitch: *“Sourcing and support back-office — approve before anything
  goes to a customer or supplier.”*

---

## 9. Document changelog

| Date | Notes |
|------|-------|
| 2026-07-03 | Initial backlog: SMB research, K-beauty/Woo/Gmail, driver list, go/no-go |

---

*Living doc — add concepts here; move items to handoff or issues when scheduled.*
