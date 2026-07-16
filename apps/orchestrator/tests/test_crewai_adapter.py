"""Tests for the CrewAI listener (adapters/crewai/agentmetry_crewai.py).

CrewAI is not an Agentmetry dependency, so the event bus is stubbed here. That
keeps CI honest about the adapter's behaviour without installing the framework.
The stub mirrors the real contract in crewai/events: BaseEventListener.__init__
calls setup_listeners(bus), and the bus exposes .on(EventClass) as a decorator.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

_EVENT_NAMES = (
    "CrewKickoffStartedEvent",
    "CrewKickoffCompletedEvent",
    "CrewKickoffFailedEvent",
    "ToolUsageStartedEvent",
    "ToolUsageFinishedEvent",
    "ToolUsageErrorEvent",
)


class _FakeBus:
    """Records handlers the way crewai_event_bus.on(...) would."""

    def __init__(self) -> None:
        self.handlers: dict[type, object] = {}

    def on(self, event_cls: type):
        def deco(fn):
            self.handlers[event_cls] = fn
            return fn

        return deco

    def validate_dependencies(self) -> None:
        pass

    def fire(self, event_cls: type, event: object) -> None:
        self.handlers[event_cls](None, event)


def _install_fake_crewai() -> types.ModuleType:
    crewai = types.ModuleType("crewai")
    events = types.ModuleType("crewai.events")

    class BaseEventListener:
        def __init__(self) -> None:
            # Mirrors the real base: registers handlers during __init__.
            self.setup_listeners(events.crewai_event_bus)

    events.BaseEventListener = BaseEventListener
    events.crewai_event_bus = _FakeBus()
    for name in _EVENT_NAMES:
        setattr(events, name, type(name, (), {}))

    sys.modules["crewai"] = crewai
    sys.modules["crewai.events"] = events
    return events


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch):
    """Load the adapter fresh against a stubbed crewai, with a captured sink."""
    monkeypatch.delenv("AGENTMETRY_CREWAI_LOG_ARGS", raising=False)
    monkeypatch.delenv("AGENTMETRY_API_KEY", raising=False)
    events = _install_fake_crewai()

    path = Path(__file__).resolve().parents[3] / "adapters" / "crewai" / "agentmetry_crewai.py"
    spec = importlib.util.spec_from_file_location("agentmetry_crewai", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sent: list[dict] = []
    monkeypatch.setattr(mod.AgentmetryListener, "_post", lambda self, payload: sent.append(payload))
    listener = mod.AgentmetryListener(quiet=True)
    return SimpleNamespace(mod=mod, events=events, bus=events.crewai_event_bus, sent=sent, listener=listener)


def _tool_event(name: str = "shell", args=None, **extra):
    return SimpleNamespace(
        tool_name=name,
        tool_args=args if args is not None else {"command": "ls -la"},
        agent_role="researcher",
        agent_id="a-1",
        **extra,
    )


# --- mapping -----------------------------------------------------------------

def test_tool_finished_maps_to_canonical_tool_called(adapter):
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event())
    assert len(adapter.sent) == 1
    p = adapter.sent[0]
    assert p["source_app"] == "crewai"
    assert p["event_type"] == "tool_called"
    assert p["outcome"] == "success"
    assert p["tool"]["qualified"] == "crewai.shell"
    assert len(p["tool"]["input_hash"]) == 64  # sha256 hex


def test_tool_error_maps_to_tool_failed(adapter):
    adapter.bus.fire(adapter.events.ToolUsageErrorEvent, _tool_event(error="boom"))
    p = adapter.sent[0]
    assert p["event_type"] == "tool_failed"
    assert p["outcome"] == "error"
    assert "boom" in p["reason"]


def test_crew_run_is_one_correlation_id(adapter):
    adapter.bus.fire(adapter.events.CrewKickoffStartedEvent, SimpleNamespace(crew_name="research"))
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event())
    adapter.bus.fire(adapter.events.CrewKickoffCompletedEvent, SimpleNamespace(output="done"))
    corrs = {p["correlation_id"] for p in adapter.sent}
    assert len(corrs) == 1, "a Crew run must correlate as one session so sequence rules can fire"
    assert adapter.sent[0]["event_type"] == "session_start"
    assert adapter.sent[-1]["event_type"] == "session_end"


def test_crew_is_marked_autonomous(adapter):
    """A Crew runs unattended; the detection engine keys on this."""
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event())
    assert adapter.sent[0]["triggered_by"] == "crewai"


# --- privacy -----------------------------------------------------------------

def test_arguments_are_not_transmitted_by_default(adapter):
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event(args={"command": "cat /etc/passwd"}))
    tool = adapter.sent[0]["tool"]
    assert "arguments" not in tool, "args must be opt-in; the hash always travels"
    assert tool["input_hash"]


def test_arguments_sent_when_opted_in(adapter, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_CREWAI_LOG_ARGS", "1")
    listener = adapter.mod.AgentmetryListener(quiet=True)
    sent: list[dict] = []
    monkeypatch.setattr(listener, "_post", lambda payload: sent.append(payload))
    adapter.bus.handlers[adapter.events.ToolUsageFinishedEvent] = (
        lambda s, e: listener._emit("tool_called", outcome="success", **listener._tool_payload(e))
    )
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event(args={"command": "cat ~/.ssh/id_rsa"}))
    assert sent[0]["tool"]["arguments"]["command"] == "cat ~/.ssh/id_rsa"


def test_secrets_are_scrubbed_before_leaving_the_process(adapter, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_CREWAI_LOG_ARGS", "1")
    listener = adapter.mod.AgentmetryListener(quiet=True)
    payload = listener._tool_payload(
        _tool_event(args={"api_key": "sk-should-not-travel", "url": "https://x"})
    )
    assert payload["tool"]["arguments"]["api_key"] == "***"
    assert "should-not-travel" not in str(payload)


def test_string_tool_args_are_handled(adapter):
    adapter.bus.fire(adapter.events.ToolUsageFinishedEvent, _tool_event(args="just a string"))
    assert adapter.sent[0]["tool"]["input_hash"]


# --- fail-safe ---------------------------------------------------------------

def test_a_dead_sink_never_breaks_the_crew(adapter, monkeypatch: pytest.MonkeyPatch):
    """An audit sink that can crash the Crew it observes is worse than none."""
    listener = adapter.mod.AgentmetryListener(ingest_url="http://127.0.0.1:9/nope", quiet=True)
    listener._emit("tool_called", outcome="success")  # must not raise
