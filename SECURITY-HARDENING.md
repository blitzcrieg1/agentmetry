# Security hardening for the first enterprise pilot

Branch `pilot-hardening`, on top of `f309c9b`. Written for the
reviewer of that branch and for the pilot customer's security team. Every
figure below comes from a command in this repository; the command is named.

Scope: making the sensor safe and credible for an EU regulated pilot on
Windows fleets managed through Intune. Items 1 to 7 and 27 (console and
enterprise auth) and the installer half of 15 to 18 are in the Agentmetry
Enterprise repository and have their own `SECURITY-HARDENING.md` there.

**State at the end of the branch**

| Check | Result | Command |
|---|---|---|
| Tests | 1624 passed, 1 skipped | `pytest -q` in `apps/orchestrator` |
| Coverage | 82% (CI floor 78%) | `pytest -q --cov=agentmetry` |
| Lint | clean | `ruff check agentmetry tests` |
| Detection benchmark | 54 cases, 0 missed, 0 false positives | `agentmetry benchmark` |
| Ruleset fingerprint | `15846a0915769d4a`, unchanged | see CLAUDE.md |

No frozen detection file was edited. No event-schema field was removed and
the hash-chain record format is unchanged; every schema change is additive and
listed under the item that made it.

---

## What changed, item by item

### 8. API authentication on by default (`dc4835b`)

**Before:** every route was open unless `AGENTMETRY_API_KEY` was set, and
`doctor` reported that as `[OK] loopback only (no API key needed)`. Any local
process, or a web page that got a request through, could read the trail,
export evidence, inject events and close detections.

