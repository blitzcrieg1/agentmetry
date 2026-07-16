# CrewAI adapter

Record every tool a [CrewAI](https://github.com/crewAIInc/crewAI) Crew executes
into your local Agentmetry trail: MITRE ATT&CK tags, DLP scanning, hashed
arguments, and correlated sequence detections across a whole Crew run.

A Crew runs unattended with real credentials and real tools. That is exactly the
threat model Agentmetry exists for: no single tool call looks wrong, but the
sequence does.

## Install

Copy `agentmetry_crewai.py` next to your Crew, or add this directory to your
`PYTHONPATH`. It has no dependencies beyond the standard library and `crewai`
itself (>= 1.0, for the `crewai.events` bus).

```python
from agentmetry_crewai import AgentmetryListener

# Instantiate once at startup and keep the reference alive for the process.
# Registering happens in the constructor.
agentmetry = AgentmetryListener()

crew = Crew(agents=[researcher], tasks=[task])
crew.kickoff()
```

Start Agentmetry first (`scripts\agentmetry.bat start`, or
`python -m uvicorn api.main:app --port 8000` from `apps/orchestrator`), then run
your Crew. Events appear in the Flight Recorder within a second.

## What it records

| CrewAI event | Canonical event |
|---|---|
| `CrewKickoffStartedEvent` | `session_start` (new `correlation_id` per Crew run) |
| `ToolUsageStartedEvent` | `approval_request` (pending) |
| `ToolUsageFinishedEvent` | `tool_called` (success) |
| `ToolUsageErrorEvent` | `tool_failed` (error) |
| `CrewKickoffCompletedEvent` / `CrewKickoffFailedEvent` | `session_end` |

Each Crew run is **one correlation id**, which is what lets sequence rules fire
across the whole Crew rather than a single tool call. Crews are marked
`triggered_by: crewai`, so the engine treats them as autonomous.

## Configuration

| Env | Default | Description |
|---|---|---|
| `AGENTMETRY_AUDIT_INGEST_URL` | `http://127.0.0.1:8000` | Where to send events |
| `AGENTMETRY_API_KEY` | *(unset)* | Sent as `X-API-Key` when set |
| `AGENTMETRY_CREWAI_LOG_ARGS` | *(off)* | Send tool arguments, not just their hash |

**Arguments are hashed and not transmitted by default.** Set
`AGENTMETRY_CREWAI_LOG_ARGS=1` to send them, which is what enables content-based
detection: a read of `~/.ssh/id_rsa` upgrading from generic Collection (T1005) to
Credential Access (T1552.004), and the DLP engine scanning for secrets. Values
that look like secrets are scrubbed before transmission either way. Turn it on if
you want the detections; leave it off if the arguments themselves are sensitive.

## What it catches

With `AGENTMETRY_CREWAI_LOG_ARGS=1`, a Crew that reads a key and then calls out:

```
session_start
tool_called    crewai.file_read    T1552.004   Credential Access
tool_called    crewai.web_fetch    T1071.001   Command and Control
*** [CRITICAL] credential-exfil: crewai.file_read accessed credentials,
    then crewai.web_fetch egressed to the network in the same session.
session_end
```

That detection fires on its own, with nobody watching.

## Failure behaviour

If Agentmetry is not running, the listener prints one warning to stderr and the
Crew continues. An audit sink that can crash the Crew it observes is worse than
no audit sink, so every transport error is swallowed by design.

## Limits

- It sees the tools CrewAI reports through its event bus. A Crew that shells out
  through a path CrewAI does not emit an event for is not recorded.
- It is a recorder, not a sandbox. It does not block CrewAI tool execution.
  (`block` mode exists for the IDE-hook path, where the hook can deny.)
