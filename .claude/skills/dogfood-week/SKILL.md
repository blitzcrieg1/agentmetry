---
name: dogfood-week
description: Score the Agentmetry dogfood week from the live trail and report the beta gate. Use when the user asks about dogfood, the weekly stats, the beta gate, whether a week was green, or how long until beta.
---

# Dogfood week

The beta gate is four consecutive green weeks. It went unstarted for weeks
because checking one meant a twenty-minute manual pass, so it never got checked.
The point of this skill is to make the question cheap enough to actually ask.

## Run

From `apps/orchestrator`:

```bash
.venv/Scripts/python.exe -m agentmetry.cli dogfood
.venv/Scripts/python.exe -m agentmetry.cli stats --days 7
```

`dogfood` is the authority on the gate. `stats` gives the seven-day counts and
the per-source breakdown, which is what goes in a weekly note.

## Report

State, in this order:

1. **Consecutive green weeks, out of 4**, and the verdict of the most recently
   *completed* week
2. Event count, sessions, detections, untriaged for that week
3. **Earliest possible beta close** as an absolute date. As of 2026-08-22 that
   is 2026-09-04, assuming weeks 3 and 4 both go green
4. Anything RED, and specifically why

A week is green when the recorder ran on at least three days, the trail chain
verifies, every critical or high detection was dispositioned, and nothing is
stuck in the hook spool.

## What counts as a problem

- **Untriaged critical or high detections.** This is the usual cause of a red
  week and it is fixable by the operator in minutes. Say which detections.
- **Fewer than three active days.** Not fixable retroactively. Say so rather
  than implying it can be rescued.
- **A moved ruleset fingerprint.** This restarts the clock. Check it and say so
  loudly if it has moved from `56ad3de1ad8533cf`.

`hook-spool.expired.jsonl` is **not** a stuck spool. Expired entries can never
drain by definition, and the dashboard warning does not distinguish the two.
Check the live spool file, not the expired one, before reporting a spool problem.

## Rules

- **Never edit detection rules, traits, the engine, or the MITRE mapping.** The
  freeze runs until 2026-09-05 and editing any of them restarts the clock this
  skill exists to measure. See `CLAUDE.md`.
- Do not disposition detections on the operator's behalf. Triage is a judgement
  about their own machine. Report what needs triage and let them decide.
- Only update `docs/commercial/outreach-log.md` if the user asks for the week to
  be recorded.
