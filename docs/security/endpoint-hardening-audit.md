# Endpoint hardening audit

Verified against the default branch at **0.9.8** (`fbb4662`, 2026-10-18).
`apps/orchestrator/agentmetry/core/version.py:13` is `__version__ = "0.9.8"`.
The brief that said v0.9.4 is stale. The README still quotes an older
benchmark paragraph; the version the code and `CHANGELOG.md` ship is 0.9.8.

Line numbers in the matrix are that commit, unless a row says the file
changed in the pull request that adds this document. That pull request
adds the managed-policy loader and the path split (PR 1 below). It does
not edit the frozen detection files. The ruleset fingerprint this audit
expects is `15846a0915769d4a` (`CLAUDE.md`).

Severity here is the auditor's judgment of the sensor's own threat model.
`SECURITY.md` (baseline lines 39-41) puts an attacker who already has code
execution as the operator's user out of scope for the open-source product.
Findings that only that attacker can exploit are still listed, because a
fleet install that runs the recorder as the developer inherits them, and
because the product's claim is a record that survives the agent.

## 1. Codebase verification matrix

### Phase 1. Local API auth and IPC

| Claim | Verdict | Evidence |
|---|---|---|
| `AGENTMETRY_API_KEY` unset means the localhost API is unauthenticated | **False in code since 0.9.3. True only in the baseline `SECURITY.md`.** | `core/auth.py:13-18` records the old skip. `effective_key` (`auth.py:40-47`) returns `settings.api_key` when set, else the per-install token from `api_token.ensure_token()`, unless `AGENTMETRY_AUTH_DISABLED=1`. `require_api_key` (`auth.py:72-100`) accepts that key (`X-API-Key` or `Bearer`), a dashboard session cookie (writes also need `X-Agentmetry-Request: 1`), or an extension principal already on `request.state`. `GET /api/v1/health` is the exception (`api/main.py:263-265`). Lifespan creates the token before the first hook (`api/main.py:179-188`). Baseline `SECURITY.md:53-55` still said "Auth is off by default." This pull request corrects that sentence. |
| Hooks and the MCP proxy talk to the orchestrator with a bearer | **Exists** | `hooks/ingest.py:145-159` sends `AGENTMETRY_API_KEY`, else `BLACKBOX_API_KEY`, else `.env`, else the ingest-token file, else `api-token`. `hooks/mcp_proxy.py:39` imports `post_ingest` and posts through it (`mcp_proxy.py:203`, `:248`, `:257`, `:270`). |
| A local process can spoof events, flood the spool, or read the API | **Vulnerable, same-user** | The token file is mode `0600` (`core/api_token.py:15-19`, `_restrict` at `:63-69`). Another OS user cannot read it. A process running as the developer can. That process holds the full key: read the trail, inject events, close detections. The ingest-token file is preferred by the hook (`ingest.py:148-151`) but `require_api_key` does not treat it as a narrower credential. `api_token.py:44-49` says the core does not mint that file; Enterprise is expected to set `request.state.principal`. Until an extension does, the hook's "ingest-only" token is either absent or equal to a key the API accepts in full. `TrustedHostMiddleware` (`api/main.py:255`) blocks DNS rebinding unless `AGENTMETRY_TRUSTED_HOSTS=*`. The dashboard bundle holds no API key (`apps/dashboard/lib/api.ts`, `lib/session.ts`): a one-time link sets an HttpOnly cookie. |
| Spool flood | **Partially bounded** | The hook refuses a further append once `hook-spool.jsonl` exceeds 32 MiB (`hooks/ingest.py:547`, `:561`). The drainer rotates the file aside and starts a fresh one (`core/audit/spool.py:22-23`, `:247`). A same-user writer can fill disk across rotations. There is no rate limit. |
| UNIX domain socket or Windows named pipe with peer credentials | **Missing** | Transport is loopback HTTP plus a bearer. No `/var/run/agentmetry.sock` and no named pipe. Peer credentials would not stop a same-user agent. They would stop a different OS user, which the `0600` token already does for the key file, and they would take the bearer out of the hook environment. Worth doing later. Not a substitute for split privilege. |

