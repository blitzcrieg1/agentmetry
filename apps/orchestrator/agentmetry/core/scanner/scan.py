"""`agentmetry scan`: run the checks over a target and report what they found.

Targets, in the order people reach for them:

- **nothing**: every MCP server configured for the agents on this machine. The
  launch package is checked for typosquats, and the configuration findings
  `agentmetry mcp` already knows (unpinned fetch-and-run, plaintext http) are
  reported beside them. Descriptions are not readable here: a live server
  hands them to the model at `tools/list`, which only the MCP proxy sees, so
  servers are reported as unobserved on that front rather than as clean. It
  also reads the instruction files an agent loads by itself (AGENTS.md,
  CLAUDE.md and their siblings) in Downloads, on the Desktop and in the home
  folder, where a browser can leave one (`instruction_files.py`).
- **a file or folder**: skills, rules files, CLAUDE.md and AGENTS.md, and any
  saved `tools/list` result (`{"tools": [...]}` or a list of tool objects),
  checked for model-steering text. The scripts a skill or rules folder carries
  are read as text and checked for the same steering text (#360); files that
  are not readable as text are named in the report as not read rather than
  passed over in silence. Instruction files an agent loads by itself are also
  checked for install directives and for where they sit.
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

from agentmetry.core.paths import user_profile_dir
from agentmetry.core.scanner import injection, instruction_files, typosquat

#: Files read as model-visible text when a folder is scanned.
TEXT_SUFFIXES = (".md", ".mdc", ".txt")
#: Script types a skill or rules folder may carry. Read as text and checked
#: for the same steering patterns as the markdown beside them (#360): a skill
#: is opted into and its job is to carry commands, so no install-directive
#: check applies, but "run this script" is exactly how a skill acts.
SCRIPT_SUFFIXES = (".sh", ".bash", ".py", ".ps1", ".js", ".ts", ".rb")
#: How many not-read file names the report lists before it starts counting
#: instead (#360). The count is always honest; the list is a sample.
NOT_READ_LISTED = 20
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
    check: str  # injection | instruction_file | typosquat | mcp_config
    category: str
    severity: str  # high | medium | low
    where: str
    detail: str


@dataclass
class ScanReport:
    target: str
    findings: list[Finding] = field(default_factory=list)
    scanned: int = 0
    #: How many of the scanned items were scripts inside the target (#360).
    scripts_scanned: int = 0
    #: Files in the target the scanner cannot read as text. The report names
    #: them so "no findings" cannot read as "everything was checked" (#360).
    not_read: list[str] = field(default_factory=list)
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
            "scripts_scanned": self.scripts_scanned,
            "findings": [asdict(f) for f in self.findings],
            "supply_chain": [asdict(f) for f in self.findings if f.check == "typosquat"],
            "not_read": self.not_read,
            "unobserved": self.unobserved,
            "errors": self.errors,
        }

    def lines(self) -> list[str]:
        out = [f"agentmetry scan: {self.target}", f"  {self.verdict} in {self.scanned} item{'s' if self.scanned != 1 else ''} scanned"]
        if self.scripts_scanned:
            out.append(f"  scripts read as text and checked: {self.scripts_scanned}")
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


def _scan_text_file(path: Path, report: ScanReport, known: dict[str, frozenset[str]] | None = None) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = injection.find_in_text(text)
    for hit in hits:
        line = text.count("\n", 0, hit.start) + 1
        report.findings.append(
            Finding("injection", hit.category, hit.severity, f"{path}:{line}", _excerpt(text, hit.start, hit.end))
        )
    if path.name in instruction_files.AUTOLOAD_NAMES:
        _check_instruction_file(path, text, bool(hits), report, known or {})


def _check_instruction_file(
    path: Path, text: str, steering: bool, report: ScanReport, known: dict[str, frozenset[str]]
) -> None:
    """Where an autoloaded instruction file sits, and whether it installs anything."""
    place = instruction_files.outside_project(path, user_profile_dir())
    if place:
        report.findings.append(
            Finding(
                "instruction_file", "outside_project", "high", str(path),
                f"an agent started here loads this file and follows it, and it sits in {place} with "
                "no repository around it, where a browser or an unzipped archive leaves files. Read "
                "it before starting an agent in this folder, and delete it if you did not put it there",
            )
        )
    for hit in instruction_files.find_installs(text):
        line = text.count("\n", 0, hit.start) + 1
        where = f"{path}:{line}"
        # Alone, a named package is a line to read. Beside text that steers the
        # model, or in a folder no project lives in, it is the payload.
        severity = "high" if steering or place else "medium"
        report.findings.append(
            Finding("instruction_file", "install_directive", severity, where, _excerpt(text, hit.start, hit.end))
        )
        if hit.ecosystem in typosquat.ECOSYSTEMS and hit.name:
            squat = typosquat.check(hit.name, hit.ecosystem, known.get(hit.ecosystem, frozenset()))
            if squat:
                report.findings.append(Finding("typosquat", squat.kind, "high", where, squat.sentence()))
    for start, end in instruction_files.find_agent_config(text):
        line = text.count("\n", 0, start) + 1
        severity = "high" if steering or place else "medium"
        report.findings.append(
            Finding("instruction_file", "agent_config", severity, f"{path}:{line}", _excerpt(text, start, end))
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


def _candidate_files(root: Path) -> tuple[list[Path], list[str], int, bool]:
    """Files the scanner reads, and the ones it must admit it cannot.

    A folder target holds whatever it holds; text, JSON and script types are
    read. Everything else is returned by name and count so the report can say
    what was not checked, instead of implying a folder was covered because it
    was walked (#360). The names are a capped sample of the skipped files
    encountered. The last value says whether an eligible file exceeded the cap.
    """
    if root.is_file():
        return [root], [], 0, False
    found: list[Path] = []
    skipped: list[str] = []
    skipped_total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in TEXT_NAMES or name.lower().endswith(
                TEXT_SUFFIXES + (".json",) + SCRIPT_SUFFIXES
            ):
                if len(found) >= MAX_FILES:
                    return found, skipped, skipped_total, True
                found.append(Path(dirpath) / name)
            else:
                skipped_total += 1
                if len(skipped) < NOT_READ_LISTED:
                    try:
                        skipped.append(str((Path(dirpath) / name).relative_to(root)))
                    except ValueError:
                        skipped.append(name)
    return found, skipped, skipped_total, False


def scan_path(target: Path, known: dict[str, frozenset[str]] | None = None) -> ScanReport:
    report = ScanReport(target=str(target))
    if not target.exists():
        report.errors.append(f"{target}: no such file or folder")
        return report
    files, not_read, not_read_total, limit_reached = _candidate_files(target)
    if limit_reached:
        report.unobserved.append(f"Scan stopped at the {MAX_FILES:,}-file limit. Additional files were not checked.")
    if not_read:
        report.not_read = not_read
        report.unobserved.append(
            f"{not_read_total} file{'s' if not_read_total != 1 else ''} not readable as text "
            f"were not checked (e.g. {', '.join(not_read[:3])})"
        )
    for path in files:
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
                if path.suffix.lower() in SCRIPT_SUFFIXES:
                    report.scripts_scanned += 1
                _scan_text_file(path, report, known)
        except OSError as exc:
            report.errors.append(f"{path}: {exc.strerror or exc}")
    return report


def run(target: str | None, *, project: Path | None = None, known_file: str | None = None) -> ScanReport:
    """Dispatch on the target's shape."""
    known = _load_known(known_file)
    if not target:
        return scan_machine(project, known)
    if target.startswith(("npm:", "pypi:")):
        return scan_package(target, known)
    return scan_path(Path(target), known)


def scan_machine(project: Path | None = None, known: dict[str, frozenset[str]] | None = None) -> ScanReport:
    """The MCP servers configured here, and the instruction files a browser could have left."""
    report = scan_mcp_config(project, known)
    report.target = (
        "this machine: MCP servers, and agent instruction files in Downloads, on the Desktop "
        "and in the home folder"
    )
    for path in instruction_files.machine_files(user_profile_dir()):
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                report.errors.append(f"{path}: larger than {MAX_FILE_BYTES:,} bytes, skipped")
                continue
            report.scanned += 1
            _scan_text_file(path, report, known)
        except OSError as exc:
            report.errors.append(f"{path}: {exc.strerror or exc}")
    return report
