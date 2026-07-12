# AgentAudit Team Tier — alert data model & endpoint boundary

**Status:** design sketch, not built. Gated on OSS traction (target ~few-dozen security teams running the local recorder) + 3–5 design partners who will pre-pay. Do not build speculatively.

**Core inversion:** don't centralize the *data*, centralize the *verdict*. The endpoint stays the system of record (it already is — `events.db` / `audit-forward.jsonl`). The cloud is an **index of alerts**, never a copy of telemetry. This is what makes the team tier (a) solo-maintainable, (b) low-liability, and (c) consistent with the OSS "your data stays local" trust story.

Every field below maps to something the endpoint already emits in canonical schema **v1.1.0** (`docs/agent-audit-event-schema.md`).

---

## 1. The three rings

**Ring 0 — never leaves the endpoint (system of record):**
- Raw, unredacted commands and full `arguments`
- Prompt text, draft text, tool *outputs*, file contents
- The full `audit-forward.jsonl` event stream (every `tool_called` / `approval_*` / `config_change`, not just the ones that alert)
- `blackbox replay <correlation_id>` reads only this. A responder pivots *to the machine* for full context.

**Ring 1 — leaves as an alert (default):** only events that trip the **triple gate** — `initiator.actor_type = autonomous` **AND** no approval on the `correlation_id` **AND** the action maps to a sensitive MITRE technique — become alerts. A normal `git log` never leaves. The alert payload is §2 below.

**Ring 2 — opt-in, off by default:** a few adjacent scrubbed events on the same `correlation_id` (the sequence that led to the alert), for teams that explicitly turn context up.

---

## 2. The alert payload (Ring 1)

```jsonc
{
  "alert_id": "…",
  "alert_schema": "1.0.0",
  "team_id": "team_abc",                 // which customer

  "detected_at_utc": "2026-07-12T18:02:03Z",

  "endpoint": {
    "endpoint_id": "ep_7f3a",            // stable per-machine pseudonym
    "developer_ref": "spiro",            // resolvable within the team (see §5 GDPR)
    "hostname": "SPYROS"                 // config-gated (real | pseudonym)
  },

  "rule": {
    "id": "AA-T1552-autonomous",
    "version": "2026.07.1",
    "name": "Autonomous credential-file read, ungated"
  },
  "severity": "high",
  "mitre": { "technique": "T1552.004", "name": "Private Keys", "tactic": "credential-access" },

  // --- the moat: the triple-gate verdict, straight from the canonical schema ---
  "verdict": {
    "initiator_actor_type": "autonomous", // <- initiator.actor_type; the thing EDR/CASB cannot see
    "approval_state": "ungated",          // no approval_request -> approval_response/success on this run
    "trigger": "agent_loop"               // <- initiator.trigger (manual | agent_loop | cron | vault_watch | ingress)
  },

  // --- enough to triage, not enough to leak ---
  "agent": { "app": "cursor", "model": "unknown" },  // <- source.app + model (app-name for most Tier B)
  "tool": {
    "qualified": "shell.run",             // <- tool.qualified
    "server": "shell",                    // <- tool.server
    "input_hash": "e3b0c442…b855",        // <- tool.input_hash; correlate the SAME command across endpoints, content-free
    "command_scrubbed": "cat ~/.ssh/id_rsa" // OPTIONAL, config-gated (see §3 dial)
  },

  "drilldown": {
    "correlation_id": "20e6b8ec-…",       // pivot key back into the local system of record
    "replay_hint": "blackbox replay 20e6b8ec-… on ep_7f3a"
  }
}
```

Also sent, out of band: a **daily heartbeat** per endpoint (`endpoint_id`, `last_seen_utc`, `recorder_version`, `rule_feed_version`) so the dashboard can show "27/30 endpoints reporting" and flag stale/disabled recorders.

---

## 3. The trust dial (what you actually sell to paranoid teams)

Three endpoint config knobs. The **team** chooses the privacy/utility tradeoff; you never make it for them.

| Knob | Options | Default | Paranoid mode |
|---|---|---|---|
| `alert.include_command` | `scrubbed` \| `hash_only` \| `off` | `scrubbed` | `hash_only` — cloud shows technique + hash; command visible only by drilling into the machine |
| `alert.identity` | `developer_ref` \| `pseudonym` | `pseudonym` | endpoint id only; the id→developer mapping stays local |
| `alert.ring2_context` | `on` \| `off` | `off` | `off` |

