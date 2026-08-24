#!/usr/bin/env python3
"""Stdio MCP proxy — logs tools/call and fingerprints tools/list, forwards to child.

Usage:
  python mcp_audit_proxy.py --server vault_fs -- \\
    python tools/vault_fs_server.py /path/to/vault

Configure Cursor/Claude MCP to run this wrapper instead of the raw server command.
Set AGENTMETRY_SOURCE_APP=mcp_proxy (default).

Correlation: all calls in one proxy process share a per-process session id
(override with AGENTMETRY_CORRELATION_ID) — NOT the JSON-RPC request id, which
collides across sessions. The JSON-RPC id is used only to match a response to
its request so a server error becomes a tool_failed event, so a paginated
tools/list can be assembled before it is hashed, and so an initialize response
can be paired with the next completed tools/list.

Redaction: tool arguments are hashed in-process (input_hash); plaintext args
never cross the wire to the orchestrator. Tool descriptions are hashed the
same way: the schema fingerprint is a digest, not the text the model saw.
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
if str(_ORCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCH_ROOT))
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from agentmetry_ingest import hash_arguments, post_ingest  # noqa: E402
from agentmetry.core.diagnostics.mcp_schema import (  # noqa: E402
    ToolsListBuffer,
    fingerprint_each_tool,
    fingerprint_tools,
    parse_initialize_result,
)

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


def build_schema_payload(
    server_name: str,
    tools: list[Any],
    correlation_id: str,
    *,
    server_version: str = "",
    list_changed: bool | None = None,
) -> dict[str, Any]:
    """Hash-only ingest of a completed `tools/list`. Descriptions stay here."""
    payload: dict[str, Any] = {
        "source_app": _source_app(),
        "adapter": "mcp_audit_proxy",
        "event_type": "mcp_schema",
        "correlation_id": correlation_id,
        "schema_fingerprint": fingerprint_tools(tools),
        "schema_tool_count": len(tools),
        # Per-tool digests so a move can name the tool rather than only the
        # server. Hashes of hashed names: still no description on the wire.
        "schema_tool_digests": fingerprint_each_tool(tools),
        "tool": {"server": server_name},
    }
    if server_version:
        payload["server_version"] = server_version
    if list_changed is not None:
        payload["list_changed"] = list_changed
    return payload


def build_schema_unavailable_payload(
    server_name: str, correlation_id: str, reason: str
) -> dict[str, Any]:
    """A `tools/list` that did not complete. Not a schema, and not an absence of one.

    One registry answers 410 to roughly half the requests for the same URL, at
    random. Treating that as "the tools are gone" is a false rug pull arriving
    by a different road from the one the fingerprint guards, and the recorder
    would be the thing manufacturing it.

    Hook coverage already distinguishes covered from absent from unknown, and
    the listing side needs the same honesty: a transport failure is a gap in
    what we saw, not a change in what the server serves. So this event says a
    listing was attempted and did not land, and the stored baseline is left
    exactly where it was.
    """
    return {
        "source_app": _source_app(),
        "adapter": "mcp_audit_proxy",
        "event_type": "mcp_schema_unavailable",
        "correlation_id": correlation_id,
        "reason": reason,
        "tool": {"server": server_name},
    }


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
        rid = msg.get("id")
        method = msg.get("method")
        if method == "initialize" and rid is not None:
            pending[str(rid)] = {"kind": "init", "server": server_name}
            continue
        if method == "tools/list" and rid is not None:
            pending[str(rid)] = {"kind": "list", "server": server_name}
            continue
        payload = build_call_payload(msg, server_name, correlation)
        if payload is None:
            continue
        # Remember this request id so an error response can be matched to it.
        if rid is not None:
            pending[str(rid)] = {
                "kind": "call",
                "qualified": payload["tool"]["qualified"],
                "server": server_name,
            }
        post_ingest(payload, quiet=True)


async def _relay_stdout(
    reader: asyncio.StreamReader,
    pending: dict[str, dict[str, str]],
    server_name: str,
    list_buf: ToolsListBuffer,
    handshake: dict[str, Any],
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
        if ctx.get("kind") == "init":
            if not msg.get("error"):
                handshake.clear()
                handshake.update(parse_initialize_result(msg.get("result")))
            continue
        if ctx.get("kind") == "list":
            if msg.get("error"):
                # Drop the pages already accumulated. Keeping them would let a
                # retried listing append onto a stale prefix and hash to a
                # fingerprint no server ever served, reported as a rug pull.
                list_buf.reset()
                err = msg.get("error")
                reason = str(err.get("message") if isinstance(err, dict) else err)
                # Dropping the pages stops the false positive. It does not
                # record that we tried and failed, and silence is not the same
                # as unknown: an operator reading a quiet week cannot tell a
                # server that never moved from one we never managed to list.
                post_ingest(
                    build_schema_unavailable_payload(
                        server_name, correlation, reason or "tools/list failed"
                    ),
                    quiet=True,
                )
                continue
            done = list_buf.add_page(msg.get("result"))
            if done is not None:
                post_ingest(
                    build_schema_payload(
                        server_name,
                        done,
                        correlation,
                        server_version=str(handshake.get("server_version") or ""),
                        list_changed=handshake.get("list_changed"),
                    ),
                    quiet=True,
                )
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
    # noqa S101: narrowing for the type checker, not a runtime check.
    # create_subprocess_exec with PIPE on all three always sets them, and
    # python -O would strip this without changing behaviour.
    assert proc.stdin and proc.stdout and proc.stderr  # noqa: S101

    pending: dict[str, dict[str, str]] = {}
    list_buf = ToolsListBuffer()
    handshake: dict[str, Any] = {}
    stdin_task = asyncio.create_task(_relay_stdin(proc.stdin, server_name, pending))
    stdout_task = asyncio.create_task(
        _relay_stdout(proc.stdout, pending, server_name, list_buf, handshake)
    )

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
