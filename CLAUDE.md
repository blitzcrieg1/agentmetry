# Agentmetry: working notes for Claude

Read this before doing anything in this repository. It exists because sessions
kept relearning the same facts, and one of those facts has a deadline attached
that is expensive to break by accident.

---

## What this is

A **local-first endpoint sensor for AI coding agents**. It records what an agent
did at the tool boundary, correlates sequences into detections, and forwards
into the SIEM the customer already runs.

It is **not** an agent OS, not a sandbox, not a CASB. An earlier incarnation of
this repo was an agent runtime; that was removed deliberately and is not coming
back. If a change starts to look like "Agentmetry runs your agents", it is the
wrong change.

**This repo stays local-first; Agentmetry Enterprise may be hosted.** Decided
2026-10-02. The open-source sensor records on the machine and never depends on a
hosted service. Enterprise (`agentmetry-enterprise`) can be a hosted fleet
console with managed ingest and cross-machine views. Do not argue Enterprise out
of the cloud on "never a vendor cloud" grounds; that line was withdrawn.

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

**The gate passed on 2026-10-02: 4 of 4, weeks 1 to 4.** Weeks 2 and 4 had
also scored RED, on one and three untriaged `session-tool-burst` detections, and
turned GREEN when those were triaged that day. The fingerprint did not move
during the run. Whether the freeze now ends, so #55 and #172 can land, is the
maintainer's decision; until it is made, the list above stays frozen.

That flip is worth knowing about. **A week scored red on untriaged detections
can be rescued at any time**, because `assess` reads the disposition store
on every run (`core/audit/dogfood.py:288`) rather than freezing a verdict when
the week ends. Too few active days is the only failure that is genuinely
permanent. Two documents in this repo asserted the opposite for a day, both
written from the RED verdict rather than the code.

Do not write an earliest-close date in this file again. It was wrong within a
week both times. The date is whatever the command prints plus seven days per
green week still needed, and a red week moves it. Run it rather than quote it:

```bash
apps/orchestrator/.venv/Scripts/python.exe -m agentmetry.cli dogfood
```

**`dogfood` scores from the SQLite index and the disposition store that the
CLI's settings name, not from the JSONL trail.** On the dogfood machine those
must be the same files the running recorder writes, which its start script
sets. From 2026-10-15 to 2026-10-19 they were not: the recorder indexed into
`audit.db` while the CLI's `.env` still named `agentmetry-trail.db`, frozen at
2026-10-14. Week 7 scored GREEN on 2,325 events instead of RED on 8,022 with
seven untriaged detections, and "1 of 4" was reported for an afternoon. If a week's
event count looks low, count the trail before believing the verdict, and
check that `settings.audit_db_path` matches the recorder's.

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
3. **`ROADMAP.md`**, what is being worked on. Refreshed 2026-10-23
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

**On the dogfood machine, three tests fail locally and pass in CI.** The
README count is 2 high because of gitignored launch entries, and
`apps/orchestrator/.env` turns on full-argument capture and an anchor log that
the test setup does not pin. So "plaintext arguments must not leave the
receiver" in `test_otel_ingest.py` and a `verify` failure in
`test_trail_chain.py` are this machine's settings, not a leak: move the `.env`
aside and they pass. Anything else that fails is real. Verifying the full
trail takes several minutes; run it in the background.

**A release is the tag plus a GitHub Release.** Pushing `v*` publishes to
PyPI through `release.yml`, which creates no Release page. 0.9.8 and 0.9.9 went
out as bare tags and the Releases page showed 0.9.7 as latest for a week. After
the tag, run `gh release create vX.Y.Z --verify-tag --latest` with that
version's CHANGELOG section as the notes.

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

