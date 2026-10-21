"""Cursor cloud-agent tool calls, read from the Cursor desktop app's own cache.

A cloud agent runs on Cursor's VM, where no hook on this machine fires. When the
desktop app streams one of those agents, it caches the conversation in its
local state database (`User/globalStorage/state.vscdb`), and the cache holds
every tool call the agent made: the terminal commands, the files read and
edited, searches, web fetches and MCP calls, each with its arguments, status
and result. Paths in those arguments are under `/workspace`, the cloud VM's
checkout, so these are calls that ran there, not on this machine.

This module reads that cache read-only and turns each completed tool call into
the payload Cursor's own `postToolUse` hook would have produced, then runs it
through the hook client's mapper. The cloud events therefore get the same
argument hashing, command traits and ATT&CK labels as local Cursor events, and
the same rules fire on them. Nothing else leaves the cache: results are never
forwarded, only an exit code when the result carries one.

## What this sees, and what it does not

* **Only agents the desktop app has streamed.** The cache is filled when an
  agent is opened in the app (`createdFromBackgroundAgent.shouldStreamMessages`).
  An agent nobody opened here leaves nothing to read.
* **After the fact.** This is a record, never a gate. A call is read once it
  has completed, errored or been cancelled, and nothing here can block one.
* **An undocumented format.** The layout was read off a real database on
  2026-10-21: `composerData:<id>` rows carrying `createdFromBackgroundAgent.bcId`,
  and `bubbleId:<id>:<bubble>` rows carrying `toolFormerData`. A row that does
  not match it is skipped and counted, never guessed at.
* **A claim, not proof.** The cache is a file the user can edit or delete.
  Cursor's own run stream (`cloud_bridge.py`) is the independent view to check
  it against, keyed on the same `cursor-cloud-<bcId>` correlation id.

## Reading safely

The database is opened with `mode=ro`, so a running Cursor is never blocked or
written to. Only rows that name a cloud agent are selected, which keeps a
multi-gigabyte database cheap to poll. A call already recorded is remembered by
a digest of its agent and tool-call id in a small state file beside the trail,
so a second run imports nothing twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SOURCE_APP = "cursor_cloud"
ADAPTER = "cursor_cloud_cache"
STATE_FILE = "cursor-cloud-cache.seen.json"

#: Tool names the cloud agent uses, mapped to the names Cursor's local hooks
#: record, so a rule keyed on `cursor.Read` or `shell.run` fires on both.
_TOOL_NAMES = {
    "read_file_v2": "Read",
    "edit_file_v2": "Write",
    "delete_file": "Delete",
    "ripgrep_raw_search": "Grep",
    "glob_file_search": "Glob",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
    "task_v2": "Task",
}
_SHELL_TOOLS = frozenset({"run_terminal_command_v2", "run_terminal_cmd"})
_FINAL_STATUSES = frozenset({"completed", "error", "cancelled"})


def default_db_path() -> Path | None:
    """Where the Cursor desktop app keeps its state database on this OS."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
        root = Path(base) / "Cursor" if base else None
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Cursor"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", "") or Path.home() / ".config") / "Cursor"
    if root is None:
        return None
    return root / "User" / "globalStorage" / "state.vscdb"


@dataclass(frozen=True)
class CloudToolCall:
    bc_id: str
    tool_call_id: str
    name: str
    status: str
    created_at: str
    args: dict[str, Any]
    exit_code: int | None = None


@dataclass
class ImportResult:
    agents: int = 0
    calls: int = 0
    new: int = 0
    posted: int = 0
    already_seen: int = 0
    failed: int = 0
    skipped: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)


