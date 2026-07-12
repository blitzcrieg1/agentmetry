#!/usr/bin/env python3
"""AgentAudit Tier B ingest client — Cursor, Claude Code, Antigravity hooks.

POST adapter events to the local orchestrator ingest API.

Environment:
  AGENTAUDIT_URL            default http://127.0.0.1:8000
  BLACKBOX_API_KEY          optional X-API-Key header
  AGENTAUDIT_SOURCE_APP     cursor | claude | antigravity | mcp_proxy
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACT_KEYS = frozenset({
    "token", "api_key", "apikey", "password", "secret", "authorization",
    "anthropic_api_key", "openai_api_key",
})

CURSOR_BEFORE = frozenset({
    "beforeShellExecution", "beforeMCPExecution", "preToolUse", "beforeReadFile",
})
CURSOR_AFTER = frozenset({
    "postToolUse", "afterMCPExecution", "afterShellExecution", "afterFileEdit",
})
CURSOR_BLOCKING = frozenset({
    "beforeShellExecution", "beforeMCPExecution", "preToolUse", "subagentStart",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_url() -> str:
    return (
        os.environ.get("AGENTAUDIT_URL")
        or os.environ.get("BLACKBOX_AUDIT_INGEST_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def _source_app() -> str:
    return os.environ.get("AGENTAUDIT_SOURCE_APP", "cursor").lower()


def _pick(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def read_hook_stdin() -> tuple[dict[str, Any], bool]:
    """Read hook JSON from stdin; use raw bytes on Windows (Cursor UTF-8 bug)."""
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return {}, False
    try:
        return json.loads(raw.decode("utf-8")), False
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            return json.loads(raw.decode("utf-8", errors="replace")), True
        except json.JSONDecodeError:
            return {"_raw_hex": raw.hex()[:2000]}, True


def redact_arguments(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return {
            k: "<redacted>" if str(k).lower() in REDACT_KEYS else v
            for k, v in args.items()
        }
    if args is None:
        return {}
    return {"value": args}


def hash_arguments(args: Any) -> str:
    clean = redact_arguments(args if isinstance(args, dict) else {"value": args})
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _hash_tool_args(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace tool.arguments with a client-side input_hash.

    Args are hashed *inside the hook process* so redacted-plaintext arguments
    never cross the wire to the orchestrator. The stored event keeps only the
    64-hex digest.
    """
    if not payload:
        return payload
    tool = payload.get("tool")
    if isinstance(tool, dict) and "arguments" in tool:
        args = tool.pop("arguments")
        if not tool.get("input_hash"):
            tool["input_hash"] = hash_arguments(args)
    return payload


def _after_outcome(data: dict[str, Any]) -> tuple[str, str, str]:
    """Derive (event_type, outcome, reason) for a post/after tool hook.

    Do not assume success — a tool that ran and failed must not be logged as
    successful. Reads whatever exit/error signal the platform provides.
    """
    exit_code = data.get("exit_code", data.get("exitCode"))
    err = _pick(data, "error", "stderr", "is_error", "isError", default=None)
    success_flag = data.get("success", data.get("ok"))
    failed = (
        (isinstance(exit_code, int) and exit_code != 0)
        or (success_flag is False)
        or (isinstance(err, str) and err.strip() != "")
        or (err is True)
    )
    if failed:
        reason = f"exit:{exit_code}" if isinstance(exit_code, int) else "tool_failed"
        return "tool_failed", "error", reason
    return "tool_called", "success", ""


