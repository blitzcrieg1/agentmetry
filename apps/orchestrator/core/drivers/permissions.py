"""Tool permissions — closed by default, per-skill allowlists, Tier 0 exec gate."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any


class ToolPermissionError(Exception):
    """The skill's YAML does not allow this tool."""


class ToolExecApprovalRequired(ToolPermissionError):
    """Tier 0 sandbox policy: exec-tagged tools are denied until a sandbox
    tier exists; each denial is recorded as a TOOL_EXEC_APPROVAL interrupt."""


def check_tool_allowed(
    skill_config: dict[str, Any],
    qualified: str,
    *,
    tags: list[str],
) -> None:
    """Raise unless the skill's `tools:` allowlist covers this qualified name.

    Closed by default: a skill without a `tools:` key can call nothing.
    Patterns use fnmatch, e.g. ["fs.read_file", "search.*"].
    """
    allow = skill_config.get("tools") or []
    if not any(fnmatch(qualified, pattern) for pattern in allow):
        raise ToolPermissionError(
            f"Skill '{skill_config.get('name', '?')}' does not allow tool '{qualified}'"
        )
    if "exec" in tags:
        raise ToolExecApprovalRequired(
            f"Tool '{qualified}' is exec-tagged — denied by Tier 0 sandbox policy"
        )
