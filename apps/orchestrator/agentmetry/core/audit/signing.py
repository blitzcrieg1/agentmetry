"""Event signing extension point (pilot hardening item 24).

The core does no cryptography and takes no dependency for it. An extension
(Agentmetry Enterprise holds the per-host Ed25519 key) registers a signer, and
the batched webhook forwarder sends each event as `{"event": ..., "signature":
...}` instead of the bare event. The event itself, and the trail, are
unchanged: the signature travels beside the record, never inside it.

What is signed is `signing_message(event)`: a domain-separation prefix and the
same canonical JSON the hash chain uses (`trail_chain.canonical_event_json`).
Anyone with the host's public key can therefore verify an event offline, from
nothing but the event as stored.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agentmetry.core.audit.trail_chain import canonical_event_json

logger = logging.getLogger(__name__)

SIGNING_DOMAIN = b"agentmetry-event-v1\n"

Signer = Callable[[dict[str, Any]], dict[str, Any]]
_SIGNER: Signer | None = None


def signing_message(event: dict[str, Any]) -> bytes:
    return SIGNING_DOMAIN + canonical_event_json(event).encode("utf-8")


def register_event_signer(signer: Signer) -> None:
    global _SIGNER
    _SIGNER = signer


def unregister_event_signer() -> None:
    global _SIGNER
    _SIGNER = None


def signature_for(event: dict[str, Any]) -> dict[str, Any] | None:
    """The registered signer's signature, or None (no signer, or it failed).

    A failure sends the event unsigned rather than not at all. A receiver that
    requires signatures refuses it, the forwarder retries, and the event waits
    in the trail: loud, and nothing lost.
    """
    if _SIGNER is None:
        return None
    try:
        return _SIGNER(event)
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("Event signer failed; sending event %s unsigned", event.get("event_id", "?"))
        return None


def wrap_for_batch(event: dict[str, Any]) -> dict[str, Any]:
    signature = signature_for(event)
    return {"event": event, "signature": signature} if signature else event
