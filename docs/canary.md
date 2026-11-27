# `agentmetry canary`

Canaries are opt-in local decoy credentials. An observed tool input containing a
literal decoy value can produce a critical DLP match. A read whose input contains
only a path does not trigger a canary match. A match identifies the observed
value and does not establish how it was obtained or where it went.

## Plant a decoy

Use an unmanaged Agentmetry installation with the bundled DLP manifest and
DLP enabled. An AWS decoy adds a profile to `~/.aws/credentials`. An env decoy
adds a variable to `.env` in an existing project. Choose a project whose
credential file you control.

```console
agentmetry canary plant --kind aws
agentmetry canary plant --kind env --project C:\work\my-project
```

The command refuses existing keys or profiles with the same generated name,
linked paths, and nonregular files. No callback is configured. The canary
producer never sends the value to a remote service. A tool that handles the
value is still subject to its own behavior and the configured DLP mode.

## List, remove, and recover

```console
agentmetry canary list
agentmetry canary remove aws-home-1
```

The command saves a recovery record before modifying a target. If an append
is interrupted, `list` shows the pending record. Run `remove` with its name
to roll back the full or partial block. If a removal is interrupted after
the file was restored, run it again to finish updating the inventory.

Removal preserves original bytes, including line endings, and keeps the
original file in place. A nonempty file created solely for a decoy can be
removed once the decoy is identified. Remove multiple decoys in the same
file in reverse order. If the file changed separately or a legacy entry has
a relative path, remove the decoy block by hand before running
`agentmetry canary forget <name>` to drop the inventory entry.

Canary commands coordinate through a local lock. Other programs editing the
same credential file do not take that lock. Avoid concurrent editing during
plant or removal.

## Detection and capture limits

The optional rules are derived from the validated literal values in
`~/.agentmetry/canary/state.json`. The inventory contains the values and
local paths. Treat it as private. If it cannot be read or fails validation,
the recorder skips the optional canary rules and retains the bundled DLP
rules. An administrator's DLP lock or a custom DLP manifest excludes the
local canary inventory.

An upgrade from 0.17.0 can read the generated inventory entries. The sibling
`rules.yaml` from 0.17.0 is ignored. If the older version left a block without
a matching inventory entry, inspect the chosen target privately and remove that
block manually.

The DLP match contains rule metadata. Raw argument and command capture is a
separate path whose scrubbers may not recognize the exact canary value.
Keep full argument and command capture disabled when using canaries unless you
have verified the settings and scrubbers on synthetic data. A process that
opens the file outside the observed tool boundary may leave no matching event.
