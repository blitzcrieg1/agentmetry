import logging
from pathlib import Path

import yaml

from .models import ToolPolicyRule

logger = logging.getLogger(__name__)

#: libyaml where it is installed. The pure-Python parser was most of the hook's
#: runtime: the DLP and tool manifests are re-read by every hook process, and
#: parsing them took ~55 ms of an ~85 ms tool call (#171). Same SafeConstructor,
#: so the same Python objects, which `test_hook_import_cost.py` checks.
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

ACTIONS = ("allow", "deny", "ask")

#: `ask` is not a valid default yet. "Ask about everything not allowlisted" is
#: zero-trust mode, and it needs the ask-gate's timeouts to be safe: an IDE
#: that never shows the prompt would otherwise stall every tool call forever.
DEFAULTS = ("allow", "deny")


def _normalise_default(raw: object) -> str:
    """A default the evaluator understands, failing closed on anything else.

    This used to fall back to `allow`, so a typo, or a reasonable guess like
    `default: ask`, silently turned the whole policy into allow-everything.
    For a security control a value nobody recognises has to deny.
    """
    value = str("allow" if raw is None else raw).strip().lower()
    if value in DEFAULTS:
        return value
    if value == "ask":
        logger.warning(
            "[tool_policy] default: ask is not supported until the ask-gate's "
            "timeouts land; treating it as deny"
        )
    else:
        logger.warning("[tool_policy] unrecognised default %r; treating it as deny", value)
    return "deny"


def load_tool_policy(manifest_path: Path | str) -> tuple[list[ToolPolicyRule], str]:
    """Load tool policy rules and the default action from YAML.

    Rules take `allow`, `deny` or `ask`. Anything unrecognised is loaded as
    `deny` with a warning rather than dropped: a dropped rule is one the
    operator wrote that silently does nothing, which fails open.
    """
    path = Path(manifest_path)
    if not path.exists():
        return [], "allow"

    with open(path, encoding="utf-8") as fh:
        data = yaml.load(fh, Loader=SAFE_LOADER)  # noqa: S506 - a safe loader

    if not data or "rules" not in data:
        return [], _normalise_default(data.get("default") if data else None)

    default = _normalise_default(data.get("default"))

    rules: list[ToolPolicyRule] = []
    for raw in data["rules"]:
        action = str(raw.get("action", "deny")).strip().lower()
        if action not in ACTIONS:
            logger.warning(
                "[tool_policy] rule %r has unrecognised action %r; treating it as deny",
                raw.get("id", ""),
                action,
            )
            action = "deny"
        tools = raw.get("tools") or []
        if isinstance(tools, str):
            tools = [tools]
        servers = raw.get("servers") or []
        if isinstance(servers, str):
            servers = [servers]
        rules.append(
            ToolPolicyRule(
                id=str(raw.get("id", "")),
                action=action,
                tools=[str(t) for t in tools],
                command_pattern=str(raw.get("command_pattern", "") or ""),
                servers=[str(s) for s in servers],
                description=str(raw.get("description", "") or ""),
            )
        )
    return rules, default