### Phase 1. Path resolution and the single-user threat model

| Claim | Verdict | Evidence |
|---|---|---|
| Running as LocalSystem or root breaks `Path.home()` IDE discovery | **Exists** | Baseline `core/diagnostics/hook_coverage.py:40-47` and `:108-112`: every surface directory is `Path.home() / home_rel` unless that surface has its own env (`QWEN_HOME`, `KIMI_CODE_HOME`, `COPILOT_HOME`). `is_service_profile` (`:174-183`) matches `systemprofile` and `ServiceProfiles`. `coverage()` (`:196-206`) then returns `unknown` for every surface, and the heartbeat marks itself degraded (`core/audit/heartbeat.py:222-235`). Hook installers in `core/audit/hook_bootstrap.py` used `Path.home()` the same way. `core/diagnostics/posture.py` and the user-unit paths in `core/diagnostics/autostart.py` did too. |
| Running as the developer lets that user, or an agent with a shell, rewrite the JSONL, recompute the chain, and edit the local anchor before the next heartbeat | **Exists, and the code says so** | `core/audit/trail_chain.py:9-14`: an attacker with write access to the data directory can edit an event, recompute every later hash, rewrite the sidecar, and produce a file that verifies. `core/audit/trail_anchor.py:8-30`: `FileAnchorSink` on the same disk adds nearly nothing, because the same writer can rewrite the anchor. Heartbeat interval default is 300 seconds (`heartbeat.py:70`). The beat copies the Merkle root into the event (`heartbeat.py:203-204`) but does not sign it. |
| Data directory and IDE home are the same concept | **Was true. Split in this pull request, defaults unchanged.** | Baseline `core/paths.py:53-63`: `data_dir()` is `AGENTMETRY_DATA_DIR`, else `AGENTMETRY_INSTALL_ROOT/data`, else the checkout `apps/orchestrator/data`, else the platform per-user directory (`paths.py:42-50`, which itself uses `Path.home()`). There was no `--user-profile-dir` and no `--policy-dir`. This pull request adds `user_profile_dir()` and the three flags. Unset, `user_profile_dir()` is still `Path.home()` and `data_dir()` is unchanged, so a solo install does not move. |

### Phase 1. DLP evasion

| Claim | Verdict | Evidence |
|---|---|---|
| DLP is regex-only, enforced in the hook process | **Exists** | `core/audit/dlp/scanner.py:58-99` compiles the rules in `agentmetry/policies/dlp/manifest.yaml` and searches one string. `pattern_type` is hard-coded `"regex"` (`scanner.py:94`). The hook path stays on stdlib; `policy_settings.py` exists so the hook does not import pydantic. |
| Scrubbing normalizes base64, URL encoding, hex, or multiline env dumps | **Missing** | `scan()` json-dumps the arguments dict (`scanner.py:73-79`) and runs each regex once. No decode step, no whitespace fold, no second pass over a decoded body. `core/audit/redaction.py:36` and `:46` are the same class of pattern match on command text and string argument values. |
| Tool outputs are scrubbed as rigorously as arguments | **Missing** | Codex `PostToolUse` reads `tool_response` only to set `reason` to `tool_completed` (`hooks/ingest.py:1034-1045` on the baseline; the return stores `arguments`, not the response body). MCP results and file-read bodies are not passed through `scan()` before they can land in a trail field. Arguments are. Responses are not. |

### Phase 1. Hook tamper window

