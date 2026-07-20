"""Sprint C: stream-json ingest, session-tool-burst, host-level subagent aggregation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import agentmetry_ingest as ingest  # noqa: E402

from core.audit.detection.live import (  # noqa: E402
    mark_host_detection_emitted,
    observe_host,
    reset_live_state,
)
from core.audit.detection.rules import (  # noqa: E402
    rule_host_subagent_swarm_burst,
    rule_session_tool_burst,
)


def _ev(**kwargs) -> dict:
    base = {
        "event_id": "e1",
        "correlation_id": "sess-1",
        "host_id": "lab-host",
        "timestamp_utc": "2026-07-20T12:00:00+00:00",
        "initiator": {"actor_type": "autonomous", "trigger": "ingress", "operator_id": "local"},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "tool": {"qualified": "kimi.shell", "server": "kimi"},
    }
    base.update(kwargs)
    return base


def test_kimi_stream_json_maps_tool_calls():
    line = {
        "role": "assistant",
        "content": "Let me check.",
        "tool_calls": [
            {
                "type": "function",
                "id": "tc_1",
                "function": {"name": "Shell", "arguments": '{"command":"ls"}'},
            }
        ],
    }
    payloads = ingest.map_kimi_stream_json_line(line, session_id="sess-stream-1")
    assert len(payloads) == 1
    assert payloads[0]["source_app"] == "kimi"
    assert payloads[0]["adapter"] == "kimi_stream_json"
    assert payloads[0]["tool"]["qualified"] == "kimi.Shell"
    assert payloads[0]["correlation_id"] == "sess-stream-1"


def test_session_tool_burst_fires_at_threshold():
    events = [_ev(event_id=f"e{i}", correlation_id="sess-burst") for i in range(40)]
    hits = rule_session_tool_burst(events)
    assert len(hits) == 1
    assert hits[0].rule_id == "session-tool-burst"


def test_host_subagent_swarm_across_sessions():
    events = []
    for i in range(8):
        events.append(
            _ev(
                event_id=f"s{i}",
                correlation_id=f"sess-{i // 2}",
                action={"type": "tool_called", "outcome": "success", "reason": "subagent_start:explore"},
                tool={"qualified": "kimi.subagent.explore", "server": "kimi"},
            )
        )
    hits = rule_host_subagent_swarm_burst(events)
    assert len(hits) == 1
    assert hits[0].rule_id == "host-subagent-swarm-burst"
    assert "8 subagent starts" in hits[0].summary


def test_observe_host_dedupes_emitted_rules():
    reset_live_state()
    ev = _ev(
        event_id="h1",
        correlation_id="sess-a",
        action={"type": "tool_called", "outcome": "success", "reason": "subagent_start:x"},
        tool={"qualified": "kimi.subagent.x", "server": "kimi"},
    )
    # Seed host window with enough subagent starts
    for i in range(7):
        observe_host(
            _ev(
                event_id=f"seed{i}",
                correlation_id=f"sess-seed-{i}",
                action={"type": "tool_called", "outcome": "success", "reason": "subagent_start:x"},
                tool={"qualified": "kimi.subagent.x", "server": "kimi"},
            )
        )
    first = observe_host(ev)
    assert any(d.rule_id == "host-subagent-swarm-burst" for d in first)
    for d in first:
        mark_host_detection_emitted("lab-host", d.rule_id)
    second = observe_host(
        _ev(
            event_id="h2",
            correlation_id="sess-b",
            action={"type": "tool_called", "outcome": "success", "reason": "subagent_start:y"},
            tool={"qualified": "kimi.subagent.y", "server": "kimi"},
        )
    )
    assert not any(d.rule_id == "host-subagent-swarm-burst" for d in second)


def test_stream_json_cli_reads_stdin(monkeypatch):
    monkeypatch.setattr(ingest, "post_ingest", lambda payload, quiet=False: True)
    line = json.dumps(
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "Read", "arguments": '{"path":"README.md"}'}},
            ],
        }
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(line + "\n"))
    assert ingest.stream_json_main("kimi") == 0
