# Windows deployment

`deploy/windows/` is what an Intune Proactive Remediation runs. The MSI
itself is not in this repository. `SECURITY.md` states that the MSI is
unsigned. This page is how to sign one, and how the scripts beside it
should behave. It does not ship a certificate.

## Detection

`Detect-Agentmetry.ps1` runs in the user context. It executes
`agentmetry doctor --json` and exits 1 when any of these are true:

- `agentmetry` is not on `PATH`
- doctor exits non-zero, or the JSON `exit_code` is non-zero
- `orchestrator_reachable` is false
- any hook surface is `uncovered` or `unknown`

`absent` is not drift. That agent is not installed. The script reads fields.
It does not parse doctor's sentences.

## Remediation

`Remediate-Agentmetry.ps1` runs `agentmetry hooks install`. When the process
is an administrator it also runs `Protect-AgentmetryData.ps1`. Otherwise it
warns and still installs hooks, because a user-context remediation can repair
IDE config and cannot repair a trail ACL.

It then pipes one JSON object to `agentmetry-hook send`:

```json
{"event_type":"hook_remediation","source_app":"agentmetry","outcome":"success","reason":"intune remediate reinstalled hooks"}
```

That event is action type `hook_remediation`. It is not stored as a tool
call, and a correlation id on the payload is dropped so it does not join an
agent session. If the post fails after a successful install, the script exits
0 and writes a warning. Exiting 1 there would make Intune reinstall forever
while the recorder is down.

Run `Protect-AgentmetryData.ps1` itself as SYSTEM (an Intune device script),
not only from the user remediation. It applies `icacls` by SID:

| Path | Who can change it |
|---|---|
| `%ProgramData%\Agentmetry\trail` | SYSTEM (`S-1-5-18`) and Administrators (`S-1-5-32-544`) |
| `%ProgramData%\Agentmetry\policy.yaml` | SYSTEM and Administrators. Users (`S-1-5-32-545`) can read. |
| `%ProgramData%\Agentmetry\spool` | SYSTEM and Administrators, plus Users modify, so hooks can append. |

Inheritance on those objects is removed first (`/inheritance:r`), so a
user-writable parent ACE does not leak in.

## Azure Trusted Signing

Sign the MSI and any shipped binaries in GitHub Actions with OIDC. Do not
put a client secret in the repository. The example workflow is
`docs/deploy/examples/windows-trusted-signing.yml`. It is not under
`.github/workflows`, so CI does not run it. Copy it there when the Azure
app registration and the Trusted Signing account exist.

The job uses `azure/login` with federated credentials (`id-token: write`)
and then `azure/trusted-signing-action@v0`. The same inputs work with
`azure/artifact-signing-action`, which is the renamed action. Prefer
`azure/trusted-signing-action@v0` unless a runner image only has the new name.

Required configuration, as repository variables, not as secrets in git:

- `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` for the login
- `AZURE_TRUSTED_SIGNING_ACCOUNT` and `AZURE_TRUSTED_SIGNING_PROFILE`
- `AZURE_TRUSTED_SIGNING_FILES`, a file or a glob the action accepts
- `endpoint`, for example `https://eus.codesigning.azure.net`, matching the
  region of the Trusted Signing account

The example's `endpoint` value is the public regional host, not a credential.
