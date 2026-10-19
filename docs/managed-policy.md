# Managed policy

A managed policy locks settings across a fleet. Every key it sets wins over
the process environment and over `.env`, in the recorder and in every IDE
hook, so a developer's `AGENTMETRY_DLP_MODE=disable` cannot undo a fleet's
`block`. A machine with no managed policy behaves exactly as before.

## Where it is read from

The first source to set a key wins.

| Order | Windows | macOS | Linux |
|---|---|---|---|
| 1 | `HKLM\SOFTWARE\Policies\Agentmetry` | | |
| 2 | `%ProgramData%\Agentmetry\policy.yaml` | `/Library/Managed Preferences/ai.agentmetry.sensor.plist` | `/etc/agentmetry/policy.yaml` |
| 3 | | `/etc/agentmetry/policy.yaml` | |
| last | `AGENTMETRY_POLICY_DIR` or `--policy-dir` | same | same |

- **Registry.** Value names are matched without regard to case. `REG_DWORD` 0
  or 1 is a boolean.
- **ProgramData.** The location comes from Windows itself, not from the
  `PROGRAMDATA` variable, which any user can change.
- **`AGENTMETRY_POLICY_DIR`.** It adds a location and never replaces one.
  Its files pass the same ownership check as the others.

## The file

Flat `key: value` YAML, or a plist dictionary on macOS. Nesting, lists and
anchors are refused rather than guessed at.

```yaml
schema: 1
dlp_mode: block
tool_policy_mode: block
auth_disabled: false
audit_sink: file,splunk
heartbeat_seconds: 300
```

| Key | Sets | Values |
|---|---|---|
| `dlp_mode` | `AGENTMETRY_DLP_MODE` | `log`, `block`, `disable` |
| `dlp_pii` | `AGENTMETRY_DLP_PII` | boolean |
| `dlp_rules_path` | `AGENTMETRY_DLP_RULES_PATH` | absolute path |
| `tool_policy_mode` | `AGENTMETRY_TOOL_POLICY_MODE` | `log`, `block`, `disable` |
| `tool_policy_path` | `AGENTMETRY_TOOL_POLICY_PATH` | absolute path |
| `auth_disabled` | `AGENTMETRY_AUTH_DISABLED` | boolean |
| `trusted_hosts` | `AGENTMETRY_TRUSTED_HOSTS` | text |
| `audit_sink` | `AGENTMETRY_AUDIT_SINK` | `file`, `webhook`, `elastic`, `splunk`, `chronicle`, `sentinel`, `both`, `all`, or a comma list |
| `auto_install_hooks` | `AGENTMETRY_AUTO_INSTALL_HOOKS` | boolean |
| `data_dir` | `AGENTMETRY_DATA_DIR` | absolute path |
| `hook_spool_path` | `AGENTMETRY_HOOK_SPOOL_PATH` | absolute path |
| `heartbeat_seconds` | `AGENTMETRY_HEARTBEAT_SECONDS` | whole number |

Secrets are not policy keys. API keys and SIEM credentials stay in the service
environment, because every user can read a policy file.

Some locks pin other settings with them:

- **A locked mode pins its rules.** Lock `dlp_mode` and `AGENTMETRY_DLP_RULES_PATH`
  is held at the built-in manifest, because a block mode pointed at an empty
  manifest blocks nothing. To use your own manifest, lock `dlp_rules_path`
  too. `tool_policy_mode` and `tool_policy_path` work the same way.
- **A locked `data_dir` pins the files inside it:** the trail, its index, and
  the detection and disposition stores.
- **The hook spool is not pinned.** On a machine-wide install the hooks run as
  each developer and usually cannot write the data directory, so lock
  `hook_spool_path` yourself if you need it fixed.

One bad value refuses the whole file, so a typo cannot lock half a policy and
quietly drop the key you cared about. A key this release does not know is
ignored, and `doctor` names it.

## Who may write it

A file is honoured only when the developer it constrains cannot change it.
The check runs on the open file, so nobody can swap the file between the
check and the read.

- **Windows.** The owner must be SYSTEM, Administrators or TrustedInstaller.
  No other SID may hold an allow entry that writes, deletes or re-permissions
  the file. Its folder must meet the same owner rule, and no other SID may
  create, delete or re-permission entries in it. Neither may be a link or a
  junction. Trust is decided from SIDs, so the check works the same on a
  Windows in any language.
- **macOS and Linux.** The file and every directory above it must be owned by
  root and not writable by group or others. The file itself may not be a
  symlink; a symlink above it must be owned by root. No ACL entry on the file
  or its folder may give another user or group write.

A new folder under `C:\ProgramData` inherits an entry that lets `Users` create
files. A file an administrator creates there by hand is owned by that
administrator's own account. Both are refused, so harden the folder once from
an elevated prompt:

```
icacls "%ProgramData%\Agentmetry" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F *S-1-5-32-545:(OI)(CI)RX /T
icacls "%ProgramData%\Agentmetry" /setowner *S-1-5-32-544 /T
```

A file that Intune, Group Policy or another management agent writes as SYSTEM
is owned by SYSTEM already. Its folder still inherits the `Users` entry, so it
still needs the first command.

## When it applies, and how to check

Locks are applied when a process starts: the recorder, each hook call, and
each CLI command. After changing the policy, restart the recorder. Hooks pick
the change up on their next call.

- `agentmetry doctor` lists what is locked and what is pinned. It fails on a
  refused source and prints the fix.
- Each heartbeat carries `policy_locked` (key names) and `policy_rejected`
  (refused locations). A refused source turns the beat `degraded`, so a SIEM
  rule on `action.type:heartbeat AND action.outcome:degraded` catches a policy
  that is not in force.

## What it does not do

- **It does not stop a local administrator.** A developer who is one can
  change anything, including the policy.
- **It does not stop a developer removing the hook** from their IDE config.
  Hook coverage reports that, and the heartbeat degrades.
