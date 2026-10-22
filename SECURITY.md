# Security Policy

Agentmetry is security tooling, so we take reports seriously, including reports
about Agentmetry itself.

## Status: Alpha

Agentmetry is in **public alpha**. It is not yet hardened for hostile
multi-tenant environments. Treat it as a local, single-operator tool. See
"Known limitations" below before deploying it anywhere that matters.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Use GitHub's [private vulnerability
reporting](https://github.com/blitzcrieg1/agentmetry/security/advisories/new)
(Security → Report a vulnerability), or email the maintainer.

Please include: what you found, how to reproduce it, and what an attacker gains.
We aim to acknowledge within 7 days. As an unfunded alpha project we cannot offer
a bounty.

## Scope

In scope:

- Bypasses of the audit trail: anything that lets an agent's tool call execute
  without producing a canonical event.
- Secret leakage through the trail: values that should have been redacted or
  hashed but are written in plaintext to the JSONL, a SIEM sink, or the dashboard.
- Detection evasion: sequences that should fire a rule (e.g. credential access
  followed by network egress) but do not.
- Authentication bypass on the API, or forwarder sinks leaking data to the wrong
  destination.

Out of scope:

- Anything requiring an attacker who already has code execution as the operator's
  own user. Agentmetry runs with the operator's privileges by design; it is a
  flight recorder, not a sandbox.
- The unmanaged-agent gap (see below). It is a known architectural limit, not a
  vulnerability.

## Known limitations (read this)

- **Agentmetry only sees what it is wired into.** It records the agents whose
  hooks or MCP proxy it is installed on. It does **not** see an unmanaged Cursor,
  ChatGPT, or Copilot session that never routes through it. Observing those is
  CASB/endpoint-DLP territory, not this product. Anyone telling you an
  agent-observability tool gives you full coverage of unmanaged AI usage is
  selling you something.
- **Auth is on by default** (since 0.9.3). The first start writes a random
  token to `<data dir>/api-token`, owner-only, and every route except
  `/api/v1/health` requires it. `AGENTMETRY_API_KEY`, when set, replaces it.
  `AGENTMETRY_AUTH_DISABLED=1` turns the check off for development: `doctor`
  warns while it is set, and fails if the API is also bound beyond loopback.
  A process running as the same OS user can read the token, which is the
  same-user limit above.
- **The ingest-only token can add events, and anyone holding it can add false
  ones.** From the release after 0.9.9 the recorder also writes `<data dir>/ingest-token`. It is
  accepted on `POST /api/v1/audit/ingest` and nowhere else: it cannot read the
  trail, export evidence or close a detection, and tests hold each of those
  routes refusing it. Hooks prefer it. Whoever can read it, which includes
  Codex's Windows sandbox accounts once `hooks install` grants them read, can
  post events that the recorder stamps with this host's identity. The hash
  chain then records them faithfully: it proves the trail was not edited after
  the fact, not that an event describes something that happened. A sandboxed,
  prompt-injected agent can therefore add fabricated events to its own record,
  but cannot read, delete or triage the record.
- **Codex's sandbox cannot use the spool.** Codex's Windows sandbox accounts
  cannot write the data directory, so a Codex event sent while the recorder is
  down is lost rather than queued for replay. Other agents' hooks, which run as
  the developer, spool as before. A spool location the sandbox can write is
  tracked in [#302](https://github.com/blitzcrieg1/agentmetry/issues/302).
- **Configured is not the same as recorded.** Hook coverage checks that each
  agent's hook entry exists. An agent can still skip it (Codex runs no hook
  the developer has not approved in its `/hooks` prompt), and that cannot be
  read from disk. `doctor` and the heartbeat therefore also name every
  configured agent with no event in the last seven days (`hooks_silent`). That
  is evidence, not proof: an agent nobody used is silent too.
- **A managed policy is only as strong as its file permissions.** A fleet lock
  (see [docs/managed-policy.md](docs/managed-policy.md)) is honoured only from
  a file the developer cannot change: owned by SYSTEM, Administrators or
  TrustedInstaller on Windows, by root elsewhere, with no other principal able
  to write it or its folder. A file that fails the check is refused whole, and
  `doctor` and the heartbeat report it. A developer who is a local
  administrator can change anything, a lock included, and a developer who
  removes the hook from their IDE is reported by hook coverage, not stopped.
- **Ingest is rate limited, not walled.** `POST /api/v1/audit/ingest` takes a
  burst of 500 events and then 20 a second per source app, and 300 and then 10
  a second per session ([#312](https://github.com/blitzcrieg1/agentmetry/issues/312)).
  Past either cap it answers 429; the hook spools the event and the recorder
  replays it within a minute with its original timestamp, and the refusals are
  counted in `/api/v1/audit/status` as `ingest_throttled`. That caps how fast
  one agent can write through the API and makes a flood visible. It does not
  stop an agent running as the developer from writing the hook spool directly;
  the spool's 32 MB cap bounds that path, per drain, instead.
- **Redaction is best-effort.** Secrets are scrubbed by pattern matching. Novel
  credential formats can slip through into the trail. Do not treat the JSONL as
  safe to publish.
- **Command logging is opt-in** (`AGENTMETRY_AUDIT_LOG_COMMANDS`). When enabled,
  shell command text is stored (after scrubbing). Leave it off if the commands
  themselves are sensitive.

## How Agentmetry checks itself

A tool that inspects other people's supply chains should be able to answer the
same questions about its own. Every one of these runs in CI on each pull request
and on master; none of it is a periodic manual pass.

| Concern | Control | Where |
|---|---|---|
| Committed secrets | gitleaks over the pushed commit range | `ci.yml` |
| Insecure code patterns | ruff `S` (bandit) and `B` (bugbear), zero findings | `ci.yml` |
| Data flow a linter cannot follow | CodeQL `security-extended`, Python and TypeScript | `codeql.yml` |
| Vulnerable dependencies | `pip-audit --strict` on the full resolved tree | `ci.yml` |
| Dependency currency | Dependabot, weekly, including GitHub Actions | `dependabot.yml` |
| Detection accuracy | 57-case benchmark, fails on any miss or false positive | `ci.yml`, `release.yml` |
| Packaging | wheel installed into a clean environment; `doctor` must report no FAIL | `release.yml` |
| Publication | PyPI Trusted Publishing (OIDC). No API token exists to leak | `release.yml` |

Two of these are deliberately **not** required status checks: CodeQL and
`pip-audit`. Both report on the world rather than on the diff, so a CVE
published overnight would block an unrelated documentation fix. A visible red
mark the maintainer reads is worth more than a blocking gate the maintainer
learns to route around.

Where a bandit finding is suppressed, the suppression carries the reasoning
next to it rather than a bare `noqa`, and the two rules disabled project-wide
(`S603`, `S607`, both about subprocess invocation) are argued in
`apps/orchestrator/pyproject.toml`. If you think one of those arguments is
wrong, that is worth an issue.

What this does **not** include, stated plainly: there is no third-party
penetration test, no SOC 2, no signed release artifact, and no reproducible
build. The MSI is unsigned. Those are real gaps, not oversights, and they are
the honest answer to a security questionnaire that asks.
