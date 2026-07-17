import yaml
from pathlib import Path

from .models import ToolPolicyRule


def load_tool_policy(manifest_path: Path | str) -> tuple[list[ToolPolicyRule], str]:
    """Load tool policy rules and default action (allow | deny) from YAML."""
    path = Path(manifest_path)
    if not path.exists():
        return [], "allow"

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data or "rules" not in data:
        return [], str(data.get("default", "allow") if data else "allow")

    default = str(data.get("default", "allow")).lower()
    if default not in ("allow", "deny"):
        default = "allow"

    rules: list[ToolPolicyRule] = []
    for raw in data["rules"]:
        action = str(raw.get("action", "deny")).lower()
        if action not in ("allow", "deny"):
            continue
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
