# Tomorrow Handoff — 2026-07-03 session

Read this first when continuing work. Detailed specs live in linked docs.

---

## Session snapshot (what happened today)

### Live system
- **BLACKBOX running:** `scripts\blackbox.bat start` → `:8000`
- **Model:** `gemini-2.5-flash-lite` (paid tier in `.env`)
- **Budget config:** 100000/day, 0.2s pacing, reserve 50
- **Tests:** **111 passed** (full pytest)
- **Proven live:** Meeting Summarizer on `00-Inbox/sample-meeting-notes.md` → archive OK

### Code changes (session — verify `git status` before commit)
- **Gemini:** default `flash-lite`; count every API attempt; per-model budget ledger
- **Degraded:** auto-clear after retry window; manual runs proceed while degraded
- **RAG:** UTF-8/UTF-16 tolerant reads (`_read_vault_text`) — PowerShell `echo >` broke watcher
- **Docs added:** see index below
- **User `.env`:** updated model + paid-tier limits (gitignored)

### Bugs hit & fixed
| Issue | Cause | Fix |
|-------|-------|-----|
| Internal Server Error on summarize | UTF-16 `test.md` crashed RAG | Encoding helper + delete bad file |
| Sticky LLM degraded | Flag never cleared | `retry_elapsed()` + health check |
| Manual runs blocked when degraded | service.py rejected manual | Manual bypass; autonomous still defers |
| Dashboard 17/20 vs Google 46/20 | Only counted HTTP 200 | Count every attempt |
| Gemini 429 on free tier | 5 RPM / 20 RPD | Switched model + paid tier |

### Do not repeat
- Windows: use `Set-Content ... -Encoding utf8` not `echo > file`
- Only one server: `blackbox start` — not parallel `uvicorn --reload`

---

## Product thinking captured today

### Positioning (honest)
- **Not:** generic agentic OS, ChatGPT replacement, enterprise platform
- **Is:** governed local runtime for **document-heavy micro-business** — vault in, approve, archive out
- **Kernel ~75%** of blueprint · **Product ~40%** of something strangers pay for
- **Great at:** personal tool + niche SMB if one vertical ships (Gmail + plugin)

### vs ChatGPT
- Chat = one-off; BLACKBOX = triggers + ledger + gate + repeat skills
- Real agent tasks (search, send email, Woo) need **drivers** — not built yet

### K-beauty e-shop (Greece → EU, Woo + Gmail)
- **Tier S vertical #1** — supplier research, support replies, product copy
- **Phase A now:** paste email → Inbox → triage/summarize
- **Phase B:** gmail + woocommerce MCP + `customer_reply` / `supplier_outreach`
- Vault layout in `future-concepts.md` §3.2

### Other Tier S verticals (expansion)
1. Professional services agencies — **works today**, best zero-driver pilot
2. Solo consultants — Obsidian crowd, 9% admin time (EU)
3. Import/wholesale (general)
4. Grant/nonprofit EU
5. Boutique recruiting

Full ranking: `vertical-opportunities.md`

### Future implementation backlog
All deferred until **go/no-go** in `future-concepts.md` §7:
- Obsidian plugin v0 (P0)
- Crash recovery UX (P0)
- Gmail, search, Woo drivers (P1)
- Sandbox Tier 1 (P1)
- Vertical skill packs

---

## Doc index (ideas preserved)

| File | Contents |
|------|----------|
| [implementation-guide.md](./implementation-guide.md) | Personal/SMB rollout, folders, phases |
| [smb-pain-research.md](./smb-pain-research.md) | 2026 survey pains × BLACKBOX fit |
| [future-concepts.md](./future-concepts.md) | Drivers, skills, Woo/Gmail, K-beauty, go/no-go |
| [vertical-opportunities.md](./vertical-opportunities.md) | Tier S/A verticals, geography, top 10 |
| **this file** | Session state + tomorrow picks |

---

## Suggested priorities for tomorrow

Pick **one** engineering + **one** product track:

### Engineering (if coding)
1. Obsidian plugin v0 spec or spike
2. OR `docs/honest-assessment.md` → save yesterday's review (optional)
3. OR start Gmail driver scaffold (read-only first)
4. Commit session changes if user asks (not committed today)

### Product (if thinking / outreach)
1. Pick pilot vertical: **agency** (easiest) vs **K-beauty contact** (highest upside)
2. Draft 30-day pilot checklist for one shop
3. Fable token-light prompt if Claude quota back — plugin or Gmail only, skip kernel

### Quick verify (2 min)
```powershell
scripts\blackbox.bat status
# Expect: ok, gemini-2.5-flash-lite, budget N/100000
```

---

## Open questions (no decision yet)
- Open repo or stay private?
- First paid pilot: agency vs K-beauty?
- Save honest assessment as doc?
- Wire logo into dashboard (user liked first cyan HUD logo — not done)

---

## One-line north star (reuse in pitches)

> **Reads your business notes and email, drafts the reply or outreach, never sends without your OK — filed in Obsidian.**

---

*Session end: 2026-07-03 ~23:55 local. User: solo dev, Greece, Windows, paid Gemini.*
