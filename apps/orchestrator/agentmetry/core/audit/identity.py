"""Host and fleet identity fields on canonical events."""

from __future__ import annotations

import socket
from functools import lru_cache

from agentmetry.core.config import settings


@lru_cache(maxsize=1)
def host_id() -> str:
    """The machine name, resolved once.

    This sits in the hot path: every canonical event calls it, and a busy
    developer produces on the order of a thousand a day. A hostname does not
    change under a running process, so resolving it per event buys nothing and
    costs a syscall.
    """
    return socket.gethostname()


def fleet_id() -> str:
    return settings.fleet_id.strip()


def identity_fields() -> dict[str, str]:
    """Top-level host/fleet keys every canonical event carries.

    `fleet_id` is omitted rather than emitted empty when unset. An empty string
    on every event is noise in the trail and a trap in a SIEM, where
    `fleet_id="*"` then matches unconfigured hosts and a `fleet_id!=""` filter
    is needed to exclude them. Absent means absent.
    """
    fields = {"host_id": host_id()}
    fleet = fleet_id()
    if fleet:
        fields["fleet_id"] = fleet
    return fields
