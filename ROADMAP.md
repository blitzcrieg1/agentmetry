# Roadmap

**Last refreshed: 2026-10-23.** State, not aspiration. Dates are absolute,
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

## Where this actually is, on 2026-10-23

| | |
|---|---|
| Version | 0.10.2 on PyPI, released 2026-10-25: `agentmetry scan` checks the instruction files an agent loads by itself (AGENTS.md, CLAUDE.md and their siblings) for installing a named package, naming the agent's own endpoint or config, and sitting in Downloads or on the Desktop, after a malicious AGENTS.md in a Downloads folder was reported that day; and the config block rule covers Codex's `apply_patch` and the Codex, Gemini and Cursor config files ([#336](https://github.com/blitzcrieg1/agentmetry/pull/336)). 0.10.1, 2026-10-23, the first package with the dashboard inside it ([#330](https://github.com/blitzcrieg1/agentmetry/pull/330)); 0.10.0 had none, and `stats` and `detections` reported an empty trail. 0.10.0, the same day: `agentmetry scan` and the MCP proxy's check on every tool description ([#322](https://github.com/blitzcrieg1/agentmetry/pull/322)), Codex hooks that launch on Windows and stay trusted once approved ([#307](https://github.com/blitzcrieg1/agentmetry/issues/307), [#308](https://github.com/blitzcrieg1/agentmetry/pull/308)), an ingest-only token for Codex's sandbox ([#302](https://github.com/blitzcrieg1/agentmetry/issues/302)), ingest rate limits ([#312](https://github.com/blitzcrieg1/agentmetry/issues/312)), and the redesigned Overview and investigation ([#309](https://github.com/blitzcrieg1/agentmetry/pull/309), [#310](https://github.com/blitzcrieg1/agentmetry/pull/310), [#321](https://github.com/blitzcrieg1/agentmetry/pull/321)). 0.9.8 and 0.9.9, between it and 0.9.7, brought the first Overview and managed policy for fleets. Since 0.9.4, `pip install agentmetry && agentmetry demo` shows a detection fire and an edited trail fail `verify`, with no clone |
| Canonical event schema | 1.2.0, additive |
| Detection rules | 14 published sequence rules plus 1 experimental, ATT&CK on every event, ATLAS on the AI-specific subset. All 14 exported as Sigma, generated from the engine |
| Benchmark | 57 recorded sessions, 26 attack and 31 benign, 0 missed and 0 false positives. The four known FPs are now *in* the corpus |
| Tests | 1986 collected. CI on 2026-10-23: 1967 passed and 19 skipped on Linux and macOS, 1980 passed and 6 skipped on Windows, 82% line coverage against a 78% floor |
| Dogfood gate | **Passed 2026-10-02, and still passing.** Run started 2026-08-30. Weeks 6 and 7 were red on 1 and 7 untriaged critical or high detections until all 16 open ones were triaged on 2026-10-23; `dogfood` then printed every complete week green, "7 of 4, Gate PASSED". The three false-positive shapes that triage found are [#329](https://github.com/blitzcrieg1/agentmetry/issues/329) |
| Own trail | 74,923 hash-chained lines, all verified on the maintainer's machine on 2026-10-23 (`agentmetry verify --trail`). 256 anchor checkpoints cover records 1 to 74,704; the 219 newer records are chain-verified only until the next checkpoint |
| Adoption | Public alpha. No design partner tenant yet and no reference customer. No sales message has gone out yet: the first ones are drafted and re-verified against live postings on 2026-10-24. 15 GitHub stars on 2026-10-23 |

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
| Public claims match shipped behaviour | Done, and it had drifted. A README audit on 2026-10-02 found a documented command that no longer ran (`python -m cli benchmark`), a `replay` that cannot show a hook session ([#209](https://github.com/blitzcrieg1/agentmetry/issues/209)), and a stale Node requirement. Fixed in the same refresh as this file. It drifted again: on 2026-10-08 the README's demo had been broken since 0.9.3 and was not in the wheel at all. Fixed in 0.9.4 ([#225](https://github.com/blitzcrieg1/agentmetry/pull/225)) |

The third gate is the one with no plan attached, and it is a real gap: every
`doctor` result on record comes from one machine. A pilot tenant closes it as a
side effect, which is another argument for the ordering below.

---

## Now

Ordered by what unblocks the most. Only the first item is not code, and it is
the most important one on the page.

| Item | Issue | Why now |
|---|---|---|
| **First design partner contact** | none, tracked in the enterprise repo | No message sent yet. The first two are drafted and their postings re-checked live on 2026-10-24; a third (a new signal) and two peer critique-asks are ready. Four of the six hiring signals the pipeline was built on in August had closed by the time they were checked in late October: a signal is perishable, so send within days of finding one. Nothing else on this list matters as much |
| The last detection precision fix | [#55](https://github.com/blitzcrieg1/agentmetry/issues/55) | Held for the dogfood run, which has passed. #44, #49, #50 and #51 were fixed in 0.7.0; this is the one left. It moves the ruleset fingerprint, so land it in one pass. Whether the freeze ends for it is the maintainer's call and has not been made |
| `session-tool-burst` noise | [#172](https://github.com/blitzcrieg1/agentmetry/issues/172) | Seven of every ten triage items when the issue was filed, on intended work, and the rule that held weeks 2 and 4 of the passing run at red. A rule change, so it belongs in the same pass as #55. The agent-specific signals in [#317](https://github.com/blitzcrieg1/agentmetry/issues/317) come after that pass, not in it |
| Decide the two cloud PRs | [#298](https://github.com/blitzcrieg1/agentmetry/pull/298), [#299](https://github.com/blitzcrieg1/agentmetry/pull/299) | A Cloud Bridge crash fix and Cursor cloud-agent capture, open since 2026-10-21 while later work merged around them. Merge or close; do not let them drift |
| Finish removing the old runtime | [#209](https://github.com/blitzcrieg1/agentmetry/issues/209) | Boot no longer mounts the driver host unless `AGENTMETRY_LEGACY_DRIVERS=1`, and `replay` reads the trail. What remains is the outbox, the vault demo, and the `mcp<2` pin those leftovers still require |

**The freeze held for the run that passed.** The ruleset fingerprint covers
`detection/rules.py`, `detection/traits.py`, `detection/engine.py`,
`audit/mitre.py` and the detection manifest, and none of them moved between
2026-08-30 and the pass. Moving it now restarts nothing that is running; it
matters again only when a new run starts.

---

## Next (October to November 2026)

Reordered 2026-08-23 around one test: **does this item make the sensor land in
somebody else's SIEM?** The three at the top are what a security team touches
before they touch anything this project renders itself. Everything the dashboard
wants has moved to the bottom of the page.

| Item | Issue | Note |
|---|---|---|
| **Splunk TA through AppInspect and a Splunkbase listing** | [enterprise #8](https://github.com/blitzcrieg1/agentmetry-enterprise/issues/8) | The TA works and has tests. It is a directory you copy onto a search head, which is a different conversation from a listing a security team can find. No public copy claims certification until it exists |
| **Per-host identity on a fleet trail** | [enterprise #1](https://github.com/blitzcrieg1/agentmetry-enterprise/issues/1) | First cut shipped: the sensor exposes a signing extension point (`register_event_signer()`, tested), the enterprise layer holds the Ed25519 device key, and the console refuses unsigned or foreign-signed events. Remaining: the key moves into the OS keystore instead of a file, replay hardening, and a run on a real fleet. Until that run, treat attribution as demonstrated, not proven at fleet scale |
| Run the recorder under its own account | [#313](https://github.com/blitzcrieg1/agentmetry/issues/313) | The recorder runs as the developer, so the developer's agent can read the full API token, read the trail and close its own detections; SECURITY.md says so. Hooks already send with the ingest-only token; the recorder is the remaining gap |
| HMAC argument hashing on fleet installs | [#314](https://github.com/blitzcrieg1/agentmetry/issues/314) | Arguments are plain SHA-256 unless a hash key is set, so anyone with SIEM read access can confirm a guessable argument by hashing it. On a fleet install, `doctor` should fail without a key |
| Heartbeat degrades on a stale anchor or a broken chain | [#318](https://github.com/blitzcrieg1/agentmetry/issues/318) | The heartbeat exists; it does not yet say when the trail's own guarantees have lapsed |
| Run every surface that was built from docs | [#316](https://github.com/blitzcrieg1/agentmetry/issues/316) | Codex deny was run live on 2026-10-22. Copilot deny in VS Code's agent host, the Sentinel sink against a real workspace, and hooks on macOS have not been |
| Coverage cannot see Codex's approval state | [#300](https://github.com/blitzcrieg1/agentmetry/issues/300) | `doctor` now names an agent that is configured and silent, which catches it after the fact. Reading approval directly is still open |
| OTLP **export** | [#315](https://github.com/blitzcrieg1/agentmetry/issues/315) | The other direction from `agentmetry otel`, which shipped in 0.9.0 as ingest. Table stakes for teams standardised on a collector |
| Tool response sizes in the trail | [#45](https://github.com/blitzcrieg1/agentmetry/issues/45) | The trail cannot tell a config lookup from a database dump. Claude Code's OTel stream carries `tool_result_size_bytes`, which the receiver does not map yet |
| Unwrapped MCP servers have no fingerprint | [#169](https://github.com/blitzcrieg1/agentmetry/issues/169) | Part 1 shipped in 0.9.2: the inventory reaches the SIEM as an opt-in `mcp_inventory` event. A server in a config file but not behind the proxy is still listed and not fingerprinted |
| Unattended sessions distinguishable from supervised ones | [#170](https://github.com/blitzcrieg1/agentmetry/issues/170) | An auto-mode session reads the same as one a person is watching |
| Per-project scoping | [#37](https://github.com/blitzcrieg1/agentmetry/issues/37) | One trail currently mixes every repo on a machine |
| Benchmark coverage for the uncovered rules | [#36](https://github.com/blitzcrieg1/agentmetry/issues/36) [#25](https://github.com/blitzcrieg1/agentmetry/issues/25) | Corpus expectations name 13 rule ids: 12 of the 14 published rules, plus the experimental rule. `host-subagent-swarm-burst` and `off-hours-activity` have no corpus case. Benign sessions harvested from the real trail beat invented ones |
| Agent-specific detection signals | [#317](https://github.com/blitzcrieg1/agentmetry/issues/317) | Five candidate traits and rules for after the freeze: an agent editing its own hook or settings file, a write outside the workspace, a typosquatted install, a CI config edit then a push, and an MCP server called after its schema changed (ATLAS AML.T0109). The ATLAS enrichment itself shipped in 0.5.0, which is why #47 is closed |

### Held until a design partner replies

Filed 2026-10-10 from a look at the field (Numbat, AgentSight, AgentTrail). They
are features, and the standing rule is no new features until a prospect answers,
so they wait in this order. None touches a frozen detection file.

| Item | Issue | Note |
|---|---|---|
| Backtest a rule over your own recent trail | [#230](https://github.com/blitzcrieg1/agentmetry/issues/230) | The engine already replays the corpus; this replays the operator's last N days, read-only |
| Rebuild past sessions from the agents' own logs | [#231](https://github.com/blitzcrieg1/agentmetry/issues/231) | The largest gap on the list: it is what answers "before install, or with hooks off". Labelled as reconstructed, never as live capture |
| Import Numbat and AgentSight output | [#232](https://github.com/blitzcrieg1/agentmetry/issues/232) | Adapters like the AGT importer. Puts the trail and the SIEM output under them instead of competing for the install |
| Signed standalone binaries | [#233](https://github.com/blitzcrieg1/agentmetry/issues/233) | After EV signing, and only if the hook's cold start does not get slower |
| An MCP server's blast radius, not only its presence | [#292](https://github.com/blitzcrieg1/agentmetry/issues/292) | Filed 2026-10-20 with the three below |
| Local honeytokens | [#293](https://github.com/blitzcrieg1/agentmetry/issues/293) | Decoy credentials whose use is a near-certain finding |
| Guardrail receipts | [#294](https://github.com/blitzcrieg1/agentmetry/issues/294) | Other guardrails' allow and deny decisions, recorded in the trail |
| Time and token breakdown by task, agent and tool | [#295](https://github.com/blitzcrieg1/agentmetry/issues/295) | A cost view, not a security one, which is why it is last |

---

## Later, or only if somebody asks

- `EventStore` protocol before a second storage backend
  ([#35](https://github.com/blitzcrieg1/agentmetry/issues/35))
- A Windsurf hook installer
  ([#7](https://github.com/blitzcrieg1/agentmetry/issues/7)). Copilot's
  shipped in 0.9.6
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

**That page predates September 2026, and the field moved under it.** Hook-based
control of coding agents is now a feature of the large endpoint vendors
(CrowdStrike Falcon, Microsoft Defender in preview, Palo Alto Networks through
Koi) and of Noma, Zenity, Pillar and Straiker, per
[Pillar's own roundup](https://www.pillar.security/blog/best-ai-coding-agent-security-tools-for-the-enterprise-2026).
In the open, Perplexity's [Numbat](https://github.com/perplexityai/numbat)
(Apache-2.0, a single Go binary) reads the same hooks and session files and
fires on the same kind of sequence, and is now the closest peer on capture.
They sell blocking and inventory inside a sensor the customer already pays
for, which is a race this project does not enter. What still none of them
publishes is a record a third party can check: the chain, Merkle inclusion
proofs, external anchors, Sigma generated from the engine, and the benchmark.
The compare page needs these rows, honestly, including where they win.

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
