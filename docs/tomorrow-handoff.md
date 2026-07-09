# Tomorrow Handoff — resume 2026-07-10

**Read this first.** Last session: **2026-07-09 late** — strategy debate complete, Path B locked, execution pack Cursor-cleared, pushed **`d3fc4b5`**.

| Link | Purpose |
|------|---------|
| [operator guide §4](./blackbox-operator-guide.md) | Day 1 ritual (do first if not done) |
| [execution pack §6](./blackbox-path-b-execution-pack-2026-07.md) | Week 2 Mon–Fri checklist |
| [profit research Part Q + S](./blackbox-agentic-os-profit-research-2026-07.md) | Action card + Round 6 fixes |
| [Week 2 Claude prompt](./fable-week2-operator-prompt.md) | Paste into Claude for kit/copy tasks |
| [dogfood scorecard](./dogfood-scorecard-v1.md) | Green week criteria |

**Strategy:** Path **B** — comms hero, doc tab 2, meeting Week 3 lane. **Debate closed** until Week 4 signal tally or €500 MRR.

---

## What we finished tonight (2026-07-09)

| Done | Detail |
|------|--------|
| Agentic OS debate | Parts **A–S** in profit research doc — Tier 1 runtime, profit paths, five surfaces, 2028 scenarios, Path B chosen |
| Execution pack | Loom script, landing copy, 3 starter kit outlines, signal log, EU one-pager, Week 2 calendar |
| Round 6 review | Part S — fixed Loom paths, FAQ boundary, trades SOP gaps, doc_summarize honesty (no approval gate) |
| Pushed | **`d3fc4b5`** — strategy + operator guide + execution pack + `.env.example` |
| Claude prompt | [`fable-week2-operator-prompt.md`](./fable-week2-operator-prompt.md) — tasks A–G for Bucket A writing |

**Not committed (local only):** `drivers.json` (gmail on), `edit-log.jsonl`, inbox scratch notes, GLM/fable scratch prompts.

---

## Tomorrow — start here (pick one track)

### Track 1 — Day 1 not done yet (priority)

1. `scripts\blackbox.bat start` → http://127.0.0.1:8000 · confirm **Live** pill
2. [operator guide §4](./blackbox-operator-guide.md): one real `customer_reply` → edit → approve
3. Create `vault/10-SOPs/os-log.md` row 1
4. **Plus:** one non-email skill (`summarize_meeting` or `doc_summarize`) on real work — Path B requirement
5. Create `vault/10-SOPs/signal-log.md` from [execution pack §4](./blackbox-path-b-execution-pack-2026-07.md)

### Track 2 — Day 1 already done → Week 2 Monday (execution pack §6)

1. Paste [fable-week2-operator-prompt.md](./fable-week2-operator-prompt.md) into Claude → **Task A** (trades starter kit full markdown)
2. Or write `vault-templates/trades/` yourself using pack §3.1
3. **No Bucket B code** unless a paying pilot blocks on Gmail Drafts

---

## Decisions locked (do not re-litigate)

| Decision | Value |
|----------|--------|
| Path | **B** — broadened horizontal |
| Marketing hero | Comms (`customer_reply`) |
| Demo tab 2 | Document intake (honest: auto-archive, no approval gate today) |
| Bucket B #1 | Week 4 tally: ≥2/3 on one surface → swap; tie → Gmail Drafts; then Stripe, then wizard |
| Compound bet | Vault + edit-log + HITL — never weaken for packaging |
| Y1 realistic ARR | €25–40K Path B band (Cursor-adjusted) |
| Success gate Month 6 | €500 MRR OR 3 paying pilots OR 2/3 screen-share wins across ≥2 surfaces |

---

## Repo truth reminders (from Part S)

- Dashboard: **The Armory · Desk** → skill card → **Task input** → **Execute**
- Edit-log: `vault/.system/feedback/edit-log.jsonl` (not vault root)
- Archive drafts: `30-Archive/drafts/`
- `customer_reply` hardcodes: `10-SOPs/customer-tone.md`, `shipping-faq.md`, `returns-policy.md`
- Trades kit **must** include shipping-faq + returns-policy (even trades-appropriate stubs)
- FAQ copy: vault local; task+SOP text → your LLM; Gmail API when Gmail skills used

---

## Fable 7 baseline (unchanged)

- **54/100 (D)** · habit **12/100** · build freeze until 4 green weeks
- **Moratorium:** no new Fable/strategy sessions until **Week 2 Friday** (14 os-log rows)
- Tests: ~238 passed, 1 skipped @ `bf7b717`+

---

## Operator state (local — never commit)

| Item | Location |
|------|----------|
| Secrets | `apps/orchestrator/.env` |
| Gmail enabled | `vault/.system/drivers.json` |
| Flywheel | `vault/.system/feedback/edit-log.jsonl` |
| Dogfood log | `vault/10-SOPs/os-log.md` (create Day 1) |
| Signal log | `vault/10-SOPs/signal-log.md` (create Week 2) |

---

## Resume prompt for Cursor

```
Continue BLACKBOX from docs/tomorrow-handoff.md. Master @ d3fc4b5.
Path B locked; debate closed until Week 4 tally. Round 6 clear — Week 2 shipping.
If Day 1 not done: operator guide §4 + os-log + one non-email skill first.
If Day 1 done: help write vault-templates/trades/ (Task A) or follow execution pack §6.
No Bucket B code unless paying pilot. Do not commit drivers.json, .env, edit-log.jsonl.
```

---

## Resume prompt for Claude

Paste [`fable-week2-operator-prompt.md`](./fable-week2-operator-prompt.md) — start with: *"Day 1 ritual done? Which task A–G first?"*

---

*Updated 2026-07-09 night · prior push `d3fc4b5` · next session: 2026-07-10*
