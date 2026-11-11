"""Bounded evidence snapshots from the events a live finding actually cites.

No I/O, additional capture, command interpretation or reconstruction from hashes.
These remain reported tool-boundary observations, not OS process evidence.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agentmetry.core.audit.redaction import scrub_secrets

from .models import Detection

MAX_ITEMS = 32
MAX_BYTES = 64 * 1024


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _snapshot(event: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {}
    omitted: list[str] = []
    sanitized: list[str] = []

    def copy(source, target, key, prefix="", limit=512):
        value = source.get(key)
        if not isinstance(value, str) or not value:
            return
        label = f"{prefix}.{key}" if prefix else key
        if len(value) > limit:
            omitted.append(label)
            return
        cleaned = scrub_secrets(value)
        if len(cleaned) > limit:
            omitted.append(label)
            return
        if cleaned != value:
            sanitized.append(label)
        target[key] = cleaned

    for key in ("event_id", "correlation_id", "timestamp_utc"):
        copy(event, item, key)
    for section, keys in (
        ("source", ("app", "adapter")),
        ("action", ("type", "outcome", "reason")),
        ("tool", ("name", "qualified", "server", "command")),
        ("gated_action", ("tool", "server")),
    ):
        source, target = _mapping(event.get(section)), {}
        for key in keys:
            copy(source, target, key, section, 4096 if key in {"command", "reason"} else 512)
        if target:
            item[section] = target

    arguments = _mapping(_mapping(event.get("tool")).get("arguments"))
    selected: dict[str, Any] = {}
    for key in ("file_path", "path", "target_file"):
        copy(arguments, selected, key, "tool.arguments", 2048)
    url = arguments.get("url")
    if isinstance(url, str) and url:
        label = "tool.arguments.url"
        try:
            if len(url) > 2048 or any(c.isspace() or ord(c) < 32 for c in url):
                raise ValueError("invalid URL")
            # Remove userinfo before parsing, including redaction placeholders
            # from canonicalization, which are not valid bracketed hostnames.
            scheme, separator, rest = url.partition("://")
            if not separator:
                raise ValueError("not an absolute URL")
            authority, slash, path = rest.partition("/")
            # A query or fragment can begin before any path slash.
            authority_end = min((i for i, c in enumerate(authority) if c in "?#"), default=len(authority))
            tail = authority[authority_end:] + (slash + path if slash else "")
            authority = authority[:authority_end].rsplit("@", 1)[-1]
            parsed = urlsplit(f"{scheme}://{authority}{tail}")
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("unsupported URL")
            _ = parsed.port  # Reject malformed ports without retaining userinfo.
            cleaned = scrub_secrets(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
            if len(cleaned) > 2048:
                raise ValueError("overlong scrubbed URL")
            selected["url"] = cleaned
            if cleaned != url:
                sanitized.append(label)
        except ValueError:
            omitted.append(label)
    if selected:
        item.setdefault("tool", {})["arguments"] = selected
    if omitted:
        item["omitted_fields"] = omitted
    if sanitized:
        item["sanitized_fields"] = sanitized
    return item


def build_artifacts(
    detection: Detection,
    events: list[dict[str, Any]],
    trigger: dict[str, Any],
    *,
    host_scope: bool = False,
) -> dict[str, Any]:
    """Copy only uniquely identified, in-scope source rows, in reference order."""
    references = list(dict.fromkeys(detection.event_ids))
    index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            index.setdefault(event_id, []).append(event)
    block: dict[str, Any] = {
        "version": 1, "items": [], "referenced_count": len(references),
        "unavailable_count": 0, "omitted_count": 0, "truncated": False,
    }
    for event_id in references:
        candidates = index.get(event_id, [])
        event = candidates[0] if len(candidates) == 1 else None
        if (
            event is None
            or not event_id
            or len(event_id) > 512
            or any(event.get(k) != trigger.get(k) for k in ("host_id", "fleet_id"))
            or (not host_scope and event.get("correlation_id") != detection.correlation_id)
        ):
            block["unavailable_count"] += 1
            continue
        if len(block["items"]) >= MAX_ITEMS:
            block["omitted_count"] += 1
            continue
        item = _snapshot(event)
        block["items"].append(item)
        if len(json.dumps(block).encode("utf-8")) > MAX_BYTES - 128:
            block["items"].pop()
            block["omitted_count"] += 1
    block["truncated"] = bool(block["omitted_count"] or any(i.get("omitted_fields") for i in block["items"]))
    return block
