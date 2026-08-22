# Roadmap

**Last refreshed: 2026-08-22.** State, not aspiration. Dates are absolute,
because the previous version phased everything in "weeks 3 to 6" from a July
start and every window had elapsed while the file still read as current.

Agentmetry is a **local-first endpoint sensor for AI coding agents**: it records
what an agent did at the tool boundary, correlates sequences, and forwards into
the SIEM you already run. Not a console, not a sandbox, not a CASB.

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

## Where this actually is, on 2026-08-22

| | |
|---|---|
| Version | 0.5.0 on PyPI, released 2026-08-21 |
| Canonical event schema | 1.2.0, additive |
| Detection rules | 15 sequence rules, ATT&CK on every event, ATLAS on the AI-specific subset |
| Benchmark | 50 recorded sessions, 26 attack and 24 benign, 0 missed and 0 false positives |
| Tests | 1113 passing, 81% coverage, floor enforced in CI |
| Dogfood gate | **2 of 4 consecutive green weeks**, clock started 2026-08-08 |
| Own trail | 27,504 hash-chained lines, 24 external anchors |
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

Declare beta when all four are true. Two are.

| Gate | Status |
|---|---|
| Four consecutive green dogfood weeks | **2 of 4.** Week 3 in progress. Earliest close **2026-09-04** |
| `agentmetry verify --trail` demonstrated in the README | Done |
| `agentmetry doctor` green on three distinct Windows 11 setups | **1 of 3.** Needs two machines that are not the maintainer's |
| Public claims match shipped behaviour | Done. `/compare`, the limitations section and the benchmark all state numbers the reader can reproduce |

The third gate is the one with no plan attached, and it is a real gap: every
`doctor` result on record comes from one machine. A pilot tenant closes it as a
side effect, which is another argument for the ordering below.

---

## Now (through 2026-09-05)

Ordered by what unblocks the most. Only the first item is not code, and it is
the most important one on the page.

| Item | Issue | Why now |
|---|---|---|
| **First design partner contact** | none, tracked in the enterprise repo | Zero messages sent against ten researched accounts. Nothing else on this list matters as much |
| Detection precision pass | [#44](https://github.com/blitzcrieg1/agentmetry/issues/44) [#49](https://github.com/blitzcrieg1/agentmetry/issues/49) [#50](https://github.com/blitzcrieg1/agentmetry/issues/50) [#51](https://github.com/blitzcrieg1/agentmetry/issues/51) [#55](https://github.com/blitzcrieg1/agentmetry/issues/55) | Five false-positive sources in frozen files. Land as one pass with #55 first, after the dogfood gate closes, so the ruleset fingerprint moves once |
| Evidence pack integrity covers `meta` | [#75](https://github.com/blitzcrieg1/agentmetry/issues/75) | The date range on an evidence pack can currently be rewritten without breaking the hash. Needs a schema bump so existing packs keep verifying |
| Work the Dependabot queue | n/a | 15 open. The four GitHub Actions bumps touch `release.yml` and want the dry run before merging |

**Held deliberately until 2026-09-05:** anything that edits
`detection/rules.py`, `detection/traits.py`, `detection/engine.py` or
`audit/mitre.py`, and anything that edits the detection manifest those four are
hashed alongside. Together they are the ruleset fingerprint, and moving it
restarts the dogfood clock. Four green weeks measured against four different
rulesets is not a number worth quoting, which is why the freeze is checkable
rather than promised.

---

## Next (September to October 2026)

| Item | Issue | Note |
|---|---|---|
| **Ingest Claude Code OpenTelemetry as a third capture tier** | [#56](https://github.com/blitzcrieg1/agentmetry/issues/56) | Anthropic ships observed approval decisions we currently infer. Ingesting beats competing, and it closes [#45](https://github.com/blitzcrieg1/agentmetry/issues/45) for free. Reasoning in [the notes](https://agentmetry.ai/blog/why-not-just-opentelemetry) |
| Tool response sizes in the trail | [#45](https://github.com/blitzcrieg1/agentmetry/issues/45) | The trail cannot tell a config lookup from a database dump |
| Per-project scoping | [#37](https://github.com/blitzcrieg1/agentmetry/issues/37) | One trail currently mixes every repo on a machine |
| Benchmark coverage for the six uncovered rules | [#36](https://github.com/blitzcrieg1/agentmetry/issues/36) [#25](https://github.com/blitzcrieg1/agentmetry/issues/25) | 13 of 15 rules have corpus coverage. Benign sessions harvested from the real trail beat invented ones |
| Agent-directed technique taxonomy | [#47](https://github.com/blitzcrieg1/agentmetry/issues/47) | Partly addressed by the ATLAS layer in 0.5.0. Reassess what is genuinely still unlabelled |
| OTLP **export** | none yet | Distinct from #56, which is ingest. Table stakes for teams standardised on a collector |

---

## Later, or only if somebody asks

- `EventStore` protocol before a second storage backend
  ([#35](https://github.com/blitzcrieg1/agentmetry/issues/35))
- Windsurf and VS Code Copilot hook installers
  ([#7](https://github.com/blitzcrieg1/agentmetry/issues/7))
- Dashboard triage queue ([#27](https://github.com/blitzcrieg1/agentmetry/issues/27))
- MCP audit proxy over SSE and streamable HTTP, not only stdio
- STIX/TAXII export of detections
- DLP beyond regex. Real, and it waits for revenue

---

## Where this sits against what else exists

Maintained at **[agentmetry.ai/compare](https://agentmetry.ai/compare)**, with
the rows where each alternative wins. Not duplicated here, because a
competitive section in a roadmap is exactly what went stale last time.

The short version: Claude Code's native OpenTelemetry is the most important
alternative and is being ingested rather than argued with. MintMCP is the
closest peer on capture and is ahead on everything procurement measures.
Prompt Security, inside SentinelOne, covers the unmanaged-agent gap this
project refuses to claim. What nobody else on that page offers is a local
hash-chained trail the customer owns, cross-agent correlation, and a detection
benchmark a sceptic can run in ten seconds.

---

## Not building

Stated so the answer is on record rather than re-argued.

- Multi-tenant cloud SaaS or any vendor control plane. The local-first
  property is the product, not a stage it grows out of
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
