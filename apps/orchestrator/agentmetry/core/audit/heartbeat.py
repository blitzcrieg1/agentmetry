"""Periodic attestation that the recorder is running, and what it is recording with.

A hook lives in a file a developer owns. `.cursor/hooks.json` can be deleted,
`claude --no-hooks` skips it, and the orchestrator can be stopped. No user-space
recorder can prevent that, and any vendor claiming otherwise is either shipping a
kernel driver or overstating.

So the goal is not to make bypass impossible. It is to make bypass **loud**.

The naive version of that idea does not work. "Alert when a machine stops sending
events" cannot distinguish a removed hook from a developer who spent the afternoon
in meetings, because an idle recorder and a disabled recorder both emit nothing.
Silence is not evidence.

A heartbeat fixes that by making the *absence* meaningful: the recorder says "I am
here" on a fixed interval whether or not anybody is coding. Two failure modes then
become separable in a SIEM with no agent-side enforcement at all:

* the orchestrator is stopped or the machine is off, and heartbeats stop;
* the orchestrator runs but a hook was removed, and heartbeats continue with
  `hooks.cursor` flipped to false.

The second is the one worth having. A liveness ping alone would keep saying
"healthy" for a machine that had quietly stopped recording its agents, which is
precisely the state an insider wants and precisely the state a green dashboard
would hide.

## Why it carries configuration and not just a timestamp

The heartbeat is an attestation of what the recorder is wired to: which hooks are
installed, the MCP configuration digest, how deep the spool is, where the trail
head sits. Each is a fact a SIEM can alert on changing, and none of them discloses
what the developer is working on. The MCP digest in particular commits to the
whole configured server surface without naming a single server, so a fleet can
detect "somebody added an MCP server on that laptop" without shipping anybody's
tool inventory to the SOC.

## What this is not

It is not tamper *resistance*. Someone who stops the orchestrator stops the
heartbeat too, and someone with enough access can forge one. It converts a silent
failure into a visible one, which is a smaller claim than prevention and the
largest claim this architecture can honestly make.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from agentmetry.core.audit.identity import identity_fields

logger = logging.getLogger(__name__)

#: How often to attest. Short enough that a SIEM can alert on two missed beats
#: inside a coffee break, long enough that a fleet of a thousand machines adds
#: roughly one event per developer per five minutes to the customer's ingest bill.
DEFAULT_INTERVAL_SECONDS = 300


def interval_seconds() -> int:
    raw = os.environ.get("AGENTMETRY_HEARTBEAT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS
    # A zero or negative interval disables the beat rather than busy-looping.
    return value if value > 0 else 0


def _hook_status() -> dict[str, bool]:
    """Which IDE hooks are installed right now, read from disk every beat.

    Deliberately re-read rather than cached from boot. A hook removed at 11am
    must show up in the 11:05 heartbeat; a value captured at startup would keep
    asserting the configuration the machine had when it last rebooted, which is
    the exact lie this feature exists to prevent.
    """
    targets = {
        "cursor": Path.home() / ".cursor" / "hooks.json",
        "claude": Path.home() / ".claude" / "settings.json",
    }
    status: dict[str, bool] = {}
    for name, path in targets.items():
        try:
            status[name] = path.is_file() and "agentmetry_ingest" in path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            status[name] = False
    return status


def _spool_depth() -> int:
    """Events buffered and not yet in the trail. Nonzero for long means capture
    is reaching the hook but not the trail, which is its own kind of blind."""
    try:
        from agentmetry.core.config import settings

        spool = Path(settings.audit_export_path).with_name("hook-spool.jsonl")
        if not spool.is_file():
            return 0
        with spool.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())
    except Exception:
        return -1


def _trail_head() -> int:
    try:
        from agentmetry.core.audit.trail_chain import load_chain_head
        from agentmetry.core.config import settings

        return int(load_chain_head(Path(settings.audit_export_path)).seq)
    except Exception:
        return -1


def _mcp_digest() -> str:
    """Commits to the configured MCP surface without naming a server."""
    try:
        from agentmetry.core.diagnostics.mcp_inventory import collect

        inv = collect()
        return inv.digest()[:16] if inv.servers else ""
    except Exception:
        return ""


def attestation() -> dict[str, Any]:
    """The facts a SIEM can alert on changing."""
    return {
        "hooks": _hook_status(),
        "spool_depth": _spool_depth(),
        "trail_head_seq": _trail_head(),
        "mcp_config_digest": _mcp_digest(),
        "interval_seconds": interval_seconds(),
    }


def build_heartbeat_event(now_utc: str) -> dict[str, Any]:
    """A canonical event, so the heartbeat reaches every sink the trail reaches.

    `action.outcome` is `degraded` when any hook is missing, so a SIEM can alert
    on `action.type:heartbeat AND action.outcome:degraded` without knowing
    anything about Agentmetry's internals. That matters: a detection a customer
    has to learn a vocabulary to write is a detection they do not write.
    """
    facts = attestation()
    hooks = facts["hooks"]
    degraded = not all(hooks.values()) or facts["spool_depth"] > 0
    missing = sorted(name for name, ok in hooks.items() if not ok)

    reason = "recorder attesting"
    if missing:
        reason = f"recorder attesting; hooks NOT installed for: {', '.join(missing)}"
    elif facts["spool_depth"] > 0:
        reason = f"recorder attesting; {facts['spool_depth']} event(s) buffered in the spool"

    return {
        "schema_version": "1.1.0",
        "event_id": str(uuid.uuid4()),
        "session_id": "",
        "correlation_id": "",
        "timestamp_utc": now_utc,
        **identity_fields(),
        "source_topic": "agentmetry/heartbeat",
        "source": {"tier": "agentmetry", "app": "agentmetry", "adapter": "heartbeat"},
        "initiator": {"actor_type": "system", "trigger": "scheduled", "operator_id": ""},
        "actor": {"type": "system", "id": "agentmetry", "role": "recorder"},
        "action": {
            "type": "heartbeat",
            "outcome": "degraded" if degraded else "success",
            "reason": reason,
        },
        "agent": {"name": "agentmetry", "skill_id": ""},
        "heartbeat": facts,
    }


# ----------------------------------------------------------------------
# The loop
# ----------------------------------------------------------------------


async def emit_heartbeat() -> dict[str, Any] | None:
    """Write one attestation to the trail and forward it to every sink."""
    from datetime import datetime, timezone

    from agentmetry.core.audit.ingest import _get_sink
    from agentmetry.core.audit.trail_db import get_trail_db

    now = datetime.now(timezone.utc).isoformat()
    event = build_heartbeat_event(now)
    # Same durability contract as a detection: the local trail insert is the
    # guarantee and raises on failure, while network sinks swallow their own
    # errors so a down SIEM cannot stop the recorder attesting locally.
    get_trail_db().insert(event)
    await _get_sink().emit(event)
    return event


async def heartbeat_forever(interval: float | None = None) -> None:
    """Attest on a fixed interval for as long as the recorder runs.

    Beats on start rather than after the first sleep. A recorder that comes back
    from a reboot and says nothing for five minutes looks, to a SIEM watching for
    absence, exactly like one that never came back.
    """
    import asyncio

    period = interval if interval is not None else interval_seconds()
    if not period:
        logger.info("Heartbeat disabled (AGENTMETRY_HEARTBEAT_SECONDS=0)")
        return

    while True:
        try:
            event = await emit_heartbeat()
            if event and event["action"]["outcome"] == "degraded":
                logger.warning("Heartbeat degraded: %s", event["action"]["reason"])
        except Exception:
            # Never let attestation kill the recorder it attests for.
            logger.exception("Heartbeat failed")
        await asyncio.sleep(period)
