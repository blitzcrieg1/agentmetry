---
name: trail-debug
description: Explain why an Agentmetry detection fired, or investigate a suspicious or missing event in the trail. Use when the user asks why a rule fired, why something was flagged, whether a finding is a false positive, or to trace an event through the trail.
---

# Trail debug

Answer the question from the trail. Do not fix the rule.

## 1. Verify before reading

```bash
cd apps/orchestrator
.venv/Scripts/python.exe -m agentmetry.cli verify --trail data/agentmetry-trail.jsonl
```

If the chain does not verify, stop and say so. Every conclusion below is drawn
from the file, so a file that fails its own check makes them worthless.

The em-dash below is quoted from real CLI output, not house copy.
A `FAILED — no checkpoint in this anchor log covers this trail` is a
different verdict from tampering. It means the configured anchor log is about
some other file, which is a misconfiguration rather than evidence of rewriting.

## 2. Find the detection and its evidence

A detection event carries `detection.event_ids`, which are the exact events that
caused it. Pull those, not the surrounding minute.

```bash
grep '"rule_id":"credential-exfil"' data/agentmetry-trail.jsonl | tail -1 | python -m json.tool
```

Then look up each id in `detection.event_ids`. The rule fired on a *sequence*;
the individual calls are usually ordinary, and that is the whole design.

## 3. Explain it

Say, concretely:

- Which rule, and the plain-English sequence it matched
- The specific events, with their commands and timestamps
- Which trait each event contributed. Traits are the vocabulary rules match on:
  a credential read, an egress, an untrusted-input read
- Whether the label is right

## 4. If it is a false positive

Say so plainly. The five known false-positive sources are already filed:

| Issue | Shape |
|---|---|
| [#44](https://github.com/blitzcrieg1/agentmetry/issues/44) | `.env.example` read as credential access |
| [#49](https://github.com/blitzcrieg1/agentmetry/issues/49) | credential path named inside an MCP argument |
| [#50](https://github.com/blitzcrieg1/agentmetry/issues/50) | pipe into an interpreter running its own script |
| [#51](https://github.com/blitzcrieg1/agentmetry/issues/51) | GitHub-raw fetch plus any later `python -c`, unlinked |
| [#55](https://github.com/blitzcrieg1/agentmetry/issues/55) | observable techniques collapsing into T1059 |

If the finding matches one of these, name the issue. If it is a **new** shape,
open an issue with the session's events as the reproduction. That is the highest
value output this skill produces: a corpus case nobody invented.

## The rule that matters

**Do not edit `rules.py`, `traits.py`, `engine.py` or `mitre.py`.** They are
frozen until 2026-09-05 because they are hashed into the ruleset fingerprint,
and changing one restarts a four-week beta gate currently at 2 of 4.

Fixing a false positive the day you find it feels obviously right and is exactly
how the last clock got reset: three detection improvements landed in week one,
each an improvement, and collectively they made the week meaningless.

File it. Land the batch on 2026-09-05, #55 first, so the fingerprint moves once.

You may disposition a detection as a false positive through the CLI or dashboard
without touching the freeze. That is triage, not a rule change, and an untriaged
critical is itself what turns a week red.
