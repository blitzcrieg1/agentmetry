# Agentmetry

A local-first endpoint sensor for AI coding agents.

Agentmetry hooks the tool lifecycle of Claude Code, Cursor, Codex, GitHub Copilot,
Antigravity, Qwen, Kimi, Qoder and CodeBuddy, writes every tool call, approval and
denial to a hash-chained JSONL trail on your machine, and runs sequence detection
over the session. A credential read followed by network egress becomes one finding
rather than two unremarkable log lines. Findings carry MITRE ATT&CK labels, and
MITRE ATLAS labels where ATLAS says something ATT&CK cannot.

Nothing leaves the machine unless you configure it, and there is no telemetry.
Forwarding to Splunk HEC, Elastic ECS, Google SecOps, Microsoft Sentinel or a
webhook (canonical JSON or CloudEvents) is off by default.

## Try it with nothing installed

```bash
uvx agentmetry demo
```

It replays a session into a temporary directory it deletes: a private-key read,
then an upload. That raises one critical finding. It then edits the trail and
shows `agentmetry verify` fail.

## Record a real agent

```bash
pip install agentmetry
agentmetry hooks install
agentmetry start
agentmetry doctor
```

`agentmetry dashboard` opens the local console with a one-time sign-in link.

## Check the detection claims yourself

The corpus ships inside the package, so this works from a clean install:

```bash
agentmetry benchmark
```

It replays recorded sessions through the real rule engine and exits non-zero on
any missed rule or any false positive. The benign half is the number that
matters: any tool can fire on an attack, and a feed that cries wolf gets muted.

## What it does not do

- **It is not a CASB.** It records the agents you wire in. An unmanaged browser
  assistant, or an IDE with its hooks off, is invisible to it.
- **It is a recorder, not a sandbox.** By default it records. DLP and tool policy
  can deny a call in the hook, before it runs, when you set them to block.
- **The DLP is regex, not ML.** A starting pack you extend in YAML.
- **macOS is in preview.** CI runs the full suite on Windows, Linux and macOS, but
  only Windows and Linux are required checks, and no hook has been exercised
  against a live agent on a Mac.
- **It is a public alpha.** Integration surfaces may still change.

For a fleet, a managed policy file can lock settings such as the DLP and tool
policy modes so a developer cannot change them. See
[docs/managed-policy.md](https://github.com/blitzcrieg1/agentmetry/blob/master/docs/managed-policy.md).

Full documentation, the event schema, and the SIEM integration guides are in the
repository.

- Source and issues: https://github.com/blitzcrieg1/agentmetry
- Website: https://agentmetry.ai

Apache-2.0.
