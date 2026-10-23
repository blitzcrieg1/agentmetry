"""`agentmetry scan`: run the checks over a target and report what they found.

Targets, in the order people reach for them:

- **nothing**: every MCP server configured for the agents on this machine. The
  launch package is checked for typosquats, and the configuration findings
  `agentmetry mcp` already knows (unpinned fetch-and-run, plaintext http) are
  reported beside them. Descriptions are not readable here: a live server
  hands them to the model at `tools/list`, which only the MCP proxy sees, so
  servers are reported as unobserved on that front rather than as clean.
- **a file or folder**: skills, rules files, CLAUDE.md and AGENTS.md, and any
  saved `tools/list` result (`{"tools": [...]}` or a list of tool objects),
  checked for model-steering text.
- **`npm:NAME` or `pypi:NAME`**: one package name, checked for typosquatting.

Output never contains the word "safe". "No findings" means these checks found
nothing, which is all it can honestly mean.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentmetry.core.scanner import injection, typosquat

#: Files read as model-visible text when a folder is scanned.
TEXT_SUFFIXES = (".md", ".mdc", ".txt")
TEXT_NAMES = (".cursorrules", ".windsurfrules", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "SKILL.md")
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"})
MAX_FILE_BYTES = 1_000_000
MAX_FILES = 2_000

#: Launcher -> ecosystem, for the package an MCP entry fetches.
LAUNCHER_ECOSYSTEM = {"npx": "npm", "pnpx": "npm", "bunx": "npm", "uvx": "pypi", "pipx": "pypi"}

#: Configuration codes from `mcp_inventory`, with the severity scan gives them.
CONFIG_SEVERITY = {"unpinned_fetch": "medium", "auto_confirm": "low", "plaintext_http": "medium", "no_command": "low"}
#: What to print for the codes the inventory carries no sentence for. Without
#: it the finding's explanation was its own code: "auto_confirm".
CONFIG_DETAIL = {
    "auto_confirm": "launched with an auto-confirm flag (-y or --yes), so the package "
    "manager installs and runs the package without asking first",
    "no_command": "a stdio server with no command, so there is nothing to check about "
    "what it launches",
}


@dataclass(frozen=True)
class Finding:
    check: str  # injection | typosquat | mcp_config
    category: str
    severity: str  # high | medium | low
    where: str
    detail: str


@dataclass
class ScanReport:
    target: str
    findings: list[Finding] = field(default_factory=list)
    scanned: int = 0
    unobserved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if not self.scanned and self.errors:
            return "not scanned"
        return f"{len(self.findings)} finding{'s' if len(self.findings) != 1 else ''}" if self.findings else "no findings"

    def exit_code(self) -> int:
        """0 nothing found, 1 findings, 2 nothing could be read.

        Unlike `mcp` and `posture`, which a health check runs in the
        background, `scan` is run on purpose before something is installed,
        so a finding is meant to stop the script that ran it.
        """
        if not self.scanned and self.errors:
            return 2
        return 1 if self.findings else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "verdict": self.verdict,
            "scanned": self.scanned,
            "findings": [asdict(f) for f in self.findings],
            "supply_chain": [asdict(f) for f in self.findings if f.check == "typosquat"],
            "unobserved": self.unobserved,
            "errors": self.errors,
        }

    def lines(self) -> list[str]:
        out = [f"agentmetry scan: {self.target}", f"  {self.verdict} in {self.scanned} item{'s' if self.scanned != 1 else ''} scanned"]
        order = {"high": 0, "medium": 1, "low": 2}
        for f in sorted(self.findings, key=lambda f: (order.get(f.severity, 3), f.where)):
            out.append(f"  [{f.severity}] {f.check}/{f.category}  {f.where}")
            out.append(f"      {f.detail}")
        for note in self.unobserved:
            out.append(f"  unobserved: {note}")
        for err in self.errors:
            out.append(f"  error: {err}")
        if not self.findings and self.scanned:
            out.append("  No findings means these checks found nothing. It does not mean safe.")
        return out


# ----------------------------------------------------------------------
# Targets
# ----------------------------------------------------------------------


def _load_known(path: str | None) -> dict[str, frozenset[str]]:
    """`--known FILE`: one name per line, `npm:` or `pypi:` prefixed, or bare for both."""
    extra: dict[str, set[str]] = {"npm": set(), "pypi": set()}
    if not path:
        return {k: frozenset(v) for k, v in extra.items()}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        eco, sep, name = line.partition(":")
        if sep and eco in extra:
            extra[eco].add(name.strip())
        else:
            extra["npm"].add(line)
            extra["pypi"].add(line)
    return {k: frozenset(v) for k, v in extra.items()}


def scan_package(spec: str, known: dict[str, frozenset[str]] | None = None) -> ScanReport:
    eco, _, name = spec.partition(":")
    report = ScanReport(target=spec)
    if eco not in typosquat.ECOSYSTEMS or not name:
        report.errors.append(f"expected npm:NAME or pypi:NAME, got {spec!r}")
        return report
    report.scanned = 1
    hit = typosquat.check(name, eco, (known or {}).get(eco, frozenset()))
    if hit:
        report.findings.append(Finding("typosquat", hit.kind, "high", spec, hit.sentence()))
    return report


def scan_mcp_config(project: Path | None = None, known: dict[str, frozenset[str]] | None = None) -> ScanReport:
    from agentmetry.core.diagnostics.mcp_inventory import collect

    inv = collect(project)
    report = ScanReport(target="MCP servers configured on this machine", scanned=len(inv.servers))
    for path, why in inv.unreadable:
        report.errors.append(f"{path}: {why}")
    for server in inv.servers:
        where = f"{server.agent}: {server.name} ({server.source})"
        for code in server.finding_codes():
            if code in ("unpinned_fetch", "plaintext_http"):
                detail = next(iter(server.findings()), code)
            else:
                detail = CONFIG_DETAIL.get(code, code)
            report.findings.append(Finding("mcp_config", code, CONFIG_SEVERITY.get(code, "low"), where, detail))
        launcher = Path(server.command).stem.lower() if server.command else ""
        eco = LAUNCHER_ECOSYSTEM.get(launcher)
        spec = server.spec()
        if eco and spec:
            hit = typosquat.check(spec, eco, (known or {}).get(eco, frozenset()))
            if hit:
                report.findings.append(Finding("typosquat", hit.kind, "high", where, hit.sentence()))
    if inv.servers:
        report.unobserved.append(
            f"tool descriptions of {len(inv.servers)} server{'s' if len(inv.servers) != 1 else ''}: a server hands "
            "them to the model at tools/list, which only the MCP proxy sees. Wrap a server with "
            "`agentmetry mcp-proxy` and its descriptions are checked on every listing, as counts on the trail."
        )
    return report


def _tools_in(doc: Any) -> list[dict[str, Any]] | None:
    """The tools in a saved `tools/list` result, or None if this is not one."""
    if isinstance(doc, dict) and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    tools = doc.get("tools") if isinstance(doc, dict) else doc
    if isinstance(tools, list) and tools and all(isinstance(t, dict) and "name" in t for t in tools):
        return tools
    return None


def _excerpt(text: str, start: int, end: int, width: int = 100) -> str:
    begin = text.rfind("\n", 0, start) + 1
    stop = text.find("\n", end)
    line = text[begin : stop if stop != -1 else len(text)].strip()
    return line if len(line) <= width else line[: width - 1] + "…"


def _scan_text_file(path: Path, report: ScanReport) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for hit in injection.find_in_text(text):
        line = text.count("\n", 0, hit.start) + 1
        report.findings.append(
            Finding("injection", hit.category, hit.severity, f"{path}:{line}", _excerpt(text, hit.start, hit.end))
        )


def _scan_tools_file(path: Path, tools: list[dict[str, Any]], report: ScanReport) -> None:
    from agentmetry.core.diagnostics.mcp_schema import _walk_strings

    for tool in tools:
        name = str(tool.get("name") or "?")
        for text in _walk_strings(tool):
            for hit in injection.find_in_text(text):
                report.findings.append(
                    Finding("injection", hit.category, hit.severity, f"{path}: tool {name}", _excerpt(text, hit.start, hit.end))
                )


def _candidate_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in TEXT_NAMES or name.lower().endswith(TEXT_SUFFIXES + (".json",)):
                found.append(Path(dirpath) / name)
                if len(found) >= MAX_FILES:
                    return found
    return found


def scan_path(target: Path) -> ScanReport:
    report = ScanReport(target=str(target))
    if not target.exists():
        report.errors.append(f"{target}: no such file or folder")
        return report
    for path in _candidate_files(target):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                report.errors.append(f"{path}: larger than {MAX_FILE_BYTES:,} bytes, skipped")
                continue
            if path.suffix.lower() == ".json":
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                tools = _tools_in(doc)
                if tools is None:
                    continue
                report.scanned += 1
                _scan_tools_file(path, tools, report)
            else:
                report.scanned += 1
                _scan_text_file(path, report)
        except OSError as exc:
            report.errors.append(f"{path}: {exc.strerror or exc}")
    return report


def run(target: str | None, *, project: Path | None = None, known_file: str | None = None) -> ScanReport:
    """Dispatch on the target's shape."""
    known = _load_known(known_file)
    if not target:
        return scan_mcp_config(project, known)
    if target.startswith(("npm:", "pypi:")):
        return scan_package(target, known)
    return scan_path(Path(target))