Not code. As of 2026-10-25 there are 2025 tests collected in CI, zero open
code scanning alerts, zero open Dependabot alerts, a dogfood gate that passed
4 of 4 on 2026-10-02 and, after the 16 open detections were triaged on
2026-10-23, prints "7 of 4, Gate PASSED" with every complete week green
(triage is what keeps it that way; untriaged criticals turn a week red),
`agentmetry demo`
runnable with nothing installed (`uvx agentmetry demo`), 0.10.2 on PyPI
(released 2026-10-25: `scan` reads the AGENTS.md and CLAUDE.md files an agent
loads by itself, and the config block rule covers Codex), and 0.10.1 before it
(released 2026-10-23: 0.10.0's `agentmetry scan`, MCP proxy check, Windows
Codex hooks, ingest rate limits and redesigned dashboard, plus the dashboard
actually inside the package; 0.10.0 had none, which only a clean-environment
install from PyPI showed. Walk the README from a fresh venv before a release,
not from the checkout). Check alerts with
`gh api repos/blitzcrieg1/agentmetry/dependabot/alerts?state=open` rather than
trusting this line. There are also **zero external users and zero
design-partner tenants**, and no sales message has gone out yet. The first
two were recorded as sent on 2026-10-23 and had not been; check with the
maintainer before treating a pipeline row as sent. Those two, a third from a
new signal and two peer critique-asks are drafted and verified; four more wait
on finding the person who joined in each closed role.

The fleet installers Cursor drafted in #282 are parked as
agentmetry-enterprise#33 (macOS) and #34 (Intune managed policy), to be built
when a prospect needs one, not before.

Do not merge Dependabot's `mcp <3` widening (#184 and its successors). CI passes
on it because no test imports the file the pin protects; see #174.

When asked "what next", the honest answer is almost always the commercial one,
and the queue is in `agentmetry-enterprise/sales/outreach-log.md` (private, checked out beside this repo as `../agentmetry-enterprise`), with the account
state in `sales/pipeline.md` and the send-ready text in
`sales/first-touch-drafts.md`. It moved out of this repo
on 2026-10-10 because it names real recipients; do not bring names or contact
details back into a public file. Say so plainly rather than offering a
comfortable engineering task instead.

---

## Feature development is stopped

**Decided by the maintainer on 2026-10-23: maintenance only, until a restart
trigger fires.** This applies to every agent working in this repository, not
only Claude.

The same rule was set on 2026-10-03 ("no new features until a prospect
replies") and did not hold: about twenty PRs merged before the first sales
message went out, and four of six hiring signals went stale unsent. With zero
users, every feature is built on a guess, and 0.10.1 left the product in a
state where nothing shippable moves a prospect as much as one reply would.

**Allowed, as maintenance:**

- Weekly triage, so the dogfood gate stays green. One untriaged critical turns
  a week red, and the site prints the streak.
- Security alerts (code scanning, Dependabot) when they appear.
- Bugs that a real person reports, fixed within a day. Responsiveness is part
  of the pitch, most of all during a launch post.
- Doc fixes when a prospect is confused by something.
- Before any release, walking the README from a fresh environment installed
  from PyPI, as 0.10.1 showed is necessary.

**Not allowed until a trigger fires:** new commands or features, dashboard
polish, the MCP fingerprinting backlog, refactors, the fleet items (#313,
#314, #318), and the detection-noise pass (#172, #329, #55). That last one
waits for outside reports to say which rules matter, and landing it resets the
"green weeks against an unchanged ruleset" line the site shows.

**Restart only when** a named person asks for something, a pilot needs it (for
example the MSI on a real tenant), or a user reports a bug.

**When asked "what next"**, lead with the commercial step. If asked for a
feature anyway, say plainly that it breaks this rule and name the commercial
step it displaces, then do what the maintainer decides. Measure a week by sends
and replies, not by merged PRs. The launch post draft is
`sales/launch-show-hn.md` in the same private repo as the outreach queue.

---

## Self-improvement guardrail

A reflection pass may propose edits to **process documents**: this file, the
skills under `.claude/skills/`, `ROADMAP.md`, `CONTRIBUTING.md`.

It may **never** propose edits to detection rules, traits, the engine, the MITRE
mapping, or the detection manifest while the freeze is in effect. A memory
system that quietly restarts a four-week gate is worse than no memory system.
