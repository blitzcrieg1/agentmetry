# Total audit prompt (paste into Cursor)

Paste everything below the line into Cursor with the repo open.

---

You are auditing this repository end to end: code, architecture, product concept, market position, and trajectory. I want a verdict I can act on, not encouragement.

## Rules of engagement

Read these first. They matter more than the task list.

1. **Verify, do not trust.** Every number in the README, the docs, and this prompt is a claim. Run the command. Read the code. If a claim and the code disagree, that disagreement is a finding and it outranks whatever else you were going to say about that area.
2. **Cite evidence.** Every finding gets a `path/to/file.py:line` or the command output that produced it. A claim with no evidence is an opinion, and I want those clearly labelled as opinions in the section reserved for them.
3. **Do not flatter me.** I do not need to hear that something is "solid" or "impressive" or "well thought out". If a design is good, one sentence saying why, then move on. Spend the words on what is wrong. A review that finds nothing serious is a review that did not look hard enough, and I will read it as a failed audit.
4. **Rank by consequence, not by how easy it is to describe.** A silent data-loss path buried in one function outranks twenty style nits. If you catch yourself writing a long list of small things, stop and go find the big thing.
5. **"Abandon this" and "pivot to X" are permitted conclusions.** If the honest read is that the concept does not work or the market will not care, say so plainly and defend it. I would rather hear it now.
6. **Distinguish what is built from what is claimed.** Public alpha projects routinely describe intentions in the present tense. Flag every instance where the docs describe something the code does not do.

## What this is

Agentmetry: a local-first flight recorder for AI coding agents. It hooks the tool lifecycle of Claude Code, Cursor, Codex and Antigravity, writes every tool call, approval and denial to a hash-chained JSONL trail on the local machine, and runs sequence detection over each session so that (for example) a credential read followed by network egress becomes one finding rather than two unremarkable log lines.

Positioning claims to test, not accept:

- Local-first. No cloud calls, no telemetry. Forwarding to Elastic ECS, Splunk HEC or a webhook exists and is off unless configured.
- The trail is the system of record. Detections and triage decisions are append-only events on the same hash chain.
- It is a recorder, not a sandbox. The only enforcement path is pre-execution DLP blocking in the hook.
- It is explicitly **not** a CASB: it sees the agents it is wired into, and an unmanaged browser assistant is invisible to it.

Context that shapes every recommendation you make:

- **Solo developer.** Any plan requiring a team is not a plan, it is a wish. Say so if that is your conclusion.
- Windows 11 primary, no Docker available locally.
- Apache-2.0, public GitHub repo, public alpha. Roughly 248 commits.
- About to publish to PyPI as `agentmetry` 0.4.0. Not yet live at the time this prompt was written.
- Monetization: no payment processing exists. Treat revenue as unproven.

## Where things are

```
apps/orchestrator/agentmetry/        the published package
  core/audit/                        trail, chain, spool, ingest, dogfood gate
  core/audit/detection/              rules, traits, engine, benchmark, corpus, disposition
  core/diagnostics/                  doctor, autostart
  api/                               FastAPI ingest and query
  cli/                               the `agentmetry` entry point
  policies/                          DLP, tool policy, detection YAML manifests
apps/orchestrator/tests/             59 test files
apps/dashboard/                      web UI
apps/landing/                        agentmetry.ai
apps/obsidian-plugin/
adapters/                            per-IDE hook adapters
scripts/                             hook clients and per-IDE installers
docs/                                event schema, detection rules, SIEM integration, compliance
```

## Start by establishing ground truth

Run these before forming any opinion, and report what they actually printed:

```bash
cd apps/orchestrator
python -m pytest -q
python -m ruff check agentmetry tests
python -m agentmetry.cli doctor
python -m agentmetry.cli benchmark
python -m agentmetry.cli dogfood
```

Claims to check against reality, and correct me where I am wrong:

- ~644 tests pass, ruff clean
- 15 built-in detection rules
- A benchmark corpus of 20 hand-labelled sessions: 14 attack, 6 benign, run through the real engine, exits non-zero on any miss or any false positive
- A four-week dogfood gate that requires four consecutive green weeks measured against a frozen ruleset fingerprint
- The hash chain verifies end to end

## Part 1: Code and architecture

Focus where the damage would be worst:

