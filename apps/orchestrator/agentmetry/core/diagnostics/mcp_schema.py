"""Fingerprint of what an MCP server told the model, not what the config file says.

`mcp_inventory` hashes the configured command line. That is the right check for
"somebody added a server". It is the wrong check for a rug pull: `postmark-mcp`
spent fifteen clean versions looking identical in `mcp.json`, then changed what
`tools/list` returned. Invariant Labs' tool-poisoning writeup is the same shape.
The payload lives in the description the model is handed, which never appears
in the config file.

This module hashes that description (plus name, schema, annotations). The
heartbeat publishes one digest over every observed server so a SIEM can alert
on the digest moving while `mcp_config_digest` stays still. That conjunction is
the rug-pull signature, and it needs no new detection rule.

## What this will not do

It does not spawn MCP servers. `npx -y` on a five-minute beat would fetch and
run whatever the registry currently serves, which is the attack, performed by
the recorder. Observation happens when a client actually lists tools, today
via `mcp_audit_proxy` intercepting `tools/list`. Until a server has been listed
the digest is empty, which is an honest gap, not a green dashboard.

The fingerprint is a hash. Tool names, descriptions and server names stay on
the machine. A heartbeat that shipped the inventory would be a surveillance
feed, and a trail event that shipped a poisoned description would be storing
the payload.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()

#: Keys that change between calls without changing what the model is told.
_VOLATILE = frozenset({"_meta"})


def _canonical_entries(tools: list[Any] | None) -> list[dict[str, Any]]:
    """Volatile keys dropped, sorted by tool name.

    Split out so the whole-listing hash and the per-tool hashes canonicalise
    identically. If they ever diverged, a tool could move its own digest
    without moving the listing digest, or the reverse, and the pair would stop
    being a diff of the same thing.
    """
    canonical: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        entry = {k: v for k, v in tool.items() if k not in _VOLATILE}
        canonical.append(entry)
    canonical.sort(key=lambda t: str(t.get("name") or ""))
    return canonical


def _blob(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def fingerprint_tools(tools: list[Any] | None) -> str:
    """Stable SHA-256 of a `tools/list` result.

    Order of tools and of object keys must not move the hash: MCP servers do
    not guarantee either. A description edit must, because that is the poison.
    """
    return hashlib.sha256(_blob(_canonical_entries(tools))).hexdigest()


def fingerprint_each_tool(tools: list[Any] | None) -> dict[str, str]:
    """`{tool_id: digest}` for one listing, alongside the whole-listing hash.

    The listing digest answers "did this server change". It cannot answer
    "which tool changed", and that is the first thing an operator asks when
    one fires. Storing the inputs would answer it, and would also mean writing
    a poisoned description into the trail and forwarding it to a SIEM, so the
    answer is a digest per tool instead: enough to name the tool that moved,
    never enough to carry the payload.

    Keyed on a hashed name for the same reason server names are hashed. A tool
    called `internal-payroll-export` is itself information.
    """
    return {
        tool_id(str(entry.get("name") or "")): hashlib.sha256(_blob(entry)).hexdigest()
        for entry in _canonical_entries(tools)
    }


def server_id(name: str) -> str:
    """Opaque 16-hex id for a server name. Publish this, never the name."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def tool_id(name: str) -> str:
    """Opaque 16-hex id for a tool name. Same rule as `server_id`."""
    return hashlib.sha256(f"tool:{name}".encode("utf-8")).hexdigest()[:16]


def tool_delta(previous: dict[str, str], current: dict[str, str]) -> dict[str, Any]:
    """What moved between two per-tool digest maps.

    Counts for added and removed, ids for changed. An id is only meaningful
    against a baseline that still holds it, so listing ids for tools that
    appeared or vanished would name things the reader cannot look up.
    """
    changed = sorted(
        tid for tid, digest in current.items()
        if tid in previous and previous[tid] != digest
    )
    return {
        "changed": changed,
        "added": len([tid for tid in current if tid not in previous]),
        "removed": len([tid for tid in previous if tid not in current]),
    }


def parse_initialize_result(result: Any) -> dict[str, Any]:
    """Handshake fields that help separate releases from rug pulls.

    ``serverInfo.version`` is attacker-controlled but useful as a benign-churn
    handle: digest moved + version moved often means a shipped release; digest
    moved + version stable is the shape worth investigating first.

    ``capabilities.tools.listChanged`` records whether the server promised
    ``notifications/tools/list_changed``; a gap between that promise and a
    silent listing change is only visible if both are captured.
    """
    out: dict[str, Any] = {}
    if not isinstance(result, dict):
        return out
    info = result.get("serverInfo")
    if isinstance(info, dict):
        version = info.get("version")
        if version is not None and str(version).strip():
            out["server_version"] = str(version).strip()
    caps = result.get("capabilities")
    if isinstance(caps, dict):
        tools = caps.get("tools")
        if isinstance(tools, dict) and "listChanged" in tools:
            out["list_changed"] = bool(tools["listChanged"])
    return out


