"""MITRE ATLAS mapping for agent-directed adversary behaviour.

Sibling of `core/audit/mitre.py`, not a replacement for it. The split runs along
a boundary ATT&CK cannot express: what the agent does **to the host** is ATT&CK,
and what is done **to or through the agent** is ATLAS.

`cursor.Read` on `~/.aws/credentials` is T1552.001 whether a human, a script or
a coding agent did it, and ATT&CK is the right taxonomy for that. An MCP server
changing its advertised tool schema between calls has no honest ATT&CK id at
all: the nearest is T1195, which describes compromise of a software
distribution channel rather than a running server swapping its tools underneath
the model. ATLAS names that exactly, so this module exists.

Verified against **ATLAS 2026.07, format-version 6.0.0**, the current content
release at the time of writing. Every id, name and tactic below was read out of
`dist/v6/ATLAS-2026.07.yaml` rather than recalled. That matters more than it
sounds: the widely-linked `dist/ATLAS.yaml` is a deprecated 5.6.0 snapshot, and
ATLAS renumbers between releases. Re-verify before adding to this table.

## Two rules this module exists to keep

**Derived, never re-parsed.** The ATLAS technique is chosen from the ATT&CK
mapping `mitre.py` already produced, not by running a second pass over the
evidence. One classifier decides what kind of action occurred, so the two
taxonomies cannot drift into disagreeing about the same event, and the known
false positives (#44, #49) are inherited rather than duplicated. When those are
fixed, this is fixed with them. A second copy of the regex logic would have
grown its own bugs and needed its own fixes.

**Absent unless ATLAS says something ATT&CK cannot.** Every mapping here adds
the claim that an AI agent's tool was the instrument. Where ATLAS offers only a
restatement of what ATT&CK already said, the field stays empty:

  - `AML.T0053 AI Agent Tool Invocation` is deliberately unused. It is true of
    every event this product records, by definition, and a field carrying one
    value everywhere is not a signal, it is decoration that makes a schema look
    thorough.
  - `AML.T0050 Command and Scripting Interpreter` is deliberately unused. It is
    ATLAS's restatement of T1059 with no agent-specific claim attached, so
    emitting it would be exactly the forced mapping this module exists to
    avoid.

The result is a field that is empty on most events and meaningful on the few
where it appears. That is the intended shape, not a gap to be filled later.

## Where it must not go

ATLAS ids never enter ECS `threat.*`. Those fields are ATT&CK-typed in practice,
and an `AML.T****` in `threat.technique.id` would corrupt every customer rollup
that groups by technique without filtering on `threat.framework` first. The
mapping rides in the vendor namespace as `agentmetry.tool.atlas.*`. See
`adapters/ecs.py`.
"""

from __future__ import annotations

import re
from typing import Any

#: The ATLAS content release these mappings were read from. Printed by the CLI
#: and recorded here so a reader can check the table rather than trust it.
ATLAS_VERSION = "2026.07"
ATLAS_FORMAT_VERSION = "6.0.0"

#: The label that names the taxonomy, mirroring ECS `threat.framework`. A
#: consumer holding both blocks must be able to tell them apart without
#: pattern-matching on the id prefix.
ATLAS_FRAMEWORK = "MITRE ATLAS"


def _a(tactic_id: str, tactic: str, technique_id: str, technique: str) -> dict[str, str]:
    """One block shape everywhere: tool calls, mcp_schema, and detections.

    `atlas_version` rides on the block rather than living only in this module.
    ATLAS renumbers between releases, so a consumer holding a two-year-old
    trail needs to know which matrix an id was resolved against to interpret
    it. A version recorded only in source is a version the event does not have.
    """
    return {
        "framework": ATLAS_FRAMEWORK,
        "tactic_id": tactic_id,
        "tactic": tactic,
        "technique_id": technique_id,
        "technique": technique,
        "atlas_version": ATLAS_VERSION,
    }


_CREDENTIAL_HARVESTING = _a(
    "AML.TA0013",
    "Credential Access",
    "AML.T0098",
    "AI Agent Tool Credential Harvesting",
)
_TOOL_EXFILTRATION = _a(
    "AML.TA0010",
    "Exfiltration",
    "AML.T0086",
    "Exfiltration via AI Agent Tool Invocation",
)
_TOOL_DESTRUCTION = _a(
    "AML.TA0011",
    "Impact",
    "AML.T0101",
    "Data Destruction via AI Agent Tool Invocation",
)

#: The rug pull, which is the signal this product was built around. ATLAS files
#: it under Defense Evasion rather than Initial Access, because the point of
#: shipping clean versions first is that scrutiny happens at adoption and not
#: at update. `postmark-mcp` shipped fifteen clean releases before the one that
#: mattered.
RUG_PULL = _a(
    "AML.TA0007",
    "Defense Evasion",
    "AML.T0109",
    "AI Supply Chain Rug Pull",
)

#: ATT&CK technique id -> the ATLAS technique that says something more about it.
#: Keyed on technique rather than tactic because the tactic is too coarse: a
#: read of a private key and a read of a source file share neither.
_FROM_ATTACK: dict[str, dict[str, str]] = {
    "T1552.001": _CREDENTIAL_HARVESTING,  # Credentials In Files
    "T1552.004": _CREDENTIAL_HARVESTING,  # Private Keys
    "T1071.001": _TOOL_EXFILTRATION,  # Web Protocols, the egress half
    "T1485": _TOOL_DESTRUCTION,  # Data Destruction
}


