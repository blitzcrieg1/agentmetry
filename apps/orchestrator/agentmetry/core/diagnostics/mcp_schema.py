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

#: Bump when the bytes fed to the hash change.
#:
#: A stored fingerprint is only comparable to one computed the same way, so a
#: baseline written under an older version is re-baselined rather than reported
#: as a change. Without that, the upgrade that fixes a blind spot hands every
#: existing user a rug-pull alert on the same morning.
#:
#: 1: `_meta` stripped before hashing.
#: 2: `_meta` hashed. See below.
FINGERPRINT_VERSION = 2

#: Keys dropped before hashing, because they change between calls without
#: changing what the model is told.
#:
#: **Empty, and it is meant to stay nearly empty.** It used to hold `_meta`, on
#: the reasonable-sounding grounds that `_meta` is transport bookkeeping. It is
#: not. `_meta` rides on the tool object, reaches clients, and whether it
#: reaches the *model* is client-dependent, which makes it the obvious place to
#: move behaviour-bearing text once descriptions are being watched. Stripping it
#: meant a poisoned listing hashed identically to a clean one: not a weakened
#: signal, an absent one (issue #142).
#:
#: The rules in this project are public on purpose, so its exemptions are public
#: too, and an exemption is a documented bypass.
#:
#: The bar for adding a key here is therefore evidence that it genuinely varies
#: per call on a real server, plus a note saying which server and why. "It looks
#: like metadata" is how the last entry got in.
_VOLATILE: frozenset[str] = frozenset()


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


#: Characters that render as nothing, or reverse rendering order, while still
#: reaching the model. Grouped by category so a finding can say what kind of
#: concealment it is without carrying the text.
#:
#: The TAG block is the one that matters most: U+E0000 to U+E007F mirrors ASCII,
#: so an entire second instruction can be written in it and displayed as an
#: empty string. Research calls the result an approval-view fidelity gap, and
#: the phrase is exact: the human approving a tool reads one string and the
#: model receives another.
#:
#: **Every one of these ranges has a legitimate use**, which the first version
#: of this module denied in a comment that said so in as many words. A reader on
#: r/mcp took it apart within a day of the release being cut:
#:
#:   * TAG characters spell the subdivision flags. Scotland, Wales and England
#:     are emoji tag sequences, a U+1F3F4 base followed by tag letters and a
#:     U+E007F terminator.
#:   * U+200D joins every emoji ZWJ sequence, so a family or a profession emoji
#:     carries one or more.
#:   * U+200C is required Persian and Arabic orthography and is used across
#:     Indic scripts. It is spelling, not decoration, so flagging it penalises
#:     correctly written non-Latin text.
#:   * Bidi isolates are the modern, recommended way to mix scripts, so any
#:     description containing Arabic or Hebrew may legitimately carry them.
#:
#: So the check is contextual rather than range-based. A character counts only
#: when nothing in its surroundings explains it, which keeps the detection
#: (TAG-encoded ASCII is still caught, because it has no flag base in front of
#: it) and drops the false positives.
#:
#: Private Use Area is deliberately absent. It is genuinely used for icon fonts
#: and would fire on legitimate descriptions, and a category that cries wolf
#: costs more than the one case it might catch.

#: Tag characters, and the two that bracket a legitimate emoji tag sequence.
_TAG_RANGE = (0xE0000, 0xE007F)
_TAG_TERMINATOR = 0xE007F
_TAG_BASE = 0x1F3F4  # waving black flag, the only base an emoji tag sequence uses

#: Zero-width and format characters, split by whether context can explain them.
_ZWJ = 0x200D
_ZWNJ = 0x200C

