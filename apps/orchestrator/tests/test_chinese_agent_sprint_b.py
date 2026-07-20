"""Sprint B: subagent swarm detection + extended Chinese agent hooks."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import agentmetry_ingest as ingest  # noqa: E402

from core.audit.detection.rules import rule_subagent_swarm_burst


def _ev(**kwargs) -> dict:
    base = {
        "event_id": "e1",
        "correlation_id": "sess-swarm",
        "timestamp_utc": "2026-07-20T12:00:00+00:00",
        "initiator": {"actor_type": "autonomous", "trigger": "ingress", "operator_id": "local"},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "tool": {"qualified": "kimi.subagent.explore", "server": "kimi"},
    }
    base.update(kwargs)
    return base


def test_subagent_swarm_fires_at_threshold():
    events = [
        _ev(
            event_id=f"s{i}",
            action={"type": "tool_called", "outcome": "success", "reason": "subagent_start:explore"},
            tool={"qualified": "kimi.subagent.explore", "server": "kimi"},
        )
        for i in range(5)
    ]
    d = next(d for d in rule_subagent_swarm_burst(events) if d.rule_id == "subagent-swarm-burst")
    assert d.severity == "high"
    assert len(d.event_ids) == 5


def test_subagent_swarm_below_threshold_is_silent():
    events = [_ev(event_id=f"s{i}") for i in range(4)]
    assert rule_subagent_swarm_burst(events) == []


def test_kimi_subagent_start_mapper():
    payload = ingest.map_kimi_hook(
        "SubagentStart",
        {"session_id": "sess-1", "agent_type": "coder", "tool_input": {}},
    )
    assert payload is not None
    assert payload["source_app"] == "kimi"
    assert payload["reason"] == "subagent_start:coder"
    assert payload["tool"]["qualified"] == "kimi.subagent.coder"


def test_qoder_maps_claude_family():
    payload = ingest.map_qoder_hook(
        "PostToolUse",
        {
            "session_id": "sess-q",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        },
    )
    assert payload is not None
    assert payload["source_app"] == "qoder"
    assert payload["adapter"] == "qoder_hook"