class ToolsListBuffer:
    """Accumulate paginated `tools/list` pages until the cursor is exhausted.

    Fingerprinting page one alone would make page two look like a rug pull.
    `add_page` returns the complete list when listing is done, otherwise None.
    """

    def __init__(self) -> None:
        self._tools: list[Any] = []

    def reset(self) -> None:
        """Discard a partial listing.

        A paginated listing that fails halfway leaves its earlier pages here.
        The client retries from page one, those pages append to the stale ones,
        and the fingerprint over the duplicated list matches nothing: an
        untouched server reads as a rug pull. This signal is only worth having
        because it rarely moves, so a false positive on a dropped page is the
        expensive failure, not the observation we skipped.
        """
        self._tools = []

    def add_page(self, result: Any) -> list[Any] | None:
        if not isinstance(result, dict):
            return None
        page = result.get("tools")
        if isinstance(page, list):
            self._tools.extend(page)
        if result.get("nextCursor"):
            return None
        done = self._tools
        self._tools = []
        return done


@dataclass
class SchemaRecord:
    fingerprint: str
    tool_count: int
    observed_at: str
    previous: str = ""
    source: str = ""
    server_version: str = ""
    list_changed: bool | None = None
    #: `{tool_id: digest}`. Empty on records written before this existed, which
    #: is why a delta against an empty baseline reports nothing changed rather
    #: than reporting every tool as new.
    tool_digests: dict[str, str] = field(default_factory=dict)


@dataclass
class SchemaStore:
    servers: dict[str, SchemaRecord] = field(default_factory=dict)

    def digest(self) -> str:
        """One hash over every observed schema, keyed by hashed server name.

        Including the server id means swapping two servers' schemas still
        moves the digest. Sorting means observation order does not.
        """
        parts = []
        for name, rec in self.servers.items():
            parts.append(f"{server_id(name)}:{rec.fingerprint}")
        parts.sort()
        return hashlib.sha256("".join(parts).encode()).hexdigest()


def store_path() -> Path:
    from agentmetry.core.config import settings

    return Path(settings.audit_export_path).with_name("mcp-schema-fingerprints.json")


def load_store(path: Path | None = None) -> SchemaStore:
    target = path or store_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return SchemaStore()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("MCP schema store unreadable (%s); treating as empty", exc)
        return SchemaStore()
    servers: dict[str, SchemaRecord] = {}
    block = raw.get("servers") if isinstance(raw, dict) else None
    if isinstance(block, dict):
        for name, rec in block.items():
            if not isinstance(rec, dict) or not rec.get("fingerprint"):
                continue
            list_changed = rec.get("list_changed")
            digests = rec.get("tool_digests")
            servers[str(name)] = SchemaRecord(
                fingerprint=str(rec.get("fingerprint") or ""),
                tool_count=int(rec.get("tool_count") or 0),
                observed_at=str(rec.get("observed_at") or ""),
                previous=str(rec.get("previous") or ""),
                source=str(rec.get("source") or ""),
                server_version=str(rec.get("server_version") or ""),
                list_changed=list_changed if isinstance(list_changed, bool) else None,
                tool_digests={
                    str(k): str(v) for k, v in digests.items() if isinstance(v, str)
                }
                if isinstance(digests, dict)
                else {},
            )
    return SchemaStore(servers=servers)


def _dump(store: SchemaStore) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "servers": {
            name: {
                "fingerprint": rec.fingerprint,
                "tool_count": rec.tool_count,
                "observed_at": rec.observed_at,
                "previous": rec.previous,
                "source": rec.source,
                **({"server_version": rec.server_version} if rec.server_version else {}),
                **({"list_changed": rec.list_changed} if rec.list_changed is not None else {}),
                **({"tool_digests": rec.tool_digests} if rec.tool_digests else {}),
            }
            for name, rec in sorted(store.servers.items())
        },
    }


