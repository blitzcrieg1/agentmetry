#!/usr/bin/env python3
"""Stdio MCP proxy — logs tools/call to Agentmetry ingest, forwards to child MCP server.

Usage:
  python mcp_audit_proxy.py --server vault_fs -- \\
    python tools/vault_fs_server.py /path/to/vault

Configure Cursor/Claude MCP to run this wrapper instead of the raw server command.
Set AGENTMETRY_SOURCE_APP=mcp_proxy (default).

Correlation: all calls in one proxy process share a per-process session id
(override with AGENTMETRY_CORRELATION_ID) — NOT the JSON-RPC request id, which
collides across sessions. The JSON-RPC id is used only to match a response to
its request so a server error becomes a tool_failed event.

Redaction: tool arguments are hashed in-process (input_hash); plaintext args
never cross the wire to the orchestrator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Repo scripts on path for ingest client
_ORCH_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ORCH_ROOT.parents[1]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from agentmetry_ingest import hash_arguments, post_ingest  # noqa: E402

# Per-process session id — ties every tool call in this MCP connection together.
_SESSION_ID = uuid.uuid4().hex


def _correlation_id() -> str:
    return os.environ.get("AGENTMETRY_CORRELATION_ID", "").strip() or _SESSION_ID


def _source_app() -> str:
    return os.environ.get("AGENTMETRY_SOURCE_APP", "mcp_proxy")


def _qualified(server_name: str, tool_name: str) -> str:
    if tool_name and "." not in tool_name:
        return f"{server_name}.{tool_name}"
    return tool_name


def build_call_payload(
    msg: dict[str, Any], server_name: str, correlation_id: str
) -> dict[str, Any] | None:
    """Build an ingest payload for a tools/call request, or None if not a call."""
    if msg.get("method") != "tools/call":
        return None
    params = msg.get("params") or {}
    tool_name = str(params.get("name") or "")
    arguments = params.get("arguments")
    clean = arguments if isinstance(arguments, dict) else {"raw": arguments}
    return {
        "source_app": _source_app(),
        "adapter": "mcp_audit_proxy",
        "event_type": "tool_called",
        "correlation_id": correlation_id,
        "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
        "tool": {
            "qualified": _qualified(server_name, tool_name),
            "server": server_name,
            "input_hash": hash_arguments(clean),
        },
    }


def build_error_payload(
    msg: dict[str, Any], ctx: dict[str, str], correlation_id: str
) -> dict[str, Any] | None:
    """Build a tool_failed payload from an error response, or None if not an error."""
    err = msg.get("error")
    if not err:
        return None
    reason = str(err.get("message") if isinstance(err, dict) else err) or "mcp_error"
    return {
        "source_app": _source_app(),
        "adapter": "mcp_audit_proxy",
        "event_type": "tool_failed",
        "outcome": "error",
        "reason": reason,
        "correlation_id": correlation_id,
        "tool": {"qualified": ctx.get("qualified", ""), "server": ctx.get("server", "")},
    }


async def _relay_stdin(
    writer: asyncio.StreamWriter, server_name: str, pending: dict[str, dict[str, str]]
) -> None:
    correlation = _correlation_id()
    while True:
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        if not line:
            writer.write_eof()
            await writer.drain()
            break
        writer.write(line.encode("utf-8"))
        await writer.drain()

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = build_call_payload(msg, server_name, correlation)
        if payload is None:
            continue
        # Remember this request id so an error response can be matched to it.
        rid = msg.get("id")
        if rid is not None:
            pending[str(rid)] = {
                "qualified": payload["tool"]["qualified"],
                "server": server_name,
            }
        post_ingest(payload, quiet=True)


async def _relay_stdout(
    reader: asyncio.StreamReader, pending: dict[str, dict[str, str]]
) -> None:
    correlation = _correlation_id()
    while True:
        line = await reader.readline()
        if not line:
            break
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = msg.get("id")
        if rid is None or "method" in msg:  # only responses carry a matched id
            continue
        ctx = pending.pop(str(rid), None)
        if ctx is None:
            continue
        err_payload = build_error_payload(msg, ctx, correlation)
        if err_payload is not None:
            post_ingest(err_payload, quiet=True)


async def run_proxy(command: list[str], server_name: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin and proc.stdout and proc.stderr

    pending: dict[str, dict[str, str]] = {}
    stdin_task = asyncio.create_task(_relay_stdin(proc.stdin, server_name, pending))
    stdout_task = asyncio.create_task(_relay_stdout(proc.stdout, pending))

    async def _stderr() -> None:
        while True:
            chunk = await proc.stderr.readline()
            if not chunk:
                break
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()

    stderr_task = asyncio.create_task(_stderr())
    code = await proc.wait()
    await asyncio.gather(stdin_task, stdout_task, stderr_task, return_exceptions=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP stdio proxy with Agentmetry logging")
    parser.add_argument("--server", required=True, help="MCP server name for qualified tool ids")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Child command after --")
    args = parser.parse_args()
    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Usage: mcp_audit_proxy.py --server NAME -- command ...", file=sys.stderr)
        return 2
    return asyncio.run(run_proxy(cmd, args.server))


if __name__ == "__main__":
    raise SystemExit(main())
