import fnmatch
import json
import logging
import re
from typing import Any

from .loader import load_tool_policy
from .models import ToolPolicyMatch, ToolPolicyRule, ToolPolicyVerdict
from ...config import settings

logger = logging.getLogger(__name__)

_POLICY: tuple[list[ToolPolicyRule], str] | None = None


def reset_policy() -> None:
    """Clear cached policy (tests / live reload)."""
    global _POLICY
    _POLICY = None


def _init_policy() -> tuple[list[ToolPolicyRule], str]:
    global _POLICY
    if _POLICY is None:
        _POLICY = load_tool_policy(settings.tool_policy_path)
    return _POLICY


def _norm(name: str) -> str:
    return name.lower().replace("_", "").replace("-", "")


def _tool_matches(pattern: str, qualified: str) -> bool:
    q = qualified.lower()
    p = pattern.lower()
    if fnmatch.fnmatch(q, p):
        return True
    short = q.split(".")[-1] if "." in q else q
    return fnmatch.fnmatch(short, p) or fnmatch.fnmatch(_norm(short), _norm(p))


_COMMAND_KEYS = ("command", "cmd", "script", "CommandLine")
# Mirrors extract_command in scripts/agentmetry_ingest.py, so a policy can target
# a file path (agent config, hooks) and not only a shell string.
_PATH_KEYS = ("path", "filepath", "file_path", "AbsolutePath", "TargetFile", "target_path")


def _nested_arg_containers(hook_data: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Every dict an IDE may hide tool arguments in, plus a raw string fallback.

    Cursor shell hooks put `command` at the top level, but Claude and Codex nest
    it under `tool_input` and Antigravity under `toolCall.args`. Without those,
    a `command_pattern` rule matched nothing on three of the four supported IDEs
    — the shipped block_shell_rm rule was Cursor-only in practice.
    """
    containers: list[dict[str, Any]] = []
    raw = ""
    for key in ("arguments", "args", "input", "tool_input", "toolInput"):
        val = hook_data.get(key)
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                raw = raw or val
                continue
        if isinstance(val, dict):
            containers.append(val)
    tool_call = hook_data.get("toolCall")
    if isinstance(tool_call, dict) and isinstance(tool_call.get("args"), dict):
        containers.append(tool_call["args"])
    return containers, raw


def _extract_command(hook_data: dict[str, Any] | str, qualified: str = "") -> str:
    if isinstance(hook_data, str):
        return hook_data
    if not isinstance(hook_data, dict):
        return ""

    nested, raw = _nested_arg_containers(hook_data)

    for key in _COMMAND_KEYS:
        val = hook_data.get(key)
        if val is not None and str(val).strip():
            return str(val)
    for container in nested:
        for key in (*_COMMAND_KEYS, "value"):
            val = container.get(key)
            if val is not None and str(val).strip():
                return str(val)
    if raw:
        return raw

    q = (qualified or "").lower()
    if q.endswith(".run_command") or q in ("bash", "shell.run", "shell"):
        val = hook_data.get("value")
        if val is not None and str(val).strip():
            return str(val)

    # Path fallback: lets a rule deny writes to agent-execution config.
    for container in (hook_data, *nested):
        for key in _PATH_KEYS:
            val = container.get(key)
            if val is not None and str(val).strip():
                return str(val)
    return ""


def _server_matches(rule: ToolPolicyRule, server: str) -> bool:
    if not rule.servers:
        return True
    if not server:
        return False
    s = server.lower()
    return any(fnmatch.fnmatch(s, pat.lower()) for pat in rule.servers)


def _rule_matches(rule: ToolPolicyRule, qualified: str, server: str, command: str) -> bool:
    if not rule.id or not rule.tools:
        return False
    if not any(_tool_matches(pat, qualified) for pat in rule.tools):
        return False
    if not _server_matches(rule, server):
        return False
    if rule.command_pattern:
        if not command:
            return False
        try:
            if not re.search(rule.command_pattern, command):
                return False
        except re.error as exc:
            logger.warning("[tool_policy] invalid regex for rule %s: %s", rule.id, exc)
            return False
    return True


def evaluate(
    tool_qualified: str,
    hook_data: dict[str, Any] | str,
    *,
    server: str = "",
    mode: str | None = None,
) -> ToolPolicyVerdict:
    """Evaluate tool allow/deny policy. Runs on plaintext hook data before hashing."""
    if mode is None:
        mode = settings.tool_policy_mode
    if mode == "disable":
        return ToolPolicyVerdict(matched=False, blocked=False, mode=mode)

    rules, default_action = _init_policy()
    if not rules and default_action == "allow":
        return ToolPolicyVerdict(matched=False, blocked=False, mode=mode)

    command = _extract_command(hook_data, tool_qualified)
    deny_hits: list[ToolPolicyRule] = []
    allow_hits: list[ToolPolicyRule] = []

    for rule in rules:
        if _rule_matches(rule, tool_qualified, server, command):
            if rule.action == "deny":
                deny_hits.append(rule)
            else:
                allow_hits.append(rule)

    if default_action == "allow":
        if deny_hits:
            hit = deny_hits[0]
            return ToolPolicyVerdict(
                matched=True,
                blocked=True,
                mode=mode,
                match=ToolPolicyMatch(rule_id=hit.id, action="deny"),
            )
        return ToolPolicyVerdict(matched=False, blocked=False, mode=mode)

    # default deny — must match an allow rule and not be overridden by deny
    if deny_hits:
        hit = deny_hits[0]
        return ToolPolicyVerdict(
            matched=True,
            blocked=True,
            mode=mode,
            match=ToolPolicyMatch(rule_id=hit.id, action="deny"),
        )
    if allow_hits:
        hit = allow_hits[0]
        return ToolPolicyVerdict(
            matched=True,
            blocked=False,
            mode=mode,
            match=ToolPolicyMatch(rule_id=hit.id, action="allow"),
        )
    return ToolPolicyVerdict(
        matched=True,
        blocked=True,
        mode=mode,
        match=ToolPolicyMatch(rule_id="default_deny", action="deny"),
    )
