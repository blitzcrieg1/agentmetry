# Tomorrow Handoff — 2026-07-06 session

Read this first when continuing. Full email spec: [fable-5-email-autopilot.md](./fable-5-email-autopilot.md).

---

## Session snapshot

### Shipped & pushed (`d56fdb6` on `master`)
- **`email_reply` graph** — classify → SOP load → replan for `customer_reply`
- **Dashboard refresh** — vault constellation (idle), pipeline overlay (runs), 3-step gmail brief viz, brand logo
- **Gmail `--auth`** loads `apps/orchestrator/.env` automatically
- **`GET /api/v1/vault/active-loops`** for live loop nodes
- **README hero** + `docs/assets/blackbox-hero.png`, `apps/dashboard/public/blackbox-logo.png`
- **Fable 5 spec** + `vault/10-SOPs/client-reply.md`
- **Tests:** ~198 passed (email_reply + existing suite)

### Operator state (YOU — local, not in repo)
| Item | Status |
|------|--------|
| Gmail OAuth | Done — token in Windows Credential Manager (`blackbox-gmail`) |
| `GMAIL_*` in `.env` | Set |
| `drivers.json` gmail `enabled: true` | **Local only** — intentionally not committed |
| First `gmail_inbox_brief` | Ran successfully — archive `30-Archive/2026-07-06-195336-gmail_inbox_brief-4962df6a.md` |
| `customer_reply` on real thread | **Not yet** |
| Telegram | **Do not enable** — use dashboard/Obsidian for approvals |

### Phase 1 shipped (uncommitted): shared memory + CI governance
- `vault/.system/GOALS.md` + `AGENTS.md` — operator-editable goals/personas injected into every skill run
- `core/memory/fts_index.py` — SQLite FTS5 keyword index over vault markdown (startup + watcher upsert)
- `_fetch_skill_context()` — prepends GOALS/AGENTS + FTS hits before Qdrant RAG
- `scripts/lint_skills.py` — CI gate: skill YAML name/graph/tools invariants
- CI: skill lint + gitleaks secret scan added to `.github/workflows/ci.yml`

### New this session (uncommitted): docs driver + Document Summarizer
- `apps/orchestrator/tools/docs_server.py` — read-only PDF/DOCX/TXT/MD extraction, jailed to vault, ships **enabled** (local, no network, like margin)
- `vault/.system/skill-definitions/doc_summarize.yaml` — drop a PDF/DOCX in the vault, run `doc_summarize` with its vault-relative path as input → TL;DR / key points / action items archived
- `apps/orchestrator/tests/test_docs_driver.py` — jail, extraction, truncation tests
- **Before first use:** `cd apps\orchestrator && .venv\Scripts\pip install pypdf python-docx && pytest -q` then restart blackbox

### Tomorrow — start here (15 min)
1. `scripts\blackbox.bat start` → hard-refresh dashboard (`Ctrl+Shift+R`)
2. Run **`customer_reply`** on Ioannis thread (or any thread id from brief queue)
3. Approve in dashboard → check Gmail Drafts → send manually
4. `blackbox stats --days 7`

### Dogfood gate (before new features)
4 green weeks · 3+ skills/week · approvals resolved · zero orphans Monday.
Until then: **no** Telegram, Stripe, CRM, dashboard redesign, send-after-approve.

### Kill / defer list
- Telegram (built, disabled — ignore)
- `vault/.system/drivers.json` gmail flip — never commit
- Scratch prompts in `docs/*prompt*.md` — untracked, optional cleanup

### Key paths
| What | Where |
|------|--------|
| Email spec | `docs/fable-5-email-autopilot.md` |
| Gmail setup | `docs/gmail-driver.md` |
| Email skills | `gmail_inbox_brief`, `customer_reply` |
| Recovery | `blackbox recovery --resume <path>` |
| Evidence export | `blackbox export --evidence --from … --to …` |

### Resume prompt for Cursor
> Continue BLACKBOX email autopilot dogfood. Gmail OAuth done, inbox brief ran once. Next: first `customer_reply` → approve → Gmail draft. Kernel done — no rewrites. See `docs/tomorrow-handoff.md` and `docs/fable-5-email-autopilot.md`.

---

*Prior sessions: [fable-session-notes.md](./fable-session-notes.md) · [phase4-5-lived-in-plan.md](./phase4-5-lived-in-plan.md)*
