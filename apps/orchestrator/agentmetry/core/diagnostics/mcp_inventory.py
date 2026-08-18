"""What MCP servers are configured on this machine, and which can change under you.

2026 made MCP the interesting attack surface. The disclosures that matter to a
recorder are not the individual CVEs, they are the shape:

* The official STDIO transport launches a server by running an arbitrary
  operating system command. A config file is therefore an execution primitive,
  and anyone who can edit it has code execution as the developer.
* `postmark-mcp` shipped fifteen clean versions before adding a line of
  exfiltration. Nothing in the config changed when it turned hostile.
* Agentjacking (Tenet Security, June 2026) had Claude Code, Cursor and Codex
  fetch attacker-controlled instructions through a legitimate MCP server and run
  them with the developer's own privileges.

Agentmetry already records what agents *did*. It could not answer the question a
security reviewer asks first, which is what those agents were *wired to*. This
answers it, and is deliberately not a detection rule: it inspects configuration
at rest rather than behaviour in a session, so it lives in `doctor` and needs
nothing from the sequence engine.

## What this can and cannot tell you

It reads the configuration an agent will act on. It does not resolve what a
package will contain when next fetched, and it cannot: `npx -y foo` is a promise
to run whatever exists at the moment of invocation. That is why an unpinned entry
is reported as the finding rather than as a detail. The honest claim is "this
machine will execute whatever that resolves to", never "this machine is
compromised".
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Fetch-and-run launchers. These resolve a package over the network on every
#: invocation, so the bytes executed are decided later than the config was read.
_FETCHING_LAUNCHER = re.compile(r"^(npx|uvx|pnpx|bunx|pipx)$", re.IGNORECASE)

#: `pkg@1.2.3` is pinned. A bare `pkg` and `pkg@latest` are not.
_PINNED_SPEC = re.compile(r"^@?[^@\s]+(?:/[^@\s]+)?@(?!latest$)[\w.\-+]+$")

#: Flags that suppress the install prompt, so a first-run fetch is silent.
_AUTO_YES = frozenset({"-y", "--yes", "-q", "--quiet"})


@dataclass(frozen=True)
class McpServer:
    """One configured server, normalised across agents."""

    agent: str
    scope: str
    name: str
    transport: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env_keys: tuple[str, ...] = ()
    source: str = ""

    def spec(self) -> str:
        """The package this entry resolves to, for pin checking."""
        for arg in self.args:
            if not arg.startswith("-"):
                return arg
        return ""

    def fingerprint(self) -> str:
        """Stable hash of everything that decides what gets executed.

        Env *keys* are included and env *values* are not. A changed variable name
        alters behaviour and is worth noticing; the values are routinely
        credentials and have no business in a diagnostic hash an operator might
        paste into an issue.
        """
        material = json.dumps(
            {
                "agent": self.agent,
                "name": self.name,
                "transport": self.transport,
                "command": self.command,
                "args": list(self.args),
                "url": self.url,
                "env_keys": list(self.env_keys),
            },
            sort_keys=True,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def findings(self) -> list[str]:
        """Configuration facts worth an operator's attention."""
        out: list[str] = []
        if self.transport == "stdio":
            if not self.command:
                out.append("stdio entry with no command; the agent cannot start it")
                return out
            launcher = Path(self.command).stem.lower()
            spec = self.spec()
            if _FETCHING_LAUNCHER.match(launcher) and spec and not _PINNED_SPEC.match(spec):
                finding = (
                    f"unpinned: {launcher} {spec} resolves over the network on every "
                    "launch, so the code that runs is chosen after this file was written"
                )
                # An auto-confirm flag is an aggravating factor, never a finding
                # on its own. `npx -y pkg@1.4.2` is a correctly configured
                # server, and reporting it would make every well-set-up machine
                # red, which is how a check stops being read.
                if _AUTO_YES & set(self.args):
                    finding += ", and an auto-confirm flag suppresses the first-run prompt"
                out.append(finding)
        elif self.url.startswith("http://"):
            out.append(f"plaintext transport: {self.url} is http, not https")
        return out


