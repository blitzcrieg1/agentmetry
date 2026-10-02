# Roadmap

**Last refreshed: 2026-10-02.** State, not aspiration. Dates are absolute,
because the previous version phased everything in "weeks 3 to 6" from a July
start and every window had elapsed while the file still read as current.

The open-source project is a **local-first endpoint sensor for AI coding
agents**: it records what an agent did at the tool boundary, correlates
sequences, and forwards into the SIEM you already run. Not a sandbox, not a
CASB, and it never depends on a hosted service.

Agentmetry Enterprise is a separate product, and it may be hosted: a fleet
console, managed ingest and cross-machine views are in scope for it. Decided
2026-10-02, replacing "no vendor control plane, in either repo".

Nothing here is a promise with a date attached. It is what is being worked on,
in what order, and why.

---

## How this file stays honest

It did not, and that cost something real: an external audit in August 2026 read
this file as current and produced six findings that were already fixed, plus a
competitor list lifted from a section that was months out of date.

Two rules, so it does not happen again.

- **Shipped work leaves this file.** It belongs in
  [CHANGELOG.md](CHANGELOG.md), which is written per release and is the record.
  A roadmap that accumulates a "Shipped" section becomes a second, worse
  changelog that nobody updates.
- **Every item names an issue.** If it is worth planning it is worth a number
  somebody else can read, comment on, and close.

---

## Where this actually is, on 2026-10-02

| | |
|---|---|
| Version | 0.9.1 on PyPI, released 2026-10-02 |
| Canonical event schema | 1.2.0, additive |
| Detection rules | 14 published sequence rules plus 1 experimental, ATT&CK on every event, ATLAS on the AI-specific subset. All 14 exported as Sigma, generated from the engine |
| Benchmark | 54 recorded sessions, 26 attack and 28 benign, 0 missed and 0 false positives. The four known FPs are now *in* the corpus |
| Tests | 1404 passing, 82% coverage, a 78% floor enforced in CI |
| Dogfood gate | **4 of 4, passed 2026-10-02.** Run started 2026-08-30. Weeks 2 and 4 were red only on untriaged detections, and turned green when they were triaged, which is how the gate is designed to work |
| Own trail | 50,704 hash-chained lines, 170 external checkpoints |
| Adoption | Public alpha. No design partner tenant yet, no reference customer |

The last row is the one that matters. Engineering is further along than
distribution by a wide margin, and the ordering below reflects that.

---

## The commercial question, resolved

The previous version of this file said *"design partner / paid pilot: defer
until after beta"* while [agentmetry.ai/pilot](https://agentmetry.ai/pilot) was
live and a ten-account pipeline sat in the enterprise repo. One of those was
wrong.

**Resolved in favour of the pilot.** A design partner engagement is what
*produces* beta evidence rather than something that waits for it: the MSI, the
Intune remediation pair and the Splunk TA have never run against a tenant that
is not this one, and no amount of local testing changes that. The pilot page
already states the limits plainly, which is what makes offering it before beta
defensible rather than reckless.

Beta is still gated on the list below. It is not gated on a signature, and a
signature is not gated on it.

---

## Beta gates

Declare beta when all four are true. Three are.