#: The category for characters that are typography rather than evidence.
#:
#: These three were counted as concealment until the reader who found the flag
#: and Persian cases was asked directly whether they had innocent uses. They do,
#: and descriptions imported from formatted documentation carry them:
#:
#:   * U+200B gives a line-break opportunity without a visible space.
#:   * U+00AD is a soft hyphen, an optional hyphenation point.
#:   * U+FEFF is legacy zero-width no-break space. U+2060 is preferred for new
#:     text, and a byte order mark belongs to the input stream rather than to
#:     every description string in it.
#:
#: Unlike ZWJ and ZWNJ there is no neighbouring character that settles the
#: question, so no positional test can clear them. They are reported under their
#: own key instead, so an operator can inspect them without a formatting quirk
#: reading as a poisoned tool. Presence alone is not evidence of anything.
FORMATTING_CATEGORY = "formatting"
_FORMATTING_CONTROLS = frozenset({0x200B, 0xFEFF, 0x00AD})

_BIDI_CONTROLS = frozenset(
    list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))
)

#: Rough pictographic ranges. Only used to decide whether a ZWJ sits between two
#: emoji, so being generous here costs a missed detection in a case that would
#: need an attacker to hide a payload inside an emoji sequence, and being narrow
#: costs a false positive on ordinary text. Generous is the right trade.
_PICTOGRAPHIC = (
    (0x00A9, 0x00AE),
    (0x203C, 0x3299),
    (0x1F000, 0x1FAFF),
    (0xFE0F, 0xFE0F),  # variation selector 16, sits inside ZWJ sequences
    (0x1F3FB, 0x1F3FF),  # skin tone modifiers
)

#: Scripts that use ZWNJ as orthography rather than decoration.
_ZWNJ_SCRIPTS = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
    (0x0900, 0x0DFF),  # Devanagari through Sinhala
    (0x0700, 0x074F),  # Syriac
)

