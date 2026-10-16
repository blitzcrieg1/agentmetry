"""Cloud Bridge: vendor cloud-agent surfaces, recorded into the local trail.

Cloud agents execute on vendor infrastructure, where no local hook can fire.
What the vendors expose instead is an API over the agent's lifecycle, and —
for Cursor — a live stream of its tool calls. This module turns those
surfaces into the same external-ingest payloads the local hook client sends,
so cloud sessions land in the same hash-chained trail, the same detections
and the same SIEM sinks as everything else.

Privacy posture, identical to the hook path: tool arguments are reduced to a
SHA-256 over redacted, canonically serialised JSON; result and response
bodies are hashed, never stored; no prompt or response text is forwarded.
Vendors encode parts of their payloads (Claude delivers `tool_use.input` as a
JSON-encoded *string*); those are decoded here, then hashed — decoding is for
classification, never for storage.

Boundary, stated once: this records what the vendor's API exposes. Cursor's
stream covers tool calls live during a run and expires afterwards; Claude's
Compliance API serves transcripts to an admin-scoped key. What happens inside
a vendor VM beyond those surfaces is the vendor's custody, and this module
does not pretend otherwise.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

REDACT_KEYS = frozenset(
    {"authorization", "api_key", "apikey", "password", "secret", "token", "session_key"}
)
_COMMAND_KEYS = ("command", "cmd", "script", "CommandLine")
_PATH_KEYS = ("path", "filepath", "file_path", "AbsolutePath", "TargetFile")


def redact_arguments(args: Any) -> Any:
    if isinstance(args, dict):
        return {
            k: ("<redacted>" if str(k).lower() in REDACT_KEYS else v)
            for k, v in args.items()
        }
    return {"value": args} if args is not None else {}


def canonical_arguments(args: Any) -> str:
    return json.dumps(redact_arguments(args), sort_keys=True, separators=(",", ":"), default=str)


def hash_arguments(args: Any) -> str:
    """SHA-256 over redacted, canonically serialised arguments.

    Keep in sync with agentmetry.hooks.ingest.hash_arguments — a sync test
    asserts both produce the same digest for the same input, so a cloud event
    and a local event carrying the same call hash identically.
    """
    return hashlib.sha256(canonical_arguments(args).encode("utf-8")).hexdigest()


def decode_maybe_encoded(value: Any) -> Any:
    """Decode the encodings vendors put around structured fields.

    Claude's Compliance API delivers `tool_use.input` as a JSON-encoded
    string; some streams wrap payloads in base64. Decode for classification,
    never store the decoded content: everything that reaches a canonical
    event from here is a hash, a length or a name.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[:1] in "{[":
        try:
            return json.loads(text)
        except ValueError:
            return value
    try:
        import base64

        decoded = base64.b64decode(text, validate=True)
        candidate = decoded.decode("utf-8")
        if candidate[:1] in "{[":
            return json.loads(candidate)
    except (ValueError, UnicodeDecodeError):
        # Not base64, or not UTF-8, or not JSON inside: return the original
        # string and let the caller hash it as an opaque value.
        return value
    return value


def tool_summary(args: Any) -> dict[str, Any]:
    """The only argument content that survives: a hashed digest, a length,
    and — for shell-shaped tools — whether the command reached a remote host.
    Command text, paths and values do not pass through this function's output.
    """
    summary: dict[str, Any] = {
        "input_hash": hash_arguments(args),
        "input_size": len(canonical_arguments(args)),
    }
    if isinstance(args, dict):
        for key in _COMMAND_KEYS:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                summary["has_command"] = True
                break
        else:
            for key in _PATH_KEYS:
                if isinstance(args.get(key), str) and args[key].strip():
                    summary["has_path"] = True
                    break
    return summary


def map_outbound_poll(source_app: str, method: str, url: str) -> dict[str, Any]:
    """The request this machine sends. The key is not in the payload.

    Query strings are dropped: a token does not belong in the trail. The path
    and host are the trace of the send.
    """
    parts = urlsplit(url)
    target = f"{method} {parts.netloc}{parts.path}"
    return {
        "source_app": source_app,
        "adapter": "cloud_bridge",
        "event_type": "tool_called",
        "outcome": "success",
        "correlation_id": f"{source_app}-outbound",
        "reason": "outbound poll; key sent and not stored",
        "tool": {
            "qualified": f"{source_app}.poll",
            "server": source_app,
            "command": target,
        },
    }


# --- Cursor Cloud Agents API -------------------------------------------------

CURSOR_DEFAULT_BASE = "https://api.cursor.com"