Tightest mode, a full alert is: *"endpoint ep_7f3a, T1552.004, autonomous + ungated, hash e3b0…, replay locally."* Actionable, and reveals **nothing about their infrastructure**. That's a claim no cloud-hungry incumbent can make: *"even our paid tier never sees your commands unless you turn it on."*

---

## 4. Why the blast radius is survivable solo

Model the breach honestly:

- **Raw-log aggregation (the trap we reject):** a breach of your cloud = every command every dev's agent ran — internal hostnames, deploy scripts, DB queries, source paths. Catastrophic; unrunnable solo.
- **This verdict-only design:** a breach = *"these companies' agents triggered these techniques."* Sensitive, worth protecting, but not credentials / code / infra. A blast radius one person can carry and honestly describe to a design partner.

`input_hash` does quiet double-duty: *"the same ungated command fired on 4 endpoints in your fleet"* (a strong worm/misconfig signal) **without a single command string leaving any machine.**

---

## 5. GDPR / employee-monitoring (EU — non-optional)

This is developer-activity monitoring; the operator is in the EU. In several jurisdictions (Germany's works councils being the sharpest), monitoring developer activity needs consent / works-council agreement, and `developer_ref` is personal data under GDPR.

Bake in from day one:
- `pseudonym` as the identity default (id→developer mapping stays on the team's side / local).
- A documented data-processing description + DPA template.
- A public "exactly what leaves the machine" page (§6). For this audience, that transparency page is not compliance overhead — it is the **single strongest trust asset** you can publish.

---

## 6. Public transparency page — draft ("What leaves your machine")

> ## What AgentAudit sends to the cloud (and what it never does)
>
> AgentAudit's recorder runs entirely on your machine. Your command history, your agents' prompts and outputs, your files — **none of it leaves.** The Team tier adds a shared dashboard by sending **only alerts**: the specific moments an agent did something sensitive *on its own, without a human approving it.*
>
> **What never leaves your machine (ever):**
> - Raw command text and full tool arguments
> - Agent prompts, drafts, tool outputs, file contents
> - Your full local audit log (`audit-forward.jsonl`) — it stays on disk, it's yours, it's the source of record
>
> **What an alert contains, by default:**
> - Which endpoint and (optionally) developer — pseudonymous unless you choose otherwise
> - When it happened
> - The MITRE ATT&CK technique it maps to (e.g. reading a private key)
> - The verdict: the agent acted **autonomously** and the action was **not approved** by a human
> - A SHA-256 hash of the command (lets us spot the same command across machines without seeing it)
> - A one-line *scrubbed* command (secrets already masked) — **and you can turn even this off**
> - A pointer to replay the full run locally on the affected machine
>
> **You hold the dial.** Set command sharing to `hash-only` or `off`; keep identities pseudonymous. In the tightest setting, an alert says *"this endpoint's agent read a private key on its own, unapproved — go look"* and nothing more.
>
> **Why this shape?** Because we're a security tool, and the fastest way to lose a security team's trust is to become the thing they have to worry about. We centralize the *verdict*, never your data. If our cloud were breached tomorrow, an attacker would learn which techniques your agents triggered — not your commands, code, or credentials.
>
> Here is the exact alert JSON schema: [link]. Here is our data-processing description and DPA: [link].

---

## 7. What this does NOT include (solo-founder discipline)

- No raw-log aggregation. No centralized policy push/enforcement (alert-only; enforcement stays local + opt-in). No custom rule builder, SAML/SCIM, RBAC beyond owner/member, SLA/HA/multi-region.
- The heavy compute (record, scrub, detect) runs on the OSS endpoint. The cloud is a thin alert roll-up + a maintained detection-rule feed + billing. That division is the entire reason a solo founder can run it.

---

*Companion: `docs/agent-audit-event-schema.md` (canonical v1.1 the alert derives from), `docs/agentaudit-schema-debate.md` (why initiator is separated from actor — the field that makes the verdict possible). Design only; build with paying design partners or not at all.*
