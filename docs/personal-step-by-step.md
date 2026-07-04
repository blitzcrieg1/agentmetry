# BLACKBOX — personal step-by-step (what you can do today)

**Repo:** `master` @ K-beauty v1 · **159 tests** · Obsidian vault = `vault/`

Use this as a checklist. Each section builds on the previous one.

---

## Part 0 — One-time setup (30 minutes)

### Step 0.1 — API key

1. Copy `apps/orchestrator/.env.example` → `apps/orchestrator/.env` (if not done).
2. Set `GEMINI_API_KEY=...` (Google AI Studio).
3. Optional: set `BLACKBOX_API_KEY` if you locked down the API.

### Step 0.2 — Python + tests (sanity check)

```powershell
cd C:\Users\spiro\Projects\agentic-os\apps\orchestrator
.\.venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Expect: **159 passed**, 1 skipped.

### Step 0.3 — Obsidian plugin

```powershell
cd C:\Users\spiro\Projects\agentic-os\apps\obsidian-plugin
npm install
npm run deploy
```

In Obsidian:

1. **Open folder as vault:** `C:\Users\spiro\Projects\agentic-os\vault`
2. **Settings → Community plugins** → disable Safe mode → enable **BLACKBOX**
3. **Settings → BLACKBOX** → Orchestrator URL: `http://127.0.0.1:8000`

### Step 0.4 — Optional dashboard UI (single port)

```powershell
cd C:\Users\spiro\Projects\agentic-os
scripts\serve.bat
```

Opens `http://127.0.0.1:8000` with dashboard + API. Re-run after dashboard code changes.

For daily use, **`scripts\blackbox.bat start`** is enough if you live in Obsidian.

### Step 0.5 — Autostart (optional)

```powershell
scripts\blackbox.bat install
```

BLACKBOX starts when you log in to Windows.

---

## Part 1 — Boot the OS (every day, 1 minute)

### Step 1.1 — Start

```powershell
cd C:\Users\spiro\Projects\agentic-os
scripts\blackbox.bat start
scripts\blackbox.bat status
```

Healthy status shows Gemini up, note count, budget.

### Step 1.2 — Open Obsidian

Vault folder: `vault/`. Status bar shows `BB …` when a skill runs.

### Step 1.3 — Check the week (optional)

```powershell
scripts\blackbox.bat stats --days 7
```

Goal: **≥3 distinct skills/week** on real notes.

---

## Part 2 — General personal workflows (no K-beauty)

### Workflow A — Drop and forget (automatic)

1. Create a **real** note in `vault/00-Inbox/`, e.g. `client-call.md`.
2. Save the file.
3. Wait ~30 seconds — trigger runs **`summarize_note`**.
4. Open **`vault/30-Archive/`** — find the new summary.

**You did:** write once; the OS processed and archived without opening chat.

---

### Workflow B — Triage a messy note (manual)

1. Open any note in Obsidian.
2. `Ctrl+P` → **BLACKBOX: Triage active note**
3. Approve if prompted.
4. Read output in **`30-Archive/`** (category, urgency, suggested action).

---

### Workflow C — Follow-up email draft (approval-gated)

1. Write a short note in `00-Inbox/` (who, context, promise, tone).
2. `Ctrl+P` → **BLACKBOX: Run skill on active note…** → **`follow_up_draft`**
3. `Ctrl+P` → **BLACKBOX: Review pending approvals** → approve or reject.
4. Copy draft from **`30-Archive/`** into Gmail yourself (send not automated yet).

---

### Workflow D — Meeting → actions

1. Paste meeting notes into `00-Inbox/` (or tag `#meeting` for meeting trigger).
2. Run **`summarize_meeting`** from skill picker, or let auto-trigger run.
3. Archive has decisions + action items.

---

### Workflow E — Weekly review

1. Friday: `Ctrl+P` → skill picker → **`weekly_review`**
2. Input can be empty or “this week” — skill reads vault context.
3. Review archive output; adjust priorities in your own project notes.

---

### Workflow F — Approvals from dashboard

1. Open `http://127.0.0.1:8000`
2. Right panel → **Pending approvals** (batch checkboxes)
3. Or Obsidian → **Approve all pending** / **Reject all pending**

---

## Part 3 — K-beauty sourcing (your vertical)

Full doc: [`kbeauty-sourcing-os.md`](./kbeauty-sourcing-os.md)

### Step 3.1 — Try the shipped sample (5 minutes)

1. `scripts\blackbox.bat start`
2. Obsidian → open **`10-Products/sample-snail-essence.md`**
3. `Ctrl+P` → **Run skill on active note…** → **`margin_compare`**
4. Approve if prompted.
5. Open **`30-Archive/`** — expect ~**60% net margin**, recommendation **strong**.

**You learned:** margin is **deterministic** from frontmatter — not LLM guessing.

---

### Step 3.2 — Enable search (once, ~10 minutes)

Only needed for **`kbeauty_trend_research`** and **`supplier_research`**.

