"""Agent posture as an event a SIEM can see, when an operator asks.

`agentmetry posture` answers "which agents here skip approval or have hooks
off", for whoever runs it on that machine. A fleet wants the same answer in the
SIEM, by host, and wants to know the day it changed.

Same contract as the MCP inventory event (`mcp_inventory_event`): off unless
`AGENTMETRY_POSTURE=1`, emitted when the recorder starts, when the findings
change and once a day regardless, written to the trail first and then to every
sink. Each finding is agent, scope label, setting, value and severity: no file
path, so no home directory or username leaves the machine.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.identity import identity_fields

#: Re-emit an unchanged posture this often, so a fleet view over a day is whole.
SNAPSHOT_SECONDS = 24 * 3600


def enabled() -> bool:
    from agentmetry.core.config import settings

    return bool(getattr(settings, "posture_enabled", False))


@dataclass
class PostureState:
    digest: str | None = None
    emitted_at: float = 0.0


def build_posture_event(now_utc: str, posture: Any, *, outcome: str) -> dict[str, Any]:
    from agentmetry.core.diagnostics.posture import NOT_CHECKED

    findings = [f.wire() for f in posture.sorted()]
    counts = posture.counts()
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": "",
        "correlation_id": "",
        "timestamp_utc": now_utc,
        **identity_fields(),
        "source_topic": "agentmetry/posture",
        "source": {"tier": "agentmetry", "app": "agentmetry", "adapter": "posture"},
        "initiator": {"actor_type": "system", "trigger": "scheduled", "operator_id": ""},
        "actor": {"type": "system", "id": "agentmetry", "role": "recorder"},
        "action": {
            "type": "posture",
            "outcome": outcome,
            "reason": f"{counts['high']} high, {counts['medium']} medium, {counts['low']} low",
        },
        "agent": {"name": "agentmetry", "skill_id": ""},
        "posture": {
            "findings": findings,
            "counts": counts,
            "digest": posture.digest()[:16],
            "files_read": len(posture.files_read),
            "files_unreadable": len(posture.unreadable),
            "not_checked": sorted(NOT_CHECKED),
        },
    }


def due(state: PostureState, digest: str, now_monotonic: float) -> str | None:
    """`snapshot`, `changed`, or None when there is nothing to say."""
    if state.digest is None:
        return "snapshot"
    if digest != state.digest:
        return "changed"
    if now_monotonic - state.emitted_at >= SNAPSHOT_SECONDS:
        return "snapshot"
    return None


async def maybe_emit_posture(state: PostureState) -> dict[str, Any] | None:
    """Emit the posture if the operator turned it on and there is news."""
    if not enabled():
        return None
    from datetime import datetime, timezone

    from agentmetry.core.audit.ingest import _get_sink
    from agentmetry.core.audit.trail_db import get_trail_db
    from agentmetry.core.diagnostics.posture import collect

    posture = collect()
    digest = posture.digest()
    now = time.monotonic()
    outcome = due(state, digest, now)
    if outcome is None:
        return None
    event = build_posture_event(datetime.now(timezone.utc).isoformat(), posture, outcome=outcome)
    get_trail_db().insert(event)
    await _get_sink().emit(event)
    state.digest, state.emitted_at = digest, now
    return event
