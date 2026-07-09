# Fable 7 — Progress rating refresh (post-dogfood)

**Use:** Copy the fenced block into Claude Fable (**Opus 4.7** — read-only). Run **after Week 1–4 dogfood** or when operator stats materially change. Do **not** run if Fable 6 (`docs/fable-6-benchmark-review-2026-07.md`) is still current and edit-log has not grown.

**Prior:** [Fable 6 benchmark](./fable-6-benchmark-review-2026-07.md) · [Dogfood scorecard](./dogfood-scorecard-v1.md)

---

```
# BLACKBOX — Fable 7: Progress rating & world-class comparison (refresh)

You are an **independent product architect**. **Assessment only — no code**, unless you find a critical security/data-loss bug.

## Why this session exists
Fable 6 (2026-07-09) rated BLACKBOX and benchmarked vs world-class projects. The operator wants an **updated rating** with **real dogfood evidence** — not a repeat of kernel architecture review.

## Repo
- **GitHub:** agentic-os · branch `master` · head `[OPERATOR: paste git rev-parse --short HEAD]`
- **Baseline report:** `docs/fable-6-benchmark-review-2026-07.md` (July audit → 2026-07-09 delta)
- **Tests:** `cd apps/orchestrator && python -m pytest -q` — report count; note if operator machine differs from CI

## Operator must paste BEFORE you score (mandatory)
Paste these verbatim or say "not available":
1. Output of `scripts\blackbox.bat stats --days 7` (or 28 if Week 4)
2. Edit-log row count: `(Get-Content vault\.system\feedback\edit-log.jsonl | Measure-Object -Line).Lines`
3. Count of files in `vault/10-SOPs/Learnings/` (if any)
4. Green/red weeks claimed from `vault/10-SOPs/os-log.md`
5. What is **proven live since Fable 6** (sop_drift_review? ingress? Gmail brief?)

**If operator pastes nothing:** score habit rows as ❌ and say "insufficient behavioral evidence — do not inflate product scores."

## Read only (closed list — no repo crawl)
1. `.cursor/rules/blackbox-handoff.mdc`
2. `docs/fable-6-benchmark-review-2026-07.md` — your baseline; update don't duplicate
3. `docs/dogfood-scorecard-v1.md`
4. `docs/tomorrow-handoff.md`
5. Operator paste block above
6. Optional if habit claims reference them:
   - `vault/.system/feedback/edit-log.jsonl` (row count + sample themes only — do not dump full PII)
   - `vault/10-SOPs/os-log.md`

## Settled identity (do not reopen)
Draft-only inbox autopilot · user-owned markdown ledger · forced approval gate · flywheel (edit→drift→SOP patch) · ingress over driver zoo · 4-week gate before send-after-approve · habit enemy = Gemini-in-Gmail

---

## DELIVERABLE: `docs/fable-7-progress-rating-YYYY-MM-DD.md`

### 1. One-paragraph "where we are now"
Plain language for the operator. Code vs habit split.

### 2. Master rating table (0–100 each + letter grade)

| Dimension | Score | Grade | vs Fable 6 Δ | One-line evidence |
|-----------|-------|-------|--------------|-------------------|
| **Kernel / runtime** (scheduler, bus, IVT, MCP, recovery) | | | | |
| **Product vision fit** (governed vault in→approve→archive) | | | | |
| **Shippable product** (paying stranger could run it) | | | | |
| **Habit / dogfood proof** | | | | |
| **Flywheel loop** (capture→drift→patch) | | | | |
| **SMB UX** (Business Mode, not dev mode) | | | | |
| **Integrations** (Gmail + ingress maturity) | | | | |
| **Governance & trust** (audit, compliance, EU story) | | | | |
| **Overall BLACKBOX** (weighted: habit 30%, product 25%, kernel 15%, shippable 15%, diff 15%) | | | | |

Use **letter grades** A/B/C/D/F with clear rubric footnote.

### 3. World-class comparison (update Fable 6 §2)

Pick **6 references** minimum: **Gemini-in-Gmail**, **Dust.tt**, **n8n**, **LangGraph+LangSmith**, **Superhuman**, plus one of **Harvey / Intercom Fin / Rewind**.

For each: **BLACKBOX wins / ties / loses** on:
- TTFV · GOV · MEM · INST · INTG · OBS · REL · ECON

End with: **"Closest comp"** + **"Unfair advantage"** + **"Unfixable disadvantage"** (one sentence each).

### 4. Tier placement (honest)

Place BLACKBOX on a 5-tier ladder:
1. **Research / kernel demo**
2. **Solo operator daily driver (technical)**
3. **SMB-ready product (non-dev can adopt)**
4. **Category leader in a wedge**
5. **World-class platform**

State current tier + what evidence moves it one tier.

### 5. Go/no-go checklist (5 criteria) — X/5 with delta from Fable 6's 3.5/5

### 6. Advice (max 10 bullets)
- **Operator** (5) — ritual only if build freeze still active
- **Cursor** (3) — only if dogfood proved a blocker
- **Do not do** (2)

### 7. September finish line — still valid or revise?

One paragraph. Measurable by Sep 30.

---

## Rules
- Cite paths and operator paste as evidence
- Do not re-score kernel above ~85 unless new kernel work shipped
- **Habit row cannot exceed 60/100 until ≥2 green weeks logged in os-log**
- Do not commit to git
- End with ---CURSOR-HANDOFF--- (doc sync to repo only)

---CURSOR-HANDOFF---
## Continue in Cursor

**Fable completed:** [one sentence]

### Paste this as your first Cursor message:
```
Sync docs/fable-7-progress-rating-[date].md into repo.
Update docs/tomorrow-handoff.md delta table and resume prompt.
Do not commit unless operator asks.
```

### Operator steps:
- [ ] Paste stats + edit-log count next time before running Fable 7

**If blocked:** [note]
---END-CURSOR-HANDOFF---
```

---

## When to run Fable 7 vs skip

| Situation | Action |
|-----------|--------|
| Edit-log still 1 row, no os-log | **Skip** — use Fable 6 + dogfood scorecard; go dogfood |
| End of Week 1 with stats pasted | **Run Fable 7 (4.7)** |
| Week 4 gate review | **Run Fable 7 (4.7)** with `--days 28` stats |
| Want another architecture essay | **Skip** — nothing new to learn |

---

*Fable 7 prompt · 2026-07-09 · baseline Fable 6 @ a156e2a*
