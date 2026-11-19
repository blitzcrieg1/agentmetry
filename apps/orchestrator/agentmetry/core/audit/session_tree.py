"""One session as the nodes of an investigation tree.

Claude requests and reported results retain their own nodes and event IDs.
Only an unambiguous native invocation links those observations. Permission
responses remain separate when the source supplies no invocation ID for them.

Legacy adapters can fold an ask, answer and call into one node with all their
event IDs when there is one pending ask for the hash in the source session.
Cursor asks as `cursor.Shell` and runs as `shell.run`, with the same input hash.
An ask with no call stays visible on its own.

Nothing here reads command text the trail does not already hold. `command` is
present only when the operator set `AGENTMETRY_LOG_COMMANDS`.
"""

from __future__ import annotations

from typing import Any

from agentmetry.core.audit.invocation import normalize_claude_tool_metadata

#: Long enough for a real shell line, short enough that one pasted script does
#: not make the payload the size of the session.
COMMAND_LIMIT = 4000
REASON_LIMIT = 400

_LIFECYCLE = {"session_start", "session_end", "config_change"}


def _tool(event: dict[str, Any]) -> dict[str, Any]:
    tool = event.get("tool") or {}
    out = {
        "qualified": str(tool.get("qualified") or tool.get("name") or ""),
        "name": str(tool.get("name") or ""),
        "server": str(tool.get("server") or ""),
        "input_hash": str(tool.get("input_hash") or ""),
    }
    command = tool.get("command")
    if isinstance(command, str) and command:
        out["command"] = command[:COMMAND_LIMIT]
        if len(command) > COMMAND_LIMIT:
            out["command_truncated"] = True
    mitre = tool.get("mitre")
    if isinstance(mitre, dict) and mitre.get("technique_id"):
        out["mitre"] = {
            k: str(mitre.get(k) or "")
            for k in ("technique_id", "technique", "tactic_id", "tactic")
        }
    return out


def _kind(event: dict[str, Any]) -> str:
    action = (event.get("action") or {}).get("type", "")
    if action == "tool_called":
        reason = str((event.get("action") or {}).get("reason") or "")
        if reason.startswith("subagent_start:"):
            return "subagent_start"
        if reason.startswith("subagent_stop:"):
            return "subagent_stop"
        return "call"
    if action == "approval_request":
        return "ask"
    if action in _LIFECYCLE or action == "detection":
        return action
    return action or "event"


def _node(event: dict[str, Any], kind: str) -> dict[str, Any]:
    action = event.get("action") or {}
    source = event.get("source") or {}
    node: dict[str, Any] = {
        "id": str(event.get("event_id") or ""),
        "event_ids": [str(event.get("event_id") or "")],
        "kind": kind,
        "timestamp_utc": str(event.get("timestamp_utc") or ""),
        "outcome": str(action.get("outcome") or ""),
        "reason": str(action.get("reason") or "")[:REASON_LIMIT],
        "app": str(source.get("app") or (event.get("agent") or {}).get("name") or ""),
        "adapter": str(source.get("adapter") or ""),
        "tool": _tool(event),
        "approval": None,
    }
    for key in ("dlp", "tool_policy"):
        if isinstance(event.get(key), dict):
            node[key] = event[key]
    if kind == "detection":
        det = event.get("detection") or {}
        node["detection"] = {
            k: det.get(k)
            for k in ("rule_id", "title", "severity", "event_ids", "technique_ids", "tactic_ids")
        }
    if kind == "ask":
        node["approval"] = "asked"
    return node


def _answer(event: dict[str, Any]) -> str:
    """What the answer to an ask says, without promoting an inference to a decision.

    Nearly every `denied` answer in a real trail is `inferred:session_ended_pending`:
    the session ended with the ask still open, and the recorder closed it. Nobody
    refused anything, so it is `expired`, not `denied`, and the tree does not
    draw it as a refusal.
    """
    action = event.get("action") or {}
    inferred = str(action.get("reason") or "").startswith("inferred:")
    if action.get("outcome") == "denied":
        return "expired" if inferred else "denied"
    return "inferred" if inferred else "approved"


def _invocation_key(event: dict[str, Any], tool: dict[str, Any]) -> tuple[str, ...] | None:
    # The tree reads one recorder's local index. The host and correlation ID
    # constrain this comparison further and do not establish device identity.
    source = event["source"]
    key = (
        event.get("host_id"), event.get("correlation_id"), event.get("session_id"),
        source.get("app"), source.get("adapter"), tool["qualified"], tool["server"],
        tool["invocation"].get("id"),
    )
    return key if all(isinstance(part, str) and part for part in key) else None


