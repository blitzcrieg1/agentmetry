"""Host and fleet identity fields on canonical events."""

from __future__ import annotations

import socket

from core.config import settings


def host_id() -> str:
    return socket.gethostname()


def fleet_id() -> str:
    return settings.fleet_id.strip()


def identity_fields() -> dict[str, str]:
    """Top-level host/fleet keys every canonical event carries."""
    return {"host_id": host_id(), "fleet_id": fleet_id()}
