#!/usr/bin/env python3
"""Agentmetry Tier B ingest client — Cursor, Claude Code, Antigravity hooks.

POST adapter events to the local orchestrator ingest API.

Environment:
  AGENTMETRY_URL            default http://127.0.0.1:8000
  AGENTMETRY_API_KEY          optional X-API-Key header (legacy: AGENTMETRY_API_KEY)
  AGENTMETRY_SOURCE_APP     cursor | claude | antigravity | codex | mcp_proxy
  AGENTMETRY_LOG_COMMANDS   1 = keep shell command text in audit (see also AGENTMETRY_AUDIT_LOG_COMMANDS in apps/orchestrator/.env)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from urllib.error import URLError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from apps.orchestrator.core.audit.dlp import scan as dlp_scan
    from apps.orchestrator.core.audit.tool_policy import evaluate as tool_policy_eval
except ImportError:
    dlp_scan = None
    tool_policy_eval = None

REDACT_KEYS = frozenset({
    "token", "api_key", "apikey", "password", "secret", "authorization",
    "anthropic_api_key", "openai_api_key",
})

COMMAND_MAX_LEN = 4096

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
        os.environ.get("AGENTMETRY_URL")
        or os.environ.get("AGENTMETRY_AUDIT_INGEST_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def _api_key() -> str:
    return (
        os.environ.get("AGENTMETRY_API_KEY", "").strip()
        or os.environ.get("AGENTMETRY_API_KEY", "").strip()
    )


def _source_app() -> str:
    return os.environ.get("AGENTMETRY_SOURCE_APP", "cursor").lower()


def _pick(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def _json_object_snippets(text: str) -> list[str]:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return [text[start : end + 1]]
    return []


def _stdin_decode_candidates(raw: bytes) -> list[tuple[str, str]]:
    """Return (text, encoding_label) attempts for hook stdin bytes."""
    if not raw.strip():
        return []

    blobs: list[tuple[bytes, str]] = [(raw, "utf-8")]
    if raw.startswith(b"\xff\xfe"):
        blobs.append((raw[2:], "utf-16-le-bom"))
    elif raw.startswith(b"\xfe\xff"):
        blobs.append((raw[2:], "utf-16-be-bom"))
    elif raw.startswith(b"\xef\xbb\xbf"):
        blobs.append((raw[3:], "utf-8-bom"))
    elif len(raw) >= 4 and raw[1:2] == b"\x00" and raw[3:4] == b"\x00":
        blobs.append((raw, "utf-16-le"))

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for blob, preferred in blobs:
        encodings: list[str] = []
        if preferred.endswith("-bom"):
            encodings.append(preferred.replace("-bom", ""))
        elif preferred == "utf-16-le":
            encodings.append("utf-16-le")
        encodings.extend(["utf-8", "utf-16-le", "utf-16", "cp1252", "latin-1"])
        for enc in encodings:
            try:
                text = blob.decode(enc).strip("\ufeff").strip("\x00")
            except UnicodeDecodeError:
                continue
            key = text[:120]
            if key in seen:
                continue
            seen.add(key)
            candidates.append((text, enc))
    return candidates


def read_hook_stdin() -> tuple[dict[str, Any], bool]:
    """Read hook JSON from stdin; tolerate Windows UTF-16 / BOM / wrapper corruption."""
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return {}, False

    for text, enc in _stdin_decode_candidates(raw):
        snippets = [text, *_json_object_snippets(text)]
        seen_snippets: set[str] = set()
        for snippet in snippets:
            if snippet in seen_snippets:
                continue
            seen_snippets.add(snippet)
            try:
                parsed = json.loads(snippet)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            extracted = snippet != text
            non_utf8 = enc not in ("utf-8", "utf-8-bom")
            if non_utf8:
                parsed["_stdin_encoding"] = enc
            return parsed, extracted or non_utf8

    return {"_raw_hex": raw.hex()[:2000], "_raw_len": len(raw)}, True


def _repo_env_path() -> Path:
    return Path(__file__).resolve().parent.parent / "apps" / "orchestrator" / ".env"


def _read_repo_env(key: str) -> str:
    path = _repo_env_path()
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return ""


def _log_commands_enabled() -> bool:
    for raw in (
        os.environ.get("AGENTMETRY_LOG_COMMANDS", ""),
        _read_repo_env("AGENTMETRY_LOG_COMMANDS"),
        _read_repo_env("AGENTMETRY_AUDIT_LOG_COMMANDS"),
    ):
        if raw.strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _log_full_args_enabled() -> bool:
    for raw in (
        os.environ.get("AGENTMETRY_LOG_FULL_ARGS", ""),
        _read_repo_env("AGENTMETRY_LOG_FULL_ARGS"),
        _read_repo_env("AGENTMETRY_AUDIT_LOG_FULL_ARGS"),
    ):
        if raw.strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def extract_command(args: Any, qualified: str = "") -> str | None:
    """Pull shell command text from tool args (Bash, run_command, shell.run, etc.)."""
    if isinstance(args, dict):
        for key in ("command", "cmd", "script", "CommandLine"):
            val = args.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()[:COMMAND_MAX_LEN]
        
        for key in ("path", "filepath", "file_path", "AbsolutePath", "TargetFile", "target_path"):
            val = args.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()[:COMMAND_MAX_LEN]
    q = (qualified or "").lower()
    if q.endswith(".run_command") or q in ("bash", "shell.run", "shell"):
        if isinstance(args, dict):
            val = args.get("value")
            if val is not None and str(val).strip():
                return str(val).strip()[:COMMAND_MAX_LEN]
    return None


def redact_arguments(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return {
            k: "<redacted>" if str(k).lower() in REDACT_KEYS else v
            for k, v in args.items()
        }
    if args is None:
        return {}
    return {"value": args}


# Inline mirror of core/audit/redaction.py — the standalone hook cannot import
# from apps/orchestrator/core. KEEP THESE PATTERNS IN SYNC (see test).
_SECRET_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(authorization:\s*)\S+"), r"\1<redacted>"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1<redacted>@"),
    (re.compile(r"(?i)(-{1,2}(?:password|token|secret|api[-_]?key|pwd)[=\s]+)\S+"), r"\1<redacted>"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|token|secret|api[-_]?key|apikey|access[-_]?key)\s*[=:]\s*[^\s;&|\"']+"
        ),
        r"\1=<redacted>",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted-aws-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<redacted-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<redacted-gh-token>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<redacted-slack-token>"),
]


def scrub_command(text: Any) -> Any:
    """Mask inline secrets in a command string before it is stored/sent."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def scrub_arg_values(args: Any) -> Any:
    if not isinstance(args, dict):
        return args
    return {k: (scrub_command(v) if isinstance(v, str) else v) for k, v in args.items()}