def _link_invocations(groups: dict[tuple[str, ...], list[dict[str, Any]]]) -> None:
    for group in groups.values():
        if len(group) == 1:
            continue
        by_phase = {node["tool"]["invocation"]["phase"]: node["id"] for node in group}
        request_id = by_phase.get("request")
        result_id = by_phase.get("result")
        if len(group) == 2 and request_id and result_id and request_id != result_id:
            evidence = {
                "status": "linked",
                "request_event_id": request_id,
                "result_event_id": result_id,
            }
        else:
            evidence = {"status": "ambiguous"}
        for node in group:
            node["invocation_evidence"] = evidence.copy()


def fold(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project a session window and link the evidence available within it."""
    nodes: list[dict[str, Any]] = []
    invocations: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    pending: dict[tuple[str, ...], dict[str, Any] | None] = {}
    for event in events:
        action = (event.get("action") or {}).get("type", "")
        if action == "heartbeat":
            continue
        kind = _kind(event)
        node = _node(event, kind)
        source = event.get("source") or {}
        if source.get("app") == "claude":
            if source.get("adapter") == "claude_hook" and action in ("approval_request", "tool_called"):
                metadata = normalize_claude_tool_metadata(event.get("tool"))
                phase = "request" if action == "approval_request" else "result"
                if metadata and metadata["invocation"]["phase"] == phase:
                    node["tool"].update(metadata)
                    node["invocation_evidence"] = {"status": "unresolved"}
                    key = _invocation_key(event, node["tool"])
                    if key is not None:
                        invocations.setdefault(key, []).append(node)
            if action == "approval_response":
                node["approval"] = _answer(event)
            nodes.append(node)
            continue

        input_hash = (event.get("gated_action") or {}).get("input_hash") if action == "approval_response" else (
            node["tool"]["input_hash"]
        )
        scope = (
            str(event.get("host_id") or ""), str(event.get("correlation_id") or ""), node["app"], str(input_hash or ""),
        )
        if action == "approval_response":
            ask = pending.get(scope)
            if ask is None:
                if scope in pending:  # two asks for the same hash leave the answer unlinked
                    node["approval"] = _answer(event)
                    nodes.append(node)
                continue
            ask["approval"] = _answer(event)
            ask["event_ids"].extend(node["event_ids"])
            if ask["approval"] in ("denied", "expired"):
                if ask["approval"] == "denied":
                    ask["kind"] = "denied"
                pending.pop(scope)
            continue
        if kind == "call":
            ask = pending.get(scope)
            if ask is not None:
                pending.pop(scope)
                ask["kind"] = "call"
                ask["event_ids"].extend(node["event_ids"])
                ask["outcome"] = node["outcome"]
                ask["reason"] = node["reason"] or ask["reason"]
                ask["asked_as"] = ask["tool"]["qualified"]
                merged_tool = node["tool"]
                # The ask may hold the command when the call does not, or the
                # other way round; keep whichever was recorded.
                if "command" not in merged_tool and "command" in ask["tool"]:
                    merged_tool["command"] = ask["tool"]["command"]
                if "mitre" not in merged_tool and "mitre" in ask["tool"]:
                    merged_tool["mitre"] = ask["tool"]["mitre"]
                ask["tool"] = merged_tool
                for key in ("dlp", "tool_policy"):
                    if key in node and key not in ask:
                        ask[key] = node[key]
                ask["id"] = node["id"]
                continue
        nodes.append(node)
        if kind == "ask" and input_hash:
            # A collision stays ambiguous for the rest of this session window.
            pending[scope] = None if scope in pending else node
    _link_invocations(invocations)
    return nodes


def session_tree(correlation_id: str, limit: int = 20000, around_utc: str = "") -> dict[str, Any]:
    """The `/audit/session/{id}/tree` payload.

    `truncated` means the nodes are a window of the session, not all of it:
    the oldest `limit` events, or with `around_utc` the ones either side of it.
    """
    from agentmetry.core.audit.trail_db import get_trail_db

    events, summary = get_trail_db().session_tree_events(
        correlation_id, limit=limit, around_utc=around_utc
    )
    nodes = fold(events)
    hosts = sorted({str(e.get("host_id") or "") for e in events if e.get("host_id")})
    apps = sorted({n["app"] for n in nodes if n["app"]})
    return {
        "correlation_id": correlation_id,
        "enabled": True,
        "summary": {**summary, "hosts": hosts, "apps": apps},
        "nodes": nodes,
        "truncated": len(events) >= limit,
    }
