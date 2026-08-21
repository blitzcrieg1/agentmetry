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
installed, the MCP configuration digest, the MCP schema digest, how deep the
spool is, where the trail head sits. Each is a fact a SIEM can alert on changing,
and none of them discloses what the developer is working on.

There are two MCP digests because they catch different lies. `mcp_config_digest`
commits to the configured command line, so a fleet can detect "somebody added an
MCP server on that laptop" without shipping anybody's tool inventory to the SOC.
`mcp_schema_digest` commits to the `tools/list` the model was actually handed.
A rug pull (Invariant Labs, `postmark-mcp`) leaves the config file identical and
changes the description. The SIEM rule is then: schema digest moved, config
digest did not. Schema change does not degrade the beat; hook removal does.
A digest that flipped because a legitimate tool was added looks the same, and
that is a fact the operator investigates rather than a finding the recorder
pretends to adjudicate.

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

from agentmetry.core.audit.canonical import SCHEMA_VERSION
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


def _hook_facts() -> dict[str, Any]:
    """Coverage for every agent surface, read from disk every beat.

    This used to check two paths while six installers and nine ingest mappings
    existed, so a machine running Codex or Qwen unrecorded still beat green. The
    registry now lives in core/diagnostics/hook_coverage.py and doctor reads the
    same one, because two copies of this list is how it drifted the first time.
    """
    from agentmetry.core.diagnostics import hook_coverage

    states = hook_coverage.coverage()
    return {
        "hooks": hook_coverage.hook_flags(states),
        "hook_coverage": states,
        "hooks_uncovered": hook_coverage.uncovered(states),
        "hooks_unverified": hook_coverage.unverified(states),
        "hook_profile": "service" if hook_coverage.is_service_profile() else "user",
    }


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


def _mcp_schema_facts() -> tuple[str, int]:
    """Commits to observed `tools/list` results, not to the config file.

    Empty when nothing has been listed yet. That is the honest state, not a
    healthy default: we refuse to spawn servers from the beat, so we can only
    hash what a client already asked for.
    """
    try:
        from agentmetry.core.diagnostics.mcp_schema import load_store

        store = load_store()
        if not store.servers:
            return "", 0
        return store.digest()[:16], len(store.servers)
    except Exception:
        return "", 0


def trail_root() -> tuple[str, int]:
    """The RFC 6962 Merkle root over the trail as it stands, and its tree size.

    This is what makes "the record already in your SIEM cannot be rewritten"
    true rather than aspirational. The adapters forward canonical events and not
    the chain envelope, so before this the customer's index held a copy of the
    events with nothing to verify them against. A periodic root changes that: it
    lands in the SIEM, outside the audited machine's blast radius, and any later
    edit below that tree size produces a root that no longer matches a value the
    machine can no longer reach.

    Cost is O(n) in trail length, measured at 646ms over 17,480 records, which is
    a 0.2% duty cycle at the default 300s beat. That ratio degrades as a trail
    grows and is the reason this is computed off the event loop. A machine with a
    million-record trail should rotate it or lengthen the interval; the honest
    limit is worth stating rather than discovering.
    """
    try:
        from pathlib import Path as _Path

        from agentmetry.core.audit.trail_merkle import merkle_root
        from agentmetry.core.config import settings

        return merkle_root(_Path(settings.audit_export_path))
    except Exception:
        return "", 0


def attestation(root: tuple[str, int] | None = None) -> dict[str, Any]:
    """The facts a SIEM can alert on changing.

    `root` is passed in rather than computed here so the caller can keep an O(n)
    hash off the event loop. Omitted, the attestation is still valid and simply
    carries no root, which is the correct degradation: a heartbeat without a root
    is less useful than one with it and considerably more useful than none.
    """
    merkle, tree_size = root if root is not None else ("", 0)
    schema_digest, schema_servers = _mcp_schema_facts()
    return {
        **_hook_facts(),
        "spool_depth": _spool_depth(),
        "trail_head_seq": _trail_head(),
        "trail_merkle_root": merkle,
        "trail_tree_size": tree_size,
        "mcp_config_digest": _mcp_digest(),
        "mcp_schema_digest": schema_digest,
        "mcp_schema_servers": schema_servers,
        "interval_seconds": interval_seconds(),
    }


def build_heartbeat_event(now_utc: str, root: tuple[str, int] | None = None) -> dict[str, Any]:
    """A canonical event, so the heartbeat reaches every sink the trail reaches.

    `action.outcome` is `degraded` when any hook is missing, so a SIEM can alert
    on `action.type:heartbeat AND action.outcome:degraded` without knowing
    anything about Agentmetry's internals. That matters: a detection a customer
    has to learn a vocabulary to write is a detection they do not write.
    """
    facts = attestation(root)
    uncovered = facts["hooks_uncovered"]
    service_profile = facts["hook_profile"] == "service"
    # `degraded` is a definite claim that capture is impaired, so only definite
    # facts set it. An agent that is not installed here is not a missing hook,
    # and the old `not all(hooks.values())` made every machine without Claude
    # Code degrade forever, which is how a fleet learns to ignore the signal.
    # A service profile does set it: from there no developer's configuration is
    # visible at all, so a confident green would be the worst of the answers.
    degraded = bool(uncovered) or facts["spool_depth"] > 0 or service_profile

    reason = "recorder attesting"
    if service_profile:
        reason = (
            "recorder attesting from a service profile; no developer hook "
            "configuration is visible from here, so coverage is unknown"
        )
    elif uncovered:
        reason = f"recorder attesting; agents present but NOT recorded: {', '.join(uncovered)}"
    elif facts["spool_depth"] > 0:
        reason = f"recorder attesting; {facts['spool_depth']} event(s) buffered in the spool"
    if facts["hooks_unverified"] and not service_profile:
        # Never coverage, never silent. Codex went missing from the attestation
        # for exactly as long as nothing said its name.
        reason += f" (unverifiable: {', '.join(facts['hooks_unverified'])})"

    return {
        "schema_version": SCHEMA_VERSION,
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
    import asyncio
    from datetime import datetime, timezone

    from agentmetry.core.audit.ingest import _get_sink
    from agentmetry.core.audit.trail_db import get_trail_db

    now = datetime.now(timezone.utc).isoformat()
    # Off the event loop: the root is O(n) in trail length and the recorder must
    # stay responsive to ingest while it hashes.
    root = await asyncio.to_thread(trail_root)
    event = build_heartbeat_event(now, root)
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
