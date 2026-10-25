"""Instruction files an agent loads on its own, and where they sit.

An agent started in a folder reads AGENTS.md, CLAUDE.md and their siblings from
it without being asked, and follows them with the permissions it already has.
In October 2026 one was found in a customer's ~/Downloads, where a web page can
save a file without a prompt, telling a coding agent to install a rogue npm
package (BleepingComputer, 2026-10-25). Nothing there was a bug to patch: the
agent did what instruction files are for.

So two questions are asked of these files only, never of skills or tool
descriptions, which legitimately say "pip install pandas" all day:

- **install_directive**: does it tell the agent to install a *named* package,
  run a package straight from a registry, or pipe a download into a shell?
  A bare `npm install` or `pip install -e .` installs the project the file
  belongs to and is silent. A named package is a reason to read the line, not
  proof of an attack, so it is medium on its own.
- **agent_config**: does it name the agent's own endpoint, proxy or execution
  config (`ANTHROPIC_BASE_URL`, `.claude/settings.json`, hooks, MCP config)?
  The Claude Code variant of that attack pointed the API at the attacker's
  server. A project's notes rarely touch these, and when they do it is worth a
  look: medium on its own.
- **outside_project**: is the file in Downloads or on the Desktop, with no
  repository between it and that folder? Nobody writes a project's agent
  instructions there; a browser or an unzipped archive does. High, whatever the
  file says.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

#: Loaded by an agent from its working directory without being asked.
#: SKILL.md is not: a skill is opted into, and its job is to carry commands.
AUTOLOAD_NAMES = frozenset({"AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", ".windsurfrules"})

_I = re.IGNORECASE
# Flags stay on the same line as the command: a fenced block's next line is a
# different command.
_FLAGS = r"(?P<flags>(?:[ \t]+-{1,2}[\w-]+(?:=\S+)?)*)"
_NPM_NAME = r"(?P<name>(?:@[\w.-]+/)?[A-Za-z0-9][\w.-]*)(?:@[\w.^~<>=*-]+)?"
_PY_NAME = r"(?P<name>[A-Za-z0-9][\w.-]*)(?:\[[\w,.-]+\])?(?:[<>=!~]=?[\w.*-]+)?"

#: (ecosystem, pattern). The ecosystem names the registry a typosquat check uses.
_INSTALLS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("npm", re.compile(rf"\b(?:npm|pnpm|cnpm)[ \t]+(?:i|install|add)\b{_FLAGS}[ \t]+{_NPM_NAME}", _I)),
    ("npm", re.compile(rf"\byarn[ \t]+(?:global[ \t]+)?add\b{_FLAGS}[ \t]+{_NPM_NAME}", _I)),
    ("npm", re.compile(rf"\bbun[ \t]+(?:add|install|i)\b{_FLAGS}[ \t]+{_NPM_NAME}", _I)),
    # Runs whatever the registry serves today, without asking.
    ("npm", re.compile(rf"\bnpx[ \t]+(?:-y|--yes)\b{_FLAGS}[ \t]+{_NPM_NAME}", _I)),
    (
        "pypi",
        re.compile(
            rf"\b(?:pip3?|python3?[ \t]+-m[ \t]+pip|py[ \t]+-m[ \t]+pip|uv[ \t]+pip)[ \t]+install\b{_FLAGS}[ \t]+{_PY_NAME}",
            _I,
        ),
    ),
    ("pypi", re.compile(rf"\b(?:uv[ \t]+(?:add|tool[ \t]+install)|pipx[ \t]+install|uvx)\b{_FLAGS}[ \t]+{_PY_NAME}", _I)),
    ("", re.compile(rf"\b(?:gem|cargo|go|brew)[ \t]+install\b{_FLAGS}[ \t]+(?P<name>[A-Za-z0-9][\w./@-]*)", _I)),
)

#: A download handed straight to a shell: nothing is left on disk to read first.
_PIPE_TO_SHELL = re.compile(
    r"\b(?:curl|wget)\b[^\n|]*\|[ \t]*(?:sudo[ \t]+)?(?:ba|z|da|k)?sh\b"
    r"|\b(?:iwr|irm|Invoke-WebRequest|Invoke-RestMethod)\b[^\n|]*\|[ \t]*(?:iex|Invoke-Expression)\b"
    r"|\b(?:iex|Invoke-Expression)\b[ \t]*\(?[ \t]*\(?[ \t]*(?:iwr|irm|New-Object[ \t]+Net\.WebClient)",
    _I,
)

#: Where an agent's own traffic and execution are configured. The Claude Code
#: variant of the Downloads attack pointed ANTHROPIC_BASE_URL at the attacker's
#: server and read the OAuth token off the wire. The names mirror the
#: agent_env_override DLP rule and the block_agent_exec_config_write policy.
_AGENT_CONFIG = re.compile(
    r"\b(?:ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|OPENAI_BASE_URL|OPENAI_API_BASE|GEMINI_BASE_URL|"
    r"HTTPS?_PROXY|NODE_OPTIONS|PYTHONSTARTUP|LD_PRELOAD)\b"
    r"|(?:^|[\s`'\"(\\/~])(?:\.claude[\\/]settings(?:\.local)?\.json|\.claude[\\/]hooks?\b|\.mcp\.json|"
    r"\.codex[\\/](?:config\.toml|hooks\.json)|\.gemini[\\/]settings\.json|\.cursor[\\/](?:mcp|hooks)\.json)",
    _I,
)

#: Flags that point the installer at the project rather than at a named package.
_PROJECT_FLAGS = re.compile(r"(?:^|\s)-(?:r|e|c)\b|--(?:requirement|editable|constraint)\b", _I)
#: A "name" that is a file the project ships, not a package.
_FILE_LIKE = re.compile(r"\.(?:txt|toml|cfg|lock|json|in)$", _I)


@dataclass(frozen=True)
class InstallHit:
    start: int
    end: int
    ecosystem: str  # npm | pypi | "" (no typosquat list for it)
    name: str  # the package, or "" for a pipe into a shell


def find_installs(text: str) -> list[InstallHit]:
    """Install directives in `text`: at most one per line, in order."""
    text = text or ""
    found: list[InstallHit] = []
    for eco, pattern in _INSTALLS:
        for m in pattern.finditer(text):
            name = m.group("name")
            if _PROJECT_FLAGS.search(m.group("flags") or "") or _FILE_LIKE.search(name):
                continue
            found.append(InstallHit(m.start(), m.end(), eco, name))
    for m in _PIPE_TO_SHELL.finditer(text):
        found.append(InstallHit(m.start(), m.end(), "", ""))
    hits: list[InstallHit] = []
    seen_lines: set[int] = set()
    for hit in sorted(found, key=lambda h: h.start):
        line = text.count("\n", 0, hit.start)
        if line in seen_lines:
            continue
        seen_lines.add(line)
        hits.append(hit)
    return hits


def find_agent_config(text: str) -> list[tuple[int, int]]:
    """Lines that name an agent's endpoint, proxy or execution config: one per line."""
    text = text or ""
    out: list[tuple[int, int]] = []
    seen_lines: set[int] = set()
    for m in _AGENT_CONFIG.finditer(text):
        line = text.count("\n", 0, m.start())
        if line not in seen_lines:
            seen_lines.add(line)
            out.append((m.start(), m.end()))
    return out


