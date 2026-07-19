# Changelog

All notable changes to Agentmetry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once out of
alpha. While in **public alpha**, minor versions may carry breaking changes to
APIs and integration surfaces. The canonical event schema is versioned
separately (currently `1.1.0`) and changes additively.

## [Unreleased]

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
- Live detections are checkpointed only after they are durably stored and
  forwarded, so a transient sink failure re-fires on the next event instead of
  being lost.
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

[Unreleased]: https://github.com/blitzcrieg1/agentmetry/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/blitzcrieg1/agentmetry/releases/tag/v0.2.0
