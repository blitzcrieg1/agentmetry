---
type: system-context
updated: 2026-07-07
---
# Current Goals

1. **Dogfood email autopilot** — 3+ `customer_reply` approvals per week on real Gmail threads
2. **Zero orphan loops** — every Monday, `blackbox recovery` shows nothing stale
3. **Prove the runtime** — `blackbox stats --days 7` shows 3+ distinct skills/week before adding drivers

# Active Constraints

- Gmail: **draft-only** — no send-after-approve until Phase 4-E unlock
- Telegram: disabled — approvals via dashboard or Obsidian plugin
- Budget: Gemini Flash with interactive reserve for manual runs
- Kill gate: **4 green dogfood weeks** before new drivers or kernel changes

# Success Metrics (weekly)

| Metric | Target |
|--------|--------|
| Skills executed | ≥ 3 distinct |
| Approvals resolved | ≥ 1 |
| Orphan loops | 0 |
| Evidence export | `blackbox export --evidence` once/month |
