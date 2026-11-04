# Coding-agent incident record

Copy this file for each incident in which a coding agent (Claude Code, Cursor,
Codex and the rest) did something it should not have: followed injected
instructions, read or sent a secret, ran a download, or changed something
nobody asked it to change. Keep the copy wherever your incident records live,
not on the affected machine.

The order of the sections is the order of the work. **Preserve, then revoke,
then clean**: cleaning up first destroys the timeline the review needs.

Every command below exists in the current release. Run `agentmetry <command>
--help` for its options.

---

## Summary

| Field | Value |
|-------|-------|
| **Incident ID** | INC-YYYY-MM-DD-001 |
| **Detected** | date and time, timezone |
| **Detected by** | detection rule / SIEM alert / developer / other |
| **Host(s)** | |
| **Agent(s)** | e.g. claude, cursor, codex |
| **Session id(s)** | the `correlation_id` from the detection |
| **Severity** | low / medium / high / critical |
| **Status** | open / contained / closed |

---

## What happened

In plain language: what the developer asked the agent to do, what it did
instead, and how somebody noticed.

---

## Evidence preserved

Do this before changing anything on the machine.

| Item | Location of the copy | Checked |
|------|----------------------|---------|
| Agentmetry trail (JSONL) and its `.chain` sidecar | | `agentmetry verify --trail <copy>` result: |
| Anchor log, kept off the machine | | `agentmetry verify --trail <copy> --anchors <off-host anchor log>` result: |
| The agent's own session transcript, for agents that keep one | | |
| The input the agent read: issue, page, file, MCP server and version | | |
| SIEM events for the same hosts and window | | |

Agentmetry records which tools ran, with arguments hashed by default. It does
not keep prompt text or tool output, so the injected text itself is in the
input and the transcript, not in the trail.

---

## Timeline

Build it from the trail, not from memory.

```bash
agentmetry detections <session-id>   # what fired in this session
agentmetry replay <session-id>       # the session as a timeline
```

| Time | Event | Source (trail seq, transcript, SIEM) |
|------|-------|--------------------------------------|
| | Agent read the untrusted input | |
| | | |

A credential read followed by a network call is the pattern a rule fires on.
It is not proof the credential went into that call. Write down which one you
know.

---

## Containment

- [ ] Agent session and process stopped
- [ ] Credentials the session read, rotated first (list them):
- [ ] Other credentials reachable from the machine, rotated or confirmed out of reach
- [ ] Input removed: MCP server taken out of the agent config / issue locked / file deleted
- [ ] Repeat blocked on other machines: deny rule added to the tool policy, `AGENTMETRY_TOOL_POLICY_MODE=block` set (pre-tool hooks only, and only as strong as the hook)

---

## Eradication

Places an agent with the developer's access can leave something behind:

- [ ] Shell profiles, scheduled tasks, startup items
- [ ] Agent configuration: settings, hooks, MCP server lists, `AGENTS.md`, `CLAUDE.md` and similar instruction files
- [ ] CI workflow files, commits and branches pushed during the session
- [ ] `agentmetry hooks status` exits 0 again: every installed agent is recorded
- [ ] `agentmetry scan` rerun after cleanup, findings reviewed

---

## Root cause

- [ ] Untrusted input followed as instructions (issue, page, file, tool result)
- [ ] MCP server changed after it was approved
- [ ] Malicious package or script driving the agent
- [ ] Agent error, no attacker
- [ ] Permission mode or approval let the call through
- [ ] Credential or token broader than the task needed
- [ ] Other:

---

## Controls that did not stop it

| Control | Why it did not stop it | Change |
|---------|------------------------|--------|
| | | |

This table is the output of the review. The timeline is how you got here.

---

## Close-out

Record a disposition on every detection in the incident, false positives
included. An undecided critical is a question for the next audit.

```bash
agentmetry disposition <session-id> <rule-id> --status resolved --note "INC-...: ..."
agentmetry prove <trail> --seq <n> -o proof.json     # one event, provable on its own
agentmetry export --evidence --from <date> --to <date> -o incident-evidence.json
```

| Field | Value |
|-------|-------|
| Closed by | |
| Date closed | |
| Evidence pack attached | yes / no |
| Proofs attached | yes / no |

If a commercial model refuses to help analyse the trail because the payload
looks like an attack, [`local-llm-forensics.md`](local-llm-forensics.md)
covers doing it with a self-hosted model.
