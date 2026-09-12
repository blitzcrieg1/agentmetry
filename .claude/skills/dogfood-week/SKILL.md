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
3. **Earliest possible beta close** as an absolute date, computed rather than
   quoted: take the end date of the week currently in progress and add seven
   days for each green week still needed after it. Never carry a date over from
   a previous run of this skill. Week 1 of the 2026-08-30 clock went RED, which
   moved the answer by a week, and every red week moves it again
4. Anything RED, and specifically why
5. **Days left in the week in progress, and its untriaged count.** This is the
   only actionable line in the report. Week 1 closed RED with six untriaged
   detections after being flagged at three, with three days still on the clock.
   A report that states the gate without stating the deadline is why

A week is green when the recorder ran on at least three days, the trail chain
verifies, every critical or high detection was dispositioned, and nothing is
stuck in the hook spool.

## What counts as a problem

- **Untriaged critical or high detections.** This is the usual cause of a red
  week and it is fixable by the operator in minutes. Say which detections.
- **Fewer than three active days.** This is the one that genuinely cannot be
  fixed retroactively, because no disposition creates a day the recorder did not
  run. Untriaged detections are the opposite: always fixable, at any time.
- **A moved ruleset fingerprint.** This restarts the clock. Check it against
  the value in `CLAUDE.md`, which is the one place that number is written down,
  and say so loudly if it has moved. This file used to carry its own copy. It
  went stale, and a skill that hardcodes a hash it does not own would have
  reported a restarted clock that had not restarted.

`hook-spool.expired.jsonl` is **not** a stuck spool. Expired entries can never
drain by definition, and the dashboard warning does not distinguish the two.
Check the live spool file, not the expired one, before reporting a spool problem.

## Rules

- **Never edit detection rules, traits, the engine, or the MITRE mapping.** The
  freeze has no fixed end date. It runs until four consecutive green weeks have
  closed, so a red week extends it. Editing any of those files restarts the
  clock this skill exists to measure. See `CLAUDE.md`.
- **A red week from untriaged detections CAN be rescued, at any time.** Every
  verdict is recomputed on every run: `build_report` reads the disposition store
  live (`core/audit/dogfood.py:289`), so nothing is frozen when a week ends.
  Week 1 of the 2026-08-30 clock scored RED for four days and flipped to GREEN
  the moment its six detections were dispositioned on 2026-09-09.

  This file previously said the opposite, in bold, and was wrong. The claim came
  from reading the RED verdict and assuming it was final instead of reading the
  code. If an operator is looking at a red week, tell them to triage it.
- Do not disposition detections on the operator's behalf. Triage is a judgement
  about their own machine. Report what needs triage and let them decide.
- Only update `docs/commercial/outreach-log.md` if the user asks for the week to
  be recorded.
