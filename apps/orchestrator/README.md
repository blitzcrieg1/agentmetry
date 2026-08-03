# Agentmetry

A local-first flight recorder for AI coding agents.

Agentmetry hooks the tool lifecycle of Claude Code, Cursor, Codex and Antigravity,
writes every tool call, approval and denial to a hash-chained JSONL trail on your
machine, and runs sequence detection over the session. A credential read followed
by network egress becomes one finding rather than two unremarkable log lines.

Everything runs locally. There are no cloud calls and no telemetry. Forwarding to
Elastic ECS, Splunk HEC or a webhook exists and is off unless you configure it.

```bash
pip install agentmetry-orchestrator
agentmetry doctor
```

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
  assistant is invisible to it.
- **It is a recorder, not a sandbox.** The only enforcement path is pre-execution
  DLP blocking in the hook.
- **The DLP is regex, not ML.** A starting pack you extend in YAML.
- **It is a public alpha.** Integration surfaces may still change.

Full documentation, the event schema, and the SIEM integration guides are in the
repository.

- Source and issues: https://github.com/blitzcrieg1/agentmetry
- Website: https://agentmetry.ai

Apache-2.0.
