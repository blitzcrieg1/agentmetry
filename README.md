<div align="center">

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo/agentmetry-logo-white.svg">
    <img src="docs/logo/agentmetry-logo-black.svg" alt="Agentmetry" width="360" />
  </picture>
</p>

<h1>Agentmetry</h1>

<p><strong>A local flight recorder for AI coding agents.</strong><br/>
It records each tool call on the machine, tags the ones it recognises, and can forward that trail to a SIEM you already run.</p>

<p align="center">
  <a href="https://pypi.org/project/agentmetry/"><img src="https://img.shields.io/pypi/v/agentmetry?style=for-the-badge&color=006dad" alt="PyPI version"></a>
  <a href="https://github.com/blitzcrieg1/agentmetry/blob/master/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=for-the-badge" alt="Apache 2.0 License"></a>
  <a href="https://github.com/blitzcrieg1/agentmetry"><img src="https://img.shields.io/badge/status-public%20alpha-orange?style=for-the-badge" alt="Project status: public alpha"></a>
  <img src="https://img.shields.io/badge/CI-Windows%20%7C%20Linux-lightgrey?style=for-the-badge" alt="CI: Windows and Linux">
</p>

<p align="center">
  <a href="#quick-start"><strong>Quick start</strong></a> ·
  <a href="docs/agentmetry-external-ingest.md"><strong>Docs</strong></a> ·
  <a href="docs/agentmetry-event-schema.md"><strong>Schema</strong></a> ·
  <a href="https://github.com/blitzcrieg1/agentmetry/issues"><strong>Issues</strong></a> ·
  <a href="CONTRIBUTING.md"><strong>Contributing</strong></a>
</p>

</div>

<div align="center">

<a href="https://agentmetry.ai/#watch"><img src="https://agentmetry.ai/video/agentmetry-demo-poster.png" alt="The 90-second Agentmetry demo: agentmetry demo, a critical credential-exfil finding, an edited trail failing verify, and a SIEM outage that queues events instead of dropping them" width="720" /></a>

<p><em>Ninety seconds, recorded from real <code>agentmetry demo</code> and <code>agentmetry benchmark</code> output on 0.9.4.<br/><a href="https://agentmetry.ai/#watch">Watch it on agentmetry.ai</a>.</em></p>

</div>

---

Public alpha. Capture, sequence detection, and SIEM forwarding work. APIs and hook payloads can still change.

## Who it is for

Security engineers and developers who want a record of what a coding agent did at the tool boundary: which agent, which session, which call, in what order.

It is a sensor. The open-source package is not a console. Fleet questions are answered in the SIEM you forward to. A hosted fleet console is allowed for Agentmetry Enterprise and is not built. The sensor never needs that service to record or to forward. See [open-core split](docs/commercial/open-core-split.md).

It does not see an unmanaged browser chat, an IDE with hooks off, or an MCP server reached over HTTP instead of the stdio proxy. That is CASB or gateway territory.

## Quick start

Python 3.11 or newer. No server and no config file.

```bash
pip install agentmetry && agentmetry demo
agentmetry doctor
agentmetry benchmark
```

