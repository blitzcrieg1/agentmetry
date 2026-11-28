"""Read-only GitHub preflight: inspect a repository at an exact commit.

`agentmetry scan --github OWNER/REPO@SHA` walks the Git tree through the
GitHub API and runs the same manifest inventory and one-step script
inspection as the local preflight. Nothing is cloned, nothing is executed,
and file contents are fetched as blobs and reduced to a SHA-256 plus
observation names before they leave the fetch layer. Set GITHUB_TOKEN (or
GH_TOKEN) for the higher rate limit; unauthenticated lookups work for
public repositories.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agentmetry.core.scanner import preflight
from agentmetry.core.scanner.preflight import (
    MAX_ENTRIES,
    MAX_FILE_BYTES,
    MAX_MANIFESTS,
    MAX_SURFACES,
    MAX_TOTAL_BYTES,
    PreflightReport,
    Reference,
    SKIP_DIRS,
    Surface,
    _entries,
    _jsonc,
    _manifest_type,
    _object,
    _script_path,
    _unique_object,
)

API_BASE = "https://api.github.com"
TARGET = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_./-]+)?$")
SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
TIMEOUT_SECONDS = 20


class FetchError(Exception):
    """A GitHub API call failed; the report is not produced."""


class GitHubAPI:
    """Minimal stdlib client for the endpoints preflight needs."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def get_json(self, path: str) -> Any:
        url = API_BASE + path
        if not url.startswith("https://"):  # path is built from regex-validated segments only
            raise FetchError(f"unexpected URL: {url!r}")
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "agentmetry"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https-only URL above
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - https-only URL above
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise FetchError(f"{path}: {exc}") from exc

    def get_blob(self, repo: str, sha: str) -> bytes:
        document = self.get_json(f"/repos/{repo}/git/blobs/{sha}")
        try:
            return base64.b64decode(document.get("content", ""))
        except ValueError as exc:
            raise FetchError(f"blob {sha}: decode failed") from exc


@dataclass(frozen=True)
class TreeEntry:
    type: str
    sha: str
    size: int


def parse_target(target: str) -> tuple[str, str | None]:
    if not TARGET.fullmatch(target):
        raise ValueError("expected OWNER/REPO or OWNER/REPO@REF")
    repo, _, ref = target.partition("@")
    return repo, ref or None


def _remote_reference(
    entries: dict[str, TreeEntry], cwd: Path | None, command: object, root_markers: tuple[str, ...],
) -> Reference:
    """Resolve a declared script path against the fetched tree, not the disk."""
    status, relative = _script_path(command, cwd, root_markers)
    if relative is None:
        return Reference(status)
    entry = entries.get(relative.as_posix())
    if entry is None:
        return Reference("not_found")
    if entry.type != "blob":
        return Reference("not_regular")
    if entry.size > MAX_FILE_BYTES:
        return Reference("oversized", relative.as_posix(), entry.size)
    return Reference("present_uninspected", relative.as_posix(), entry.size)


def inspect_github(target: str, api: GitHubAPI | None = None) -> PreflightReport:
    """Inventory execution declarations of OWNER/REPO at a pinned commit."""
    repo, ref = parse_target(target)
    api = api or GitHubAPI(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None)
    if ref is None or not SHA.fullmatch(ref):
        commit = api.get_json(f"/repos/{repo}/commits/{ref or 'HEAD'}")
        sha = str(commit["sha"]).lower()
    else:
        sha = ref.lower()
    report = PreflightReport(f"github:{repo}@{sha}")

    tree_doc = api.get_json(f"/repos/{repo}/git/trees/{sha}?recursive=1")
    if tree_doc.get("truncated"):
        report.note(PurePosixPath("."), "tree_truncated")
    entries: dict[str, TreeEntry] = {}
    for item in tree_doc.get("tree", []):
        path = item.get("path", "")
        if not path:
            continue
        parts = path.split("/")
        if any(part in SKIP_DIRS for part in parts[:-1]) or len(parts) > preflight.MAX_DEPTH:
            continue
        if len(entries) >= MAX_ENTRIES:
            report.note(PurePosixPath("."), "repository_entry_limit_reached")
            break
        entries[path] = TreeEntry(item.get("type", ""), item.get("sha", ""), item.get("size", 0))

    def read_blob(relative: PurePosixPath) -> bytes | None:
        entry = entries.get(relative.as_posix())
        if entry is None or entry.type != "blob":
            raise OSError("not a blob")
        if entry.size > MAX_FILE_BYTES:
            return None
        return api.get_blob(repo, entry.sha)

    remaining = MAX_TOTAL_BYTES
    manifests = 0
    for path in sorted(entries):
        relative = PurePosixPath(path)
        kind = _manifest_type(Path(path))
        entry = entries[path]
        if kind is None or entry.type != "blob":
            continue
        if manifests == MAX_MANIFESTS:
            report.note(relative, "manifest_limit_reached")
            break
        if entry.size > MAX_FILE_BYTES:
            report.note(relative, "manifest_size_limit")
            continue
        manifests += 1
        try:
            raw = api.get_blob(repo, entry.sha)
        except FetchError:
            report.note(relative, "manifest_unreadable")
            continue
        if len(raw) > MAX_FILE_BYTES or remaining - len(raw) < 0:
            report.note(relative, "manifest_size_limit" if len(raw) > MAX_FILE_BYTES else "total_byte_limit")
            if remaining - len(raw) < 0:
                break
            continue
        remaining -= len(raw)
        if kind == "pytest":
            if len(report.surfaces) == MAX_SURFACES:
                report.note(relative, "surface_limit_reached")
                break
            reference = preflight._inspect_reference(
                read_blob, _remote_reference(entries, relative.parent, [relative.name], ()), report)
            report.surfaces.append(
                Surface(path, "file", "pytest_conftest", "import_time", reference))
            report.manifests_read += 1
            continue
        text = raw.decode("utf-8-sig")
        if kind in ("tasks", "vscode_mcp", "devcontainer"):
            text = _jsonc(text)
        try:
            document = _object(json.loads(text, object_pairs_hook=_unique_object))
        except (ValueError, RecursionError):
            report.note(relative, "invalid_or_unsupported_manifest")
            continue
        markers = ("${CLAUDE_PROJECT_DIR}",) if kind == "claude" else ()
        if kind in ("tasks", "vscode_mcp") or path.lower() == ".cursor/mcp.json":
            markers = ("${workspaceFolder}",)
        for location, trigger, mechanism, command, cwd in _entries(Path(path), kind, document):
            if len(report.surfaces) == MAX_SURFACES:
                report.note(relative, "surface_limit_reached")
                break
            if mechanism == "remote":
                reference = Reference("remote_uninspected")
            else:
                reference = preflight._inspect_reference(
                    read_blob, _remote_reference(entries, cwd, command, markers), report)
            report.surfaces.append(Surface(path, location, trigger, mechanism, reference))
        report.manifests_read += 1
    return report
