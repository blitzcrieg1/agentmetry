"""Bounded Claude hook observations, not independently verified execution.

Keep this stdlib-only: it is imported in the hook process as well as the
receiver. Both paths must retain the same subset without Pydantic coercion.
"""

from __future__ import annotations

from typing import Any

MAX_INVOCATION_ID = 256
MAX_DURATION_MS = (1 << 53) - 1
_PHASES = {
    "PreToolUse": "request",
    "PostToolUse": "result",
    "PostToolUseFailure": "result",
}


def normalize_claude_tool_metadata(tool: object) -> dict[str, Any]:
    """Allowlist normalized metadata; invalid optional scalars stay absent.

    Invalid phase/status combinations drop the new blocks, not the event.
    Never copy response bodies, free-text errors, paths or arbitrary fields.
    """
    if not isinstance(tool, dict):
        return {}
    raw = tool.get("invocation")
    if not isinstance(raw, dict):
        return {}
    hook = raw.get("hook_event")
    if not isinstance(hook, str) or hook not in _PHASES:
        return {}
    phase = _PHASES[hook]
    if raw.get("phase") != phase or raw.get("provenance") != "harness_reported":
        return {}
    invocation = {
        "phase": phase,
        "hook_event": hook,
        "provenance": "harness_reported",
    }
    identifier = raw.get("id")
    if (
        isinstance(identifier, str)
        and 0 < len(identifier) <= MAX_INVOCATION_ID
        and all("!" <= char <= "~" for char in identifier)
    ):
        invocation["id"] = identifier
    metadata: dict[str, Any] = {"invocation": invocation}
    if phase == "request":
        return metadata
    raw_result = tool.get("result")
    if not isinstance(raw_result, dict):
        return {}
    expected = "reported_failure" if hook == "PostToolUseFailure" else "reported_success"
    if raw_result.get("status") != expected:
        return {}
    result: dict[str, Any] = {"status": expected}
    duration = raw_result.get("duration_ms")
    # bool is an int subclass. Strings and integral floats must not be coerced.
    if type(duration) is int and 0 <= duration <= MAX_DURATION_MS:
        result["duration_ms"] = duration
    if hook == "PostToolUseFailure":
        interrupted = raw_result.get("is_interrupt")
        if type(interrupted) is bool:
            result["is_interrupt"] = interrupted
        result["error_kind"] = "interrupted" if interrupted is True else "tool_failure"
    metadata["result"] = result
    return metadata


def claude_hook_tool_metadata(hook: str, data: dict[str, Any]) -> dict[str, Any]:
    """Extract documented source scalars before arguments are hashed away."""
    if hook not in _PHASES:
        return {}
    tool: dict[str, Any] = {
        "invocation": {
            "id": data.get("tool_use_id"),
            "phase": _PHASES[hook],
            "hook_event": hook,
            "provenance": "harness_reported",
        },
    }
    if _PHASES[hook] == "result":
        tool["result"] = {
            "status": "reported_failure" if hook == "PostToolUseFailure" else "reported_success",
            "duration_ms": data.get("duration_ms"),
            "is_interrupt": data.get("is_interrupt"),
        }
    return normalize_claude_tool_metadata(tool)