| Claim | Verdict | Evidence |
|---|---|---|
| Coverage states are covered, uncovered, absent, unknown | **Exists** | `hook_coverage.py:18-21` and the constants at `:82-85`. |
| Attestation is a 300 second poll, so a hook can be removed and restored inside the interval with no event | **Vulnerable** | `coverage()` re-reads disk on every call and is deliberately not cached (`hook_coverage.py:196-201`). Nothing watches inode, mtime, or a hash between calls. `heartbeat.py:70` is 300 seconds. A removal that is still present at the next beat shows up as `uncovered` and degrades the beat. A removal that is restored before the beat leaves no `hook_config_tampered` event. There is no such event type. |
| Managed IDE hooks | **Exists, and they are not sensor policy** | `core/audit/managed_hooks.py` writes vendor admin hook locations (`agentmetry hooks install --managed`). That stops a user from deleting the IDE's copy only where the vendor honors a root-owned hook file. It does not lock sensor configuration, and it does not emit a tamper event when the user-level file changes. |

### Phase 1. Per-host attribution

| Claim | Verdict | Evidence |
|---|---|---|
| Hash chain plus RFC 6962 Merkle (leaf `0x00`, node `0x01`) proves order and integrity | **Exists** | `core/audit/trail_merkle.py:64-65` (`_LEAF_PREFIX = b"\x00"`, `_NODE_PREFIX = b"\x01"`) and `:71-75`. The chain envelope is `trail_chain.py:5`. |
| That also attributes the root to this host | **Missing** | `heartbeat.py:161-186` computes the root on the machine from the file. `build_heartbeat_event` sets `session_id` to `""` (`heartbeat.py:249`) and carries `trail_merkle_root` and `trail_tree_size` unsigned (`:203-204`). `core/audit/signing.py:1-12` is an extension point: the core does no cryptography, `register_event_signer` signs one canonical event (`SIGNING_DOMAIN` at `:25`), and the signature travels beside the record. Nothing signs `(host_id, session_id, tree_size, merkle_root, timestamp)` on the heartbeat or on an anchor checkpoint. A writer who also controls forwarding can suppress the beat or republish a recomputed root. The local anchor file does not stop that (`trail_anchor.py:23-30`). |

### Phase 1. Dashboard, packaging, SECURITY.md

| Surface | Verdict | Evidence |
|---|---|---|
| Dashboard | **Does not embed the API token** | Session cookie via `agentmetry dashboard`. No key in `apps/dashboard/lib/api.ts`. |
| Packaging in this repo | **Missing** | No `deploy/` tree at `fbb4662`. No LaunchDaemon, no pkg script, no Intune proactive remediation, no `icacls` script for the trail. `SECURITY-HARDENING.md:8-10` says the installer half of the pilot lives in the private Enterprise repo. `SECURITY.md:97-99` (baseline, and still true): no signed release artifact, and the MSI is unsigned. |
| `SECURITY.md` auth sentence | **Was stale. Corrected in this pull request.** | Code has required a token since 0.9.3 (`auth.py:1-18`). The policy file still described the pre-0.9.3 default. |

Detection count, so the brief's "14 rules" is checked rather than repeated: `core/audit/detection/rules.py` defines 15 `rule_*` functions. The published set is 14 plus the experimental `rule_autonomous_unapproved_write` (`rules.py:406`). Those files are frozen. This audit does not change them.

### Phase 2. MDM deployment (state at 0.9.8, before the follow-up pull request)

