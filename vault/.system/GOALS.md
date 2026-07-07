---
type: system-context
updated: 2026-07-07
---
# Current Goals

## Success sentence (Mode A)

**Four consecutive green dogfood weeks, ≥3 hours/week saved, product success optional.**

## The Daily Stack (Mon–Fri)

| Time | Loop | Skill(s) | Trigger |
|------|------|----------|---------|
| **08:00** | Morning Brief | `gmail_inbox_brief` → triage | Cron (`gmail-morning-brief`) |
| **10:00–16:00** | Ingestion | `doc_summarize` on PDF/DOCX drop | Vault watch (`00-Inbox/*.{pdf,docx}`) |
| **14:00** | Response wave | `customer_reply` / follow-ups | Manual / plugin |
| **17:00** | Day-close | `summarize_meeting` / partial review | Manual |

## Weekly operator goals

1. **Dogfood email autopilot** — 3+ `customer_reply` approvals on real Gmail threads
2. **Zero orphan loops** — every Monday, `blackbox recovery` shows nothing stale
3. **Prove the runtime** — `blackbox stats --days 7` shows 3+ distinct skills/week before new drivers

# Active Constraints

- Gmail: **draft-only** — no send-after-approve until Phase 4-E unlock (4 green weeks)
- Telegram: disabled — approvals via dashboard or Obsidian plugin
- Budget: Gemini Flash with interactive reserve for manual runs; Ollama for sovereignty experiments
- Kill gate: **4 green dogfood weeks** before new drivers or kernel changes
- Compliance: Trust-Kit in `docs/compliance/` — alignment docs only, not legal advice

# Success Metrics (weekly)

| Metric | Target |
|--------|--------|
| Skills executed | ≥ 3 distinct |
| Approvals resolved | ≥ 1 |
| Orphan loops | 0 |
| Time saved (self-reported) | ≥ 45 min/week → 3 hrs by week 4 |
| Evidence export | `blackbox export --evidence` once/month |
