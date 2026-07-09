# Dogfood scorecard v1

Extracted from [fable-6-benchmark-review-2026-07.md](./fable-6-benchmark-review-2026-07.md) §5.

## Daily ritual (Mon–Fri, ≤20 min)

1. `scripts\blackbox.bat status` — green? If not: `blackbox doctor`, fix, **no feature work**.
2. Feed one real input: paste a real customer email / drop a real doc into `00-Inbox/` (or let the morning brief run if Gmail is mounted).
3. Process the Approval Inbox: approve, **edit where the draft is wrong** (edits are the product), or reject.
4. If a draft was wrong because a *policy* is wrong or missing → note it; that's Friday's drift-review fuel.

## Friday ritual (≤30 min)

1. `scripts\blackbox.bat stats --days 7` — record the numbers in `vault/10-SOPs/os-log.md` (one line).
2. Run `sop_drift_review` (input: `20`) → review the patch proposal → approve → confirm it landed in `10-SOPs/Learnings/`.
3. Count edit-log rows: `(Get-Content vault\.system\feedback\edit-log.jsonl | Measure-Object -Line).Lines`
4. Monday check moved here: `blackbox recovery` → orphans must be 0.

## What to measure (and where it lives)

| Metric | Source | Green threshold |
|--------|--------|-----------------|
| Drafts approved / week | `blackbox stats --days 7` (customer_reply + follow_up_draft + client_brief successes) | **≥ 5** |
| Distinct skills used / week | same | **≥ 3** |
| Flywheel captures / week | edit-log row delta | **≥ 2** |
| Drift reviews run / week | `10-SOPs/Learnings/` new files | **≥ 1** |
| Orphans at Friday check | `blackbox recovery` | **0** |
| Hours saved (self-reported) | os-log.md one-liner | **≥ 3** |

**Green week** = all six thresholds met. Four consecutive green weeks = gate cleared (matches `GOALS.md` success sentence).

## Red week / kill signals

- **Any week with 0 flywheel captures** → the drafts are either perfect (unlikely) or you're rubber-stamping. Stop, read three drafts critically, edit honestly.
- **Two consecutive weeks < 5 drafts** → the vault-only archive is likely the friction ("draft isn't where I work") → **trigger the Gmail re-wire** (`customer_reply` → `gmail.create_draft`) *as an ops fix, not a feature*. This is the one pre-authorized build during the gate.
- **Any kernel exception in daily use** → building freezes entirely until `doctor` + logs explain it.
- **Suite red on your machine for > 2 days** → fix the tests before anything else; a red suite you ignore trains you to ignore everything.

## Decision tree

```
IF drafts/week ≥5 AND captures ≥2 for 2 weeks AND archive-in-vault feels fine
    THEN stay vault-only through week 4                       ELSE defer nothing:
IF vault-only is measurably the blocker (you re-type drafts into Gmail)
    THEN wire customer_reply → gmail.create_draft (draft-only)  ELSE defer
IF sop_drift_review ran manually ≥3 Fridays without drama
    THEN add weekly cron trigger for it                        ELSE keep manual
IF an external system (Woo/Make) actually posts to you weekly
    THEN harden ingress (idempotency key + dedup)              ELSE defer
IF 4 consecutive green weeks
    THEN unlock send-after-approve (BLACKBOX_GMAIL_SEND_ENABLED gate review)
    ELSE the gate holds — no new drivers, no new channels
```

## Week-4 gate review (what Fable/Cursor re-assesses with real stats)

1. `blackbox stats --days 28` — drafts, skills, per-week trend.
2. Edit-log: total rows, rows/week trend, which skills generate corrections.
3. `10-SOPs/Learnings/` — how many patches approved; did any make it into the live SOPs; did correction *rate decline* on patched topics (the flywheel's actual proof).
4. Honest hours-saved tally vs the ≥3h/week target.
5. Decision: send-after-approve unlock? Gmail re-wire retrospective? Pilot conversation start?
