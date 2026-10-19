# macOS deployment

The files in `deploy/macos/` split the recorder from the developer session.

`ai.agentmetry.daemon.plist` is a LaunchDaemon. It runs as root and starts
`agentmetry serve` with `--data-dir /var/db/agentmetry` and
`--policy-dir /etc/agentmetry`. The trail, the API token, and the anchor stay
in `/var/db/agentmetry`. A user-space agent must not be able to write that
directory. The package should install it root:wheel.

A single-user Mac can put one absolute home path, one line, in
`/var/db/agentmetry/user-profile`. The daemon wrapper
(`agentmetry-daemon.sh`) passes that path as `--user-profile-dir`. The
LaunchAgent must not write this file. A multi-user Mac leaves it absent. The
daemon then does not pretend it can see every home. Coverage comes from the
user agent.

`ai.agentmetry.agent.plist` is a LaunchAgent with `LimitLoadToSessionType` set
to `Aqua`. Every 300 seconds it runs `agentmetry hooks status` against
`$HOME`. It runs `agentmetry hooks install` only when that command exits 1.
It does not write `/var/db/agentmetry`. Installing on every interval would
change file mtimes and hide a later tamper check.

`agentmetry-mdm-profile.mobileconfig` is a configuration profile with two
payloads:

- `ai.agentmetry.sensor`, the preference domain the sensor reads from
  `/Library/Managed Preferences/ai.agentmetry.sensor.plist`. The example locks
  `dlp_mode`, `tool_policy_mode`, and `auth_disabled`. It does not carry a
  token or a SIEM credential. Those do not belong in a mode-0644 file.
- `com.apple.servicemanagement`, a managed login item rule of type `Label`
  for `ai.agentmetry.agent`.

The sensor accepts that plist as a flat dictionary of policy keys, or as the
Managed Preferences wrapper (`Forced` / `mcx_preference_settings`). `Payload*`
keys are ignored. A file at that path that a user can write is refused.

## Building the package

`deploy/macos/build_pkg.sh` copies the plists and scripts into a payload,
runs `pkgbuild` and `productbuild`, and optionally `codesign` and
`xcrun notarytool`. Identities and the notary password are environment
variables. The script has no certificate and no password in it.

```bash
export AGENTMETRY_CODESIGN_IDENTITY="Developer ID Application: Example (TEAMID)"
export AGENTMETRY_INSTALLER_IDENTITY="Developer ID Installer: Example (TEAMID)"
export APPLE_ID="release@example.com"
export APPLE_TEAM_ID="TEAMID"
export APPLE_APP_PASSWORD="(app-specific password, not stored in the repo)"
deploy/macos/build_pkg.sh
```

`codesign` uses `--options runtime` and `--timestamp`. Unsigned output
requires `AGENTMETRY_ALLOW_UNSIGNED=1`. Notarization runs only when
`APPLE_ID`, `APPLE_TEAM_ID`, and `APPLE_APP_PASSWORD` are all set.

The script does not download a Python runtime. Point the installed
`/usr/local/bin/agentmetry` at the interpreter you ship (a venv on the
payload, or a separately installed wheel). Keep that tree root-owned.
