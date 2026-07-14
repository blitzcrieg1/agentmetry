# Security Policy

Agentmetry is security tooling, so we take reports seriously — including reports
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

- Bypasses of the audit trail — anything that lets an agent's tool call execute
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
- **Auth is off by default.** With no `AGENTMETRY_API_KEY` set, the local API is
  unauthenticated so local dev works out of the box. Set the key before exposing
  the port beyond localhost.
- **Redaction is best-effort.** Secrets are scrubbed by pattern matching. Novel
  credential formats can slip through into the trail. Do not treat the JSONL as
  safe to publish.
- **Command logging is opt-in** (`AGENTMETRY_AUDIT_LOG_COMMANDS`). When enabled,
  shell command text is stored (after scrubbing). Leave it off if the commands
  themselves are sensitive.
