"""Inspect declarations that can start execution from a repository."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
from dataclasses import asdict, dataclass, field
from itertools import islice
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator

from agentmetry.core.scanner import script_inspect

MAX_ENTRIES = 12_000
MAX_DEPTH = 32
MAX_MANIFESTS = 512
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 16_000_000
MAX_SURFACES = 1_000
MAX_NOTICES = 100

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"})
MANIFEST_TYPES = {
    ".claude/settings.json": "claude",
    ".claude/settings.local.json": "claude",
    ".mcp.json": "mcp",
    ".cursor/mcp.json": "mcp",
    ".vscode/mcp.json": "vscode_mcp",
    ".vscode/tasks.json": "tasks",
    ".devcontainer.json": "devcontainer",
    ".devcontainer/devcontainer.json": "devcontainer",
}
NPM_INSTALL_EVENTS = ("preinstall", "install", "postinstall", "prepublish", "preprepare", "prepare", "postprepare")
CONTAINER_EVENTS = ("initializeCommand", "onCreateCommand", "updateContentCommand",
                    "postCreateCommand", "postStartCommand", "postAttachCommand")
INTERPRETERS = frozenset({"node", "bun", "python", "python3", "bash", "sh", "pwsh", "powershell"})
SCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".ts", ".py", ".sh", ".ps1", ".bat", ".cmd"})
SCRIPT_PATH = re.compile(r"[\w .:/\\-]+", flags=re.ASCII)


@dataclass(frozen=True)
class Reference:
    status: str
    path: str | None = None
    size_bytes: int | None = None
    content_sha256: str | None = None
    observations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Surface:
    manifest: str
    location: str
    trigger: str
    mechanism: str
    reference: Reference


@dataclass
class PreflightReport:
    target: str
    manifests_read: int = 0
    surfaces: list[Surface] = field(default_factory=list)
    unobserved: list[dict[str, str]] = field(default_factory=list)
    omitted_notices: int = 0

    def note(self, path: Path, reason: str) -> None:
        if len(self.unobserved) < MAX_NOTICES:
            self.unobserved.append({"path": path.as_posix(), "reason": reason})
        else:
            self.omitted_notices += 1

    def exit_code(self) -> int:
        return 2 if self.unobserved or self.omitted_notices else 0

    def to_json(self) -> dict[str, Any]:
        return {"mode": "repository_preflight", **asdict(self),
                "coverage": "partial" if self.exit_code() else "supported_manifests_read"}

    def lines(self) -> list[str]:
        status = "Partial inventory" if self.exit_code() else "Inventory"
        out = [f"Agentmetry repository preflight: {json.dumps(self.target)}",
               f"  {status}: {len(self.surfaces)} declarations in {self.manifests_read} supported manifests"]
        for surface in self.surfaces:
            ref = surface.reference
            suffix = ""
            if ref.path is not None:
                suffix = f" {json.dumps(ref.path)} ({ref.size_bytes} bytes"
                if ref.content_sha256 is not None:
                    suffix += f", sha256:{ref.content_sha256[:12]}"
                suffix += ")"
                if ref.observations:
                    suffix += f" observations={','.join(ref.observations)}"
            out.append(f"  {surface.trigger} | {surface.mechanism} | "
                       f"{json.dumps(surface.manifest)}:{surface.location} | {ref.status}{suffix}")
        for issue in self.unobserved:
            out.append(f"  Unobserved: {json.dumps(issue['path'])} | {issue['reason']}")
        if self.omitted_notices:
            out.append(f"  {self.omitted_notices} additional notices omitted")
        out.append("  Declarations describe possible execution. Referenced scripts are hashed and")
        out.append("  pattern-checked as data; contents stay out of the report and runtime behavior stays unobserved.")
        return out


def _jsonc(text: str) -> str:
    """Remove comments and trailing commas without rewriting quoted values."""
    parts: list[str] = []
    i = 0
    comma: int | None = None
    while i < len(text):
        fragment = text[i]
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = len(text) if end == -1 else end
            parts.append(" ")
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("unterminated comment")
            i = end + 2
            parts.append(" ")
            continue
        if fragment == '"':
            start = i
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i >= len(text):
                raise ValueError("unterminated string")
            fragment = text[start:i + 1]
        if not fragment.isspace():
            if comma is not None and fragment in ("}", "]"):
                parts[comma] = ""
            comma = len(parts) if fragment == "," else None
        parts.append(fragment)
        i += 1
    return "".join(parts)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("ambiguous duplicate key")
        value[key] = item
    return value


def _linked(info: os.stat_result) -> bool:
    # Windows junctions also use reparse points. Treat the entire category as
    # outside the scan rather than following vendor-specific redirections.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _manifest_type(relative: Path) -> str | None:
    name = relative.as_posix()
    if os.name == "nt":
        name = name.lower()
    parts = name.split("/")
    if parts[-1] == "package.json":
        return "npm"
    if len(parts) == 3 and parts[0] == ".devcontainer" and parts[-1] == "devcontainer.json":
        return "devcontainer"
    if name in ("conftest.py", "tests/conftest.py"):
        return "pytest"
    return MANIFEST_TYPES.get(name)


def _manifests(root: Path, report: PreflightReport) -> Iterator[tuple[Path, str]]:
    pending = [Path(".")]
    remaining = MAX_ENTRIES
    manifests = 0
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(root / directory) as entries:
                batch = list(islice(entries, remaining + 1))
        except OSError:
            report.note(directory, "directory_unreadable")
            continue
        if len(batch) > remaining:
            report.note(directory, "repository_entry_limit_reached")
            return
        remaining -= len(batch)
        for entry in sorted(batch, key=lambda x: x.name):
            relative = directory / entry.name
            if entry.name in SKIP_DIRS:
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                report.note(relative, "entry_unreadable")
                continue
            if _linked(info):
                report.note(relative, "linked_path_skipped")
            elif stat.S_ISDIR(info.st_mode):
                if len(relative.parts) <= MAX_DEPTH:
                    pending.append(relative)
                else:
                    report.note(relative, "directory_depth_limit_reached")
            elif kind := _manifest_type(relative):
                if not stat.S_ISREG(info.st_mode):
                    report.note(relative, "non_regular_manifest")
                    continue
                if manifests == MAX_MANIFESTS:
                    report.note(relative, "manifest_limit_reached")
                    return
                manifests += 1
                yield relative, kind


def _words(command: object) -> list[str] | None:
    if isinstance(command, list) and command and all(isinstance(x, str) and x for x in command):
        return command
    if not isinstance(command, str) or any(char in command for char in "\r\n;&|<>`"):
        return None
    try:
        lexer = shlex.shlex(command, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = lexer.escape = ""
        return list(lexer)
    except ValueError:
        return None


def _script_path(
    command: object, cwd: Path | None, root_markers: tuple[str, ...],
) -> tuple[str, PurePosixPath | None]:
    """Parse a simple declared script path. Returns (status, repo-relative path)."""
    if cwd is not None:
        cwd = Path(str(cwd))
    words = _words(command)
    if not words:
        return "not_resolved", None
    first = words[0].replace("\\", "/")
    if first.lower().removesuffix(".exe") in INTERPRETERS and len(words) > 1:
        path = words[1].replace("\\", "/")
        if path.startswith("-"):
            return "not_resolved", None
    elif "/" in first or PurePosixPath(first).suffix.lower() in SCRIPT_SUFFIXES:
        path = first
    else:
        return "not_identified", None
    # Recognize documented root markers only as a prefix. No arbitrary
    # variable expansion, and a shell string with single quotes stays opaque.
    if not isinstance(command, str) or "'" not in command:
        for marker in root_markers:
            if path.startswith(marker + "/"):
                path = path[len(marker) + 1:]
                cwd = Path(".")
                break
    if not SCRIPT_PATH.fullmatch(path) or path.startswith("-"):
        return "not_resolved", None
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or PureWindowsPath(path).drive or ".." in candidate.parts:
        return "outside_or_parent_path", None
    if not candidate.parts or cwd is None or ":" in path:
        return "not_resolved", None
    relative = cwd / Path(*candidate.parts)
    return "ok", PurePosixPath(relative.as_posix())


def _reference(
    root: Path, cwd: Path | None, command: object, root_markers: tuple[str, ...],
) -> Reference:
    """Check the path of a simple declared script on the local filesystem."""
    status, relative = _script_path(command, cwd, root_markers)
    if relative is None:
        return Reference(status)
    current = root
    try:
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if _linked(info):
                return Reference("linked_path_skipped")
    except FileNotFoundError:
        return Reference("not_found")
    except OSError:
        return Reference("unreadable")
    if not stat.S_ISREG(info.st_mode):
        return Reference("not_regular")
    if info.st_size > MAX_FILE_BYTES:
        return Reference("oversized", relative.as_posix(), info.st_size)
    return Reference("present_uninspected", relative.as_posix(), info.st_size)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("unsupported manifest field")
    return value


def _array(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("unsupported manifest field")
    return value


def _mcp_entries(doc: dict[str, Any], vscode: bool) -> Iterator[tuple[str, str, str, object, Path | None]]:
    key = "servers" if vscode else "mcpServers"
    for i, entry in enumerate(_object(doc.get(key, {})).values(), 1):
        record = _object(entry)
        marker = f"{key} entry {i}"
        if isinstance(record.get("command"), str) and record["command"]:
            args = _array(record.get("args", []))
            # MCP clients do not share a cwd contract. Inventory the process
            # without claiming a relative argument resolves at the repo root.
            yield marker, "mcp_server", "process", [record["command"], *args], None
        elif isinstance(record.get("url"), str) and record["url"]:
            yield marker, "mcp_server", "remote", None, None
        else:
            yield marker, "mcp_server", "unresolved", None, None
        if "headersHelper" in record:
            yield marker + " headersHelper", "mcp_headers_helper", "shell", record["headersHelper"], None


def _entries(
    relative: Path, kind: str, doc: dict[str, Any],
) -> Iterator[tuple[str, str, str, object, Path | None]]:
    if kind == "claude":
        hooks = _object(doc.get("hooks", {}))
        for i, group in enumerate(_array(hooks.get("SessionStart", [])), 1):
            for j, hook in enumerate(_array(_object(group).get("hooks", [])), 1):
                handler = _object(hook)
                mode = handler.get("type")
                launch = {"command": "shell", "http": "remote", "prompt": "agent", "agent": "agent"}
                command = handler.get("command") if mode == "command" else None
                if isinstance(command, str) and "args" in handler:
                    command = [command, *_array(handler["args"])]
                    launch["command"] = "process"
                yield (f"hooks.SessionStart group {i} handler {j}", "claude_session_start",
                       launch.get(mode, "unresolved") if isinstance(mode, str) else "unresolved",
                       command, Path("."))
    elif kind in ("mcp", "vscode_mcp"):
        yield from _mcp_entries(doc, kind == "vscode_mcp")
    elif kind == "tasks":
        for i, task in enumerate(_array(doc.get("tasks", [])), 1):
            task = _object(task)
            if _object(task.get("runOptions", {})).get("runOn") == "folderOpen":
                mode = task.get("type")
                mechanism = mode if mode in ("process", "shell") else "unresolved"
                bracket = f"tasks entry {i}"
                command = task.get("command")
                if mechanism == "process" and isinstance(command, str) and "args" in task:
                    command = [command, *_array(task["args"])]
                workspace_default = "cwd" not in _object(task.get("options", {}))
                yield bracket, "vscode_folder_open", mechanism, command, Path(".") if workspace_default else None
                if task.get("dependsOn"):
                    yield bracket + " dependsOn", "vscode_folder_open", "dependency", None, None
    elif kind == "npm":
        scripts = _object(doc.get("scripts", {}))
        for event in NPM_INSTALL_EVENTS:
            if event in scripts:
                command = scripts[event]
                if not isinstance(command, str):
                    raise ValueError("npm lifecycle script is not a string")
                yield f"scripts.{event}", "npm_install", "shell", command, relative.parent
    elif kind == "pytest":
        # pytest imports conftest.py at collection time; the file itself is
        # the referenced script.
        yield "file", "pytest_conftest", "import_time", [relative.name], relative.parent
    else:
        for event in CONTAINER_EVENTS:
            if event in doc:
                # Commands after initialization run in a container with its
                # own paths. Parallel command objects stay opaque at this layer.
                yield event, "devcontainer_lifecycle", (
                    "host" if event == "initializeCommand" else "container"
                ), doc[event], None


def _inspect_reference(read, reference: Reference, report: PreflightReport) -> Reference:
    """Follow one execution step: hash and pattern-check a resolved script.

    `read` maps a repo-relative PurePosixPath to bytes (or None past the size
    limit) and is the only place file content is loaded; it is read as data,
    never executed. Contents never leave this function: the report carries
    the sha256 and observation names alone.
    """
    if reference.status != "present_uninspected" or reference.path is None:
        return reference
    relative = PurePosixPath(reference.path)
    try:
        raw = read(relative)
    except OSError:
        report.note(relative, "script_unreadable")
        return reference
    if raw is None:
        report.note(relative, "script_size_limit")
        return reference
    digest, observations = script_inspect.inspect_bytes(raw, relative.suffix.lower())
    return Reference("present_inspected", reference.path, reference.size_bytes, digest, observations)


def _inspect_local(root: Path, reference: Reference, report: PreflightReport) -> Reference:
    """Local-filesystem reader for _inspect_reference: O_NOFOLLOW, bounded."""
    def read(relative: PurePosixPath) -> bytes | None:
        return _read_manifest(root / Path(*relative.parts), MAX_FILE_BYTES)

    return _inspect_reference(read, reference, report)


def _read_manifest(path: Path, limit: int) -> bytes | None:
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode):
        raise OSError("manifest is not a regular file")
    if info.st_size > limit:
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("manifest is not a regular file")
        data = stream.read(limit + 1)
    return data if len(data) <= limit else None


def inspect_repository(target: Path) -> PreflightReport:
    report = PreflightReport(str(target))
    try:
        root_info = target.lstat()
    except OSError:
        report.note(Path("."), "repository_unreadable")
        return report
    if _linked(root_info) or not stat.S_ISDIR(root_info.st_mode):
        report.note(Path("."), "expected_a_regular_directory")
        return report

    remaining = MAX_TOTAL_BYTES
    for relative, kind in _manifests(target, report):
        path = target / relative
        limit = min(MAX_FILE_BYTES, remaining)
        try:
            raw = _read_manifest(path, limit)
            if raw is None:
                report.note(relative, "manifest_size_limit" if limit == MAX_FILE_BYTES else "total_byte_limit")
                if limit != MAX_FILE_BYTES:
                    return report
                continue
            remaining -= len(raw)
            if kind == "pytest":
                if len(report.surfaces) == MAX_SURFACES:
                    report.note(relative, "surface_limit_reached")
                    return report
                reference = _inspect_local(
                    target, _reference(target, relative.parent, [relative.name], ()), report)
                report.surfaces.append(
                    Surface(relative.as_posix(), "file", "pytest_conftest", "import_time", reference))
                report.manifests_read += 1
                continue
            text = raw.decode("utf-8-sig")
            if kind in ("tasks", "vscode_mcp", "devcontainer"):
                text = _jsonc(text)
            document = _object(json.loads(text, object_pairs_hook=_unique_object))
            markers = ("${CLAUDE_PROJECT_DIR}",) if kind == "claude" else ()
            if kind in ("tasks", "vscode_mcp") or relative.as_posix().lower() == ".cursor/mcp.json":
                markers = ("${workspaceFolder}",)
            for location, trigger, mechanism, command, cwd in _entries(relative, kind, document):
                if len(report.surfaces) == MAX_SURFACES:
                    report.note(relative, "surface_limit_reached")
                    return report
                reference = (Reference("remote_uninspected") if mechanism == "remote"
                             else _inspect_local(target, _reference(target, cwd, command, markers), report))
                report.surfaces.append(Surface(relative.as_posix(), location, trigger, mechanism, reference))
            report.manifests_read += 1
        except OSError:
            report.note(relative, "manifest_unreadable")
        except (ValueError, RecursionError):
            report.note(relative, "invalid_or_unsupported_manifest")
    return report