def _write_store(store: SchemaStore, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(_dump(store), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _normalise(server: str, fingerprint: str) -> tuple[str, str]:
    name = (server or "").strip()
    fp = (fingerprint or "").strip().lower()
    if not name or len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        raise ValueError("mcp_schema requires a server name and a 64-hex fingerprint")
    return name, fp


def classify_observation(
    server: str, fingerprint: str, *, tool_count: int = 0, path: Path | None = None
) -> str:
    """`new`, `changed`, or `same`, without writing anything.

    Split out of `record_observation` so a caller can get the verdict, durably
    record it, and only then advance the store. Committing first loses the rug
    pull outright: the fingerprint is on disk, the trail write fails, the next
    observation reads `same`, and no event is ever emitted. The spool does not
    save it either, because the retried payload takes that same `same` branch.
    A duplicate trail event from two racing observers is a far cheaper failure
    than one silently dropped, so this ordering is deliberate.
    """
    name, fp = _normalise(server, fingerprint)
    with _lock:
        existing = load_store(path or store_path()).servers.get(name)
    if existing is None:
        return "new"
    if existing.fingerprint == fp:
        return "same"
    if existing.tool_count == 0 and tool_count > 0:
        # Growing out of an empty baseline is a first sighting, not a move.
        #
        # A registry that intermittently answers with no tools, or a server
        # listed before it finished starting, writes an empty baseline. The
        # next healthy listing then differs from it, and reporting that as
        # `changed` labels a server coming up correctly as a rug pull. This is
        # the same false positive as a 410, arriving through a success.
        #
        # Deliberately one-way. Going from a populated listing to an empty one
        # stays `changed`, because tools actually disappearing is a real event
        # and the whole point of watching.
        return "new"
    return "changed"


def classify_tool_delta(
    server: str, tool_digests: dict[str, str], *, path: Path | None = None
) -> dict[str, Any]:
    """Which tools moved, read without writing.

    Split from `record_observation` for the same reason `classify_observation`
    is: the caller needs the verdict before the store advances, because once
    it advances the previous map is gone and the delta cannot be recovered.

    A server with no stored per-tool map yields an empty delta rather than one
    claiming every tool is new. Records written before this field existed have
    no map, and reporting a whole catalogue as added on first upgrade would
    manufacture exactly the alert this is meant to explain.
    """
    name = (server or "").strip()
    if not name:
        return tool_delta({}, {})
    with _lock:
        existing = load_store(path or store_path()).servers.get(name)
    if existing is None or not existing.tool_digests:
        return tool_delta({}, {})
    return tool_delta(existing.tool_digests, tool_digests)


def record_observation(
    server: str,
    fingerprint: str,
    tool_count: int,
    *,
    source: str = "mcp_proxy",
    server_version: str = "",
    list_changed: bool | None = None,
    tool_digests: dict[str, str] | None = None,
    path: Path | None = None,
    now: str | None = None,
) -> str:
    """Persist an observed fingerprint. Returns `new`, `changed`, or `same`.

    `same` updates the timestamp only, so a SIEM is not flooded with a trail
    event every time an agent reconnects to an unchanged server.
    """
    name, fp = _normalise(server, fingerprint)
    stamp = now or datetime.now(timezone.utc).isoformat()
    target = path or store_path()
    with _lock:
        store = load_store(target)
        existing = store.servers.get(name)
        if existing and existing.fingerprint == fp:
            existing.observed_at = stamp
            existing.tool_count = tool_count
            if server_version:
                existing.server_version = server_version
            if list_changed is not None:
                existing.list_changed = list_changed
            if tool_digests:
                # An unchanged listing backfills the per-tool map for records
                # written before it existed, so the first real change after an
                # upgrade has a baseline to diff against instead of reporting
                # nothing.
                existing.tool_digests = dict(tool_digests)
            _write_store(store, target)
            return "same"
        previous = existing.fingerprint if existing else ""
        store.servers[name] = SchemaRecord(
            fingerprint=fp,
            tool_count=tool_count,
            observed_at=stamp,
            previous=previous,
            source=source,
            server_version=server_version,
            list_changed=list_changed,
            tool_digests=dict(tool_digests or {}),
        )
        _write_store(store, target)
        return "changed" if previous else "new"


def schema_summary_lines(store: SchemaStore | None = None) -> list[str]:
    """Operator-facing overlay for `agentmetry mcp`. Never prints descriptions."""
    store = store if store is not None else load_store()
    if not store.servers:
        return [
            "  schema digest: (none observed; wrap a server with mcp_audit_proxy "
            "to capture tools/list)"
        ]
    lines = [
        f"  schema digest: {store.digest()[:16]} ({len(store.servers)} server(s) observed)"
    ]
    for name, rec in sorted(store.servers.items()):
        extra = f", was {rec.previous[:16]}" if rec.previous else ""
        version = f", v={rec.server_version}" if rec.server_version else ""
        notify = (
            ", listChanged"
            if rec.list_changed
            else (", no listChanged" if rec.list_changed is False else "")
        )
        lines.append(
            f"      schema {name}: {rec.fingerprint[:16]} "
            f"({rec.tool_count} tools{version}{notify}{extra})"
        )
    return lines
