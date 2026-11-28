# `agentmetry scan`

What an agent is about to depend on, checked before it runs.

The recorder answers what an agent did. `scan` answers the question a reviewer
asks first: is the tool, skill or MCP server it is wired to shaped like an
attack. It reads configuration and text already on the machine. It never runs
a server and never fetches a package.

```bash
agentmetry scan                      # MCP servers, and instruction files in Downloads, Desktop and ~
agentmetry scan ./skills             # a file or folder: skills, rules, a saved tools/list
agentmetry scan --preflight ./repo   # inventory declarations that can start execution
agentmetry scan --wheel ./example-1.0-py3-none-any.whl  # inspect Python startup declarations
agentmetry scan pypi:request         # one package name
agentmetry scan --json               # the report as JSON
agentmetry scan --known names.txt    # add your own package names (npm:/pypi: or bare)
```

The dependency and instruction scanner exits **0** for no findings, **1** for
findings and **2** if nothing could be read. Unlike
`agentmetry mcp` and `agentmetry posture`, which a health check runs in the
background and which exit 0 with findings, `scan` is run on purpose before an
install, so a finding stops the script that ran it.

The output never contains the word "safe". "No findings" means these checks
found nothing, which is all it can honestly mean.

## Repository execution preflight

Run `agentmetry scan --preflight PATH` against a checkout before opening it
in an agent or running project setup. Add `--json` for structured inventory.
The preflight reads manifests in the named directory and reports where each
declaration is defined. Entries describe potential execution and carry no
malware verdict or severity.

| Manifest | Declaration |
|---|---|
| `.claude/settings.json`, `.claude/settings.local.json` | Claude Code `SessionStart` handlers. [Hooks reference](https://code.claude.com/docs/en/hooks#sessionstart) |
| `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json` | Project MCP process or remote server declarations and any declared header helper. [Claude Code MCP](https://code.claude.com/docs/en/mcp), [Cursor MCP](https://cursor.com/docs/mcp), [VS Code MCP](https://code.visualstudio.com/docs/agent-customization/mcp-servers) |
| `.vscode/tasks.json` | Tasks with `runOptions.runOn: folderOpen`. A dependency entry signals that further tasks need review. [VS Code tasks](https://code.visualstudio.com/docs/debugtest/tasks#_run-behavior) |
| `package.json` in the checkout | npm install lifecycle entries. Scripts such as `test` are outside this inventory. [npm lifecycle order](https://docs.npmjs.com/cli/v11/using-npm/scripts/#life-cycle-operation-order) |
| `.devcontainer.json`, `.devcontainer/devcontainer.json`, `.devcontainer/*/devcontainer.json` | Host initialization and container creation, start and attach lifecycle fields. [Dev Container specification](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainer-reference.md) |
| `conftest.py`, `tests/conftest.py` | pytest imports these at collection time, before any test runs. Reported as `pytest_conftest` with mechanism `import_time` |

The report keeps manifest paths, entry locations and reference status. Commands,
arguments, environment fields, server names, endpoint URLs and script contents
stay out of the report. A simple npm script path can be checked relative to its
package. For simple startup hooks and default editor tasks, relative paths
are checked from the repository root. That assumes you open this directory as
the project. Supported project-root placeholders can also locate a candidate
script in the checkout. Other shell syntax, client-dependent working directories,
task dependencies and container paths remain unresolved. The preflight does not
resolve agent trust, policy or enablement.

A resolved script is followed one step: the file is read as data (never
executed, never followed through a link), hashed with SHA-256, and checked
against a small set of conservative observation patterns, for example
`download_pipe_to_shell` (a `curl` or `wget` piped into a shell) or
`module_level_subprocess_call` (a module-level `subprocess` call in Python,
which runs on import). The report carries the reference status
`present_inspected`, the file size, the content hash prefix and the
observation names only. Contents stay on the machine. Observations name a
shape; they are not a malware verdict or a severity.

The scan skips symbolic links and Windows junctions, dependency and build
directories, and manifests outside the supported paths. It caps directory
entries at 12,000, depth at 32, manifests at 512, data at 1,000,000 bytes per
manifest and 16,000,000 bytes total, and declarations at 1,000. Malformed or
unreadable manifests, links and limits are reported as partial coverage.
Preflight exits **0** when it reads the supported manifests in scope or finds
none, and **2** on an incomplete inventory. Script reference statuses describe
what could be located and do not change manifest coverage. This inventory cannot
see hooks from an installed plugin, downloaded dependencies or child processes.

## Python wheel startup check

Run `agentmetry scan --wheel PATH` on a local `.whl` before installing it.
Use `--json` for a structured report and `--expected-sha256 HEX` to compare
the artifact with an independently obtained digest. The report always labels
publisher provenance as unverified. A digest match establishes byte identity
with the artifact represented by the expected hash. [PyPI attestations](https://docs.pypi.org/attestations/)

The scanner reads archive metadata and startup declarations at the wheel root
and directly under `.data/purelib` or `.data/platlib` directories. It reports
partial coverage if a startup file sits in a noncanonical `.data` directory.
It distinguishes executable `.pth` import lines from path entries and counts
`.start` entry points. Python 3.15 also recognizes indented import lines and
can ignore `.pth` imports when a matching `.start` file exists. The report
lists where declarations appear and leaves runtime behavior to the installed
interpreter and its configuration. [Wheel format](https://packaging.python.org/en/latest/specifications/binary-distribution-format/), [Python 3.14 site](https://docs.python.org/3.14/library/site.html), [Python 3.15 site](https://docs.python.org/3.15/library/site.html)

The report includes archive member names, counts and up to 32 executable
declaration line numbers per file. It omits line contents. The scanner uses
bounded reads and leaves the wheel uninstalled and unextracted. Limits are
128 MiB per wheel, 4 MiB and 4,096 entries in its ZIP directory, 128 startup
files, 64 KiB per startup file and 4 MiB total startup text. Startup text is
read as UTF-8 with optional BOM. Archive layouts and startup content outside
the supported formats produce a partial report when encountered.

The wheel check exits **0** after inspecting supported locations without an
executable declaration or hash mismatch, **1** when either requires review
and **2** when the report is incomplete. Incomplete reports can also contain
findings. Path-only entries are shown without raising a finding. Normal
packages can declare startup code. This check covers the two named startup
file formats, with package code, other auto-import mechanisms such as
`sitecustomize`, transitive dependencies and verification of attestations
outside its scope.

## Existing scan checks

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
- Preflight observations are static and shallow: a script can hide behavior
  behind encoding, build steps or a downloaded second stage.
- An instruction phrased unlike any category above is invisible to it.
- Writing *about* these attacks resembles them. This page produces five
  findings when scanned, which is the check working, not failing. Point it at
  what an agent will read (skills, rules, tool listings), not at security
  writing.
- A clean scan is not a clean bill of health. Pair it with the recorder, which
  sees what the server actually did, and with `agentmetry mcp`, which records
  when its description changes.