| Gate | Status |
|---|---|
| Four consecutive green dogfood weeks | **Passed 2026-10-02**, weeks 1 to 4 of the run that started 2026-08-30 |
| `agentmetry verify --trail` demonstrated in the README | Done |
| `agentmetry doctor` green on three distinct Windows 11 setups | **1 of 3.** Needs two machines that are not the maintainer's |
| Public claims match shipped behaviour | Done, and it had drifted. A README audit on 2026-10-02 found a documented command that no longer ran (`python -m cli benchmark`), a `replay` that cannot show a hook session ([#209](https://github.com/blitzcrieg1/agentmetry/issues/209)), and a stale Node requirement. Fixed in the same refresh as this file |

The third gate is the one with no plan attached, and it is a real gap: every
`doctor` result on record comes from one machine. A pilot tenant closes it as a
side effect, which is another argument for the ordering below.

---

## Now

Ordered by what unblocks the most. Only the first item is not code, and it is
the most important one on the page.

| Item | Issue | Why now |
|---|---|---|
| **First design partner contact** | none, tracked in the enterprise repo | Zero messages sent against ten researched accounts. The dogfood gate passing is the checkable fact the openers were missing. Nothing else on this list matters as much |
| The last detection precision fix | [#55](https://github.com/blitzcrieg1/agentmetry/issues/55) | Held for the dogfood run, which has now passed. #44, #49, #50 and #51 were fixed in 0.7.0; this is the one left. It moves the ruleset fingerprint, so land it in one pass |
| `session-tool-burst` noise | [#172](https://github.com/blitzcrieg1/agentmetry/issues/172) | Every detection that held a week at red in the run was this rule, on intended work. A rule change, so it belongs in the same pass as #55 |
| Evidence pack integrity covers `meta` | [#75](https://github.com/blitzcrieg1/agentmetry/issues/75) | The date range on an evidence pack can currently be rewritten without breaking the hash. Needs a schema bump so existing packs keep verifying |
| The removed runtime out of the boot path, `replay` on the trail | [#209](https://github.com/blitzcrieg1/agentmetry/issues/209) | The orchestrator still mounts the old runtime's MCP host on every boot, `replay` reads only its outbox, and it holds `mcp` below 2 |

**The freeze held for the run that passed.** The ruleset fingerprint covers
`detection/rules.py`, `detection/traits.py`, `detection/engine.py`,
`audit/mitre.py` and the detection manifest, and none of them moved between
2026-08-30 and the pass. Moving it now restarts nothing that is running; it
matters again only when a new run starts.

---

## Next (September to October 2026)

Reordered 2026-08-23 around one test: **does this item make the sensor land in
somebody else's SIEM?** The three at the top are what a security team touches
before they touch anything this project renders itself. Everything the dashboard
wants has moved to the bottom of the page.

| Item | Issue | Note |
|---|---|---|
| **Splunk TA through AppInspect and a Splunkbase listing** | [enterprise #8](https://github.com/blitzcrieg1/agentmetry-enterprise/issues/8) | The TA works and has tests. It is a directory you copy onto a search head, which is a different conversation from a listing a security team can find. No public copy claims certification until it exists |
| **Per-host identity on a fleet trail** | [enterprise #1](https://github.com/blitzcrieg1/agentmetry-enterprise/issues/1) | A fleet trail is tamper-evident and not yet attributable. Ed25519 per host, so a forwarded event says which machine signed it |
| OTLP **export** | none yet | The other direction from `agentmetry otel`, which shipped in 0.9.0 as ingest. Table stakes for teams standardised on a collector |
| Tool response sizes in the trail | [#45](https://github.com/blitzcrieg1/agentmetry/issues/45) | The trail cannot tell a config lookup from a database dump. Claude Code's OTel stream carries `tool_result_size_bytes`, which the receiver does not map yet |
| MCP server inventory as an event | [#169](https://github.com/blitzcrieg1/agentmetry/issues/169) | `agentmetry mcp` lists what the agents are wired to, but the SIEM never sees it |
| Unattended sessions distinguishable from supervised ones | [#170](https://github.com/blitzcrieg1/agentmetry/issues/170) | An auto-mode session reads the same as one a person is watching |
| Per-project scoping | [#37](https://github.com/blitzcrieg1/agentmetry/issues/37) | One trail currently mixes every repo on a machine |
| Benchmark coverage for the six uncovered rules | [#36](https://github.com/blitzcrieg1/agentmetry/issues/36) [#25](https://github.com/blitzcrieg1/agentmetry/issues/25) | 13 of 15 rules have corpus coverage. Benign sessions harvested from the real trail beat invented ones |
| Agent-directed technique taxonomy | [#47](https://github.com/blitzcrieg1/agentmetry/issues/47) | Partly addressed by the ATLAS layer in 0.5.0. Reassess what is genuinely still unlabelled |

---

## Later, or only if somebody asks

- `EventStore` protocol before a second storage backend
  ([#35](https://github.com/blitzcrieg1/agentmetry/issues/35))
- Windsurf and VS Code Copilot hook installers
  ([#7](https://github.com/blitzcrieg1/agentmetry/issues/7))
- MCP audit proxy over SSE and streamable HTTP, not only stdio
- STIX/TAXII export of detections
- DLP beyond regex. Real, and it waits for revenue

### The dashboard, last on purpose

It is a **local inspection surface for the machine the sensor runs on**, and it
stays one. Fleet views belong to Agentmetry Enterprise: the Splunk app in the
enterprise repo today, and possibly a hosted console later. A fleet triage queue
built here would be the second-best version of either.

It is not being deleted and it is not unmaintained: it builds in CI, and the
Next 16 migration went in because dependency alerts had to close, not because a
screen needed adding. That is the level of attention it gets.

- Keyboard triage queue for the Detections tab
  ([#27](https://github.com/blitzcrieg1/agentmetry/issues/27))
- Remove the removed product's state model
  ([#26](https://github.com/blitzcrieg1/agentmetry/issues/26))
- Work through the 12 `set-state-in-effect` sites and let the rule error again
  ([#95](https://github.com/blitzcrieg1/agentmetry/issues/95))

---

## Where this sits against what else exists

Maintained at **[agentmetry.ai/compare](https://agentmetry.ai/compare)**, with
the rows where each alternative wins. Not duplicated here, because a
competitive section in a roadmap is exactly what went stale last time.

The short version: Claude Code's native OpenTelemetry is the most important
alternative, and it is ingested rather than argued with (`agentmetry otel`,
0.9.0). MintMCP is the
closest peer on capture and is ahead on everything procurement measures.
Prompt Security, inside SentinelOne, covers the unmanaged-agent gap this
project refuses to claim. What nobody else on that page offers is a local
hash-chained trail the customer owns, cross-agent correlation, and a detection
benchmark a sceptic can run in ten seconds.

---

## Not building

Stated so the answer is on record rather than re-argued.

- A hosted dependency in the open-source sensor. It records on the machine and
  forwards only where the operator points it, and that does not change. A
  hosted Agentmetry Enterprise, if it is built, is a separate product the
  sensor never needs
- CASB or shadow-AI discovery. Different sensor, different category, and
  [others do it](https://agentmetry.ai/compare)
- ML guardrails and prompt firewalls. A recorder does not need a model
- An agent runtime, a skill kernel, or a LangGraph rewrite. Removed once
  already and staying removed
- Autonomous remediation. Blocking is opt-in, at the hook boundary, and stays
  the smaller half of the product

---

## Helping

The most useful contributions are small, testable and self-contained:
**detection rules**, **DLP patterns**, **SIEM adapters**, **YAML rules**, and
**benchmark corpus cases**. A case that makes a rule fire when it should not is
worth more than a case that confirms it works.

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[good first issues](https://github.com/blitzcrieg1/agentmetry/labels/good%20first%20issue).

Being told a detection is wrong is worth more than being told it is right. If a
rule fires on something legitimate on your machine, that is the highest-value
issue you can open.