| Claim | Verdict | Evidence |
|---|---|---|
| Hierarchical managed policy that the user cannot downgrade | **Missing at 0.9.8. Added in this pull request.** | Before this change, `AGENTMETRY_DLP_MODE`, `AGENTMETRY_AUTH_DISABLED`, `AGENTMETRY_TRUSTED_HOSTS`, and `AGENTMETRY_TOOL_POLICY_MODE` were process environment. A user or an agent with a shell could set them. There was no loader for `/Library/Managed Preferences/ai.agentmetry.sensor.plist`, `/etc/agentmetry/policy.yaml`, `HKLM\SOFTWARE\Policies\Agentmetry`, or `%ProgramData%\Agentmetry\policy.yaml`. `managed_hooks.py` is IDE hook placement, not this. |
| macOS LaunchDaemon, LaunchAgent, pkg, mobileconfig | **Missing at 0.9.8. Follow-up pull request.** | No files under `deploy/macos/`. |
| Intune Detect/Remediate and trail `icacls` | **Missing at 0.9.8. Follow-up pull request.** | `agentmetry hooks status` already returns 0, 1, or 2 for coverage (`cli/__init__.py` `_hooks_status`, written so a deployment tool does not parse doctor prose). It does not check that the service is up, and it does not harden the trail directory. `doctor` had no `--json`. |
| Azure Trusted Signing for the MSI | **Missing. Documented in the follow-up, not wired.** | `SECURITY.md` states the MSI is unsigned. No workflow in this repo signs it. |

## 2. Architectural decisions and trade-offs

### Solo install stays one process

The open-source default is one user, one data directory, hooks in `Path.home()`, no managed file. That is the product `SECURITY.md` describes. Adding a daemon, a socket, and a keystore as the only way to run `agentmetry start` would break `uvx agentmetry demo` and every existing checkout. The flags are optional:

- `--user-profile-dir` / `AGENTMETRY_USER_PROFILE_DIR`: whose IDE configs to install and attest. Unset, `Path.home()`.
- `--data-dir` / `AGENTMETRY_DATA_DIR`: trail, token, logs, spool default. The existing precedence is unchanged.
- `--policy-dir` / `AGENTMETRY_POLICY_DIR`: an extra managed location, subject to the same ownership check as `/etc`. It is not a bypass.

A service account that is given `--user-profile-dir` checks that home and does not report the beat as a service profile. Without the flag, the service-profile failure stays, because attesting the SYSTEM profile as if it were the developer is the bug the coverage module already names.

### Managed policy locks by presence, and only non-secrets

The first trusted managed source wins per key. A key it sets cannot be changed by `~/.agentmetry/policy.yaml` or by the environment. A key it omits stays free, so a fleet can lock `dlp_mode` and leave `data_dir` alone.

Lockable keys are operational: `dlp_mode`, `dlp_pii`, `tool_policy_mode`, `auth_disabled`, `trusted_hosts`, `audit_sink`, `auto_install_hooks`, `data_dir`, `hook_spool_path`, `heartbeat_seconds`. API tokens, the hash key, and SIEM credentials are not in the schema. A mode-0644 policy file would publish them.

Trust is the ownership check, not the filename. On POSIX the file and every parent must be uid 0, mode with no group or world write, and not a symlink. On Windows, `icacls` output may grant write only to SYSTEM and Administrators (inherit-only ACEs ignored). `HKLM` is trusted because a standard user cannot write it. A file that calls itself managed and is user-writable is refused whole. Doctor fails on that. There is no `AGENTMETRY_SKIP_MANAGED_POLICY`. That variable would be the downgrade.

The parser is a small YAML subset plus `plistlib` and `winreg`. The hook does not import PyYAML or pydantic for this. `apply_locked_env()` runs at the start of the hook's `main()`, not at import, so the hook import-cost test stays a measure of the import.

A bad value refuses the whole managed document. Unknown keys are ignored and doctor warns. Missing managed paths are skipped. A solo machine with no `/etc/agentmetry` sees no change.

### Split privilege is a deployment, not a default

The trail is only as strong as the account that can write it. The chain comments already say that. The deployment that matches the claim is:

- A LaunchDaemon or Windows service, running as root or LocalSystem, owns `/var/db/agentmetry` or `C:\ProgramData\Agentmetry`. The trail, the anchor, and the full API token live there. Users and user-space agents do not have write or delete.
- A LaunchAgent or a per-user scheduled task, in the Aqua or interactive session, owns hook files under the developer home and reports coverage. It does not write the trail directory.
- The daemon is passed `--user-profile-dir` when the machine has one developer. A multi-user daemon cannot see every home from one process. The per-user agent is the coverage reporter. The daemon does not pretend otherwise.