#: Right-to-left scripts. A bidi control in text with none of these has nothing
#: to reorder, which is what makes it unexplained.
_RTL_SCRIPTS = (
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0700, 0x074F),  # Syriac
    (0x0780, 0x07BF),  # Thaana
    (0x07C0, 0x07FF),  # N'Ko
    (0x0800, 0x085F),
    (0xFB1D, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _in(point: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(low <= point <= high for low, high in ranges)


def _explained_tag_indices(points: list[int]) -> set[int]:
    """Indices belonging to a well-formed emoji tag sequence.

    The grammar is narrow: a U+1F3F4 base, one or more tag characters, then a
    U+E007F terminator. Tag characters anywhere else have no other use, so this
    keeps the detection while letting the subdivision flags through.
    """
    explained: set[int] = set()
    i = 0
    while i < len(points):
        if points[i] != _TAG_BASE:
            i += 1
            continue
        j = i + 1
        while j < len(points) and _TAG_RANGE[0] <= points[j] < _TAG_TERMINATOR:
            j += 1
        if j > i + 1 and j < len(points) and points[j] == _TAG_TERMINATOR:
            explained.update(range(i, j + 1))
            i = j + 1
        else:
            i += 1
    return explained


def _neighbour(points: list[int], index: int, step: int) -> int | None:
    """The nearest code point either side, skipping variation selectors."""
    i = index + step
    while 0 <= i < len(points):
        if points[i] != 0xFE0F:
            return points[i]
        i += step
    return None


def _scan_text(text: str, found: dict[str, int]) -> None:
    points = [ord(c) for c in text]
    tag_ok = _explained_tag_indices(points)
    has_rtl = any(_in(p, _RTL_SCRIPTS) for p in points)

    for i, point in enumerate(points):
        if _TAG_RANGE[0] <= point <= _TAG_RANGE[1]:
            if i not in tag_ok:
                found["tag_block"] = found.get("tag_block", 0) + 1
            continue

        if point in _FORMATTING_CONTROLS:
            found[FORMATTING_CATEGORY] = found.get(FORMATTING_CATEGORY, 0) + 1
            continue

        if point == _ZWJ:
            before = _neighbour(points, i, -1)
            after = _neighbour(points, i, 1)
            joins_emoji = (
                before is not None
                and after is not None
                and _in(before, _PICTOGRAPHIC)
                and _in(after, _PICTOGRAPHIC)
            )
            if not joins_emoji:
                found["zero_width"] = found.get("zero_width", 0) + 1
            continue

        if point == _ZWNJ:
            before = _neighbour(points, i, -1)
            after = _neighbour(points, i, 1)
            orthographic = (before is not None and _in(before, _ZWNJ_SCRIPTS)) or (
                after is not None and _in(after, _ZWNJ_SCRIPTS)
            )
            if not orthographic:
                found["zero_width"] = found.get("zero_width", 0) + 1
            continue

        if point in _BIDI_CONTROLS and not has_rtl:
            found["bidi_control"] = found.get("bidi_control", 0) + 1


def _walk_strings(value: Any):
    """Every string anywhere in a tool definition.

    Deliberately not a list of field names. #103 settled that argument for the
    severity split and it applies here for the same reason: an allowlist fails
    open on whatever the spec adds next, and a field nobody has thought about
    yet should default to inspected rather than invisible.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def scan_concealed_text(tools: list[Any] | None) -> dict[str, int]:
    """Counts of unexplained concealed characters, or an empty dict if clean.

    Counts only. Never the text, never which tool, never the surrounding
    string. A finding that carries the payload has stored the payload, which is
    the rule the whole module is built on.

    This catches one narrow class of poisoning on a single observation, which
    the fingerprint cannot do at all. That limit is worth stating precisely,
    because "blind on the first listing" understates it: the fingerprint answers
    "did this move", never "should this have been here". A server hostile at its
    first release that never changed since has a stable digest forever and is
    never flagged by it, at listing one or listing one hundred.

    This check does **not** make a clean listing trustworthy either, first or
    otherwise. An instruction written in ordinary visible text needs none of
    these characters and is invisible here.

    "Unexplained" is doing real work in the first line. Every range here has a
    legitimate use, so context decides: a tag character inside a subdivision
    flag, a ZWJ between two emoji, a ZWNJ next to Persian or Devanagari, and a
    bidi control in text that actually contains a right-to-left script are all
    silent. See the comment above `_TAG_RANGE` for who found that out and how.

    The result carries two grades of finding under different keys. `tag_block`,
    `zero_width` and `bidi_control` are concealment: something is hidden and
    nothing around it explains why. `formatting` is typography that no
    positional test can clear, and on its own it is not evidence of poisoning.
    `build_schema_canonical` keeps them in separate blocks for that reason.
    """
    found: dict[str, int] = {}
    for text in _walk_strings(_canonical_entries(tools)):
        _scan_text(text, found)
    return found


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
    #: Which hashing this fingerprint was computed with. Defaults to 1 because
    #: a record that does not say was written before the field existed.
    fingerprint_version: int = 1


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
                fingerprint_version=int(rec.get("fingerprint_version") or 1),
            )
    return SchemaStore(servers=servers)


def _dump(store: SchemaStore) -> dict[str, Any]:
    return {
        "schema_version": 3,
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
                "fingerprint_version": rec.fingerprint_version,
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
    if existing.fingerprint_version != FINGERPRINT_VERSION:
        # The stored digest was computed over different bytes, so it is not
        # comparable and a mismatch says nothing about the server. Re-baseline
        # instead. Without this, the release that closed the `_meta` blind spot
        # would have reported a rug pull on every server every user had ever
        # observed, on upgrade day, and taught them the alert is noise.
        #
        # `rebaselined` rather than `new`, and the distinction is the whole
        # point (issue #146). `new` says "we had never seen this server". This
        # says "we had a baseline, our hashing changed, and we are trusting
        # whatever the server says today without comparing it to anything".
        #
        # Those carry different evidence. If a server was already poisoned
        # before the upgrade, this observation adopts the poisoned state and an
        # operator reading a quiet week must be able to see that, rather than
        # find a word that also means "nothing has ever been wrong here".
        # Trading a loud false positive for a silent false negative is the
        # worse half of that trade for a recorder.
        return "rebaselined"
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
            existing.fingerprint_version = FINGERPRINT_VERSION
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
            fingerprint_version=FINGERPRINT_VERSION,
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
