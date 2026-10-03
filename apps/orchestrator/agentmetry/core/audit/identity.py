"""Host and fleet identity fields on canonical events."""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable
from functools import lru_cache

from agentmetry.core.config import settings

logger = logging.getLogger(__name__)

#: Returns the identity to stamp for the request being handled, or None to let
#: the next provider, and finally this machine, answer.
IdentityProvider = Callable[[], "dict[str, str] | None"]

_PROVIDERS: list[IdentityProvider] = []


def register_identity_provider(provider: IdentityProvider) -> None:
    """The extension point for who an event is recorded as.

    Agentmetry Enterprise authenticates each ingest request with a per-host token
    and needs the event to record the host the token was issued to, not this
    machine. It used to get that by replacing `identity_fields` in four modules
    that had imported it by name. That works until a fifth call site appears or
    an import moves, and then it fails silently, as mis-attribution. A provider
    registered here is consulted by the one function every call site already
    uses, so there is nothing to patch and nothing to miss.

    Idempotent: registering the same provider twice registers it once.
    """
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def unregister_identity_provider(provider: IdentityProvider) -> None:
    if provider in _PROVIDERS:
        _PROVIDERS.remove(provider)


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

    A registered provider answers first (see `register_identity_provider`). One
    that raises is logged and skipped rather than allowed to fail the event: the
    recorder must keep recording, and the machine's own identity is the honest
    fallback, not a guess.
    """
    for provider in _PROVIDERS:
        try:
            provided = provider()
        except Exception:
            logger.exception("identity provider %r failed; recording this machine", provider)
            continue
        if provided:
            return dict(provided)
    fields = {"host_id": host_id()}
    fleet = fleet_id()
    if fleet:
        fields["fleet_id"] = fleet
    return fields
