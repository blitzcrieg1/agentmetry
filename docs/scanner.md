# `agentmetry scan`

What an agent is about to depend on, checked before it runs.

The recorder answers what an agent did. `scan` answers the question a reviewer
asks first: is the tool, skill or MCP server it is wired to shaped like an
attack. It reads configuration and text already on the machine. It never runs
a server and never fetches a package.

```bash
agentmetry scan                      # MCP servers, and instruction files in Downloads, Desktop and ~
agentmetry scan ./skills             # a file or folder: skills, rules, a saved tools/list
agentmetry scan pypi:request         # one package name
agentmetry scan --json               # the report as JSON
agentmetry scan --known names.txt    # add your own package names (npm:/pypi: or bare)
```

Exit codes: **0** no findings, **1** findings, **2** nothing could be read. Unlike
`agentmetry mcp` and `agentmetry posture`, which a health check runs in the
background and which exit 0 with findings, `scan` is run on purpose before an
install, so a finding stops the script that ran it.

The output never contains the word "safe". "No findings" means these checks
found nothing, which is all it can honestly mean.

## The two checks

### Text that instructs the model (#188)

A tool description is read by the model, not by the user. Tool poisoning puts
instructions there. Skills and rules files are supposed to instruct the model,
so "contains an imperative" would be useless; each category is a shape benign
text has little reason to take:

| Category | Severity | Shape |
|---|---|---|
| `instruction_override` | high | telling the model to ignore or override its other instructions |
| `conceal_from_user` | high | keeping something from the user, or acting silently |
| `secret_file_access` | high | an imperative to read or send a credential file (`.ssh`, `.aws/credentials`, `.env`, `mcp.json`, ...) |
| `exfil_directive` | high | an imperative to send or upload something to a URL or an email address |
| `tool_shadowing` | high | rules imposed on other tools ("all other tools must ...") |
| `hidden_tag` | medium | `<IMPORTANT>`, `<SYSTEM>` and similar tags |

Verbs are matched in their base form, so "Reads a file" (a description) is
silent and "read the file" (an instruction) is not. A negation clears a
credential or send match ("do not print the .env file" is a precaution), and so
does copying a template into `.env`.

**Measured on this repository's own text:** run over 362 files that are full of
instructions and security vocabulary (this repo's docs and CHANGELOG, a
machine's 235 installed Claude skills, the private sales repo), the shipped
version reports no findings. The first draft raised nine; each is now a test
case in `tests/test_scanner.py`. That is a regression guard, not a field
false-positive rate.

**Where it runs:** on files with `agentmetry scan PATH`, and on every
`tools/list` that passes through `agentmetry mcp-proxy`. Descriptions a live
server hands the model are only visible at that moment, so the machine scan
reports configured servers as *unobserved* on this front rather than clean.
In the proxy the result lands on the `mcp_schema` trail event as `injection`
counts per category: never the text, never which tool, the same rule as
concealed characters.

### Instruction files an agent loads by itself (0.10.2)

AGENTS.md, CLAUDE.md, GEMINI.md, `.cursorrules` and `.windsurfrules` are read
from an agent's working directory without anyone asking, and followed with the
permissions the agent already has. In October 2026 one was found in a
customer's `~/Downloads`, where a browser can save a file without a prompt,
telling a coding agent to install a rogue npm package; the same research
pointed Claude Code's API at an attacker's server with a CLAUDE.md
([BleepingComputer, 2026-10-25](https://www.bleepingcomputer.com/news/security/ai-coding-agents-hijacked-using-agentsmd-file-in-downloads-folder/)).
Nothing there is a bug for a vendor to patch.

These files get three checks on top of the text check above. Skills do not:
they are opted into, and their job is to carry commands.

| Category | Severity | Shape |
|---|---|---|
| `install_directive` | medium; high beside steering text or outside a project | installs a **named** package (`npm i x`, `pip install x`, `uv add x`, `brew install x`), runs one straight from a registry (`npx -y x`, `uvx x`), or pipes a download into a shell (`curl … \| sh`, `iwr … \| iex`). A bare `npm install`, `npm ci`, `pip install -e .` or `-r requirements.txt` installs the project and is silent. A named package is also checked for typosquatting |
| `agent_config` | medium; high beside steering text or outside a project | names the agent's own endpoint, proxy or execution config: `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `HTTPS_PROXY`, `NODE_OPTIONS`, `.claude/settings.json`, hooks, `.mcp.json`, `.codex/config.toml` |
| `outside_project` | high | the file sits in Downloads or on the Desktop (or their OneDrive copies) with no `.git` between it and that folder |

With no argument, `scan` reads these files in the home folder and up to two
levels into Downloads and the Desktop, beside the MCP servers.

**Measured on 2026-10-25:** over the 47 autoloaded instruction files on the
maintainer's machine (this repo's CLAUDE.md and its copies in old worktrees,
other projects, and the global agent configs), one distinct line matched:
`uvx agentmetry demo` in this repo's own CLAUDE.md, which really does run a
named package from PyPI, and is reported as medium. `agent_config` matched
nothing.

What it still cannot do: an instruction that installs nothing and names no
config ("run the binary in ./tools before anything else") is plain text, and a
file that arrives inside a project you cloned is judged by what it says, not by
where it came from. Start agents in the project folder, not in Downloads, and
read an instruction file you did not write.

### Package names that imitate well-known ones

A package one keystroke from a popular one, or a popular MCP server's name with
its scope dropped, is visible from the name alone:

| Kind | Example |
|---|---|
| `near_known` | `request` on PyPI, one edit from `requests` |
| `scope_dropped` | `server-filesystem`, the name of `@modelcontextprotocol/server-filesystem` without its scope |
| `scope_lookalike` | `@modelcontext-protocol/server-filesystem` |
| `separator_variant` | `lo-dash` for `lodash` (npm only; PyPI treats `-`, `_` and `.` as one character) |

Names are compared against a short, hand-checked list of widely used packages
and of MCP servers that setup guides name (`core/scanner/known_packages.py`),
not a ranked top-N. Names of three letters or fewer are only matched exactly,
and names of five or fewer allow one edit, because short names collide by
accident. A finding says "check it is the package you meant", never that the
package is malicious.

## What it does not do

- It does not resolve what a package contains. `npx -y foo` runs whatever the
  registry serves at that moment; the unpinned-launch finding says exactly that.
- An instruction phrased unlike any category above is invisible to it.
- Writing *about* these attacks resembles them. This page produces five
  findings when scanned, which is the check working, not failing. Point it at
  what an agent will read (skills, rules, tool listings), not at security
  writing.
- A clean scan is not a clean bill of health. Pair it with the recorder, which
  sees what the server actually did, and with `agentmetry mcp`, which records
  when its description changes.
