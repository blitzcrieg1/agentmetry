# `agentmetry canary`: local honeytokens

An opt-in command that plants decoy credentials on the machine and turns a read
of one into a finding at the tool boundary. Nothing it plants ever leaves the
machine.

## Why this exists

Every other credential rule guesses. A regex sees something shaped like an AWS
key and reports it, and the operator has to decide whether it was real. A canary
inverts that: the value was planted by the operator, it cannot be a working
credential, so touching it is not a guess. It is evidence that an agent reached
for credentials it had no reason to want.

The cost is that it only catches the agent that touches *your* decoy. That is a
narrower net than a general credential rule, and it is the point — the finding
should be close to certain, not merely suspicious.

## Turning it on

Nothing is planted until you run the command. There is no default decoy, no
background timer, and no ruleset entry in the shipped manifest.

```console
$ agentmetry canary plant --kind aws
planted aws-home-1
  where   C:\Users\you\.aws\credentials [agentmetry-canary-1]
  rule    canary_aws-home-1 (merged into the DLP ruleset)
  remove  agentmetry canary remove aws-home-1
```

That appended a profile to `~/.aws/credentials` and wrote a rule whose pattern is
the two values it just planted. If an agent later reads that profile, or copies
its contents into an argument, the DLP scanner matches on the next tool call.

A project-local decoy is the same shape, anchored to a `.env` instead:

```console
$ agentmetry canary plant --kind env --project C:\work\my-project
```

## Managing what is planted

```console
$ agentmetry canary list
aws-home-1    aws  C:\Users\you\.aws\credentials [agentmetry-canary-1]
              rule canary_aws-home-1  planted 2026-11-26T05:31:04+00:00

$ agentmetry canary remove aws-home-1
removed aws-home-1 (C:\Users\you\.aws\credentials [agentmetry-canary-1])
```

`remove` deletes exactly what `plant` appended and drops the matching DLP rule.
If the file does not end with the exact block that was appended — because
somebody edited it by hand — it refuses rather than truncating work it cannot
attribute:

```console
$ agentmetry canary remove aws-home-1
refusing: ... no longer ends with what canary planted (someone edited it since).
Remove the block by hand, then run `agentmetry canary forget aws-home-1`
```

`forget` exists for that case: drop the bookkeeping and the DLP rule, leave the
file alone.

## What it guarantees

| Guarantee | How |
| --- | --- |
| **Local only.** | Detection is a DLP regex over what the agent already submitted. There is no callback, no beacon, and no network call anywhere in the path. |
| **The trail records the rule id, never the value.** | The rule is anchored on the planted value, so the scanner reports `canary_aws-home-1`; the value itself is redacted by the same code that redacts a real token. |
| **Never overwrites a real credential.** | `plant` refuses when the profile or key already exists in that file. It appends, it never rewrites. |
| **Reversible.** | `remove` removes the exact block and the exact rule. The file did not exist before planting, it is deleted; if it did, it is restored to what it held. |
| **Off by default.** | Nothing exists until you run `plant`, and the packaged DLP manifest contains no canary rule. |

## Where the pieces live

```
~/.agentmetry/canary/state.json   what is planted, enough to undo it
~/.agentmetry/canary/rules.yaml   the generated DLP rules
```

`load_dlp_rules` merges that directory after the built-in manifest, and only
when it exists. The hook reads the DLP manifest on every tool call, which is why
this is a directory check rather than a second unconditional parse.

## Limits worth knowing

- **It only works while the recorder runs.** The decoy is a value in a file; a
  read becomes an event because the hook sees the tool call, not because the file
  watches itself.
- **A canary is not a tripwire on the filesystem.** It catches a read that goes
  through a tool the hook sees. An agent that opens the file out of process is
  outside what the tool boundary can observe — the same limit as every hook-based
  rule.
- **The values are recognisably fake on purpose.** `AGENTMETRY-CANARY` in an
  `.env` is a reminder to a human reader, and it also means an attacker who reads
  the file knows it is a decoy. That is the honest trade: a near-certain finding
  beats a subtle one you cannot explain.

## Related

- [DLP manifest](../apps/orchestrator/agentmetry/policies/dlp/manifest.yaml) — the rules canary appends to at runtime
- [Detection rules](detection-rules.md) — the sequence rules, and why they are frozen
- [Scanner](scanner.md) — the other half of the DLP path
