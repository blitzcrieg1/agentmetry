"""What this machine is configured to let an agent do, for the local dashboard.

The fleet console in a vendor product inventories every laptop. This is the
one-machine version of that question, answered from checks that already exist:
which agents are installed and hooked, which settings skip a prompt, which MCP
servers are configured, and which tool-policy rules are loaded.

Nothing here is a detection, and nothing leaves the machine unless the
dashboard, which is served from this process, asks for it. Arguments, env
values, file paths and command lines stay out of the payload. A URL keeps only
its host, through `McpServer.wire_entry`.
"""

from __future__ import annotations

from typing import Any

from agentmetry.core.audit.tool_policy.capability import ASK_HONOURED
from agentmetry.core.diagnostics.mcp_schema import FINGERPRINT_VERSION


def _schema_view(name: str, store: Any) -> dict[str, Any]:
    """What the proxy has listed for one server, without the tool text."""
    record = store.servers.get(name)
    if record is None:
        return {"observed": False, "listing": "not_observed", "observed_at": "", "tool_count": None}
    if record.fingerprint_version != FINGERPRINT_VERSION:
        listing = "not_comparable"
    elif record.previous and record.previous != record.fingerprint:
        listing = "changed"
    else:
        listing = "baseline"
    return {
        "observed": True,
        "listing": listing,
        "observed_at": record.observed_at,
        "tool_count": record.tool_count,
    }


def snapshot() -> dict[str, Any]:
    """One read of this machine. Safe to call from a request handler."""
    from agentmetry.core.audit.dlp.loader import load_dlp_rules
    from agentmetry.core.audit.identity import host_id
    from agentmetry.core.audit.policy_settings import policy_settings
    from agentmetry.core.audit.tool_policy.loader import load_tool_policy
    from agentmetry.core.diagnostics.hook_coverage import SURFACES, coverage, is_service_profile
    from agentmetry.core.diagnostics.mcp_inventory import collect as collect_mcp
    from agentmetry.core.diagnostics.mcp_schema import load_store
    from agentmetry.core.diagnostics.posture import NOT_CHECKED, collect as collect_posture

    states = coverage()
    agents = [{"name": surface.name, "state": states.get(surface.name, "unknown")} for surface in SURFACES]

    posture = collect_posture()
    inventory = collect_mcp()
    store = load_store()
    policy = policy_settings()
    rules, default_action = load_tool_policy(policy.tool_policy_path)
    dlp_rules = load_dlp_rules(policy.dlp_rules_path)

    servers = []
    for server in inventory.servers:
        entry = server.wire_entry()
        entry.update(_schema_view(server.name, store))
        servers.append(entry)

    return {
        "host_id": host_id(),
        "profile": "service" if is_service_profile() else "user",
        "agents": agents,
        "posture": {
            "findings": [{**item.wire(), "why": item.why} for item in posture.sorted()],
            "counts": posture.counts(),
            "unreadable": len(posture.unreadable),
            "not_checked": [{"agent": agent, "why": why} for agent, why in sorted(NOT_CHECKED.items())],
        },
        "mcp": {
            "config_digest": inventory.digest()[:16],
            "schema_digest": store.digest()[:16] if store.servers else "",
            "observed_servers": len(store.servers),
            "servers": servers,
        },
        "policy": {
            "mode": policy.tool_policy_mode,
            "default": default_action,
            "rules": [
                {
                    "id": rule.id,
                    "action": rule.action,
                    "description": rule.description,
                    "tools": len(rule.tools),
                    "matches_command": bool(rule.command_pattern),
                }
                for rule in rules
            ],
            "ask_reaches": [{"agent": agent, "hook": hook} for agent, hook in sorted(ASK_HONOURED)],
            "dlp_mode": policy.dlp_mode,
            "dlp_rules": len(dlp_rules),
        },
    }
