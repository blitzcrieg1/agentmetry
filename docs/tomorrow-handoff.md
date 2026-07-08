# Tomorrow Handoff — 2026-07-07 session

Read this first when continuing. Email spec: [fable-5-email-autopilot.md](./fable-5-email-autopilot.md). Round 5 verdict: **ritual over code** — see [glm-52-round5-implementation-handoff-prompt.md](./glm-52-round5-implementation-handoff-prompt.md).

---

## Session snapshot (2026-07-07 evening)

### Shipped & pushed (`49fc7c9` on `master`)

- **Compliance Trust-Kit** — `docs/compliance/` (AI Act checklist, ISO mapping, incident template, data residency)
- **Evidence export v1.1** — approval signature, SOP hash, provider metadata, drivers snapshot
- **SOP injection** — `sop_paths` in skill YAML; `customer_reply` loads reply SOP + client note
- **PDF/DOCX trigger** — `inbox-document-summarize.yaml` → `doc_summarize`
- **Stale-loop auto-archive** — terminal loops >7d → `30-Archive/active-loops/` on boot
- **Phase 4-E shadow** — `gmail.send_draft` disabled unless `BLACKBOX_GMAIL_SEND_ENABLED=1`
- **Portable drivers** — `{PYTHON}`, `{ORCHESTRATOR_ROOT}`, `{VAULT_PATH}` tokens + `blackbox doctor --fix`
- **Dashboard** — approval keyboard: `a` / `Shift+a` / `r`
- **GOALS.md** — Daily Stack + success sentence
- **README** — updated for dogfood stack
- **Tests:** ~220 passed

### Tonight — project started (local)

| Item | Status |
|------|--------|
| `blackbox doctor` | All green after vault path fix |
| `blackbox start` | Running — http://127.0.0.1:8000 |
| Dashboard | Built (`npm run build`) + served on `:8000` |
| Vault path | `.env` → `BLACKBOX_VAULT_PATH=C:/Users/spiro/Projects/agentic-os/vault` (**absolute** — do not revert to `../../vault`) |
| Gmail driver | **enabled locally** in `drivers.json` — **do not commit** |
| Gmail mounted | `list_threads`, `get_thread`, `create_draft`, `send_draft` (shadow) |
| `pypdf` + `python-docx` | Installed in venv |
| Stale loops / recovery | **0** — clean board |
| T0 logged | `vault/.system/run-log.md` — Week 1 dogfood started |
| **`customer_reply` on real thread** | **NOT YET — #1 priority tomorrow** |

### GLM Round 5 verdict (adopted)

- **Mixed sprint** — cockpit built, plane not flown
- **Week 1 only:** inbox brief → one real `customer_reply` → approve → Gmail draft → manual send
- **No new code** until Week 4 gate unless dogfood hits a blocker
- **Compliance** — trust signal in demos, not primary pitch
- **Defer** `client_dossier_update` skill until Week 4+ (use doc finalize link instead)

---

## Tomorrow morning — start here (15 min)

1. `scripts\blackbox.bat status` — expect **ok**, gmail mounted, 0 pending if clean shutdown
2. If not running: `scripts\blackbox.bat start` → open http://127.0.0.1:8000
3. **First real run:** Gmail → copy thread ID → dashboard → **`customer_reply`** → approve (`a`) → check **Gmail Drafts** → send manually
4. Optional 08:00: confirm `gmail-morning-brief` trigger enabled in `vault/.system/trigger-rules/`
5. `scripts\blackbox.bat stats --days 7`

### Week 1 success metric

**1 real draft created and manually sent.** Nothing else counts.

### Kill signal (Week 1)

`customer_reply` fails to load SOP/thread — debug only, no new features.

---

## Operator state (local — never commit)

| Item | Location |
|------|----------|
| Secrets | `apps/orchestrator/.env` |
| Gmail OAuth token | Windows Credential Manager (`blackbox-gmail`) |
| Gmail enabled | `vault/.system/drivers.json` → `"gmail".enabled: true` |
| SOP to edit | `vault/10-SOPs/client-reply.md` |
| Goals / Daily Stack | `vault/.system/GOALS.md` |

---

## Dogfood gate (unchanged)

4 green weeks · ≥3 hrs/week saved · 3+ skills/week · approvals resolved · zero orphans Monday.

Until then: **no** send-after-approve, Telegram, new skills, kernel changes, compliance GTM.

---

## Key commands

```powershell
scripts\blackbox.bat start
scripts\blackbox.bat status
scripts\blackbox.bat doctor
scripts\blackbox.bat stats --days 7
scripts\blackbox.bat recovery
blackbox export --evidence --from 2026-07-01 --to 2026-07-07
```

Rebuild dashboard after UI changes: `cd apps\dashboard && set NEXT_PUBLIC_SAME_ORIGIN=true && npm run build` then `blackbox stop && blackbox start`.

---

## Key paths

| What | Where |
|------|--------|
| Handoff (this file) | `docs/tomorrow-handoff.md` |
| Email spec | `docs/fable-5-email-autopilot.md` |
| Compliance Trust-Kit | `docs/compliance/README.md` |
| Round 5 research prompt | `docs/glm-52-round5-implementation-handoff-prompt.md` |
| Email skills | `gmail_inbox_brief`, `customer_reply` |
| Client reply SOP | `vault/10-SOPs/client-reply.md` |

---

## Resume prompt for Cursor

> Continue BLACKBOX **Week 1 dogfood**. Stack is running at :8000; gmail mounted locally; vault path fixed; commit `49fc7c9` pushed. **Next: first real `customer_reply` → approve → Gmail draft → manual send.** Ritual over code — no new features. See `docs/tomorrow-handoff.md`.

---

*Prior: `49fc7c9` dogfood stack · `ef4216c` shared memory + docs driver · `d56fdb6` email_reply graph*