The user agent must not be the writer of `/var/db`. If it is, the split is cosmetic.

### HostSigner stays pluggable and off by default

Ordering is already proved on the host. Attribution needs a key the agent cannot use. The interface, not implemented in these two pull requests:

```text
sign_checkpoint(host_id, session_id, tree_size, merkle_root, timestamp) -> signature
```

Called from the heartbeat and from anchor checkpoints. The signature is a sibling of the event, the same way `signing.py` keeps signatures out of the canonical record, so the hash chain does not change and the detection freeze is untouched.

Backends, in the order a fleet should adopt them:

1. Ed25519 key file on the data directory, ACL limited to the daemon account. Ships first because it has no vendor SDK. A same-user install still cannot keep the key from the agent, which is why this backend is honest only behind the split above.
2. macOS Keychain or Secure Enclave, Windows DPAPI or TPM, via the same interface.
3. An MDM SCEP certificate, when the customer already has one. The sensor should not run its own CA.

No backend is loaded when none is configured. Solo `agentmetry start` does not gain a crypto dependency.

### What not to do on the hook hot path

No file watcher inside the hook process. No ML model. No YAML library. No base64 brute force of every argument on every tool call until that pass has a measured cost and a test that the hook still returns before the IDE times it out. Decode and response scanning belong in a later change with that measurement, still stdlib.

UNIX sockets are a later transport. They do not fix the same-user writer. They are worth adding once the daemon is a different uid, so the socket's peer credential is the check and the full token never sits in the user's environment. The hook would still need a credential that can append and cannot read or close, which is the ingest-scoped token the core does not enforce yet.

### Hook tamper signal

A watcher on the IDE config paths (mtime, inode, and a hash of the hook command) should append `hook_config_tampered` as soon as the file changes, not at the next 300 second beat. The per-user agent is the right process: it is already in the session that can see `~`. The daemon should treat a missing beat from that agent as unverified coverage, which it already does when `hook_profile` is `service`.

Do not have that agent rewrite hook files on every interval. Rewriting changes mtime and fights the watcher. Install only when coverage is `uncovered`.

## 3. Prioritized implementation plan

Each item is one reviewable pull request. None of them edit `rules.py`, `traits.py`, `engine.py`, `mitre.py`, or `policies/detection/manifest.yaml`.

| PR | Scope | Status |
|---|---|---|
| 1 | Managed policy hierarchy. `--data-dir`, `--user-profile-dir`, `--policy-dir`. Defaults unchanged. Tests for POSIX and Windows ACL logic with mocks. This audit. `SECURITY.md` auth sentence. | This pull request |
| 2 | macOS LaunchDaemon and LaunchAgent, pkg build script, MDM profile. Intune Detect and Remediate. `icacls` for the trail and `policy.yaml`. `doctor --json`. `hook_remediation` as its own action so the event is not stored as a tool call. Azure Trusted Signing documented as an example workflow, not wired into CI. | Follow-up pull request |
| 3 | `hook_config_tampered` from a user-session watcher (mtime, inode, hash). No rewrite on the poll interval. | Not started |
| 4 | `HostSigner` interface and the Ed25519 key-file backend, signing the heartbeat and anchor checkpoint. Keychain, DPAPI, TPM, and SCEP behind the same interface, off unless configured. | Not started |
| 5 | DLP: one decode pass (base64, URL, hex) and the same scan on tool response text that arguments already get. Measure the hook. Stay on stdlib. | Not started |
| 6 | Core enforcement of an ingest-scoped token: the hook credential can append and cannot read the trail or close a detection. Today the hook's preferred file is not a scope. | Not started |
| 7 | Optional UNIX socket or named pipe for the daemon uid, peer-credential check, bearer not required for local append. | Not started |
| 8 | Spool byte budget across rotations, so a same-user flood stops instead of moving to the next file. | Not started |