@dataclass
class McpInventory:
    servers: list[McpServer] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    unreadable: list[tuple[str, str]] = field(default_factory=list)

    @property
    def flagged(self) -> list[McpServer]:
        return [s for s in self.servers if s.findings()]

    def digest(self) -> str:
        """One hash over the whole configured surface.

        Publish it beside a trail anchor and a later change becomes detectable
        without disclosing which servers a machine talks to.
        """
        joined = "".join(sorted(s.fingerprint() for s in self.servers))
        return hashlib.sha256(joined.encode()).hexdigest()


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def config_locations(project: Path | None = None) -> list[tuple[str, str, Path]]:
    """(agent, scope, path) for every config this build knows how to read.

    A missing file is normal rather than an error: a machine running Cursor and
    not Claude Code should report on Cursor and stay silent about the rest.
    """
    home = Path(os.path.expanduser("~"))
    found: list[tuple[str, str, Path]] = [
        ("claude", "user", home / ".claude.json"),
        ("claude", "user", home / ".claude" / "settings.json"),
        ("cursor", "user", home / ".cursor" / "mcp.json"),
        ("windsurf", "user", home / ".codeium" / "windsurf" / "mcp_config.json"),
        ("vscode", "user", home / ".vscode" / "mcp.json"),
    ]
    if project:
        found += [
            ("claude", "project", project / ".mcp.json"),
            ("cursor", "project", project / ".cursor" / "mcp.json"),
            ("vscode", "project", project / ".vscode" / "mcp.json"),
        ]
    return found


def _blocks(node: Any, path: str = "") -> Iterable[tuple[str, dict]]:
    """Every `mcpServers` mapping in a document, with where it was found.

    Claude Code nests one under each entry of `projects`, keyed by absolute path,
    so reading only the top level finds nothing on a machine with several.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key == "mcpServers" and isinstance(value, dict):
                yield path or "<root>", value
            else:
                yield from _blocks(value, here)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _blocks(value, f"{path}[{index}]")


def _scope_label(scope: str, where: str) -> str:
    """Keep the scope useful without pasting absolute project paths into output."""
    if not where or where == "<root>":
        return scope
    tail = where.rsplit(".", 1)[-1]
    return f"{scope}:{Path(tail).name or tail}"


def _normalise(agent: str, scope: str, where: str, name: str, cfg: Any, source: Path) -> McpServer:
    if not isinstance(cfg, dict):
        return McpServer(agent, scope, name, "unknown", source=str(source))
    url = str(cfg.get("url") or cfg.get("serverUrl") or "")
    declared = str(cfg.get("type") or cfg.get("transport") or "").lower()
    transport = declared or ("stdio" if cfg.get("command") else ("http" if url else "unknown"))
    env = cfg.get("env")
    return McpServer(
        agent=agent,
        scope=_scope_label(scope, where),
        name=name,
        transport=transport,
        command=str(cfg.get("command") or ""),
        args=tuple(str(a) for a in (cfg.get("args") or [])),
        url=url,
        env_keys=tuple(sorted(env)) if isinstance(env, dict) else (),
        source=str(source),
    )


def collect(project: Path | None = None) -> McpInventory:
    """Read every known config and normalise what it declares."""
    inv = McpInventory()
    for agent, scope, path in config_locations(project):
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A config this build cannot parse is a fact worth reporting, not a
            # reason to abort. The agent may be running it regardless.
            inv.unreadable.append((str(path), str(exc)))
            continue
        inv.files_read.append(str(path))
        for where, block in _blocks(document):
            for name, cfg in block.items():
                inv.servers.append(_normalise(agent, scope, where, str(name), cfg, path))
    inv.servers.sort(key=lambda s: (s.agent, s.name))
    return inv


def summary_lines(inv: McpInventory) -> list[str]:
    """Operator-facing report. Never prints env values or absolute project paths."""
    if not inv.files_read and not inv.unreadable:
        return ["No MCP configuration found for any known agent."]
    if not inv.servers and not inv.unreadable:
        return [
            f"No MCP servers configured ({len(inv.files_read)} config file(s) read). "
            "Nothing is wired to an agent on this machine."
        ]

    lines = [f"{len(inv.servers)} MCP server(s) across {len(inv.files_read)} config file(s)"]
    for server in inv.servers:
        target = server.url or " ".join(filter(None, (server.command, *server.args)))
        lines.append(f"  [{server.agent}/{server.transport}] {server.name}: {target[:88]}")
        for finding in server.findings():
            lines.append(f"      ! {finding}")
    for path, exc in inv.unreadable:
        lines.append(f"  ? unreadable: {Path(path).name} ({exc[:60]})")
    if inv.servers:
        lines.append(f"  config digest: {inv.digest()[:16]}")
    return lines