1. Get a free key: [serper.dev](https://serper.dev) or [tavily.com](https://tavily.com)
2. Add to `apps/orchestrator/.env`:
   ```
   SERPER_API_KEY=your_key_here
   ```
3. Edit **`vault/.system/drivers.json`** — set `"search"` → `"enabled": true`
   - **Do not commit** this flip.
4. Restart or remount:
   ```powershell
   scripts\blackbox.bat stop
   scripts\blackbox.bat start
   ```
5. Confirm: `scripts\blackbox.bat status` or dashboard → drivers show search mounted.

(`margin` driver ships **enabled** — no key needed.)

---

### Step 3.3 — Research trends + wholesalers

1. `Ctrl+P` → skill picker → **`kbeauty_trend_research`**
2. Input example: `korean snail mucin serum Greece EU wholesale`
3. Approve the brief when prompted.
4. Read **`30-Archive/`**:
   - Trend signals (URLs cited)
   - Wholesaler leads (verify yourself)
   - Retail signals marked **unverified**

**You do next:** click 3 URLs; ignore anything without a real price on the page.

---

### Step 3.4 — Capture a supplier quote

1. Paste wholesaler email/PDF text into `00-Inbox/quote-vendor-x.md`
2. Run **`supplier_intake`** on that note.
3. Copy structured fields into **`10-Suppliers/_template-supplier.md`** (new file per vendor).

Set `verified: true` only after you confirmed MOQ, COA, incoterms directly.

---

### Step 3.5 — Create your real product note

1. Duplicate **`10-Products/_template-product.md`** → e.g. `10-Products/my-serum.md`
2. Fill frontmatter from **real** quote + **your** retail check:

   | Field | Source |
   |-------|--------|
   | `wholesale_unit_price` | Supplier quote |
   | `moq` | Supplier quote |
   | `shipping_per_unit` | Your freight estimate |
   | `retail_price` | Greek/EU shop you checked manually |
   | `vat_pct` | 24 (Greece) or your rate |
   | `fees_pct` | Payment gateway ~2–3% |

   Blank = missing. Never zero unless truly zero.

3. Run **`margin_compare`** on `10-Products/my-serum.md`
4. Read recommendation + **Missing data** section before ordering stock.

---

### Step 3.6 — Full K-beauty loop (repeat per SKU)

```
kbeauty_trend_research  →  leads in 30-Archive
        ↓
Contact wholesaler (you)  →  paste quote → supplier_intake
        ↓
10-Products/my-sku.md     →  real numbers in frontmatter
        ↓
margin_compare            →  go / no-go margin
        ↓
follow_up_draft           →  RFQ or follow-up email draft (vault only)
```

---

## Part 4 — Gmail (optional, draft-only)

Doc: [`gmail-driver.md`](./gmail-driver.md)

1. Google Cloud → Gmail API → OAuth desktop client
2. `python apps/orchestrator/tools/gmail_server.py --auth` (per doc)
3. Enable `gmail` in `drivers.json` (`enabled: true`, local only)
4. Restart blackbox

**Still no send** until a later phase — read inbox + create drafts only.

---

## Part 5 — Folder law (keep the OS sane)

| Folder | Your rule |
|--------|-----------|
| `00-Inbox/` | **Only entry point** — calls, quotes, ideas, paste-from-email |
| `10-Products/` | One note per SKU you might import |
| `10-Suppliers/` | One note per vendor |
| `10-SOPs/` | How you calculate margin, write emails, triage |
| `20-Active-Loops/` | Don't edit — running jobs |
| `30-Archive/` | **Read outputs here** |

---

## Part 6 — What to do this week (7-day plan)

| Day | Action | Success |
|-----|--------|---------|
| **Mon** | Part 1 boot + Part 3.1 sample margin | Archive shows ~60% margin |
| **Tue** | Part 3.2 enable search + one trend research | Wholesaler leads in archive |
| **Wed** | Part 2 Workflow A — real inbox drop | Auto-summary appears |
| **Thu** | Part 3.5 — one **your** product note + margin_compare | Real go/no-go number |
| **Fri** | Part 2 Workflow C — follow_up_draft on a real contact | Draft in archive, approved |
| **Sat** | `blackbox stats --days 7` | ≥3 skills used |
| **Sun** | Read `30-Archive/` — would you miss this if off? | Yes/no decision |

---

## Part 7 — Commands cheat sheet

```powershell
scripts\blackbox.bat start
scripts\blackbox.bat stop
scripts\blackbox.bat status
scripts\blackbox.bat stats --days 7
scripts\blackbox.bat logs -f
scripts\blackbox.bat backup
```

Obsidian: `Ctrl+P` → type **BLACKBOX**

---

## Part 8 — What's next (after this week)

| When | What |
|------|------|
| Margin loop feels useful | Enable Gmail → RFQ wholesalers (`gmail-driver.md`) |
| Dogfood holds 4 weeks | Fable: `supplier_outreach` skill |
| Crashes annoy you | Fable: checkpoint resume |
| Pilot customer appears | Installer + Woo read-only |

**Not next:** browser scraping, kernel rewrite, more skills for breadth.

---

## Quick troubleshooting

| Problem | Fix |
|---------|-----|
| Plugin “error” | `blackbox status` — is orchestrator up? |
| Skill does nothing | Check `20-Active-Loops/`; review pending approvals |
| Search skill fails | Enable search driver + `SERPER_API_KEY` in `.env` |
| Margin “missing data” | Fill required frontmatter — see `10-SOPs/kbeauty-margin.md` |
| Qdrant down | OK — keyword RAG fallback; optional Docker Qdrant later |

---

*Personal step-by-step v1 — 2026-07-04*