def post_ingest(payload: dict[str, Any], *, quiet: bool = False) -> bool:
    url = f"{_base_url()}/api/v1/audit/ingest"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("BLACKBOX_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            resp.read()
        return True
    except Exception as exc:
        if not quiet:
            print(f"agentaudit ingest failed: {exc}", file=sys.stderr)
        return False


def _get_tail(source_app: str, *, limit: int = 50) -> dict[str, Any]:
    url = f"{_base_url()}/api/v1/audit/tail?sources={source_app}&limit={limit}&scope=all"
    headers = {}
    api_key = os.environ.get("BLACKBOX_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def selftest() -> int:
    """POST a synthetic event and confirm it lands in the audit tail.

    Turns silent hook failure into a visible GREEN/RED, so the operator can tell
    whether they are actually being audited before trusting the trail.
    """
    source = _source_app()
    nonce = f"selftest-{os.urandom(8).hex()}"
    posted = post_ingest({
        "source_app": source,
        "adapter": f"{source}_selftest",
        "event_type": "tool_called",
        "correlation_id": nonce,
        "tool": {"qualified": "agentaudit.selftest", "server": "agentaudit", "input_hash": "0" * 64},
    })
    if not posted:
        print(
            f"AgentAudit hooks: RED — could not POST to ingest at {_base_url()}. "
            "Is the orchestrator running? Check AGENTAUDIT_URL / BLACKBOX_API_KEY.",
            file=sys.stderr,
        )
        return 1
    try:
        body = _get_tail(source)
    except Exception as exc:
        print(
            f"AgentAudit hooks: YELLOW — event POSTed but tail read failed: {exc}",
            file=sys.stderr,
        )
        return 2
    found = any(e.get("correlation_id") == nonce for e in body.get("events", []))
    if found:
        print(f"AgentAudit hooks: GREEN — synthetic event round-tripped for source '{source}'.")
        return 0
    print(
        "AgentAudit hooks: RED — event POSTed but not found in the audit tail. "
        "Ingest disabled (BLACKBOX_AUDIT_INGEST_ENABLED) or sink misconfigured?",
        file=sys.stderr,
    )
    return 1


def _initiator_from_hook(hook_name: str, data: dict[str, Any]) -> str:
    human_hooks = {
        "beforeSubmitPrompt", "UserPromptSubmit", "sessionStart", "SessionStart",
    }
    if hook_name in human_hooks:
        return "human"
    if _pick(data, "permission", "permissionDecision", default="") == "ask":
        return "human"
    return "agent"


def _cursor_tool_context(hook_name: str, data: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    tool_name = str(_pick(data, "tool_name", "tool", "name", default="unknown"))
    mcp_server = str(_pick(data, "mcp_server", "server", default=""))
    args = _pick(data, "tool_input", "arguments", "input", default=None)
    if args is None and "command" in data:
        args = {"command": data["command"]}
    clean = redact_arguments(args)

    if hook_name in ("afterShellExecution", "beforeShellExecution"):
        return "shell.run", "shell", clean
    if hook_name in ("afterMCPExecution", "beforeMCPExecution") and mcp_server:
        qualified = tool_name if "." in tool_name else f"{mcp_server}.{tool_name}"
        return qualified, mcp_server, clean
    if tool_name.startswith("mcp__"):
        return tool_name, mcp_server or "mcp", clean
    return f"cursor.{tool_name}", "cursor", clean


def map_cursor_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    hook_name = str(data.get("hook_event_name") or hook_name)
    correlation = str(_pick(data, "conversation_id", "generation_id", "session_id", default=""))
    session_id = str(_pick(data, "session_id", "conversation_id", default=""))
    initiator = _initiator_from_hook(hook_name, data)

    if hook_name == "sessionStart":
        return {
            "source_app": "cursor",
            "adapter": "cursor_hook",
            "event_type": "session_start",
            "correlation_id": correlation or session_id,
            "session_id": session_id,
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        }

    if hook_name in ("sessionEnd", "stop"):
        return {
            "source_app": "cursor",
            "adapter": "cursor_hook",
            "event_type": "session_end",
            "correlation_id": correlation or session_id,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
        }

    if hook_name in CURSOR_BEFORE:
        qualified, server, clean = _cursor_tool_context(hook_name, data)
        decision = str(_pick(data, "permission", default="ask"))
        outcome = "pending" if decision == "ask" else ("denied" if decision == "deny" else "success")
        return {
            "source_app": "cursor",
            "adapter": "cursor_hook",
            "event_type": "approval_request" if decision in ("ask", "deny") else "tool_called",
            "outcome": outcome,
            "reason": f"decision:{decision};hook:{hook_name}",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": qualified, "server": server, "arguments": clean},
        }

    if hook_name in CURSOR_AFTER:
        qualified, server, clean = _cursor_tool_context(hook_name, data)
        event_type, outcome, reason = _after_outcome(data)
        return {
            "source_app": "cursor",
            "adapter": "cursor_hook",
            "event_type": event_type,
            "outcome": outcome,
            "reason": reason,
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": qualified, "server": server, "arguments": clean},
        }

    if hook_name == "postToolUseFailure":
        tool_name = str(_pick(data, "tool_name", "tool", default="unknown"))
        return {
            "source_app": "cursor",
            "adapter": "cursor_hook",
            "event_type": "tool_failed",
            "outcome": "error",
            "reason": str(_pick(data, "error", "message", default="tool_failed")),
            "correlation_id": correlation,
            "session_id": session_id,
            "tool_qualified": f"cursor.{tool_name}",
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
        }

    return None


def map_claude_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    hook_name = str(data.get("hook_event_name") or hook_name)
    correlation = str(_pick(data, "session_id", default=""))
    session_id = correlation
    initiator = _initiator_from_hook(hook_name, data)
    tool_name = str(_pick(data, "tool_name", default="unknown"))
    tin = _pick(data, "tool_input", default={})
    clean = redact_arguments(tin)

    if hook_name in ("SessionStart",):
        return {
            "source_app": "claude",
            "adapter": "claude_hook",
            "event_type": "session_start",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        }

    if hook_name in ("Stop", "SubagentStop"):
        return {
            "source_app": "claude",
            "adapter": "claude_hook",
            "event_type": "session_end",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
        }

    if hook_name in ("PreToolUse", "Notification"):
        decision = str(_pick(data, "permissionDecision", default="ask"))
        outcome = "pending" if decision == "ask" else ("denied" if decision == "deny" else "success")
        return {
            "source_app": "claude",
            "adapter": "claude_hook",
            "event_type": "approval_request",
            "outcome": outcome,
            "reason": f"decision:{decision};hook:{hook_name}",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": tool_name, "server": "claude", "arguments": clean},
        }

    if hook_name == "PostToolUse":
        event_type, outcome, reason = _after_outcome(data)
        return {
            "source_app": "claude",
            "adapter": "claude_hook",
            "event_type": event_type,
            "outcome": outcome,
            "reason": reason,
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": tool_name, "server": "claude", "arguments": clean},
        }

    if hook_name == "UserPromptSubmit":
        return {
            "source_app": "claude",
            "adapter": "claude_hook",
            "event_type": "session_start",
            "correlation_id": correlation,
            "session_id": session_id,
            "reason": "user_prompt",
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        }

    return None


def map_antigravity_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    hook_name = str(data.get("hook_event_name") or data.get("event") or hook_name)
    correlation = str(_pick(data, "conversationId", "conversation_id", default=""))
    session_id = correlation
    tool_name = str(_pick(data, "tool_name", "toolName", default="unknown"))
    args = _pick(data, "tool_input", "toolInput", default={})
    clean = redact_arguments(args)
    is_hitl = tool_name in ("ask_permission", "ask_question")

    if hook_name in ("PreInvocation", "sessionStart"):
        return {
            "source_app": "antigravity",
            "adapter": "antigravity_hook",
            "event_type": "session_start",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        }

    if hook_name == "Stop":
        return {
            "source_app": "antigravity",
            "adapter": "antigravity_hook",
            "event_type": "session_end",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
        }

    if hook_name == "PreToolUse":
        event_type = "approval_request" if is_hitl else "approval_request"
        return {
            "source_app": "antigravity",
            "adapter": "antigravity_hook",
            "event_type": event_type,
            "outcome": "pending",
            "reason": f"hook:{hook_name};hitl:{is_hitl}",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": f"antigravity.{tool_name}", "server": "antigravity", "arguments": clean},
        }

    if hook_name in ("PostToolUse", "PostInvocation"):
        event_type, outcome, reason = _after_outcome(data)
        return {
            "source_app": "antigravity",
            "adapter": "antigravity_hook",
            "event_type": event_type,
            "outcome": outcome,
            "reason": reason,
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": f"antigravity.{tool_name}", "server": "antigravity", "arguments": clean},
        }

    return None


def map_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    source = _source_app()
    if source == "claude":
        payload = map_claude_hook(hook_name, data)
    elif source == "antigravity":
        payload = map_antigravity_hook(hook_name, data)
    elif source == "cursor":
        payload = map_cursor_hook(hook_name, data)
    elif "conversationId" in data:  # auto-detect when env unset
        payload = map_antigravity_hook(hook_name, data)
    elif hook_name[:1].isupper():
        payload = map_claude_hook(hook_name, data)
    else:
        payload = map_cursor_hook(hook_name, data)
    # Hash tool args in-process so plaintext never crosses the wire.
    return _hash_tool_args(payload)


def hook_main(hook_name: str) -> int:
    data, decode_error = read_hook_stdin()
    if decode_error:
        data["_stdin_decode_error"] = True

    payload = map_hook(hook_name, data)
    if payload:
        if decode_error:
            payload["reason"] = (payload.get("reason", "") + ";stdin_decode_error").strip(";")
        post_ingest(payload, quiet=True)

    # Observe-only by default. AgentAudit records; it must never change the
    # IDE's enforcement decision. Emitting {"permission":"allow"} here would
    # auto-approve a tool call the user would otherwise be prompted to review —
    # a security regression for an audit tool. Only emit a decision when the
    # operator explicitly opts in via AGENTAUDIT_ENFORCE=allow|deny|ask.
    enforce = os.environ.get("AGENTAUDIT_ENFORCE", "").strip().lower()
    if enforce in ("allow", "deny", "ask") and (
        hook_name in CURSOR_BLOCKING or hook_name == "PreToolUse"
    ):
        print(json.dumps({"permission": enforce}))

    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentAudit external ingest client")
    sub = parser.add_subparsers(dest="cmd", required=True)

    hook_p = sub.add_parser("hook", help="Run as an IDE hook (hook name as arg)")
    hook_p.add_argument("hook_name")

    send_p = sub.add_parser("send", help="Send a JSON payload file or stdin")
    send_p.add_argument("--file", "-f", help="JSON file path")
    send_p.add_argument("--source-app", default=None)

    sub.add_parser("selftest", help="POST a synthetic event and confirm it lands")

    args = parser.parse_args(argv)

    if args.cmd == "hook":
        return hook_main(args.hook_name)

    if args.cmd == "selftest":
        return selftest()

    if args.source_app:
        os.environ["AGENTAUDIT_SOURCE_APP"] = args.source_app

    if args.file:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        payload = json.loads(sys.stdin.read())

    return 0 if post_ingest(payload) else 1


if __name__ == "__main__":
    # python scripts/agentaudit_ingest.py [cursor|claude|antigravity] hook <EventName>
    if len(sys.argv) >= 2 and sys.argv[1] in ("cursor", "claude", "antigravity"):
        os.environ["AGENTAUDIT_SOURCE_APP"] = sys.argv[1]
        if len(sys.argv) >= 4 and sys.argv[2] == "hook":
            sys.exit(hook_main(sys.argv[3]))
        if len(sys.argv) >= 3:
            sys.exit(hook_main(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    if len(sys.argv) >= 3 and sys.argv[1] == "hook":
        sys.exit(hook_main(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] not in ("hook", "send", "selftest"):
        sys.exit(hook_main(sys.argv[1]))
    sys.exit(cli_main())
