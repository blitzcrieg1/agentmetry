# Fable 7 — Progress rating & world-class comparison (refresh)

**Reviewer:** Fable (independent product architect) · **Date:** 2026-07-09 (evening — **same day as Fable 6**)
**Repo:** `master` @ `a156e2a` (unchanged since Fable 6) · working tree has Cursor's doc sync + two test fixes, uncommitted
**Tests:** `python -m pytest -q` → **238 passed, 1 failed, 1 skipped** — the 1 failure is `ModuleNotFoundError: No module named 'docx'` (missing optional `python-docx` on operator machine; environment, not code). **Both Fable 6 test defects are fixed** (gmail ships-disabled guard, sop_drift isolation) and now pass in the full suite.
**Operator paste:** none provided. Evidence gathered directly from the vault instead — and it confirms the paste would have been empty.
**Session type:** assessment only — no code written, nothing committed.

---

## 1. Where we are now (one paragraph)

The codebase is in its best state ever — 238 green tests, both reliability defects from this morning's review already fixed, the dogfood scorecard extracted and in place — and the behavioral evidence is exactly where it was this morning: **one** edit-log row, **zero** Learnings patches, **no** `os-log.md`, all three archived drafts timestamped July 8 evening. In other words: since Fable 6 was delivered roughly eight hours ago, the repo gained documentation and test fixes and the *habit* gained nothing, because no dogfood day has happened yet — which is fine (it's the same day) but means this session cannot honestly report progress on the only axis that's currently gated. Blunt meta-observation, since you asked for blunt: commissioning a second assessment hours after the first, before running a single ritual day, is itself a data point — assessment is starting to compete with dogfooding for the same scarce hours. The next number that matters is not in this document; it's tomorrow's first row in `os-log.md`.

**Insufficient behavioral evidence — habit rows scored on facts found, not inflated by product quality.**

---

## 2. Master rating table

Rubric: **A ≥ 85** (world-class for the stage) · **B 70–84** (strong, gaps known) · **C 55–69** (works, unproven) · **D 40–54** (built, not validated) · **F < 40** (absent/no evidence).

| Dimension | Score | Grade | vs Fable 6 Δ | One-line evidence |
|-----------|-------|-------|--------------|-------------------|
| **Kernel / runtime** | 83 | B | +1 | Same kernel @ `a156e2a`; both flaky-suite defects fixed (`tests/test_gmail_driver.py` +21/-4, `tests/test_sop_drift_review.py` +6) — suite now trustworthy on the operator machine, which is a real reliability gain; capped per rules (no new kernel work) |
| **Product vision fit** | 74 | B | 0 | Unchanged since this morning: vault→draft→forced approval→archive proven live 2026-07-08; nothing new shipped or run |
| **Shippable product** | 53 | D | +1 | `docs/dogfood-scorecard-v1.md` now exists as an onboarding-ish artifact; suite green modulo a missing optional dep (`python-docx`) that would bite a paying stranger on install — same dev-grade install wall |
| **Habit / dogfood proof** | 12 | F | new row | 1 edit-log row (unchanged), 3 drafts all from one evening (Jul 8, `30-Archive/drafts/`), `10-SOPs/Learnings/` = README only, **`os-log.md` does not exist**, 0 ritual days completed, 0 green weeks |
| **Flywheel loop** | 55 | C | 0 | Capture stage live (1 real row); `sop_drift_review` still never operator-run; patch stage never exercised — loop remains 1/3 proven, exactly as at Fable 6 |
| **SMB UX** | 45 | D | 0 | Approval Inbox live as default; start/status/doctor still CLI; drafts land in vault, not Gmail — untouched today |
| **Integrations** | 42 | D | +2 | Gmail driver guard test now correctly asserts committed state (local enable no longer reddens suite — removes a daily-use irritant); ingress still never fired live |
| **Governance & trust** | 70 | B | new row | Forced gate (`approval_threshold: 1.1`), outbox audit trail, compliance kit + evidence export, local-first EU story, secrets in keyring — strongest non-kernel dimension, but zero external validation |
| **Overall BLACKBOX** | **54** | **D** | — | Weighted: habit 30%×12 + product 25%×74 + kernel 15%×83 + shippable 15%×53 + differentiation 15%×65 ≈ **54** |

The overall D is not a product insult — it's the weighting doing its job. Habit is 30% of the grade and stands at 12/100. Two logged green weeks alone (habit → ~55, still under the 60 cap) would lift the overall to ~67 (C) with zero new code. **No commit can raise this grade. Only mornings can.**

---

## 3. World-class comparison (update of Fable 6 §2)

Dimensions: TTFV · GOV (governed outbound) · MEM (learns from edits) · INST (install) · INTG (integration surface) · OBS (audit) · REL (reliability) · ECON.