def get_atlas_mapping(mitre: Any) -> dict[str, str] | None:
    """The ATLAS technique for an already-classified tool call, or None.

    Takes the `tool.mitre` block rather than the evidence, deliberately. See the
    module docstring: deriving keeps one classifier of what happened and makes
    the two taxonomies incapable of contradicting each other about one event.

    None is the common answer and the correct one. Most tool calls are a read,
    a grep or a build, and ATLAS has nothing to say about those that ATT&CK has
    not already said better.
    """
    if not isinstance(mitre, dict):
        return None
    technique_id = str(mitre.get("technique_id") or "")
    if not technique_id:
        return None
    return _FROM_ATTACK.get(technique_id)


def attach_atlas(tool: Any) -> None:
    """Add `tool["atlas"]` in place when the call warrants one.

    A no-op when the tool has no ATT&CK mapping, when ATLAS adds nothing, or
    when an adapter already supplied its own. Enrichment must never overwrite
    what a caller asserted: an adapter closer to the source knows more than a
    lookup table does, and silently replacing its answer would make the richer
    integration the less accurate one.
    """
    if not isinstance(tool, dict) or tool.get("atlas"):
        return
    mapping = get_atlas_mapping(tool.get("mitre"))
    if mapping is not None:
        tool["atlas"] = dict(mapping)


# ---------------------------------------------------------------------------
# Detection-level mapping
#
# ATT&CK describes what a tool call did. ATLAS at THIS level describes the
# adversary technique a whole sequence is evidence of, which is a claim only a
# rule can make and never a single call.
#
# Deliberately small. Of the fifteen built-in rules, one describes an ATLAS
# technique; the rest are host and operations behaviour that ATT&CK already
# covers, and tagging them would put an AI-threat label on a shell command.
# The empty entries are the design, not a backlog.
# ---------------------------------------------------------------------------

#: `AML.T0051.001`, whose canonical `name` field is the bare word "Indirect"
#: because ATLAS names sub-techniques relative to their parent. Rendered here
#: with the parent so the string is readable on its own in a SIEM column.
INDIRECT_PROMPT_INJECTION = _a(
    "AML.TA0005",
    "Execution",
    "AML.T0051.001",
    "LLM Prompt Injection: Indirect",
)

#: rule_id -> ATLAS technique. Absent means the rule has no ATLAS meaning, and
#: absent is the common case.
DETECTION_ATLAS: dict[str, dict[str, str]] = {
    # Content arrives from a channel the model did not control, and the agent
    # then acts on it. That sequence is the observable signature of indirect
    # prompt injection: ATLAS describes injection "via a separate data channel
    # ingested by the LLM, such as text or multimedia pulled from databases or
    # websites". The rule cannot prove intent, and neither does the label: it
    # says which technique this is evidence of, not that an adversary exists.
    "untrusted-input-then-risky-action": INDIRECT_PROMPT_INJECTION,
}

#: ATLAS id grammar, for validating analyst-supplied overrides. Four digits,
#: optional three-digit sub-technique.
TECHNIQUE_ID_RE = re.compile(r"^AML\.T\d{4}(\.\d{3})?$")
TACTIC_ID_RE = re.compile(r"^AML\.TA\d{4}$")

#: Mappings declared in the YAML manifest, layered over the table above so an
#: analyst can map their own rule without editing Python. Populated at rule
#: build time; cleared whenever the YAML rules are rebuilt.
_yaml_atlas: dict[str, dict[str, str]] = {}


class AtlasMappingError(ValueError):
    """A YAML rule declared an `atlas` block that is not usable."""


def parse_yaml_atlas(rule_id: str, spec: Any) -> dict[str, str] | None:
    """Validate an analyst-supplied `atlas:` block from the rule manifest.

    Raises rather than dropping the block. A mapping silently discarded because
    of a typo is worse than one that fails loudly: the rule keeps firing, the
    analyst believes it is tagged, and nothing says otherwise until somebody
    queries for a technique id that was never emitted.
    """
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise AtlasMappingError(f"{rule_id}: atlas must be a mapping, got {type(spec).__name__}")

    technique_id = str(spec.get("technique_id") or "").strip()
    if not TECHNIQUE_ID_RE.match(technique_id):
        raise AtlasMappingError(
            f"{rule_id}: atlas.technique_id {technique_id!r} is not an ATLAS id "
            "(expected AML.TXXXX or AML.TXXXX.YYY)"
        )
    tactic_id = str(spec.get("tactic_id") or "").strip()
    if tactic_id and not TACTIC_ID_RE.match(tactic_id):
        raise AtlasMappingError(
            f"{rule_id}: atlas.tactic_id {tactic_id!r} is not an ATLAS tactic id "
            "(expected AML.TAXXXX)"
        )

    return {
        "framework": ATLAS_FRAMEWORK,
        "tactic_id": tactic_id,
        "tactic": str(spec.get("tactic") or "").strip(),
        "technique_id": technique_id,
        "technique": str(spec.get("technique") or "").strip(),
        # The analyst's own pin. They resolved the id against some release, and
        # claiming ours would attribute their mapping to a matrix they may not
        # have read.
        "atlas_version": str(spec.get("atlas_version") or ATLAS_VERSION).strip(),
    }


def reset_yaml_atlas() -> None:
    _yaml_atlas.clear()


def register_yaml_atlas(rule_id: str, mapping: dict[str, str] | None) -> None:
    if mapping is not None:
        _yaml_atlas[rule_id] = mapping


def atlas_for_rule(rule_id: str) -> dict[str, str] | None:
    """The ATLAS block for a firing rule, or None.

    YAML wins over the built-in table: an operator editing their own manifest
    is making a deliberate statement about their environment, and a shipped
    default that silently overrode it would make the override feature a lie.
    """
    if not rule_id:
        return None
    found = _yaml_atlas.get(rule_id) or DETECTION_ATLAS.get(rule_id)
    return dict(found) if found is not None else None
