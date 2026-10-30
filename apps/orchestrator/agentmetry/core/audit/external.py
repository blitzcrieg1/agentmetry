"""Canonical events from external agent adapters (Tier B — Cursor, Claude, etc.)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.identity import identity_fields
from agentmetry.core.audit.hashing import arguments_fingerprint
from agentmetry.core.audit.redaction import scrub_arg_values, scrub_secrets
from agentmetry.core.audit.run_context import (
    actor_from_initiator,
    build_initiator,
    operator_from_payload,
)
from agentmetry.core.config import settings

ExternalApp = Literal[
    "cursor", "claude", "antigravity", "codex", "mcp_proxy",
    "qwen", "kimi", "qoder", "codebuddy", "trae", "crewai", "opensre", "copilot", "zcode",
    "cursor_cloud", "claude_cloud", "grok_build", "grok_bot", "agentmetry",
]

KNOWN_EXTERNAL_APPS = frozenset({
    "cursor", "claude", "antigravity", "codex", "mcp_proxy",
    "qwen", "kimi", "qoder", "codebuddy", "trae", "crewai", "opensre", "copilot", "zcode",
    "cursor_cloud", "claude_cloud", "grok_build", "grok_bot",
})

_ACTION_MAP = {
    "session_start": ("session_start", "success"),
    "session_end": ("session_end", "success"),
    "tool_called": ("tool_called", "success"),
    "tool_denied": ("tool_called", "denied"),
    "tool_failed": ("tool_called", "error"),
    "approval_request": ("approval_request", "pending"),
    "approval_response": ("approval_response", "success"),
    # A deployment tool (an Intune remediation, a LaunchAgent) reinstalled
    # hooks. That changes this machine's configuration; it is not a tool call.
    # Unmapped it was stored as `tool_called`, which tool-sequence rules count.
    "hook_remediation": ("config_change", "success"),
}

#: The only payload fields a remediation notice keeps. Anything session- or
#: tool-shaped a client attached is dropped: it would join the notice to an
#: agent's session, or give a detection a tool to read.
_REMEDIATION_FIELDS = frozenset({
    "event_type", "source_app", "outcome", "reason", "timestamp_utc", "adapter",
    "triggered_by", "initiator", "operator",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_tool(qualified: str) -> tuple[str, str]:
    if "." in qualified:
        driver, name = qualified.split(".", 1)
        return driver, name
    return "", qualified


#: What an agent that is not on the allowlist is recorded as.
UNKNOWN_APP = "unknown"

_CLAIMED_APP_UNSAFE = re.compile(r"[^a-z0-9_.-]")


def _resolve_source_app(raw: Any) -> tuple[str, str]:
    """The app to record, and the name the client claimed when that differs.

    An unlisted name used to be recorded as `cursor`. So an OpenClaw plugin, a
    LangGraph handler or anything else posting to ingest landed in the trail,
    the SIEM and the detections attributed to Cursor: a confident wrong answer
    in a record whose value is that it is right. It is now `unknown`, with the
    claimed name kept beside it, reduced to a short identifier so a client
    cannot write arbitrary text into a field SIEM rules group on.

    A missing name still means Cursor. That default predates `source_app`, and
    hooks installed before it may still post without one.
    """
    source_app = str(raw or "cursor").strip().lower()
    if source_app in KNOWN_EXTERNAL_APPS or source_app == "agentmetry":
        return source_app, ""
    return UNKNOWN_APP, _CLAIMED_APP_UNSAFE.sub("", source_app)[:64]


def build_external_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an adapter payload into canonical v1.1 JSON."""
    source_app, claimed_app = _resolve_source_app(payload.get("source_app"))

    event_type = str(payload.get("event_type") or "tool_called")
    if event_type == "hook_remediation":
        payload = {k: v for k, v in payload.items() if k in _REMEDIATION_FIELDS}
    action_type, default_outcome = _ACTION_MAP.get(event_type, ("tool_called", "success"))
    outcome = str(payload.get("outcome") or default_outcome)
    if event_type == "hook_remediation" and outcome not in ("success", "error"):
        # Anything else is not a confirmed success, and a fleet alerting on
        # failed remediations must not have one hidden by a spelling.
        outcome = "error"
    # Scrubbed and bounded like `command`: a reason is free text from the
    # capture side, and an MCP server's error can echo the request it failed
    # on, bearer token included (audit PUB-04, 2026-10-30). Prefixes the rules
    # read (`inferred:`, `subagent_start:`) survive the scrubber.
    reason = scrub_secrets(str(payload.get("reason") or ""))[:4096]

    correlation_id = str(payload.get("correlation_id") or payload.get("thread_id") or "")
    session_id = str(payload.get("session_id") or "")

    operator = operator_from_payload(payload)
    initiator_raw = payload.get("initiator")
    if isinstance(initiator_raw, dict) and initiator_raw.get("actor_type"):
        initiator = {
            "actor_type": str(initiator_raw.get("actor_type") or "human"),
            "trigger": str(initiator_raw.get("trigger") or "manual"),
            "operator_id": operator[0],
            "operator_source": operator[1],
        }
    else:
        trigger = str(payload.get("triggered_by") or "manual")
        initiator = build_initiator(trigger, operator)

    tool_block = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
    tool_qualified = str(
        tool_block.get("qualified")
        or payload.get("tool_qualified")
        or payload.get("tool_name")
        or ""
    )
    driver_name, tool_name = _split_tool(tool_qualified)

    args = tool_block.get("arguments")
    # A hook that hashed client-side says how; a digest computed here uses the
    # orchestrator's key. Either way the label below records which it was.
    hash_kind = "hmac" if str(tool_block.get("input_hash_alg") or "") == "hmac-sha256" else "hash"
    if tool_block.get("input_hash"):
        input_hash = str(tool_block.get("input_hash"))
    elif isinstance(args, dict):
        input_hash, hash_kind = arguments_fingerprint(args)
    else:
        input_hash = str(payload.get("input_hash") or "")

    skill_id = str(payload.get("skill_id") or payload.get("skill") or "")

    model_raw = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_provider = str(model_raw.get("provider") or source_app)
    model_id = str(model_raw.get("id") or payload.get("model_id") or source_app)

    adapter = str(payload.get("adapter") or f"{source_app}_hook")

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "correlation_id": correlation_id,
        "timestamp_utc": str(payload.get("timestamp_utc") or _utc_now()),
        **identity_fields(),
        "source_topic": f"external/{source_app}/{event_type}",
        "source": {
            "tier": "external",
            "app": source_app,
            "adapter": adapter,
        },
        "initiator": initiator,
        "actor": actor_from_initiator(initiator),
        "action": {
            "type": action_type,
            "outcome": outcome,
            "reason": reason,
        },
        "agent": {
            "name": source_app,
            "skill_id": skill_id,
        },
        "model": {"id": model_id, "provider": model_provider},
    }
    if claimed_app:
        event["source"]["claimed_app"] = claimed_app

    if tool_qualified:
        server = str(tool_block.get("server") or driver_name or source_app)
        command = str(tool_block.get("command") or "").strip()
        redaction = f"{hash_kind}+command" if command else hash_kind
        event["tool"] = {
            "name": tool_name or tool_qualified,
            "qualified": tool_qualified,
            "server": server,
            "input_redaction": redaction,
            "input_hash": input_hash,
            "parameters_redacted": not bool(command) and not isinstance(tool_block.get("arguments"), dict),
        }
        if command:
            event["tool"]["command"] = scrub_secrets(command)[:4096]
        if isinstance(tool_block.get("arguments"), dict):
            event["tool"]["arguments"] = scrub_arg_values(tool_block.get("arguments"))

        # Hook-side command classification labels. In the default hashed-only
        # config these are the ONLY detection signal the command leaves behind.
        traits_raw = tool_block.get("traits")
        if isinstance(traits_raw, list):
            traits = [str(t) for t in traits_raw if t]
            if traits:
                event["tool"]["traits"] = traits

        # Prefer the hook's MITRE mapping: it saw the plaintext command before
        # hashing, so its content upgrade (e.g. a key-file read → T1552) is
        # strictly better informed than a name-only recompute here.
        adapter_mitre = tool_block.get("mitre")
        if isinstance(adapter_mitre, dict) and adapter_mitre.get("tactic_id"):
            event["tool"]["mitre"] = {
                key: str(adapter_mitre.get(key) or "")
                for key in ("tactic_id", "tactic", "technique_id", "technique")
            }
        else:
            from agentmetry.core.audit.canonical import get_mitre_mapping
            # Pass command/args as evidence so a read of a key/secret upgrades to
            # Credential Access (T1552) instead of generic Collection.
            evidence = command or tool_block.get("arguments")
            mitre = get_mitre_mapping(tool_qualified, evidence)
            if mitre:
                event["tool"]["mitre"] = mitre

        # After both branches, so an adapter that supplied its own ATT&CK block
        # gets the ATLAS sibling too rather than only the ones we classified.
        from agentmetry.core.audit.atlas import attach_atlas

        attach_atlas(event["tool"])

    gated = payload.get("gated_action")
    if isinstance(gated, dict) and gated.get("tool"):
        event["gated_action"] = {
            "tool": str(gated.get("tool") or ""),
            "server": str(gated.get("server") or ""),
            "input_hash": str(gated.get("input_hash") or ""),
        }

    # DLP verdict — rule metadata only, never the matched value. The hook scans
    # plaintext before hashing; if we drop the verdict here, a `log`-mode match
    # (the default mode) leaves no trace anywhere and the DLP engine is a no-op.
    dlp = payload.get("dlp")
    if isinstance(dlp, dict) and dlp.get("rule_id"):
        event["dlp"] = {
            "rule_id": str(dlp.get("rule_id") or ""),
            "mode": str(dlp.get("mode") or ""),
            "pattern_type": str(dlp.get("pattern_type") or "regex"),
            "category": str(dlp.get("category") or ""),
            "severity": str(dlp.get("severity") or ""),
            "rule_ids": [str(r) for r in (dlp.get("rule_ids") or []) if r],
        }

    tool_policy = payload.get("tool_policy")
    if isinstance(tool_policy, dict) and tool_policy.get("rule_id"):
        event["tool_policy"] = {
            "rule_id": str(tool_policy.get("rule_id") or ""),
            "action": str(tool_policy.get("action") or ""),
            "mode": str(tool_policy.get("mode") or ""),
            "blocked": bool(tool_policy.get("blocked")),
        }

    if payload.get("seq") is not None:
        event["seq"] = payload["seq"]

    # Policy verdicts annotate; they never rewrite what happened. This event has
    # already executed on the agent's machine, so claiming "denied" here would
    # put a lie in the trail and hide the event from every detection rule that
    # keys on outcome == "success". See core/audit/policy.py.
    if settings.policy_enabled and event["action"]["type"] in ("tool_called", "approval_request"):
        from agentmetry.core.audit.policy import annotate as annotate_policy

        annotate_policy(event)

    return event