| Reference | BLACKBOX wins | Ties | Loses |
|---|---|---|---|
| **Gemini in Gmail** | GOV (forced gate vs none), MEM (owned edit-log vs opaque), OBS (ledger vs nothing) | ECON (BYOK ≈ bundled, both cheap) | **TTFV, INST** (zero-install, already at point of need — decisive), REL (Google SaaS) |
| **Dust.tt** | GOV (forced vs per-app), MEM (closed correction loop vs feedback), OBS (user-owned ledger) | ECON | TTFV, INST (managed SaaS), INTG (managed connectors) |
| **n8n** | GOV, MEM, OBS (n8n has none of the three) | REL (both 🟡 self-hosted) | **INTG** (1000+ nodes — unwinnable; ingress judo is the correct answer), TTFV, INST (cloud tier) |
| **LangGraph + LangSmith** | GOV, MEM, INST (BLACKBOX at least has an operator UI), ECON (it's your substrate, not a comp for buyers) | — | OBS (LangSmith traces richer), REL (battle-tested at scale) |
| **Superhuman AI** | GOV, MEM, OBS, ECON (their $30/mo validates your €29) | — | TTFV, INST, REL (polished SaaS); their voice-matching is shallow MEM but *shipped and felt* |
| **Intercom Fin** | GOV (Fin auto-resolves — anti-gate by design), MEM (owned vs vendor), ECON ($0.99/resolution vs ~€2–10/mo flat) | OBS | TTFV, INST, REL, and *proof* — Fin has resolution-rate case studies; BLACKBOX has one edit-log row |

- **Closest comp:** Dust.tt — governed agents for small teams — but BLACKBOX is local-first and single-operator where Dust is managed and team-shaped.
- **Unfair advantage:** the user-owned plain-markdown ledger + forced approval gate + edit→drift→SOP-patch loop is a compounding-trust artifact no one in this table builds, because each of them monetizes owning the layer BLACKBOX gives away.
- **Unfixable disadvantage:** Gemini-in-Gmail's zero-install presence at the exact point of need — BLACKBOX will never out-convenience it and must never try; every won user will be won on ownership and compounding, proven over weeks.

---

## 4. Tier placement (honest)

**Current: Tier 1.5 — a kernel demo that has *visited* Tier 2 but doesn't live there.** The July 8 evening session proved a technical solo operator *can* drive it daily (real email → SOP-grounded draft → edit → approve → capture). But "daily driver" is an evidence claim about days, and the count of completed ritual days is zero. Tier 2 is claimed by fourteen consecutive `os-log.md` rows, not by capability. Tier 3 (SMB-ready) is blocked by the install wall (Python + npm + `.env` + OAuth + today's `python-docx` miss is a preview of every stranger's first hour) and vault-only draft delivery. **What moves it one tier: one logged green week.** Nothing in the repo is the bottleneck for that.

---

## 5. Go/no-go checklist

| Criterion | Fable 6 | Now | Note |
|---|---|---|---|
| Obsidian plugin usable | ✅ | ✅ | — |
| Crash recovery + resume | ✅ | ✅ | — |
| Gmail driver MVP in CI | ✅ | ✅ | Guard test now sane (asserts committed state) |
| Weekly dogfood habit | ❌ | ❌ | 1 edit-log row, no os-log — unchanged |
| 30-day pilot readiness | ❌ | ❌ | Blocked behind habit gate by design |

**3.5/5 → 3.5/5 (Δ 0).** Same score, higher confidence: the ✅s are now backed by a suite that's green on your machine, not just CI. The remaining 1.5 points are purchasable only with calendar days.

---

## 6. Advice (max 10)

**Operator (ritual only — build freeze holds):**
1. Tomorrow 08:00: Day 1 of the daily ritual from `docs/dogfood-scorecard-v1.md`. Create `vault/10-SOPs/os-log.md` with its first row even if every number is red — the file's existence is the commitment device.
2. Get to **3 edit-log rows by Friday**, then run the first live `sop_drift_review` and approve or reject its patch. That single run moves Flywheel 55→~70 and is this week's only score-moving act.
3. Fire the one ingress call from `tomorrow-handoff.md` (5 minutes, PowerShell block is ready) so H stops being theoretical.
4. **Moratorium on assessment sessions until Week 2 Friday.** Fable 6 + Fable 7 in one day, plus five new research-prompt docs in the working tree — reviews and prompts are consuming the exact hours the gate needs. The next review input is 14 os-log rows.
5. `pip install python-docx` in the orchestrator venv (it's a dev-env gap, not code) — then the suite is fully green locally.

**Cursor (housekeeping only — dogfood proved no new blocker):**
6. Commit the pending sync when operator asks: two test fixes, `dogfood-scorecard-v1.md`, Fable 6/7 reports, handoff update. **Exclude** `vault/.system/drivers.json` (gmail-enabled local state) and `edit-log.jsonl`.
7. Guard the docx test with `pytest.importorskip("docx")` so a missing optional dep skips instead of failing (`apps/orchestrator/tests/test_docs_driver.py:24`).
8. Nothing else. No feature session until a red-week trigger or the Week 4 gate.

**Do NOT:**
9. Do not act on the new K-beauty-sourcing / Phase-4A-Gmail / GLM-research prompt docs during the gate — they are Week 5+ inputs at best.
10. Do not touch send-after-approve, new drivers, or channels — unchanged from Fable 6 §6C, restated because the prompt pile suggests temptation.

---

## 7. September finish line — still valid?

**Still valid, verbatim, zero revision** — because zero calendar days have elapsed since it was set this morning. The Fable 6 finish line (four green weeks logged, ≥40 approved drafts, ≥10 captures, ≥3 approved SOP patches with declining repeat-correction rate, Gmail Drafts delivery, one weekly live ingress source, suite green locally) remains exactly the right September 30 target, and today's only legitimate update to it is procedural: the finish line's first dependency — `os-log.md`, Day 1, Row 1 — is now overdue by the length of this assessment.

---

*Assessment only — nothing committed. Test evidence: 238 passed / 1 failed (env: `python-docx` missing) / 1 skipped @ `a156e2a` local. Habit rows scored from direct vault inspection; no operator paste was provided and none was needed — the vault is the paste.*