def hash_arguments(args: Any) -> str:
    clean = redact_arguments(args if isinstance(args, dict) else {"value": args})
    blob = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _hash_tool_args(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Replace tool.arguments with a client-side input_hash.

    Args are hashed *inside the hook process* so redacted-plaintext arguments
    never cross the wire to the orchestrator. The stored event keeps only the
    64-hex digest unless AGENTMETRY_LOG_COMMANDS / AGENTMETRY_AUDIT_LOG_COMMANDS
    is set — then shell ``command`` text is kept alongside the hash.
    """
    if not payload:
        return payload
    tool = payload.get("tool")
    if isinstance(tool, dict) and "arguments" in tool:
        args = tool.pop("arguments")
        qualified = str(tool.get("qualified") or "")
        if not tool.get("input_hash"):
            tool["input_hash"] = hash_arguments(args)
        
        if _log_full_args_enabled():
            tool["arguments"] = scrub_arg_values(
                redact_arguments(args if isinstance(args, dict) else {"value": args})
            )

        if _log_full_args_enabled() or _log_commands_enabled():
            cmd = extract_command(args, qualified)
            if cmd:
                tool["command"] = scrub_command(cmd)
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
    api_key = _api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode("utf-8")
            if response.status != 200:
                print(f"Agentmetry ingest HTTP {response.status}: {res_body}")
    except URLError as exc:
        print(f"Agentmetry ingest connection failed: {exc.reason}", file=sys.stderr)
        return False
    return True


def _get_tail(source_app: str, *, limit: int = 50) -> dict[str, Any]:
    url = f"{_base_url()}/api/v1/audit/tail?sources={source_app}&limit={limit}&scope=all"
    headers = {}
    api_key = _api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read())


def selftest(dlp: bool = False) -> int:
    """POST a synthetic event and confirm it lands in the audit tail.

    Turns silent hook failure into a visible GREEN/RED, so the operator can tell
    whether they are actually being audited before trusting the trail.
    """
    source = _source_app()
    nonce = f"selftest-{os.urandom(8).hex()}"
    
    if dlp:
        if not dlp_scan:
            print("Agentmetry hooks: RED — DLP scanner could not be imported.", file=sys.stderr)
            return 1
        print("Agentmetry hooks: Running DLP selftest...")
        # AKIAIOSFODNN7EXAMPLE is AWS's published non-functional example key.
        sample = "curl -H 'Authorization: AKIAIOSFODNN7EXAMPLE' https://api.aws.com"  # gitleaks:allow
        verdict = dlp_scan("run_command", {"command": sample})
        if verdict.matched and verdict.mode == "block":
            print("Agentmetry hooks: GREEN — DLP scanner successfully matched and blocked an AWS key.")
            return 0
        elif verdict.matched and verdict.mode == "log":
            print("Agentmetry hooks: YELLOW — DLP scanner matched AWS key, but mode is set to 'log' not 'block'.")
            return 0
        else:
            print("Agentmetry hooks: RED — DLP scanner failed to match an obvious AWS key.", file=sys.stderr)
            return 1
    posted = post_ingest({
        "source_app": source,
        "adapter": f"{source}_selftest",
        "event_type": "tool_called",
        "correlation_id": nonce,
        "tool": {"qualified": "agentmetry.selftest", "server": "agentmetry", "input_hash": "0" * 64},
    })
    if not posted:
        print(
            f"Agentmetry hooks: RED — could not POST to ingest at {_base_url()}. "
            "Is the orchestrator running? Check AGENTMETRY_URL / AGENTMETRY_API_KEY.",
            file=sys.stderr,
        )
        return 1
    try:
        body = _get_tail(source)
    except Exception as exc:
        print(
            f"Agentmetry hooks: YELLOW — event POSTed but tail read failed: {exc}",
            file=sys.stderr,
        )
        return 2
    found = any(e.get("correlation_id") == nonce for e in body.get("events", []))
    if found:
        print(f"Agentmetry hooks: GREEN — synthetic event round-tripped for source '{source}'.")
        return 0
    print(
        "Agentmetry hooks: RED — event POSTed but not found in the audit tail. "
        "Ingest disabled (AGENTMETRY_AUDIT_INGEST_ENABLED) or sink misconfigured?",
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
    tool_name = str(_pick(data, "tool_name", "toolName", "tool", "name", default="unknown"))
    mcp_server = str(_pick(data, "mcp_server", "mcpServer", "server", default=""))
    args = _pick(data, "tool_input", "toolInput", "arguments", "input", default=None)
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
    hook_name = str(_pick(data, "hook_event_name", "hookEventName", default=hook_name))
    correlation = str(_pick(
        data, "conversation_id", "conversationId", "generation_id", "generationId",
        "session_id", "sessionId", default="",
    ))
    session_id = str(_pick(data, "session_id", "sessionId", "conversation_id", "conversationId", default=""))
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


def _codex_tool_context(tool_name: str, tool_input: Any) -> tuple[str, str, dict[str, Any]]:
    clean = redact_arguments(tool_input if isinstance(tool_input, dict) else {"value": tool_input})
    name = str(tool_name or "unknown")
    if name == "Bash":
        return "shell.run", "shell", clean
    if name == "apply_patch":
        return "codex.apply_patch", "codex", clean
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3:
            server, tool = parts[1], parts[2]
            qualified = tool if "." in tool else f"{server}.{tool}"
            return qualified, server, clean
        return name, "mcp", clean
    return f"codex.{name}", "codex", clean


def map_codex_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """OpenAI Codex CLI hooks — schema aligned with Claude Code (session_id, tool_name, tool_input)."""
    hook_name = str(data.get("hook_event_name") or hook_name)
    correlation = str(_pick(data, "session_id", "turn_id", default=""))
    session_id = str(_pick(data, "session_id", default=correlation))
    tool_name = str(_pick(data, "tool_name", default="unknown"))
    tool_input = _pick(data, "tool_input", default={})
    model_id = str(_pick(data, "model", default=""))
    permission_mode = str(_pick(data, "permission_mode", default=""))
    initiator = _initiator_from_hook(hook_name, data)

    base: dict[str, Any] = {
        "correlation_id": correlation,
        "session_id": session_id,
        "initiator": {"actor_type": initiator, "trigger": "manual", "operator_id": "local"},
    }
    if model_id:
        base["model"] = {"id": model_id, "provider": "openai"}

    if hook_name == "SessionStart":
        return {
            **base,
            "source_app": "codex",
            "adapter": "codex_hook",
            "event_type": "session_start",
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
            "reason": str(_pick(data, "source", default="startup")),
        }

    if hook_name in ("Stop", "SubagentStop"):
        return {
            **base,
            "source_app": "codex",
            "adapter": "codex_hook",
            "event_type": "session_end",
        }

    if hook_name == "UserPromptSubmit":
        return {
            **base,
            "source_app": "codex",
            "adapter": "codex_hook",
            "event_type": "session_start",
            "reason": "user_prompt",
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        }

    qualified, server, clean = _codex_tool_context(tool_name, tool_input)

    if hook_name in ("PreToolUse", "PermissionRequest"):
        return {
            **base,
            "source_app": "codex",
            "adapter": "codex_hook",
            "event_type": "approval_request",
            "outcome": "pending",
            "reason": f"hook:{hook_name};permission_mode:{permission_mode or 'default'}",
            "tool": {"qualified": qualified, "server": server, "arguments": clean},
        }

    if hook_name == "PostToolUse":
        event_type, outcome, reason = _after_outcome(data)
        if data.get("tool_response") is not None and outcome == "success":
            reason = reason or "tool_completed"
        return {
            **base,
            "source_app": "codex",
            "adapter": "codex_hook",
            "event_type": event_type,
            "outcome": outcome,
            "reason": reason,
            "tool": {"qualified": qualified, "server": server, "arguments": clean},
        }

    return None


def _antigravity_tool_from_data(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Parse Antigravity 2.0 (toolCall) and legacy (toolName/toolInput) stdin."""
    tool_call = data.get("toolCall")
    if isinstance(tool_call, dict):
        name = str(tool_call.get("name") or "unknown")
        raw_args = tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {}
        args = dict(raw_args)
        if "CommandLine" in args and "command" not in args:
            args["command"] = args["CommandLine"]
        if "Cwd" in args and "cwd" not in args:
            args["cwd"] = args["Cwd"]
        return name, args
    name = str(_pick(data, "tool_name", "toolName", default="unknown"))
    raw = _pick(data, "tool_input", "toolInput", default={})
    return name, raw if isinstance(raw, dict) else {}


def map_antigravity_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    hook_name = str(data.get("hook_event_name") or data.get("event") or hook_name)
    correlation = str(_pick(data, "conversationId", "conversation_id", default=""))
    session_id = correlation
    tool_name, raw_args = _antigravity_tool_from_data(data)
    clean = redact_arguments(raw_args)
    is_hitl = tool_name in ("ask_permission", "ask_question")
    has_tool = tool_name != "unknown" or isinstance(data.get("toolCall"), dict)

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

    if hook_name == "PreToolUse" and has_tool:
        event_type = "approval_request" if is_hitl else "tool_called"
        return {
            "source_app": "antigravity",
            "adapter": "antigravity_hook",
            "event_type": event_type,
            "outcome": "pending" if is_hitl else "success",
            "reason": f"hook:{hook_name};hitl:{is_hitl}",
            "correlation_id": correlation,
            "session_id": session_id,
            "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
            "tool": {"qualified": f"antigravity.{tool_name}", "server": "antigravity", "arguments": clean},
        }

    if hook_name in ("PostToolUse", "PostInvocation"):
        event_type, outcome, reason = _after_outcome(data)
        step = data.get("stepIdx")
        if has_tool:
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
        if hook_name == "PostToolUse" and correlation:
            return {
                "source_app": "antigravity",
                "adapter": "antigravity_hook",
                "event_type": event_type,
                "outcome": outcome,
                "reason": f"step:{step};{reason}".strip(";"),
                "correlation_id": correlation,
                "session_id": session_id,
                "initiator": {"actor_type": "agent", "trigger": "manual", "operator_id": "local"},
            }

    return None


def map_hook(hook_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
    source = _source_app()
    if source == "claude":
        payload = map_claude_hook(hook_name, data)
    elif source == "codex":
        payload = map_codex_hook(hook_name, data)
    elif source == "antigravity":
        payload = map_antigravity_hook(hook_name, data)
    elif source == "cursor":
        payload = map_cursor_hook(hook_name, data)
    elif "conversationId" in data:  # auto-detect when env unset
        payload = map_antigravity_hook(hook_name, data)
    elif _pick(data, "model", default="") and hook_name[:1].isupper():
        payload = map_codex_hook(hook_name, data)
    elif hook_name[:1].isupper():
        payload = map_claude_hook(hook_name, data)
    else:
        payload = map_cursor_hook(hook_name, data)
    # Hash tool args in-process so plaintext never crosses the wire.
    payload = _hash_tool_args(payload)
    adapter_override = os.environ.get("AGENTMETRY_ADAPTER", "").strip()
    if payload and adapter_override:
        payload["adapter"] = adapter_override
    return payload


def _emit_hook_stdout(hook_name: str) -> None:
    """Antigravity requires JSON on stdout; Cursor/Codex use permission when enforcing."""
    source = _source_app()
    enforce = os.environ.get("AGENTMETRY_ENFORCE", "").strip().lower()

    if source == "antigravity":
        if hook_name == "PreToolUse":
            decision = {"allow": "allow", "deny": "deny", "ask": "ask"}.get(enforce, "allow")
            print(json.dumps({"decision": decision}))
        elif hook_name in ("PostToolUse", "PostInvocation", "PreInvocation"):
            print("{}")
        elif hook_name == "Stop":
            print(json.dumps({"decision": "stop"}))
        return

    if enforce in ("allow", "deny", "ask") and (
        hook_name in CURSOR_BLOCKING
        or hook_name in ("PreToolUse", "PermissionRequest")
    ):
        print(json.dumps({"permission": enforce}))


def _hook_debug_path() -> Path:
    data_dir = Path(__file__).resolve().parent.parent / "apps" / "orchestrator" / "data"
    source = _source_app() or "hook"
    return data_dir / f"{source}-hook-debug.log"


def hook_main(hook_name: str) -> int:
    data, decode_error = read_hook_stdin()
    if decode_error:
        data["_stdin_decode_error"] = True

    if os.environ.get("AGENTMETRY_HOOK_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        debug_path = _hook_debug_path()
        try:
            with debug_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{_utc_now()} {hook_name} stdin={json.dumps(data)[:2000]}\n")
        except OSError:
            pass

    payload = map_hook(hook_name, data)
    if payload:
        if decode_error:
            payload["reason"] = (payload.get("reason", "") + ";stdin_decode_error").strip(";")
            
        if payload.get("event_type") in ("tool_called", "approval_request"):
            tool_block = payload.get("tool") or {}
            tool_name = tool_block.get("qualified", "")
            server = tool_block.get("server", "")

            if tool_policy_eval:
                tp_verdict = tool_policy_eval(tool_name, data, server=server)
                if tp_verdict.matched:
                    payload["tool_policy"] = {
                        "rule_id": tp_verdict.match.rule_id if tp_verdict.match else "",
                        "action": tp_verdict.match.action if tp_verdict.match else "",
                        "mode": tp_verdict.mode,
                        "blocked": tp_verdict.blocked,
                    }
                    if tp_verdict.blocked and tp_verdict.mode == "block":
                        rule_id = tp_verdict.match.rule_id if tp_verdict.match else "policy"
                        payload["outcome"] = "denied"
                        payload["reason"] = f"tool_policy:{rule_id}"
                        payload["event_type"] = "tool_called"
                        post_ingest(payload, quiet=True)
                        source = _source_app()
                        if source == "antigravity":
                            print(json.dumps({"decision": "deny"}))
                        else:
                            print(json.dumps({"permission": "deny"}))
                        return 0

            if dlp_scan:
                dlp_verdict = dlp_scan(tool_name, data)
            else:
                dlp_verdict = None
            if dlp_verdict and dlp_verdict.matched:
                # Rule metadata only — never the matched value.
                payload["dlp"] = {
                    "rule_id": dlp_verdict.match.rule_id,
                    "mode": dlp_verdict.mode,
                    "pattern_type": dlp_verdict.match.pattern_type,
                    "category": dlp_verdict.match.category,
                    "severity": dlp_verdict.match.severity,
                    "rule_ids": [m.rule_id for m in (dlp_verdict.matches or [])],
                }
                if dlp_verdict.mode == "block":
                    payload["outcome"] = "denied"
                    payload["reason"] = f"dlp:{dlp_verdict.match.rule_id}"
                    payload["event_type"] = "tool_called"
                    post_ingest(payload, quiet=True)
                    source = _source_app()
                    if source == "antigravity":
                        print(json.dumps({"decision": "deny"}))
                    else:
                        print(json.dumps({"permission": "deny"}))
                    return 0

        post_ingest(payload, quiet=True)

    # Observe-only: Antigravity still needs {"decision":"allow"} on PreToolUse stdout.
    _emit_hook_stdout(hook_name)

    return 0


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agentmetry external ingest client")
    sub = parser.add_subparsers(dest="cmd", required=True)

    hook_p = sub.add_parser("hook", help="Run as an IDE hook (hook name as arg)")
    hook_p.add_argument("hook_name")

    send_p = sub.add_parser("send", help="Send a JSON payload file or stdin")
    send_p.add_argument("--file", "-f", help="JSON file path")
    send_p.add_argument("--source-app", default=None)

    test_p = sub.add_parser("selftest", help="POST a synthetic event and confirm it lands")
    test_p.add_argument("--dlp", action="store_true", help="Run DLP scanner test")

    args = parser.parse_args(argv)

    if args.cmd == "hook":
        return hook_main(args.hook_name)

    if args.cmd == "selftest":
        return selftest(dlp=args.dlp)

    if args.source_app:
        os.environ["AGENTMETRY_SOURCE_APP"] = args.source_app

    if args.file:
        payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        payload = json.loads(sys.stdin.read())

    return 0 if post_ingest(payload) else 1


if __name__ == "__main__":
    # python scripts/agentmetry_ingest.py [cursor|claude|antigravity|codex] hook <EventName>
    if len(sys.argv) >= 2 and sys.argv[1] in ("cursor", "claude", "antigravity", "codex"):
        os.environ["AGENTMETRY_SOURCE_APP"] = sys.argv[1]
        if len(sys.argv) >= 4 and sys.argv[2] == "hook":
            sys.exit(hook_main(sys.argv[3]))
        if len(sys.argv) >= 3:
            sys.exit(hook_main(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        sys.exit(selftest(dlp="--dlp" in sys.argv))
    if len(sys.argv) >= 3 and sys.argv[1] == "hook":
        sys.exit(hook_main(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] not in ("hook", "send", "selftest"):
        sys.exit(hook_main(sys.argv[1]))
    sys.exit(cli_main())
