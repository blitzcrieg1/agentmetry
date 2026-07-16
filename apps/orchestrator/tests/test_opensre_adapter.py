"""Tests for the OpenSRE recorder (adapters/opensre/agentmetry_opensre.py).

OpenSRE is not an Agentmetry dependency. The recorder duck-types on the event's
`type` discriminator rather than importing core.events, so these fakes mirror
the real frozen dataclasses in Tracer-Cloud/opensre core/events.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[3] / "adapters" / "opensre" / "agentmetry_opensre.py"


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTMETRY_OPENSRE_LOG_ARGS", raising=False)
    monkeypatch.delenv("AGENTMETRY_API_KEY", raising=False)
    spec = importlib.util.spec_from_file_location("agentmetry_opensre", _PATH)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def rec(mod, monkeypatch: pytest.MonkeyPatch):
    sent: list[dict] = []
    r = mod.AgentmetryRecorder(quiet=True)
    monkeypatch.setattr(r, "_post", lambda payload: sent.append(payload))
    return SimpleNamespace(r=r, sent=sent, mod=mod)


def _tool_end(name="run_shell", args=None, is_error=False, result="ok"):
    # Mirrors ToolExecutionEndEvent(tool_call_id, tool_name, args, result, is_error, iteration)
    return SimpleNamespace(
        type="tool_execution_end",
        tool_call_id="tc-1",
        tool_name=name,
        args=args if args is not None else {"command": "kubectl get pods"},
        result=result,
        is_error=is_error,
        iteration=1,
    )


# --- mapping -----------------------------------------------------------------

def test_tool_end_maps_to_tool_called(rec):
    rec.r(_tool_end())
    assert len(rec.sent) == 1
    p = rec.sent[0]
    assert p["source_app"] == "opensre"
    assert p["event_type"] == "tool_called"
    assert p["outcome"] == "success"
    assert p["tool"]["qualified"] == "opensre.run_shell"
    assert len(p["tool"]["input_hash"]) == 64


def test_tool_error_maps_to_tool_failed(rec):
    rec.r(_tool_end(is_error=True, result="permission denied"))
    p = rec.sent[0]
    assert p["event_type"] == "tool_failed"
    assert p["outcome"] == "error"
    assert "permission denied" in p["reason"]


def test_agent_run_is_one_correlation_id(rec):
    rec.r(SimpleNamespace(type="agent_start", data={}))
    rec.r(_tool_end())
    rec.r(SimpleNamespace(type="agent_end", data={}))
    corrs = {p["correlation_id"] for p in rec.sent}
    assert len(corrs) == 1, "one incident run must correlate as one session"
    assert rec.sent[0]["event_type"] == "session_start"
    assert rec.sent[-1]["event_type"] == "session_end"


def test_sre_agent_is_marked_autonomous(rec):
    rec.r(_tool_end())
    assert rec.sent[0]["triggered_by"] == "opensre"


def test_unrelated_events_are_ignored(rec):
    """The RuntimeEvent union is wide; only tool/agent lifecycle is recorded."""
    for kind in ("turn_start", "message_update", "provider_request_start", "turn_end"):
        rec.r(SimpleNamespace(type=kind, data={}))
    assert rec.sent == []


# --- privacy -----------------------------------------------------------------

def test_arguments_not_transmitted_by_default(rec):
    rec.r(_tool_end(args={"command": "cat /etc/shadow"}))
    assert "arguments" not in rec.sent[0]["tool"]
    assert rec.sent[0]["tool"]["input_hash"]


def test_arguments_sent_when_opted_in(mod, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_OPENSRE_LOG_ARGS", "1")
    sent: list[dict] = []
    r = mod.AgentmetryRecorder(quiet=True)
    monkeypatch.setattr(r, "_post", lambda p: sent.append(p))
    r(_tool_end(args={"path": "~/.aws/credentials"}))
    assert sent[0]["tool"]["arguments"]["path"] == "~/.aws/credentials"


def test_secrets_scrubbed(mod, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_OPENSRE_LOG_ARGS", "1")
    r = mod.AgentmetryRecorder(quiet=True)
    payload = r._tool_payload(_tool_end(args={"api_key": "sk-nope", "host": "prod"}))
    assert payload["tool"]["arguments"]["api_key"] == "***"
    assert "sk-nope" not in str(payload)


# --- good citizenship / fail-safe --------------------------------------------

def test_chained_callback_still_runs(mod, monkeypatch: pytest.MonkeyPatch):
    """Wiring Agentmetry must not steal an existing on_runtime_event."""
    seen: list[object] = []
    r = mod.AgentmetryRecorder(quiet=True, chain_to=seen.append)
    monkeypatch.setattr(r, "_post", lambda p: None)
    ev = _tool_end()
    r(ev)
    assert seen == [ev]


def test_chained_callback_runs_even_if_recording_raises(mod, monkeypatch: pytest.MonkeyPatch):
    seen: list[object] = []

    def boom(_payload):
        raise RuntimeError("sink exploded")

    r = mod.AgentmetryRecorder(quiet=True, chain_to=seen.append)
    monkeypatch.setattr(r, "_post", boom)
    r(_tool_end())  # must not raise
    assert len(seen) == 1, "the host's callback must survive our failure"


def test_a_dead_sink_never_breaks_the_agent(mod):
    r = mod.AgentmetryRecorder(ingest_url="http://127.0.0.1:9/nope", quiet=True)
    r(_tool_end())  # must not raise
