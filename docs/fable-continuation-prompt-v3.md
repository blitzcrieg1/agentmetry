# Fable continuation prompt — Phase 3 (instrument & dogfood)

**Model:** Claude Opus 4.8  
**Context:** Post-audit (`docs/product-audit-2026-07.md`). Kernel is done; product-reality is not.

Copy the fenced block below into Claude.

---

```
# BLACKBOX Phase 3 — Stop building the OS; measure usage; one live driver

You are continuing **BLACKBOX** (Obsidian-Cortex Agentic OS) on branch `master` (head `21da830`+).

## Situation (read this first)

BLACKBOX is a **genuinely complete governed-agent kernel** wrapped around a product **not yet used in anger even once**. Every blueprint subsystem exists and is tested (scheduler, bus, IVT, drivers host, sandbox Tier 0+1, recovery, Obsidian plugin v0.1). **129 pytest**, CI green.

But **go/no-go §7** (`docs/future-concepts.md`) has **3/5 boxes checked**. The 2 unchecked boxes measure **reality, not code**:
- [ ] At least 3 production skills used weekly (dogfooding)
- [ ] Gmail or search driver MVP **proven live** (not just mocked in CI)
- [ ] 30-day pilot without kernel fixes

**Critical gap:** The dogfooding criterion is **unmeasurable today**. `execution_logs` has `skill_name`; `runs.jsonl` records every run; `telemetry.get_stats()` returns globals + last-10 only — **no per-skill weekly aggregation**. The operator cannot answer "did I use 3 skills this week?" without hand-parsing JSONL.

**The finish line is not more subsystems.** It is: **usage instrumentation → one live external driver → operator dogfoods for 4 weeks → then one outbound path.**

## Read before coding
1. `docs/product-audit-2026-07.md` — scorecard, finish line
2. `.cursor/rules/blackbox-handoff.mdc`
3. `core/telemetry/store.py` — `ExecutionLog`, `get_stats()` (lines 76–114)
4. `api/routes/runs.py` — JSONL tail + `summarize_runs()`
5. `core/notifiers/audit.py` — `runs.jsonl` path
6. `tools/search_server.py`, `vault/.system/drivers.json`, `supplier_research.yaml`
7. `core/execution/recovery.py:31-33` — resume NOT supported (known limit; do not fix in Phase 3)

## Environment
- Windows 11, local-first, solo dev, Greece/EU
- `cd apps/orchestrator && pip install -e ".[dev]" && pytest -q` — **129+ must stay green**
- `scripts\blackbox.bat start` → `:8000`
- **Do not commit** unless operator explicitly asks
- **No kernel work** — scheduler, IVT, bus, budget are done

---

## Phase 3 scope — IN ORDER (weeks 1–4)

Build **P3-A and P3-B only** in this session. P3-C is operator habit, not code.

### P3-A — Per-skill usage stats (HIGHEST PRIORITY — do first)

**Problem:** Go/no-go dogfooding gate is unmeasurable.

**Implement:**

1. **`GET /api/v1/runs/stats?window_days=7`** (add to `api/routes/runs.py` or new route)
   - Aggregate from **`execution_logs`** (SQLite) — preferred source; has `skill_name`, `created_at`, `status`
   - Fallback or merge with `runs.jsonl` if needed for runs missing from DB
   - Response shape:
     ```json
     {
       "window_days": 7,
       "since": "ISO8601",
       "by_skill": [
         { "skill": "inbox_triage", "runs": 4, "completed": 3, "last_run": "..." }
       ],
       "distinct_skills": 5,
       "go_no_go": {
         "dogfooding_met": true,
         "threshold": 3,
         "message": "5 distinct skills used in last 7 days"
       }
     }
     ```
   - **`dogfooding_met`:** `distinct_skills >= 3` counting skills with ≥1 completed/approved run in window

2. **Extend `TelemetryStore`** — add `get_skill_stats(window_days: int)` with SQL `GROUP BY skill_name` + date filter. Do not load all rows into Python on large DBs.

3. **Dashboard tile** — small panel on telemetry page (`apps/dashboard/components/telemetry/`)
   - "This week: N skills" with list; green if ≥3
   - Poll `/api/v1/runs/stats?window_days=7`

4. **Optional CLI:** `blackbox stats [--days 7]` — print same summary for terminal

5. **Tests:** `tests/test_run_stats.py` — seed ExecutionLog rows, assert grouping + go_no_go flag

**Acceptance:** Operator can open dashboard or curl one URL and see whether go/no-go dogfooding is met.

**Out of scope:** Fancy charts, export CSV, multi-user.

---

### P3-B — Search driver live once (second priority)

**Problem:** `supplier_research` declares `search.web` but driver ships `enabled: false`, no key; 5 tests are HTTP-mocked only. Go/no-go "driver stable" needs **real bytes moved once**.

**Implement:**

1. **`@pytest.mark.live`** opt-in test in `tests/test_search_driver.py` (or `tests/test_live_search.py`)
   - Skip unless `SERPER_API_KEY` or `TAVILY_API_KEY` in env AND `BLACKBOX_LIVE_TESTS=1`
   - Mount search driver, call `search.web` with query `"test"`, assert non-empty results
   - Document in test docstring + `apps/orchestrator/README` or handoff

2. **`docs/search-driver-live.md`** (short) — operator steps:
   - Add key to driver env / `.env`
   - Set `"enabled": true` for search in `vault/.system/drivers.json`
   - `POST /api/v1/drivers/remount` or restart
   - Run `supplier_research` from dashboard or Obsidian
   - Archive appears in `30-Archive/`

3. **Do NOT** enable search by default in committed `drivers.json` — keep `enabled: false`; doc only.

4. **Health endpoint:** confirm `/api/v1/health` shows search driver state when enabled (may already work — verify, fix if broken)

**Acceptance:** Mocked CI unchanged (129 tests). Live test skips cleanly without key. Doc lets operator prove E2E in 10 minutes.

**Out of scope:** Gmail, Woo, auto-enable search in repo.

---

### P3-C — Operator dogfooding (NOT YOUR JOB TO CODE)

Document in handoff update only:
- Use ≥3 skills weekly for 4 weeks on **real notes** (not samples)
- Suggested trio: `inbox_triage`, `summarize_note`, `follow_up_draft` or `client_brief`
- Check weekly: `GET /api/v1/runs/stats?window_days=7`

---

## Explicitly DO NOT build this session

| Forbidden | Why |
|-----------|-----|
| Gmail / Woo / calendar / browser drivers | Phase 4, only after P3-C dogfooding holds |
| Checkpoint resume | Phase 4 (`recovery.py` dismiss-only today — document, don't fix yet) |
| New skills | 9 skills > 0 used; breadth is not the constraint |
| Kernel changes | Marginal return ~zero |
| Woo/Gmail-send | Backlog stays triaged per go/no-go |

---

## Known limits to document (don't gloss)

- **Crash recovery dismisses; does not resume** — orphaned mid-run = mark_failed/dismiss; checkpoint exists but no re-entry (`recovery.py` docstring)
- **`supplier_research` dead on fresh checkout** until operator enables search + key
- **Outbound wedge #2** = drafts only; no send path

---

## Deliverables

1. P3-A code + tests (stats endpoint, store method, dashboard tile, optional CLI)
2. P3-B live test marker + operator doc
3. Update `.cursor/rules/blackbox-handoff.mdc` — Phase 3 shipped, new API route, go/no-go instrumentation
4. Append `docs/fable-session-notes.md` — verify commands
5. **Do not commit** unless operator asks

## Verify
```powershell
cd apps\orchestrator && pytest -q
cd apps\dashboard && npm run build
scripts\blackbox.bat start
curl http://127.0.0.1:8000/api/v1/runs/stats?window_days=7
# Optional live:
# $env:BLACKBOX_LIVE_TESTS=1; $env:SERPER_API_KEY="..."; pytest -m live -q
```

## One sentence for this session
**Ship per-skill weekly stats so the dogfooding gate is measurable; add opt-in live search proof; then stop — the operator dogfoods for a month before any Gmail work.**

Start with **P3-A**. Proceed to P3-B when P3-A acceptance passes. Report blockers with file:line evidence.
```

---

## After Phase 3 (for operator — do not build yet)

| Phase | When | What |
|-------|------|------|
| **Phase 4** | Dogfooding holds 4 weeks | Gmail draft-only driver; then checkpoint resume |
| **Phase 5** | Phase 4 stable | 30-day agency pilot (zero new drivers); K-beauty later |

---

*Prior prompts: [v1](./fable-continuation-prompt.md) · [v2](./fable-continuation-prompt-v2.md) · [audit](./fable-audit-prompt.md)*