- **The chain and the trail.** Can events be lost, silently reordered, or written unchained? What happens on concurrent writers, a crash mid-write, a full disk, or a clock that jumps backwards? Is the "append-only" claim actually enforced or merely intended?
- **The hook path.** `scripts/agentmetry_ingest.py` runs inside the user's agent on every tool call. What is its latency and failure behaviour? It fails open by design; is that the right call, and is it honest about it? What happens when the orchestrator is down, when the spool fills, when an event expires?
- **The detection engine.** Are the rules sound or are they string matching wearing a trench coat? How would you evade them in five minutes? Assess the trait classifier and the MITRE mapper as separate classifiers that must agree, and check whether the rules trust the right one. (Two known false positives are filed as issues #40 and #41. Find the ones nobody has filed.)
- **The benchmark.** Six benign sessions is a small denominator for a false-positive rate. What is the real statistical confidence in the claim, and how should it be stated honestly?
- **The security posture of the product itself.** It reads every command an agent runs. What does it store, where, with what permissions, and what would an attacker with local user access get? See issue #34 on chain anchoring and #33 on fleet identity.
- Test quality, not just count. Are they pinning behaviour or restating the implementation? Find tests that would pass if the feature were deleted.

## Part 2: Concept and product

- Who is the actual user on day one, and what makes them install this rather than nod and move on? Be specific about the moment of adoption.
- Is a local-first, no-cloud recorder a durable position or a temporary one that a platform vendor closes by shipping the feature themselves? What happens to this project the day Anthropic or Cursor ships native audit logging?
- The CASB gap is stated honestly in the docs. Is honesty enough, or does it make the product unbuyable for the buyer who has the budget?
- Read `README.md`, `apps/orchestrator/README.md`, `ROADMAP.md`, and the landing page copy. Do they describe the same product? Would a stranger understand what this is in thirty seconds?
- The dogfood gate deliberately blocks rule changes for four weeks. Is that discipline or self-injury for a project that needs iteration speed?

## Part 3: Compare it to the field

Position it honestly against real projects. For each, say what it does better, worse, and whether that comparison even makes sense:

- **Runtime detection:** Falco, Wazuh/OSSEC, auditd, Sysmon
- **Detection content:** SigmaHQ, MITRE ATT&CK tooling
- **LLM and agent observability:** Langfuse, LangSmith, Arize Phoenix, OpenLLMetry/Traceloop, and the OpenTelemetry GenAI semantic conventions
- **AI/agent security vendors:** Invariant Labs, Lakera, Zenity, Prompt Security, WitnessAI, and IR Scribe (irscribe.com, closed source, the nearest direct competitor)
- **Secret scanning:** gitleaks, TruffleHog
- **Session recording:** Teleport

Two questions I care about most: is there an existing project that already does this well enough that Agentmetry has no reason to exist, and is Agentmetry reinventing a wheel it should instead be a plugin to? Should the trail emit OpenTelemetry GenAI spans instead of a bespoke schema, and what is lost if it does?

## Part 4: Your opinion

A separate section, clearly labelled as opinion, where you take positions and defend them.

- What is this project actually worth building, on a scale from "shut it down" to "this is a category"?
- What is the single biggest thing that will kill it, and is that thing fixable by one person?
- What is the most over-engineered part relative to its value?
- What is the most under-built part relative to its importance?
- If you had to cut 40% of the codebase, what goes?
- Is the four-week dogfood gate a good idea? Argue both sides, then pick one.

## Part 5: The plan

Given one solo developer, no team, no budget:

- **Next 7 days.** Concrete, ordered, each item with the reason it beats the alternative.
- **Next 30 days.** What single outcome would most change this project's odds?
- **The 6-month bet.** Name the one thing worth being right about, and what it would take to find out cheaply.
- **What to stop doing.** Be specific and unkind here. Name the files, features and docs to delete.
- For each recommendation, state the falsifiable signal that would tell me it was wrong.

Existing open issues (#1, #3, #4, #5, #6, #7, #8, #25, #26, #27, #28, #33, #34, #35, #36, #37, #40, #41) are context, not a backlog to rubber-stamp. Tell me which are mis-prioritized and which should be closed as never worth doing.

## Output

A single markdown document.

Lead with a **verdict paragraph**: what this is, whether it should continue, and the one thing to do next. Then a scorecard across architecture, code quality, security, product clarity, market position and execution, each scored with a one-line justification. Then the findings, ranked by consequence, each with evidence. Opinion and plan sections last.

Do not pad. If a section has nothing worth saying, write one line saying so and move on.