**Now:** the first start writes a random token to `<data dir>/api-token`,
owner-only (0600; on Windows an `icacls` ACL with one entry). Every route
except `/api/v1/health` requires it, as `X-API-Key` or a bearer token. The
hook, the OTel receiver and the CLI read the same file, so nothing needs
configuring. `AGENTMETRY_API_KEY` still wins when set. A disposition records
the decider from how the request authenticated (the dashboard session's
operator, or an extension's principal), never only from the request body.
`AGENTMETRY_AUTH_DISABLED=1` is the development override; `doctor` warns while
it is on and fails if the API is also bound beyond loopback, and reports the
token file's path and whether other users can read it.

Files: `core/api_token.py`, `core/auth.py`, `api/routes/auth.py`,
`api/routes/audit.py`, `core/diagnostics/doctor.py`, `hooks/ingest.py`, `cli`.
Tests: `tests/test_auth_default.py` (including a sweep of every route in the
OpenAPI schema, so a route added later without auth fails CI),
`tests/test_doctor.py`.

### 9. Host-header allowlist against DNS rebinding (`35bd965`)

`TrustedHostMiddleware` refuses any `Host` other than localhost, 127.0.0.1,
::1 and `AGENTMETRY_TRUSTED_HOSTS`. Files: `api/trusted_host.py`.
Tests: `tests/test_trusted_host.py`.

### 10. Data out of `site-packages` (`a1abe33`)

An installed wheel kept its trail and `.env` inside `site-packages`, where
`pip uninstall` or a venv rebuild deletes evidence. Data now resolves to
`AGENTMETRY_DATA_DIR`, then the MSI's install root, then the checkout, then the
per-user directory (`%LOCALAPPDATA%\Agentmetry`, `~/.local/share/agentmetry`,
`~/Library/Application Support/Agentmetry`), stdlib only so the hook can use
it. `doctor` warns about data left in the old location; it is never moved
automatically. Files: `core/paths.py`. Tests: `tests/test_paths.py`.

### 11. Keyed argument fingerprints (`a37aa76`)

Plain SHA-256 of a guessable argument can be confirmed by anyone with SIEM
read access. With `AGENTMETRY_HASH_KEY` (one value per fleet) the hook and the
orchestrator use HMAC-SHA256 and label it `input_redaction: "hmac"`. Unset,
nothing changes. Docs say "pseudonymised". `doctor` warns on a fleet install
with no key. Schema: new value `hmac` / `hmac+command` for `input_redaction`.
Files: `core/audit/hashing.py`, `hooks/ingest.py`, `core/audit/external.py`.
Tests: `tests/test_hash_key.py`.

### 12. `serve.bat` binds loopback (`24a477a`)

`AGENTMETRY_BIND`, default 127.0.0.1. Test: `tests/test_serve_script_binds_loopback.py`.

### 13. The dashboard holds no key (`dc4835b`)

The dashboard compiled `NEXT_PUBLIC_AGENTMETRY_API_KEY` into its JavaScript.
Now `agentmetry dashboard` asks for a one-time link (120 s, single use) that
sets an HttpOnly, SameSite=Strict session cookie. Writes from the cookie need
`X-Agentmetry-Request: 1`; a WebSocket on the cookie needs a loopback Origin;
a session cannot mint further links. Files: `core/dashboard_session.py`,
`apps/dashboard/lib/*.ts`. Tests: `tests/test_auth_default.py`.

### 14. No hook rewriting on boot (`24a477a`)

The orchestrator rewrote `~/.cursor/hooks.json` and Claude settings at every
start. Now opt-in with `AGENTMETRY_AUTO_INSTALL_HOOKS=1`.
Tests: `tests/test_suite_leaves_real_home_alone.py`.

### 15 and 18, core half: machine-wide installs (`3818aa1`)

`AGENTMETRY_HOOK_SPOOL_PATH` lets the MSI put the spool where user-context
hooks may write; the hook, the drain and the heartbeat resolve it through one
function. An `ingest-token` file, which the hook prefers, holds an ingest-only
credential an extension provisions (Enterprise writes a host-bound token
there, readable by local users; it can send events and nothing else).
Tests: `tests/test_shared_install.py`.

### 19. Forwarding from a cursor (`1d94690`)

**Before:** each network sink was called inline, once per event, with a fresh
client and no retry. A SIEM outage lost every event it spanned.

**Now:** the trail is the queue. One forwarder per sink tails it from
`forward-cursors/<sink>.json`, batches (HEC concatenation, Elastic `_bulk` with
`_id` = `event_id`, Chronicle batches, the console's `{"events": [...]}`),
retries with exponential backoff and jitter capped at five minutes, and moves
the cursor only after the destination accepts. The cursor names the last
record by hash, so a replaced trail is detected and resynced. A malformed
event is bisected out and dead-lettered instead of wedging the feed.
`/api/v1/audit/status` reports per-sink seq and failure age.
`agentmetry replay` now reads the trail instead of the empty legacy outbox.
Acceptance test from the brief: a four-hour outage on a virtual clock with
traffic arriving throughout, and a restart mid-outage, deliver every event in
order. Tests: `tests/test_forwarder.py`.

### 20. Trail rotation (`858ea39`, refs #101)

`agentmetry trail rotate`, or `AGENTMETRY_TRAIL_ROTATE_BYTES`, archives the
active file into `<trail>.archive/` with a manifest. Records are unchanged and
the chain continues across segments; verify, Merkle roots (anchors taken
before a rotation still verify), the index backfill, the forwarder and replay
all read every segment. Nothing is deleted. Off by default.
Policy: `docs/trail-retention.md`. Tests: `tests/test_trail_chain.py`.

### 21. MCP proxy in the package (`00c6484`)

`agentmetry mcp-proxy [--server NAME] -- <server command>` works from a wheel
or the MSI; the proxy used to exist only in a checkout. `tools/mcp_audit_proxy.py`
remains as an alias for existing configs. Tests:
`tests/test_mcp_proxy_packaged.py` builds the wheel, installs it into a clean
venv and runs the proxy outside the repository; `release.yml` also runs it
from the fresh full install.

### 22. Container and legacy drivers (`9ad21a9`, #209)

One `agentmetry` service on 127.0.0.1:8000, no qdrant, postgres, ollama or
Gemini; the Dockerfile CMD is `agentmetry.api.main:app`, the image runs as a
non-root user; the legacy MCP driver mount at boot is opt-in
(`AGENTMETRY_LEGACY_DRIVERS=1`). Tests: `tests/test_container_and_legacy_runtime.py`.

### 23. Hook latency (`4c46217`): improved, target not met

`scripts/bench_hook.py` runs one real hook process per sample against a stub
ingest server. On the maintainer's Windows machine: **p50 366 ms before,
254 ms after.** The interpreter alone is 49 ms there. The win was an unused
HTTPS context and proxy lookup on every loopback POST, plus `argparse` and
`subprocess` on the hook path. See "Open" for what 100 ms needs.
Tests: `tests/test_hook_import_cost.py`. CI's Windows job prints the benchmark.

### 24, core half: signing extension point (`f8c3834`)

`register_event_signer()`; with a signer registered the batched forwarder
sends `{"event", "signature"}` items. The event and the trail are unchanged.
Tests: `tests/test_event_signing.py`.

### 25. Microsoft Sentinel (`47dd6ba`, `a2c4692`)

`AGENTMETRY_AUDIT_SINK=sentinel`: the Logs Ingestion API with an Entra
client-credentials token, forwarder-only. Setup with a DCR generated from the
code's column list (`docs/integrations/sentinel.md`), and KQL for the
recorder's detections plus S1 to S7 (`docs/integrations/detections-sentinel.md`).
Tests (`tests/test_sentinel.py`) check the wire format, that the documented DCR
matches the record columns, and that every rule id in `rules.py` is on the KQL page.

### 26, core half: admin-managed hook locations (`1f18a7e`)

`agentmetry hooks install --managed` (as administrator) writes Claude Code's
`managed-settings.d` drop-in, Cursor's enterprise `hooks.json` and Codex's
`requirements.toml`, merging the shared files and parsing every document
before writing. `--lock` adds `allowManagedHooksOnly` / `allow_managed_hooks_only`.
Tests: `tests/test_managed_hooks.py` (writes only under a temp directory).

### Supporting changes

- `1a59377`: an identity-provider extension point, so Enterprise binds event
  identity without monkeypatching core functions (item 6's core half).
- `17b1925`: a test that a refused ingest (401, 403, 429, 5xx) is spooled, not
  dropped, which is what lets enterprise auth fail closed safely.

---

## Behaviour a user will notice

- **Authentication is on.** Scripts calling the API need the token from
  `<data dir>/api-token` or `AGENTMETRY_API_KEY`. Open the dashboard with
  `agentmetry dashboard`.
- **Hooks are no longer installed at boot.** Run `agentmetry hooks install`,
  or set `AGENTMETRY_AUTO_INSTALL_HOOKS=1`.
- **The trail is always written when a network sink is configured,** because
  it is what the forwarder reads.
- **`docker compose up`** starts one service; the agent-runtime services are gone.
- **An installed wheel keeps data in the per-user directory.** `doctor` says
  where any older data is.

## Incident during this work

A packaging test, before the fix in `00c6484`, launched the proxy with every
`AGENTMETRY_*` variable stripped and a mistyped ingest URL variable, so it
posted one synthetic event to the maintainer's running dogfood recorder:
seq 52292, `source.app = mcp_proxy`, `fake_server.read_file`, 2026-10-03
14:56 UTC. It is still in that trail. The trail is hash-chained evidence and
is not edited; the event is benign and is not a detection. A later change in
this branch would have done the same through the test suite, so `4c46217`
added an autouse fixture that points every test at a dead port, and the live
trail was checked after each subsequent run (only the session's own tool calls
and heartbeats arrived).

## Open, and why

| Item | State | What is needed |
|---|---|---|
| 23 hook latency | 254 ms p50, target 100 ms | A thin hook that asks the running orchestrator to evaluate DLP and policy, keeping local evaluation only as a fallback. That moves the enforcement boundary and needs a design decision before code. What remains in-process is urllib, YAML and dataclasses for the manifests, the detection package (imported by the frozen `mitre.py`), and regex compilation |
| 20 retention | Rotation ships; pruning does not | Deleting segments changes what verification and anchors prove. Design in `docs/trail-retention.md` (prune only behind an off-host anchor, leave a checkpoint, never prune undecided findings); #101 rules out shipping it silently |
| 25 Sentinel | Built and tested against the API reference | A run against a live Log Analytics workspace |
| 26 managed hooks | Paths from vendor docs as of 2026-10 | Confirm on a real Intune device; whether Codex still asks the developer to trust managed hooks is unconfirmed |
| 24 signing | Core hook only here | See the Enterprise document (keystore, hook leg) |
| Dashboard | Signed-out state handled | A sign-in page in the dashboard itself, rather than relying on `agentmetry dashboard` |

Merged as [#220](https://github.com/blitzcrieg1/agentmetry/pull/220) on
2026-10-03, after the two CodeQL findings it raised were fixed (`6497b58`,
`8930740`). Released in 0.9.3 on 2026-10-04; 0.9.2 was tagged on the release
commit before it and carries none of these changes.
