# Changelog

All notable changes to Agentmetry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once out of
alpha. While in **public alpha**, minor versions may carry breaking changes to
APIs and integration surfaces. The canonical event schema is versioned
separately (currently `1.1.0`) and changes additively.

## [Unreleased]

### Fixed
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

### Added
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
- **YAML detection manifest** (`policies/detection/manifest.yaml`) — tunable burst
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
