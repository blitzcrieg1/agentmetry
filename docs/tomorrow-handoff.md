# Tomorrow Handoff — 2026-07-09 session

Read this first when continuing. Full benchmark: [fable-6-benchmark-review-2026-07.md](./fable-6-benchmark-review-2026-07.md). Dogfood ritual: [dogfood-scorecard-v1.md](./dogfood-scorecard-v1.md).

---

## Session snapshot (2026-07-09)

### Shipped & pushed (prior session)

| Commit | Contents |
|--------|----------|
| **`1d1dede`** | Approval Inbox UI, vault-only `customer_reply`, flywheel capture, `sop_drift_review`, SOPs |
| **`a156e2a`** | Universal webhook ingress (`POST /api/v1/ingress`) |

### Fable 6 verdict (2026-07-09)

- **Code velocity exceptional; habit velocity ~zero.** Only behavioral evidence: **1 row** in `edit-log.jsonl`.
- **Flywheel 1/3 proven:** capture live; drift review + SOP patch never operator-run.
- **Benchmark:** Closest to Dust.tt; differentiated on forced approval gate, user-owned ledger, edit→SOP loop.
- **Real enemy:** Gemini-in-Gmail (convenience); win on ownership + compounding only.
- **Gate drift:** Telegram + 3D orbit shipped during gate — freeze now.
- **Build freeze** except test fixes (done locally, uncommitted).

### Delta scorecard (July audit → today)

| Layer | July | Today | Δ |
|-------|------|-------|---|
| A. AOS blueprint (kernel) | ~78 | **~82** | +4 |
| B. Product vision | ~62 | **~74** | +12 |
| C. Industry "agentic OS" | ~28 | **~34** | +6 |
| D. Shippable product | ~45 | **~52** | +7 |
| E. Go/no-go | 2.5/5 | **3.5/5** | +1 |
| F. Compounding intelligence (flywheel) | — | **~55** | new |
| G. SMB UX (Business Mode) | — | **~45** | new |
| H. Integration (ingress vs drivers) | — | **~40** | new |

### Proven live

| Item | Status |
|------|--------|
| Vault-only `customer_reply` → approve → archive | ✅ Live |
| Flywheel capture (edit on approve) | ✅ Live (1 row) |
| Approval Inbox (operator mode default) | ✅ Live |

### Built + tested — not operator-run

| Item | Status |
|------|--------|
| `sop_drift_review` | pytest only |
| Webhook ingress | pytest only |
| Gmail `create_draft` on approve | ❌ Not wired |

---

## Top 3 operator actions (this week — ritual over code)

1. **Daily ritual starting tomorrow:** one real email through `customer_reply`, edit honestly, approve. See [dogfood-scorecard-v1.md](./dogfood-scorecard-v1.md).
2. **Friday: first live `sop_drift_review`** — one edit-log row is enough; prove the approve-a-patch motion.
3. **Fire one real ingress call** (PowerShell block below) so integration row stops being theoretical.

Also: log the week in `vault/10-SOPs/os-log.md` with the six scorecard metrics — even if every number is red.

---

## Tomorrow morning — start here

1. `scripts\blackbox.bat status` → http://127.0.0.1:8000
2. Daily ritual (above) — **no feature work** unless red-week trigger fires
3. `scripts\blackbox.bat stats --days 7`

### Week 1 success metric

**≥5 drafts/week, ≥2 flywheel captures/week, ≥3 distinct skills.** Corrections captured matter more than drafts alone.

### Pre-authorized ops fix (red-week only)

If vault-only forces re-typing into Gmail for 2 weeks → wire `customer_reply` → `gmail.create_draft` (draft-only).

---

## Operator state (local — never commit)

| Item | Location |
|------|----------|
| Secrets | `apps/orchestrator/.env` (+ `BLACKBOX_API_KEY` for ingress) |
| Gmail enabled | `vault/.system/drivers.json` → `"gmail".enabled: true` |
| Flywheel edit log | `vault/.system/feedback/edit-log.jsonl` |
| Customer SOPs | `vault/10-SOPs/customer-tone.md`, `shipping-faq.md`, `returns-policy.md` |
| Vault path | `.env` → `BLACKBOX_VAULT_PATH=C:/Users/spiro/Projects/agentic-os/vault` |

---

## Key commands

```powershell
scripts\blackbox.bat start
scripts\blackbox.bat status
scripts\blackbox.bat doctor
scripts\blackbox.bat stats --days 7

# Ingress test (after BLACKBOX_API_KEY set)
$headers = @{
  "X-API-Key"      = $env:BLACKBOX_API_KEY
  "X-Target-Skill" = "customer_reply"
  "X-Source-Name"  = "woocommerce"
  "Content-Type"   = "application/json"
}
$body = '{"customer_email":"test@example.com","subject":"Where is my order?","body":"Order #1234 shipped 5 days ago, no tracking."}'
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/ingress" -Method POST -Headers $headers -Body $body
```

---

## Explicitly deferred (4 green weeks gate)

- Send-after-approve (`send_draft` live)
- New channels (Telegram freeze — no WhatsApp/Slack)
- Woo/CRM/calendar drivers
- Dashboard/3D polish
- Ingress idempotency (until real external source posts weekly)

---

## Resume prompt for Cursor

> Continue BLACKBOX dogfood Week 1+. Master at `a156e2a`. Fable 6 benchmark in `docs/fable-6-benchmark-review-2026-07.md`. Build freeze — ritual over code. Next: daily customer_reply + edit, Friday sop_drift_review, one ingress call. Go/no-go 3.5/5. Do not commit `.env`, gmail-enabled `drivers.json`, or `edit-log.jsonl`.

---

*Prior: Fable 6 benchmark · `a156e2a` ingress · `1d1dede` Approval Inbox + flywheel*