To see the demo without installing anything, `uvx agentmetry demo` (with
[uv](https://docs.astral.sh/uv/)) or `pipx run agentmetry demo` runs it from a
throwaway environment.

`agentmetry demo` replays a session through the real ingest path into a temp directory it deletes: a private-key read, a cloud key that DLP matches without storing the value, then a URL fetch. The sequence fires one critical `credential-exfil`. It then edits that finding and shows `verify` fail, re-hashes the file the way someone with the whole machine could, and shows `verify` pass again with a different chain head. That last step is what `agentmetry anchor` is for. Nothing is kept and nothing leaves the machine.

`agentmetry doctor` checks the install and exits 0 when nothing is broken. Warnings are expected on a fresh install: no trail yet, the orchestrator is not running, autostart is not registered.

`agentmetry benchmark` replays the detection corpus through the real rule engine and exits non-zero on a miss or a false positive. The figures it prints are below.

`agentmetry demo --scenario hf` replays the HF July 2026 patterns (`credential-read-then-cloud-api` and `remote-staging-then-execute`). `--scenario all` runs both.

An installed package keeps its trail, indexes, and API token in the user data directory: `%LOCALAPPDATA%\Agentmetry` on Windows, `~/.local/share/agentmetry` on Linux, `~/Library/Application Support/Agentmetry` on macOS. A git checkout keeps `apps/orchestrator/data`. `AGENTMETRY_DATA_DIR` overrides both. `doctor` prints the directory in use.

To record a real agent, then look at it:

```bash
agentmetry hooks install
agentmetry start
agentmetry dashboard
```

`agentmetry dashboard` opens a one-time sign-in link. The browser does not hold the API token.

## Agents and platforms

| Surface | What is recorded | How you turn it on |
| --- | --- | --- |
| Claude Code | Tool calls and a person's yes at a prompt, via hooks. Or, after the fact, via `agentmetry otel` (record only: no deny, no ask). Use one path. Both together record each call twice. | `agentmetry hooks install`, or `agentmetry otel` |
| Cursor | Tool calls and inferred approvals | `agentmetry hooks install` |
| Codex | Same. Codex skips untrusted hooks until its `/hooks` prompt is approved. | `agentmetry hooks install` |
| Qwen, Kimi, Qoder, CodeBuddy | Tool calls and inferred approvals | `agentmetry hooks install` |
| Antigravity | Tool calls and inferred approvals | `scripts/install_antigravity_hooks.ps1` on Windows. `hooks install` and `scripts/install.sh` do not write these. |
| MCP servers | Every stdio `tools/call`, plus a `tools/list` fingerprint | `agentmetry mcp-proxy -- <server command>` |
| CrewAI, OpenSRE | Framework adapters | [adapters/crewai](adapters/crewai/), [adapters/opensre](adapters/opensre/) |
| Microsoft Agent Governance Toolkit files | Import after the file's own chain verifies | `agentmetry import-agt` |

| OS | What is tested |
| --- | --- |
| Windows | CI on `windows-latest`, plus the `hooks-windows` job. PyPI classifier `Operating System :: Microsoft :: Windows`. |
| Linux | CI on `ubuntu-latest`, plus the `install-linux` job. PyPI classifier `Operating System :: POSIX :: Linux`. |
| macOS | The full test suite runs on `macos-latest` in CI since 2026-10-10, as a non-required check. That covers the per-user data directory, the launchd agent (`agentmetry install`) and the managed-hook paths. No hook has been exercised against a live agent on a Mac, and PyPI does not list a macOS classifier yet. |

CI is `.github/workflows/ci.yml`. The test matrix is `ubuntu-latest`, `windows-latest` and `macos-latest`. The macOS leg is not yet a required check.

## What you get

- **Sequence detections.** Fourteen published rules, plus one experimental rule (`autonomous-unapproved-write`) that stays registered and is not part of the published set: no IDE capture surface produces the signal it reads, and it is not exported to Sigma. Rules match ordered steps inside a session. `credential-exfil` is credential access, then network egress. Reversed, it does not fire. The list is [docs/detection-rules.md](docs/detection-rules.md).
- **MITRE ATT&CK tags** on tool calls the mapper recognises (`agentmetry/core/audit/mitre.py`). A call it does not recognise carries no tag.
- **MITRE ATLAS labels** on the subset where ATLAS says something ATT&CK cannot (`agentmetry/core/audit/atlas.py`, content release 2026.07). Five techniques are emitted: indirect prompt injection (`AML.T0051.001`), agent-tool credential harvesting (`AML.T0098`), exfiltration via tool invocation (`AML.T0086`), destruction via tool invocation (`AML.T0101`), and MCP supply-chain rug pull (`AML.T0109`). `AML.T0050` and `AML.T0053` are deliberately not emitted.
- **Canonical events, schema 1.2.0.** SHA-256 argument hashes by default. The secret value is not stored. Schema: [docs/agentmetry-event-schema.md](docs/agentmetry-event-schema.md).
- **SIEM and webhook export.** File (default, hash-chained JSONL), generic webhook, Elastic ECS, Splunk HEC, Google SecOps UDM, Microsoft Sentinel (not yet run against a live workspace), and CloudEvents v1.0 as a webhook format. Loki is Grafana Alloy tailing the local file, not a native sink. The same list is in the table below.
- **Claude Code OpenTelemetry ingest.** `agentmetry otel` is a loopback OTLP/HTTP JSON receiver. It shipped in 0.9.0. It does not export Agentmetry's own events as OTLP. That direction is not built.
- **Evidence.** `agentmetry verify --trail` checks the hash chain. `agentmetry anchor` publishes a checkpoint the host cannot rewrite. `agentmetry prove` is an inclusion proof for one event. `agentmetry export --evidence` writes an evidence pack. `agentmetry export --compliance-digest` is a period summary.

## Checked claims

These are the numbers from commands, not from a slide.

```
  cases            54 (26 attack, 28 benign)
  rules covered    13
  expected firings 26
  detected         26
  missed           0
  false positives  0
```

That block is what `agentmetry benchmark` printed from the PyPI 0.9.4 package and from this tree. "Rules covered 13" counts rule ids named in corpus expectations. Twelve of those are published rules. The thirteenth is the experimental rule. Two published rules have no corpus case: `host-subagent-swarm-burst` and `off-hours-activity`. They are named in `apps/orchestrator/tools/generate_sigma_pack.py` so the Sigma pack still has them.

1639 tests collected (`pytest --collect-only -q` from `apps/orchestrator`). A full run on Python 3.12 reported 1631 passed and 8 skipped, and 82% line coverage (`pytest -q --cov=agentmetry --cov-report=term`). CI fails the coverage job under 78%.

The corpus and the expectations live in [`apps/orchestrator/agentmetry/core/audit/detection/corpus/`](apps/orchestrator/agentmetry/core/audit/detection/corpus/).

## What it does not do

**Not a sandbox.** The default is detect and record. DLP and tool policy can deny a call at the hook, before it runs, when set to `block`. That is off by default (`log`). An after-the-fact hook cannot deny a tool that already ran.

**Not a CASB.** Hooks are cooperative. No event is not evidence that nothing happened.

**Not a console.** There is no central enforcement and no central triage in this package. Policy is per machine. See [fleet via your SIEM](docs/integrations/fleet-via-siem.md).

**Approvals are mostly inferred.** A tool that runs after a prompt is marked `inferred:*` and is not a record of a click. Claude Code's OTel stream is the exception: a person's yes is stored as an observed approval (`otel_decision:*`).

**The chain is not attribution.** Verification catches in-place edits, inserted or reordered lines, and forged appends. Anyone who can rewrite the file and the sidecar can produce a trail that verifies. `agentmetry anchor` is the check for that. The chain also does not prove who wrote a line.

What a token holder can and cannot claim is narrower than it sounds. `ExternalIngestBody` in `agentmetry/api/routes/audit.py` has no `host_id` or `fleet_id` field, and `agentmetry/core/audit/identity.py` stamps each event with the receiving orchestrator's hostname and its configured `fleet_id`. A client cannot claim to be another machine. It can claim another user: the hook reports the account that ran the agent, and `initiator.operator_source` says whether that id came from the caller (`hook_os`, `hook_configured`, `client`) or from the orchestrator. Anyone holding the API token can inject events that arrive stamped as the machine that accepted them.

**MITRE coverage is narrow on purpose.** It is not an official mapping and has not been through a MITRE evaluation.

**Microsoft Sentinel** has a sink and KQL docs. It has not yet run against a live workspace.

## Forwarding

The JSONL trail is the system of record. Network sinks tail it from a cursor and retry. The cursor moves only after a batch is accepted. `GET /api/v1/audit/status` reports each sink.

| Sink | Configuration |
| --- | --- |
| File (default) | `AGENTMETRY_AUDIT_SINK=file` |
| Webhook | `AGENTMETRY_AUDIT_SINK=webhook` and `AGENTMETRY_AUDIT_WEBHOOK_URL` |
| Enterprise batch webhook | webhook sink plus `AGENTMETRY_AUDIT_WEBHOOK_FORMAT=batch` (`{"events": [...]}`) |
| CloudEvents | webhook sink plus `AGENTMETRY_AUDIT_WEBHOOK_FORMAT=cloudevents` |
| Elastic ECS | `AGENTMETRY_AUDIT_SINK=elastic` |
| Splunk HEC | `AGENTMETRY_AUDIT_SINK=splunk` |
| Google SecOps | `AGENTMETRY_AUDIT_SINK=chronicle` |
| Microsoft Sentinel | `AGENTMETRY_AUDIT_SINK=sentinel`. [Setup](docs/integrations/sentinel.md). Not yet run against a live workspace. |
| Loki | Not a sink mode. Grafana Alloy tails the JSONL. [Homelab notes](docs/integrations/loki-homelab.md). |

Guides: [docs/integrations/](docs/integrations/). Detections are also a [Sigma pack](docs/integrations/sigma/README.md) (23 rules): 15 generated files for the 14 published sequence rules (`encoded-command-download` is two severities), plus 8 rules for recorder health and triage.

`agentmetry otel` receives Claude Code's stream. It does not replace hooks for policy. Mapped today: `tool_result` becomes `tool_called` or `tool_failed` (arguments only if `OTEL_LOG_TOOL_DETAILS=1`); a person's yes on `tool_decision` becomes an observed approval. Other documented types are counted, not dropped silently. Prompts are not forwarded. `--print-env` and `--print-mapping` print the rest.

## Dashboard recording

The player below is the local dashboard (event stream, detections, live feed). The CLI demo is the 90-second video at the top.

<!--
  Bare github.com/user-attachments URL, on its own line. See docs/readme-media.md.
-->

https://github.com/user-attachments/assets/edd2002e-47c1-4885-8500-b3651f648018

From a clone, `python scripts/demo_dashboard.py` seeds a local dashboard. Build `apps/dashboard` first (`npm install && npm run build`). The script says so if the export is missing.

## CLI Reference

`agentmetry` from `pip install agentmetry`. In a clone, use the orchestrator venv.

| Command | What it does |
| --- | --- |
| `agentmetry demo` | Replay an attack session in-process, then tamper with the trail and show `verify` catch it. `--scenario hf` or `--scenario all`. Nothing is kept. |
| `agentmetry doctor` | Preflight. `--fix` creates a portable `drivers.json` in a checkout. |
| `agentmetry benchmark` | Replay the detection corpus and score the rules. |
| `agentmetry start` / `agentmetry stop` / `agentmetry status` | Run the orchestrator detached, stop it, or check health. |
| `agentmetry serve` | Foreground process that autostart registers. |
| `agentmetry install` / `agentmetry uninstall` | Start at logon and restart on failure. Task Scheduler on Windows, a systemd user unit on Linux, a launch agent on macOS. |
| `agentmetry hooks install` | Write hook configs for supported agents found on the machine. `agentmetry hooks status` exits 0, 1, or 2. |
| `agentmetry hook` | Forward one IDE hook event. Hook configs should call `agentmetry-hook` instead. |
| `agentmetry otel` | Receive Claude Code's OpenTelemetry stream. No hooks required. |
| `agentmetry mcp-proxy` | Wrap a stdio MCP server command. |
| `agentmetry mcp` | List MCP servers configured for agents on this machine. |
| `agentmetry dashboard` | Open the dashboard signed in. |
| `agentmetry logs` | Tail the orchestrator log. |
| `agentmetry stats` | Trail metrics. `agentmetry stats --days 7`. |
| `agentmetry detections` | List detections for one session, via the API. |
| `agentmetry disposition` | Set a detection's triage status. `false_positive` and `risk_accepted` require `--note`. |
| `agentmetry replay` | ASCII timeline of one session from the trail. |
| `agentmetry export` | `--evidence` or `--compliance-digest`. |
| `agentmetry verify` | Recompute an evidence-pack hash, or `agentmetry verify --trail` for the JSONL chain. |
| `agentmetry trail` | `rotate` or `segments`. See [trail retention](docs/trail-retention.md). |
| `agentmetry anchor` | Publish a checkpoint. See [anchoring](docs/anchoring.md). |
| `agentmetry prove` | Inclusion proof for one record, or `--check` to verify one. |
| `agentmetry import-agt` | Ingest a Microsoft Agent Governance Toolkit audit file. |
| `agentmetry backup` / `agentmetry restore` | Zip the data stores, or restore one with the server stopped. |
| `agentmetry dogfood` | Score the beta gate, or `--start` its clock. |

Clone installers, not part of the wheel: `scripts/install.ps1` (Windows) and `scripts/install.sh` (Linux and macOS). `scripts/otel_receiver.py` is a shim for `agentmetry otel`.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md). Issues: [github.com/blitzcrieg1/agentmetry/issues](https://github.com/blitzcrieg1/agentmetry/issues). Roadmap: [ROADMAP.md](ROADMAP.md).

| Area | Start here |
| --- | --- |
| Hooks | [docs/agentmetry-external-ingest.md](docs/agentmetry-external-ingest.md) |
| Schema | [docs/agentmetry-event-schema.md](docs/agentmetry-event-schema.md) |
| Detection rules | [docs/detection-rules.md](docs/detection-rules.md) and the corpus under `apps/orchestrator/agentmetry/core/audit/detection/corpus/` |
| DLP rules | `apps/orchestrator/agentmetry/policies/dlp/manifest.yaml` |
| Sigma | [docs/integrations/sigma/README.md](docs/integrations/sigma/README.md) |

PRs need a signed [CLA](CLA.md) (v1.0).

## Security

The trail stays on the machine unless you set a sink. Tool arguments are SHA-256 by default. Set `AGENTMETRY_HASH_KEY` and the fingerprints are HMAC-SHA256. Every API route except health needs the per-install token or `AGENTMETRY_API_KEY`. `AGENTMETRY_AUTH_DISABLED=1` is for development, and `doctor` flags it.

Report vulnerabilities via [private vulnerability reporting](https://github.com/blitzcrieg1/agentmetry/security/advisories/new). See [SECURITY.md](SECURITY.md).

## License

Apache-2.0, Copyright 2026 blitzcrieg1. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Companies use [CCLA.md](CCLA.md). Trademark: [TRADEMARK.md](TRADEMARK.md). Commercial intent, non-binding: [COMMERCIAL.md](COMMERCIAL.md).

## Maintainer

Built and maintained by Ioannis L. [LinkedIn](https://www.linkedin.com/in/ioannis-l-074439194/).
