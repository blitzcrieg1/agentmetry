# Agentmetry: working notes for Claude

Read this before doing anything in this repository. It exists because sessions
kept relearning the same facts, and one of those facts has a deadline attached
that is expensive to break by accident.

---

## What this is

A **local-first endpoint sensor for AI coding agents**. It records what an agent
did at the tool boundary, correlates sequences into detections, and forwards
into the SIEM the customer already runs.

It is **not** an agent OS, not a console, not a sandbox, not a CASB. An earlier
incarnation of this repo was an agent runtime; that was removed deliberately and
is not coming back. If a change starts to look like "Agentmetry runs your
agents", it is the wrong change.

The public framing lives on [agentmetry.ai](https://agentmetry.ai) and in
`README.md`. Use "Agentic OS" only in the README, GitHub description, or
investor material. Never in landing-page copy or a cold first line.

---

## The detection freeze, restarted 2026-08-30

**Do not edit these files.** They are hashed into the ruleset fingerprint, and
changing any of them restarts the four-week dogfood clock that gates beta.

```
apps/orchestrator/agentmetry/core/audit/detection/rules.py
apps/orchestrator/agentmetry/core/audit/detection/traits.py
apps/orchestrator/agentmetry/core/audit/detection/engine.py
apps/orchestrator/agentmetry/core/audit/mitre.py
apps/orchestrator/agentmetry/policies/detection/manifest.yaml
```

The clock **restarted on 2026-08-30**, after 0.7.0, and the freeze runs again from
there. The previous run reached 3 of 4 green weeks and was ended deliberately:
four known false positives (#44, #49, #50, #51) were shipping as criticals to
the first external tester, and a clean gate measured against a ruleset that
fires critical on `.env.example` is not worth the weeks it took.

**Week 1 (2026-08-30 to 2026-09-05) scored RED for four days**, on six
untriaged critical and high detections, then flipped to GREEN on 2026-09-09 when
they were triaged. The recorder was never the problem: seven active days, 4,449
events. Only the triage was.

That flip is worth knowing about. **A week scored red on untriaged detections
can be rescued at any time**, because `build_report` reads the disposition store
on every run (`core/audit/dogfood.py:289`) rather than freezing a verdict when
the week ends. Too few active days is the only failure that is genuinely
permanent. Two documents in this repo asserted the opposite for a day, both
written from the RED verdict rather than the code.

Do not write an earliest-close date in this file again. It was wrong within a
week both times. The date is whatever the command prints plus seven days per
green week still needed, and a red week moves it. Run it rather than quote it:

```bash
apps/orchestrator/.venv/Scripts/python.exe -m agentmetry.cli dogfood
```

Four green weeks measured against four different rulesets is not a number worth
quoting, which is why the freeze is checkable rather than promised. Verify the
fingerprint has not moved before opening any PR that touches
`apps/orchestrator/agentmetry/core/audit/`:

```bash
apps/orchestrator/.venv/Scripts/python.exe -c "from agentmetry.core.audit.dogfood import ruleset_fingerprint; print(ruleset_fingerprint()[:16])"
# expect 15846a0915769d4a
```

Four of the five parked detection-precision bugs were fixed in 0.7.0 and are
closed: #44, #49, #50, #51. Fixing them is why the clock restarted.

**Still parked: [#55](https://github.com/blitzcrieg1/agentmetry/issues/55)
alone.** It is the last change that will move the fingerprint, so land it in
one pass rather than piecemeal, and expect another restart when it lands.

Files in `detection/` that are **not** frozen and are safe to edit:
`disposition.py`, `live.py`, `live_store.py`, `benchmark.py`, `yaml_rules.py`,
`yaml_config.py`, `models.py`.

---

## Where truth lives

In this order. When they disagree, the earlier one wins and the later one is
stale and should be fixed.

1. **The code**, and a command you can run
2. **`CHANGELOG.md`**, what shipped, per release
3. **`ROADMAP.md`**, what is being worked on. Refreshed 2026-08-22
4. **Open GitHub issues**
5. Everything else

**Do not trust an audit document.** Three external audits in August 2026 each
read a stale `ROADMAP.md` as current and produced findings that were already
fixed, including one that recommended building a feature which had shipped the
previous day. If a document and a command disagree, run the command.

`ROADMAP.md` carries two rules that keep it honest: shipped work leaves the file
for `CHANGELOG.md`, and every item names an issue. Keep both.

---

## Commands

The orchestrator lives in `apps/orchestrator` with a venv at `.venv`. On
Windows the interpreter is `.venv/Scripts/python.exe`.

```bash
cd apps/orchestrator
.venv/Scripts/python.exe -m pytest -q              # the count moves, read it
.venv/Scripts/python.exe -m ruff check agentmetry tests
.venv/Scripts/python.exe -m agentmetry.cli benchmark   # must be 0 missed, 0 FP
.venv/Scripts/python.exe -m agentmetry.cli dogfood     # the beta gate
.venv/Scripts/python.exe -m agentmetry.cli doctor      # install health
.venv/Scripts/python.exe -m agentmetry.cli stats --days 7
.venv/Scripts/python.exe -m agentmetry.cli verify --trail data/agentmetry-trail.jsonl
```

Dashboard is `apps/dashboard` (Next 16, React 19, npm, `output: "export"`).
The marketing site is a **separate repo** at `../ai-audit-watch` and uses
**bun**, not npm. Running `npm install` there once produced a broken lockfile;
do not do it.

---

## How to work here

**Commit only when asked.** Do the work, report it, and wait. This is a
standing preference and it is not negotiable by convenience.

**Branch and PR.** `master` is protected with five required checks and
`enforce_admins` on, so nothing merges from a direct push. Match the existing
commit-message voice: what changed, why it was wrong before, what it cost.

**Never skip hooks or bypass signing.** If a hook fails, fix the cause.

**Do not commit** `.env`, a local `drivers.json`, anything under
`apps/orchestrator/data/`, or a real trail. `.agents/hooks.json` holds
machine-specific absolute paths and is frequently dirty; leave it alone unless
the task is about hooks.

**No em-dashes in anything public.** README, site copy, blog posts, LinkedIn,
outreach. Use periods, commas, colons or parentheses. This is a house rule
because em-dashes read as machine-written.

**Invent no number.** Every figure in public copy must come from a command
somebody can run. If a number cannot be produced on demand, it does not go in.

---

## What the project is actually short of

Not code. As of 2026-09-09 there are 1240 tests, zero open Dependabot and code
scanning alerts, and a released package on PyPI. There are also **zero external
users, zero design-partner tenants, and zero sent sales messages** against ten
researched accounts with drafted openers.

When asked "what next", the honest answer is almost always the commercial one,
and the queue is in `docs/commercial/outreach-log.md`. Say so plainly rather
than offering a comfortable engineering task instead.

---

## Self-improvement guardrail

A reflection pass may propose edits to **process documents**: this file, the
skills under `.claude/skills/`, `ROADMAP.md`, `CONTRIBUTING.md`.

It may **never** propose edits to detection rules, traits, the engine, the MITRE
mapping, or the detection manifest while the freeze is in effect. A memory
system that quietly restarts a four-week gate is worse than no memory system.
