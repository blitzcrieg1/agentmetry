"""The configured MCP servers as an event a SIEM can see, when an operator asks (#169).

`agentmetry mcp` answers "what are the agents on this machine wired to", but
only for whoever runs it, on that machine. Nothing reached the trail, so no SIEM
could answer "which machines have this server" or "when did it first appear".

This is deliberately not the heartbeat. The heartbeat goes to every sink on
every install and commits to the MCP surface by digest alone, so that recording
your own laptop never ships your tool inventory to a SOC. That property stays.
The inventory is a separate event, off unless `AGENTMETRY_MCP_INVENTORY=1`, for
the fleet that wants it.

When on, it is emitted when the recorder starts, whenever the configured
surface changes, and once a day regardless, so a dashboard over the last 24
hours sees every host. Each server is reduced to `McpServer.wire_entry()`: no
arguments, no environment, no URL beyond its host.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.identity import identity_fields

logger = logging.getLogger(__name__)

#: Re-emit an unchanged inventory this often, so a fleet view over a day is whole.
SNAPSHOT_SECONDS = 24 * 3600

#: The event goes to every sink. A machine with more servers than this is
#: reported by count, with the list cut and `truncated` set.
LIMIT = 100


def enabled() -> bool:
    from agentmetry.core.config import settings

    return bool(getattr(settings, "mcp_inventory_enabled", False))


@dataclass
class InventoryState:
    """What was last emitted, so an unchanged surface is not re-sent every beat."""

    digest: str | None = None
    emitted_at: float = 0.0


def build_inventory_event(now_utc: str, inventory: Any, *, outcome: str) -> dict[str, Any]:
    servers = list(inventory.servers)
    entries = [s.wire_entry() for s in servers[:LIMIT]]
    flagged = sum(1 for e in entries if e["findings"])
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": "",
        "correlation_id": "",
        "timestamp_utc": now_utc,
        **identity_fields(),
        "source_topic": "agentmetry/mcp_inventory",
        "source": {"tier": "agentmetry", "app": "agentmetry", "adapter": "mcp_inventory"},
        "initiator": {"actor_type": "system", "trigger": "scheduled", "operator_id": ""},
        "actor": {"type": "system", "id": "agentmetry", "role": "recorder"},
        "action": {
            "type": "mcp_inventory",
            "outcome": outcome,
            "reason": f"{len(servers)} MCP server(s) configured, {flagged} flagged",
        },
        "agent": {"name": "agentmetry", "skill_id": ""},
        "mcp_inventory": {
            "servers": entries,
            "server_count": len(servers),
            "truncated": len(servers) > LIMIT,
            "config_digest": inventory.digest()[:16] if servers else "",
            "files_read": len(inventory.files_read),
            "files_unreadable": len(inventory.unreadable),
        },
    }


def due(state: InventoryState, digest: str, now_monotonic: float) -> str | None:
    """`snapshot`, `changed`, or None when there is nothing to say."""
    if state.digest is None:
        return "snapshot"
    if digest != state.digest:
        return "changed"
    if now_monotonic - state.emitted_at >= SNAPSHOT_SECONDS:
        return "snapshot"
    return None


async def maybe_emit_inventory(state: InventoryState) -> dict[str, Any] | None:
    """Emit the inventory if the operator turned it on and there is news."""
    if not enabled():
        return None
    from datetime import datetime, timezone

    from agentmetry.core.audit.ingest import _get_sink
    from agentmetry.core.audit.trail_db import get_trail_db
    from agentmetry.core.diagnostics.mcp_inventory import collect

    inventory = collect()
    digest = inventory.digest() if inventory.servers else ""
    now = time.monotonic()
    outcome = due(state, digest, now)
    if outcome is None:
        return None
    event = build_inventory_event(datetime.now(timezone.utc).isoformat(), inventory, outcome=outcome)
    # The heartbeat's durability contract: the local insert is the guarantee,
    # network sinks swallow their own failures.
    get_trail_db().insert(event)
    await _get_sink().emit(event)
    state.digest, state.emitted_at = digest, now
    return event