def map_cursor_agent(agent: dict[str, Any], runs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One cloud agent + its runs -> external-ingest payloads.

    Cursor exposes lifecycle and outcome: agent status, run status, duration,
    pushed branches and the PR URL. Tool-call detail is not in these
    endpoints; when the connector attaches to a live stream (v1.1) those
    arrive as separate tool_called events.
    """
    agent_id = str(agent.get("id") or "unknown")
    status = str(agent.get("status") or "unknown")
    out: list[dict[str, Any]] = [
        {
            "source_app": "cursor_cloud",
            "adapter": "cloud_bridge",
            "event_type": "session_start" if status == "ACTIVE" else "session_end",
            "outcome": "success",
            "correlation_id": f"cursor-cloud-{agent_id}",
            "session_id": agent_id,
            "reason": f"cloud_agent:{status}",
        }
    ]
    for run in runs or []:
        git = run.get("git") or {}
        branches = git.get("branches") or []
        pr_url = str(next((b.get("prUrl") for b in branches if b.get("prUrl")), "") or "")
        out.append(
            {
                "source_app": "cursor_cloud",
                "adapter": "cloud_bridge",
                "event_type": "session_end",
                "outcome": "success" if str(run.get("status")) == "FINISHED" else str(run.get("status") or "unknown").lower(),
                "correlation_id": f"cursor-cloud-{agent_id}",
                "session_id": str(run.get("id") or ""),
                "reason": (
                    f"cloud_run:{run.get('status')};duration_ms:{run.get('durationMs', 0)};"
                    f"branches:{len(branches)};pr:{'yes' if pr_url else 'no'}"
                ),
            }
        )
    return out


def map_cursor_stream_tool_call(call: dict[str, Any], agent_id: str, run_id: str) -> dict[str, Any] | None:
    """One tool_call event from a live run stream -> a tool_called payload.

    `args` arrives as an object or an encoded string; either way it becomes a
    hash here. `result` is never forwarded — only its presence and size.
    """
    args = decode_maybe_encoded(call.get("args"))
    summary = tool_summary(args)
    name = str(call.get("name") or "unknown")
    status = str(call.get("status") or "unknown")
    result = call.get("result")
    return {
        "source_app": "cursor_cloud",
        "adapter": "cloud_bridge",
        "event_type": "tool_called",
        "outcome": "success" if status == "completed" else status,
        "correlation_id": f"cursor-cloud-{agent_id}",
        "session_id": run_id,
        "tool": {
            "qualified": f"cursor_cloud.{name}",
            "server": "cursor_cloud",
            "input_hash": summary["input_hash"],
            "input_size": summary["input_size"],
            "has_result": result is not None,
        },
    }


# --- Claude Compliance API ---------------------------------------------------

CLAUDE_DEFAULT_BASE = "https://api.anthropic.com"


def map_claude_tool_use(block: dict[str, Any], session_id: str) -> dict[str, Any]:
    """One tool_use transcript block -> a tool_called payload.

    Claude encodes `input` as a JSON-encoded string; decode_maybe_encoded
    turns it back into structure so the same redact-and-hash pipeline applies
    as for local events. Only the hash, size and tool name are forwarded.
    """
    decoded = decode_maybe_encoded(block.get("input"))
    summary = tool_summary(decoded)
    name = str(block.get("name") or "unknown")
    truncated = bool(block.get("truncated"))
    return {
        "source_app": "claude_cloud",
        "adapter": "cloud_bridge",
        "event_type": "tool_called",
        "outcome": "success",
        "correlation_id": session_id,
        "session_id": session_id,
        "tool": {
            "qualified": f"claude_cloud.{name}",
            "server": "claude_cloud",
            "input_hash": summary["input_hash"],
            "input_size": summary["input_size"],
            "truncated": truncated,
        },
    }


def map_claude_messages(session: dict[str, Any], messages: dict[str, Any]) -> list[dict[str, Any]]:
    """A Compliance API transcript -> tool_called payloads, one per tool_use.

    Text, thinking and system content are dropped here, not stored: the
    transcript's words belong to the vendor's retention policy, while the
    sequence of tool calls belongs in the customer's trail.
    """
    session_id = str(session.get("id") or "unknown")
    out: list[dict[str, Any]] = []
    for message in messages.get("data", []) or []:
        for block in message.get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            out.append(map_claude_tool_use(block, session_id))
    return out


def map_claude_session(session: dict[str, Any]) -> dict[str, Any]:
    """A listed session -> a session_start payload (metadata only)."""
    return {
        "source_app": "claude_cloud",
        "adapter": "cloud_bridge",
        "event_type": "session_start",
        "outcome": "success",
        "correlation_id": str(session.get("id") or "unknown"),
        "session_id": str(session.get("id") or ""),
        "reason": f"cloud_session:{session.get('created_at', '')[:10]}",
    }


# --- Grok Build (reserved) ----------------------------------------------------

def map_grok_build_session_unsupported() -> None:
    """Reserved for the Grok Build on-disk log parser.

    Grok Build is a local CLI: its tool executions happen on this machine,
    so the capture surface is its session logs, not a vendor cloud API. The
    parser lands when a real session-log sample exists to write it against —
    an invented format would be a parser that parses nothing.
    """
    raise NotImplementedError(
        "grok_build capture lands with the on-disk log parser; install Grok "
        "Build, run one session, and point the parser at its log directory."
    )


# --- Fetchers (poll-once semantics; the caller owns scheduling) ---------------


def fetch_cursor_agents(api_key: str, base: str = CURSOR_DEFAULT_BASE) -> list[dict[str, Any]]:
    import httpx

    resp = httpx.get(
        f"{base.rstrip('/')}/v1/agents",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_cursor_runs(agent_id: str, api_key: str, base: str = CURSOR_DEFAULT_BASE) -> list[dict[str, Any]]:
    import httpx

    resp = httpx.get(
        f"{base.rstrip('/')}/v1/agents/{agent_id}/runs",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("runs", []) or resp.json().get("items", [])


def fetch_claude_sessions(api_key: str, kind: str = "local", base: str = CLAUDE_DEFAULT_BASE, limit: int = 20) -> list[dict[str, Any]]:
    import httpx

    resp = httpx.get(
        f"{base.rstrip('/')}/v1/compliance/apps/sessions/{kind}",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        params={"limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_claude_messages(api_key: str, kind: str, session_id: str, base: str = CLAUDE_DEFAULT_BASE, limit: int = 500) -> dict[str, Any]:
    import httpx

    resp = httpx.get(
        f"{base.rstrip('/')}/v1/compliance/apps/sessions/{kind}/{session_id}/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        params={"limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
