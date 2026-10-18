"""One session as the nodes of an investigation tree.

A hook records a tool call as up to three events: the agent asking
(`approval_request`), the answer (`approval_response`) and the call itself
(`tool_called`). A detection may cite any of them, and the DLP and tool policy
verdicts sit on the ask, not the call. Drawn one event per node, a session
shows every call two or three times and splits each verdict from the call it
judged. So the three are folded into one node here, joined on the input hash
the hook computes for all of them, and the node keeps every event id it
absorbed so a cited id still finds it.

Cursor asks as `cursor.Shell` and runs as `shell.run`; the hash is the same,
which is why the join is on the hash and not the tool name. An ask with no call
after it stays a node of its own: that is a denial, or a call the agent
abandoned, and either is worth seeing.

Nothing here reads command text the trail does not already hold. `command` is
present only when the operator set `AGENTMETRY_LOG_COMMANDS`.
"""

from __future__ import annotations

from typing import Any

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


def fold(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold a time-ordered session into tree nodes, asks joined to their calls."""
    nodes: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}  # input_hash -> the ask waiting for its call
    for event in events:
        action = (event.get("action") or {}).get("type", "")
        if action == "heartbeat":
            continue
        if action == "approval_response":
            gated = event.get("gated_action") or {}
            ask = pending.get(str(gated.get("input_hash") or ""))
            if ask is None:
                continue  # an answer to an ask outside this window says nothing alone
            ask["approval"] = _answer(event)
            ask["event_ids"].append(str(event.get("event_id") or ""))
            if ask["approval"] in ("denied", "expired"):
                if ask["approval"] == "denied":
                    ask["kind"] = "denied"
                pending.pop(ask["tool"]["input_hash"], None)
            continue
        kind = _kind(event)
        if kind == "call":
            call = _node(event, "call")
            input_hash = call["tool"]["input_hash"]
            ask = pending.pop(input_hash, None) if input_hash else None
            if ask is not None:
                ask["kind"] = "call"
                ask["event_ids"].extend(call["event_ids"])
                ask["outcome"] = call["outcome"]
                ask["reason"] = call["reason"] or ask["reason"]
                ask["asked_as"] = ask["tool"]["qualified"]
                merged_tool = call["tool"]
                # The ask may hold the command when the call does not, or the
                # other way round; keep whichever was recorded.
                if "command" not in merged_tool and "command" in ask["tool"]:
                    merged_tool["command"] = ask["tool"]["command"]
                if "mitre" not in merged_tool and "mitre" in ask["tool"]:
                    merged_tool["mitre"] = ask["tool"]["mitre"]
                ask["tool"] = merged_tool
                for key in ("dlp", "tool_policy"):
                    if key in call and key not in ask:
                        ask[key] = call[key]
                ask["id"] = call["id"]
                continue
            nodes.append(call)
            continue
        node = _node(event, kind)
        nodes.append(node)
        if kind == "ask" and node["tool"]["input_hash"]:
            # A second ask with the same input before any call replaces the
            # first as the one the next call answers; the first stays a node.
            pending[node["tool"]["input_hash"]] = node
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
