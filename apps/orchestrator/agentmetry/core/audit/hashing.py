"""Canonical hashing for tool arguments and audit payloads."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def arguments_sha256(arguments: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(arguments))


def _fleet_key() -> bytes:
    from agentmetry.core.config import settings

    return settings.hash_key.strip().encode("utf-8")


def fingerprint(data: str | bytes) -> tuple[str, str]:
    """A digest of tool input, and the `input_redaction` stem that names it.

    HMAC-SHA256 under AGENTMETRY_HASH_KEY when one is set ("hmac"), plain
    SHA-256 otherwise ("hash"). Both are 64 hex characters, so every consumer
    that compares or stores `input_hash` is unchanged; the label says which.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    key = _fleet_key()
    if key:
        return hmac.new(key, data, hashlib.sha256).hexdigest(), "hmac"
    return hashlib.sha256(data).hexdigest(), "hash"


def arguments_fingerprint(arguments: dict[str, Any]) -> tuple[str, str]:
    return fingerprint(canonical_json(arguments))