def open_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=5)


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str) and value.strip()[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None


def iter_cloud_composers(con: sqlite3.Connection) -> Iterator[tuple[str, str]]:
    """(composer id, cloud agent id) for every conversation streamed from a cloud agent."""
    rows = con.execute(
        "SELECT key, value FROM cursorDiskKV"
        " WHERE key LIKE 'composerData:%' AND value LIKE '%createdFromBackgroundAgent%'"
    )
    for key, value in rows:
        data = _json(value)
        origin = data.get("createdFromBackgroundAgent") if isinstance(data, dict) else None
        bc_id = origin.get("bcId") if isinstance(origin, dict) else None
        if isinstance(bc_id, str) and bc_id:
            yield str(key).split(":", 1)[1], bc_id


def _exit_code(result: Any) -> int | None:
    data = _json(result)
    code = data.get("exitCode") if isinstance(data, dict) else None
    return code if isinstance(code, int) and not isinstance(code, bool) else None


def iter_tool_calls(
    con: sqlite3.Connection, composer_id: str, bc_id: str, skipped: Counter | None = None
) -> Iterator[CloudToolCall]:
    """Every finished tool call in one cloud agent's cached conversation."""
    skipped = skipped if skipped is not None else Counter()
    rows = con.execute(
        "SELECT value FROM cursorDiskKV WHERE key LIKE ?", (f"bubbleId:{composer_id}:%",)
    )
    for (value,) in rows:
        bubble = _json(value)
        tool = bubble.get("toolFormerData") if isinstance(bubble, dict) else None
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        call_id = tool.get("toolCallId")
        status = str(tool.get("status") or "")
        if not isinstance(name, str) or not name or not isinstance(call_id, str) or not call_id:
            skipped["unrecognised_row"] += 1
            continue
        if status not in _FINAL_STATUSES:
            skipped["not_finished"] += 1
            continue
        args = _json(tool.get("params"))
        if not isinstance(args, dict):
            args = _json(tool.get("rawArgs"))
        yield CloudToolCall(
            bc_id=bc_id,
            tool_call_id=call_id,
            name=name,
            status=status,
            created_at=str(bubble.get("createdAt") or ""),
            args=args if isinstance(args, dict) else {},
            exit_code=_exit_code(tool.get("result")) if name in _SHELL_TOOLS else None,
        )


def _mcp_tool(name: str) -> str:
    """`mcp-<server>-<tool>` to `MCP:<tool>`, the name the local hooks record.

    Server names contain dashes too, so only the last segment is taken as the
    tool. A tool whose own name has a dash keeps only its tail.
    """
    tail = name.rsplit("-", 1)[-1]
    return f"MCP:{tail or 'unknown'}"


def hook_event(call: CloudToolCall) -> tuple[str, dict[str, Any]]:
    """The (hook name, payload) Cursor's local hooks would have sent for this call."""
    data: dict[str, Any] = {"conversation_id": call.bc_id}
    if call.status == "error":
        data["error"] = "tool_error"
    elif call.status == "cancelled":
        data["error"] = "cancelled"
    if call.exit_code is not None:
        data["exit_code"] = call.exit_code

    if call.name in _SHELL_TOOLS:
        command = call.args.get("command")
        data["command"] = command if isinstance(command, str) else ""
        return "afterShellExecution", data

    if call.name.startswith("mcp-"):
        tool_name = _mcp_tool(call.name)
        tool_input = dict(call.args)
    else:
        tool_name = _TOOL_NAMES.get(call.name, call.name.removesuffix("_v2"))
        tool_input = dict(call.args)
        path = call.args.get("path") or call.args.get("targetFile") or call.args.get("relativeWorkspacePath")
        if tool_name in ("Read", "Write", "Delete") and isinstance(path, str):
            # Only the path, as the local hooks send it. Edit bodies stay behind.
            tool_input = {"path": path}
    data["tool_name"] = tool_name
    data["tool_input"] = tool_input
    return "postToolUse", data


def to_payload(call: CloudToolCall) -> dict[str, Any] | None:
    """One cached cloud tool call as an external-ingest payload, hashed in-process."""
    from agentmetry.hooks.ingest import _hash_tool_args, map_cursor_hook

    hook_name, data = hook_event(call)
    payload = _hash_tool_args(map_cursor_hook(hook_name, data))
    if not payload:
        return None
    payload["source_app"] = SOURCE_APP
    payload["adapter"] = ADAPTER
    payload["correlation_id"] = f"cursor-cloud-{call.bc_id}"
    payload["session_id"] = call.bc_id
    if call.created_at:
        payload["timestamp_utc"] = call.created_at
    if call.status == "cancelled":
        payload["reason"] = "cancelled"
    payload.setdefault("initiator", {})["actor_type"] = "agent"
    return payload


def _seen_key(call: CloudToolCall) -> str:
    return hashlib.sha256(f"{call.bc_id}\n{call.tool_call_id}".encode()).hexdigest()[:32]


def _load_seen(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set(data.get("seen", [])) if isinstance(data, dict) else set()


def _save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"v": 1, "seen": sorted(seen)}), encoding="utf-8")
    os.replace(tmp, path)


def import_cache(
    db_path: Path,
    *,
    post: Callable[[dict[str, Any]], bool],
    state_path: Path,
    dry_run: bool = False,
) -> ImportResult:
    """Read every cached cloud tool call not yet recorded, and post it.

    A call is remembered only after `post` accepted it, so a run that fails
    half way resumes where it stopped instead of skipping the rest.
    """
    result = ImportResult()
    seen = _load_seen(state_path)
    con = open_readonly(db_path)
    try:
        for composer_id, bc_id in iter_cloud_composers(con):
            result.agents += 1
            for call in iter_tool_calls(con, composer_id, bc_id, result.skipped):
                result.calls += 1
                result.tools[call.name] += 1
                key = _seen_key(call)
                if key in seen:
                    result.already_seen += 1
                    continue
                payload = to_payload(call)
                if payload is None:
                    result.skipped["unmapped"] += 1
                    continue
                result.new += 1
                if dry_run:
                    continue
                if post(payload):
                    seen.add(key)
                    result.posted += 1
                else:
                    result.failed += 1
    finally:
        con.close()
        if not dry_run:
            _save_seen(state_path, seen)
    return result
