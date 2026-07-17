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


def _extract_command(hook_data: dict[str, Any] | str, qualified: str = "") -> str:
    if isinstance(hook_data, str):
        return hook_data
    if not isinstance(hook_data, dict):
        return ""

    for key in ("command", "cmd", "script", "CommandLine"):
        val = hook_data.get(key)
        if val is not None and str(val).strip():
            return str(val)

    args = hook_data.get("arguments") or hook_data.get("args") or hook_data.get("input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args
    if isinstance(args, dict):
        for key in ("command", "cmd", "script", "CommandLine", "value"):
            val = args.get(key)
            if val is not None and str(val).strip():
                return str(val)
    q = (qualified or "").lower()
    if q.endswith(".run_command") or q in ("bash", "shell.run", "shell"):
        val = hook_data.get("value")
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