def risky_folders(home: Path) -> list[tuple[str, Path]]:
    """Where a browser or an archive drops files nobody wrote as a project.

    Includes the OneDrive copies Windows redirects Desktop and Downloads to.
    """
    return [(label, base / label) for label in ("Downloads", "Desktop") for base in (home, home / "OneDrive")]


def outside_project(path: Path, home: Path) -> str:
    """'Downloads' or 'Desktop' when `path` sits there outside any repository, else ''."""
    try:
        resolved = path.resolve()
    except OSError:
        return ""
    for label, folder in risky_folders(home):
        try:
            root = folder.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        d = resolved.parent
        while True:
            if (d / ".git").exists():
                return ""
            if d == root or d.parent == d:
                break
            d = d.parent
        return label
    return ""


#: How far into each folder the machine-wide scan looks. An unzipped archive
#: puts its AGENTS.md one or two levels down; deeper is somebody's project.
MACHINE_DEPTH = {"Downloads": 2, "Desktop": 2}


def machine_files(home: Path, limit: int = 500) -> list[Path]:
    """Autoloaded instruction files in Downloads, on the Desktop and in the home folder itself."""
    found: list[Path] = []
    for name in sorted(AUTOLOAD_NAMES):
        candidate = home / name
        if candidate.is_file():
            found.append(candidate)
    for label, folder in risky_folders(home):
        if not folder.is_dir():
            continue
        depth = MACHINE_DEPTH[label]
        base = len(folder.parts)
        for dirpath, dirnames, filenames in os.walk(folder):
            here = Path(dirpath)
            keep = len(here.parts) - base < depth
            dirnames[:] = [d for d in dirnames if keep and not d.startswith(".") and d != "node_modules"]
            for fname in filenames:
                if fname in AUTOLOAD_NAMES:
                    found.append(here / fname)
                    if len(found) >= limit:
                        return found
    return found
