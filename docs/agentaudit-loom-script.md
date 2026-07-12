# AgentAudit — 60-second Loom script

**Purpose:** the video that plays under the LinkedIn post. First click after it goes to the GitHub repo, so the words here match the README (#1) exactly.

**Voice:** IRT peer showing a tool to other IRT/SOC people. Not a sales demo. No "game-changer," no "excited to announce," no ARR, no "sign up." Talk like you'd talk in a war room.

**Hard cap: 60 seconds.** If a take runs long, cut the Loki beat (Beat 4) first — it's the optional rung, not the hero.

**Record before recording:** run the [dogfood checklist](./agentaudit-dogfood-checklist.md) first. Everything on screen below must be real output from your own run — same `thread_id`, same JSONL lines. Never stage a value.

---

## Setup (open these, in this order, before you hit record)

1. **Terminal** — orchestrator already running (`scripts\blackbox.bat start`), venv active so `blackbox` works.
2. **Browser tab 1** — dashboard `http://127.0.0.1:8000`, on **The Armory · Desk**, a `customer_reply` run sitting at the approval interrupt (so the approve/reject click is instant on camera).
3. **Editor** — `apps\orchestrator\data\audit-forward.jsonl` open, scrolled to the bottom.
4. *(Optional)* **Browser tab 2** — Grafana Explore `http://localhost:3001`, query `{job="agent-audit"} | json` already typed. Only if Loki came up clean in dogfood.

Redact on screen: nothing here shows customer PII — `customer_reply` on a sample note is fine. If your input note has real content, swap it for a sample first.

---

## Beat sheet + word-for-word narration

### Beat 1 — Hook (0:00–0:06)

**Screen:** the dashboard, agent run paused at the approval gate. Cursor hovering the approve button.

**Say:**
> "When an autonomous agent runs a tool at two in the morning — can you prove what it did? Most stacks keep nothing you'd hand an incident responder."

### Beat 2 — Problem + Tier C honesty (0:06–0:16)

**Screen:** stay on the dashboard; let the paused approval sit there as the visual.

**Say:**
> "This is AgentAudit — a local flight recorder for the agents you actually govern. One honest caveat up front: it records agents that run *through* this host. Unmanaged ChatGPT or Cursor on the same box? That's a CASB problem, not this."

### Beat 3 — The demo (0:16–0:50)

**Screen action 1 (0:16–0:24):** Click **reject** on the approval. Then start a second run and **approve** it. (Or, if you pre-staged two, approve one and reject the other.)

**Say:**
> "Every decision is an event. I reject this one — that's a denial, on the record. I approve the next — that's logged too, with who and when."

**Screen action 2 (0:24–0:36):** Switch to the terminal. Run `blackbox replay <thread_id>` for the approved run. Let the ASCII timeline print.

**Say:**
> "Here's the whole run replayed from the local outbox — the tool it called, the approval, in order. No vendor cloud in that path."

**Screen action 3 (0:36–0:50):** Switch to the editor showing `audit-forward.jsonl`. Highlight one `tool_called` line — point the cursor at `correlation_id`, `tool.qualified`, `action.outcome`, and `tool.input_hash`.

**Say:**
> "And it's just JSONL you own. One line per event — the correlation id ties the run together, the tool that ran, the outcome, and a SHA-256 of the arguments. Grep it, replay it, or write detections on it."

### Beat 4 — SIEM (optional, 0:50–0:55) — cut this first if over time

**Screen:** Grafana Explore, the same two runs showing up JSON-parsed.

**Say:**
> "Want it in a SIEM? Forward to Loki, Elastic, Splunk, or a webhook. Here's the free homelab Loki stack — same events."

### Beat 5 — Close (0:55–1:00)

**Screen:** back to the editor or the GitHub repo page. Overlay text appears (see below).

**Say:**
> "It's open source, Apache-2.0. Schema, detections, and the free Loki stack are in the repo. If you do IR — tell me where the schema falls short."

**On-screen overlay text for the final 5 seconds:**
> **AgentAudit — local flight recorder for governed agents**
> **Apache-2.0 · github.com/blitzcrieg1/agentic-os**
> **Records agents through this host. Not unmanaged copilots — that's CASB.**

---

## Phrase bank (keep these identical across README / Loom / LinkedIn)

- "local flight recorder for the agents you govern" / "...you actually govern"
- "can you prove what it did?"
- "one line per event" / "JSONL you own"
- "the correlation id ties the run together"
- "a SHA-256 of the arguments" (never say the args themselves are logged — they're hashed/redacted)
- "records agents through this host — not unmanaged copilots; that's a CASB problem"
- "grep it, replay it, or write detections on it"

## Do-not-say list

- ❌ "audits all AI on your machine" / "full visibility" — false, breaks Tier C honesty
- ❌ "replaces your CASB" / "shadow AI detection" — it's Tier A, not Tier C
- ❌ "enterprise SIEM platform" — it's a flight recorder; SIEM is optional L2–L4
- ❌ "game-changer," "revolutionary," "excited to announce," "sign up," any price
- ❌ Naming a `blackbox export --audit` hash chain — not shipped yet

---

## If a take breaks

- Draft/timeline looks wrong on camera → keep rolling, say "and that's real output, not staged" and move on. Authenticity beats polish for this audience.
- Over 60s → drop Beat 4 (Loki) entirely. The JSONL + replay is the complete hero.
- Loki didn't come up clean in dogfood → Beat 4 was already cut; don't improvise it live.

---

*Companion: README (#1) is the landing page for the repo link; LinkedIn post (#4) embeds this video and reuses the phrase bank. Record only after the [dogfood checklist](./agentaudit-dogfood-checklist.md) is GREEN.*
