# AgentAudit — LinkedIn launch post

**Voice:** IRT peer to other IRT/SOC people. Not "excited to announce." No emoji spam, no hashmark soup, no ARR, no "sign up." Post it from your own account as a builder who does IR, not as a vendor.

**Depends on:** README (#1) wording + Loom (#3) phrase bank. Embed the Loom video or link it in the first comment (LinkedIn suppresses reach on posts with outbound links in the body — put the GitHub link in comment #1).

---

## Primary draft (~190 words)

> When an agent runs a tool at 2am, can you prove what it did?
>
> Most agent stacks keep nothing you'd hand an incident responder. So I built a small open-source thing for the ones I actually govern.
>
> **AgentAudit** is a local flight recorder for AI agents. Every tool call, every denial, every human approval becomes one JSON line you own — with the correlation id that ties the run together, the tool that ran, the outcome, and a SHA-256 of the arguments. Replay any run from the local outbox. Run inference locally with Ollama or bring your own cloud key — either way the audit trail stays on your machine. Forward it to Loki, Elastic, Splunk, or a webhook if you want — or keep it as plain JSONL and grep it.
>
> One honest boundary: it records agents that run *through* the host. Unmanaged ChatGPT, Cursor on auto-approve, browser copilots on the same machine — it does **not** see those. That's a CASB / secure-web-gateway problem, not this. AgentAudit is Tier A remediation, not a shadow-AI spy.
>
> Apache-2.0. Schema, Sigma rules, and a free Docker Loki stack are in the repo.
>
> If you do IR or detection engineering — tell me where the schema falls short of a real investigation. That's the feedback I want.
>
> Repo in the comments.

**Comment #1 (post immediately after):**
> github.com/blitzcrieg1/agentic-os — audit layer + `docs/agent-audit-event-schema.md` for the canonical event format. 60-second demo: [Loom link]

---

## Shorter variant (~110 words, if the long one feels heavy)

> When an agent runs a tool at 2am, can you prove what it did?
>
> **AgentAudit** — an open-source local flight recorder for AI agents. Tool calls, denials, and approvals become JSONL you own: correlation id, tool, outcome, SHA-256 of the args. Replay any run locally; run inference locally with Ollama or bring your own cloud key — either way the audit trail stays on your machine. Forward to Loki / Elastic / Splunk / webhook if you want one.
>
> Honest boundary: it records agents that run *through* the governed host. Unmanaged ChatGPT/Cursor/browser copilots on the same box — it doesn't see those; that's CASB territory, not this.
>
> Apache-2.0. Schema + Sigma rules + free Loki stack in the repo. If you do IR — tell me where the schema falls short.
>
> Link in comments.

---

## Rules for whatever you post

- **Tier C paragraph stays above the CTA.** Non-negotiable — it's the credibility move for this audience. Removing it to "tighten" the post breaks [tier-c-honesty].
- **Phrase bank consistency** — "can you prove what it did?", "local flight recorder", "JSONL you own", "a SHA-256 of the arguments", "records agents through the host", "that's a CASB problem, not this" — all match the README and Loom verbatim.
- **The ask is feedback, not signups** — "tell me where the schema falls short" invites the exact IRT/SOC people you want, and it's an honest ask from a solo builder.
- **Link in comment #1, not the body** — LinkedIn de-ranks posts with body links.
- **No claims not shipped** — no `--audit` hash chain (spec only), no "full visibility", no CASB parity.

## Do-not-post list

- ❌ "Excited to announce", "thrilled to share", "game-changer", "the future of AI security"
- ❌ Any metric you don't have (users, stars, ARR)
- ❌ "Replaces your SIEM" — it *feeds* one, optionally
- ❌ Emoji every line / 15 hashtags — 2–3 tags max at the very end if any (`#dfir #detectionengineering #aisecurity`)

---

## Optional follow-up post (a week later, if the first lands)

Second-post ideas that keep the peer tone and don't require new code:
- "Here are the 3 Sigma rules I shipped and the one I *couldn't* write yet (approval-bypass needs sequence correlation) — how would you detect it?"
- "What a denied tool call looks like in the JSONL, and why the burst rule fires at 5/min."
- Screenshot of a `blackbox replay` timeline with a one-paragraph IR read.

Each is a genuine detection-engineering conversation starter, not a re-announcement.

---

*Companion: README (#1) is the repo landing; Loom (#3) is the embedded video; both share the phrase bank above. Post only after the Loom is recorded from a GREEN dogfood run.*