PR 2's Detect script reads `doctor --json` (findings, the coverage map, `orchestrator_reachable`) and exits 1 when the service is down, when any present surface is `uncovered`, or when a surface is `unknown`. `absent` is fine. It does not parse the text report. `hooks status` remains the coverage-only exit code it already is.

Remediate runs `agentmetry hooks install`, then the `icacls` script when it is elevated, then posts one `hook_remediation` event. If the post fails after a successful install, the script exits 0 and prints a warning, so Intune does not reinstall on a loop. `hook_remediation` maps to action type `hook_remediation`, with an empty correlation id and no tool block, so the frozen sequence rules do not see a tool call.

The macOS user agent runs `hooks status` and calls `hooks install` only when that exits 1. It does not write `/var/db/agentmetry`.

## 4. Phase 3. ML and behavioral analysis (design only)

This section is a design. It is not a pull request, and it does not add a model, a dependency, or a new detection rule.

### What the trail already is

The canonical JSONL is the feature store. Each record has a time, a session, an action type, a tool name, an argument hash, optional traits the hook computed before hashing, a DLP verdict that is metadata only, and a hash-chain position. Training input is that record after redaction. It is not the raw prompt and not the raw tool output. A model that needs the plaintext has to live where the hook does, and the hook is the path this audit keeps small.

### Features worth extracting

Per session, over a fixed window:

- Tool-name sequence and the action types, as a short n-gram, not the arguments.
- Counts: file reads, shell calls, network-looking tools, distinct paths (from hashes, so the path text stays hashed).
- Rate: calls per minute, bytes of trail this session appended.
- Whether a call was gated, denied, or followed a DLP match.
- Coverage state and spool depth from the heartbeat, so a session that runs while hooks are `uncovered` is a feature of its own.

Normal, for this product, is a developer session: bursts of reads and edits, occasional shell, approvals that match the tool policy. Anomalous, as a hypothesis to test on a recorded corpus before any rule exists, is a session that suddenly reads far more files than its own baseline, a tool sequence that has not appeared in that repo's history, or a network tool after a credential-shaped path. Those are the same shapes the frozen sequence rules already name. A model that restates `rule_credential_exfil` is not a finding.

### Baseline

Fit on this machine's own historical sessions, after a human has triaged the detections those sessions already produced. A global model trained on other customers' trails is a hosted product, and this repo stays local-first. The baseline is a file under the data directory, written by the daemon account, so the agent cannot edit its own threshold. Cold start: no score until the operator has a stated minimum of sessions. Publishing a number for that minimum before the corpus exists would be inventing one.

### Deviation, and what it must not do

A score is an event on the trail (`action.type` something like `behavior_score`, additive, no reuse of `tool_called`). It can degrade the heartbeat and it can open a detection for a person. It must not revoke a tool, approve a tool, or rewrite a hook.

`CONTRIBUTING.md` is explicit: no default self-approve, ever. The mirror is no default self-revoke. An automatic deny changes what the agent does, which changes the record, and a wrong deny is an outage the developer will route around by removing the hook. That is the tamper window in section 1. Mitigation that is safe in this architecture is: record the score, show it in the dashboard, and let a person change `tool_policy_mode` or a managed policy key. A later enterprise control may bind a high score to an already-declared block rule. The binding is a human-signed policy, not a weight the model updates on the host.

### Guardrails before any of this is code

- No new third-party import on `agentmetry.hooks.ingest`.
- No edit to the frozen detection files. A model score is a separate event. It does not retune `rules.py`.
- The training file and the threshold file live in the daemon's data directory, not in the developer home.
- Evaluation is the existing benchmark discipline: a corpus, a count of misses, a count of false positives, both from a command. A score with no such command does not ship.
- The dogfood gate stays a ruleset fingerprint. A model change must not be able to move that fingerprint.
