"""Claude observation metadata across the real mapper and both ingest paths.

All payloads are authored fixtures. No Claude session, model, OS process or
independent execution evidence is established by these tests.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.hook_bootstrap import merge_claude_hooks
from agentmetry.core.audit.ingest import reset_ingest_sink_cache
from agentmetry.core.audit.spool import drain_spool
from agentmetry.core.audit.trail_db import get_trail_db
from agentmetry.core.config import settings
from agentmetry.hooks import ingest

_MARKER = "SYNTHETIC_CLAUDE_RESULT_MUST_STAY_PRIVATE"


@pytest.fixture(autouse=True)
def _isolated_hook(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "account_for_hook", lambda *_args: None)
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    monkeypatch.delenv("AGENTMETRY_ADAPTER", raising=False)
    monkeypatch.setenv("AGENTMETRY_LOG_FULL_ARGS", "0")
    monkeypatch.setenv("AGENTMETRY_AUDIT_LOG_FULL_ARGS", "0")
    monkeypatch.setenv("AGENTMETRY_LOG_COMMANDS", "0")
    monkeypatch.setenv("AGENTMETRY_AUDIT_LOG_COMMANDS", "0")


def _payload(hook="PostToolUse", identifier="toolu_synthetic_001", **extra):
    payload = ingest.map_hook(
        hook,
        {
            "hook_event_name": hook,
            "session_id": "synthetic-claude-session",
            "tool_name": "Bash",
            "tool_input": {"command": "printf synthetic"},
            "tool_use_id": identifier,
            "tool_response": _MARKER,
            **extra,
        },
    )
    assert payload is not None
    return payload


def _http(payload):
    return ExternalIngestBody.model_validate(payload).model_dump(exclude_none=True)


def _stored(path):
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    return [unwrap_trail_record(json.loads(line)) for line in path.read_text().splitlines()]


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    output = tmp_path / "canonical.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", output)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "policy_enabled", False)
    reset_ingest_sink_cache()
    from agentmetry.api.main import app

    # No lifespan: this check must not install hooks or start background tasks.
    yield TestClient(app), output
    reset_ingest_sink_cache()


def test_contract_request_result_survive_http_and_persistence(recorder):
    client, output = recorder
    # A result can arrive first. Identical arguments on concurrent invocations
    # must not erase the two distinct source IDs, including in indexed JSON.
    for identifier in ("toolu_synthetic_001", "toolu_synthetic_002"):
        for hook in ("PostToolUse", "PreToolUse"):
            response = client.post("/api/v1/audit/ingest", json=_payload(hook, identifier))
            assert response.status_code == 200
    observations = [e for e in _stored(output) if e["source"]["adapter"] == "claude_hook"]
    indexed, _ = get_trail_db().tail(scope="all", limit=30)
    indexed = [e for e in indexed if e["source"]["adapter"] == "claude_hook"]
    for events in (observations, indexed):
        assert len(events) == 4
        assert len({e["event_id"] for e in events}) == 4
        assert {
            (e["session_id"], e["tool"]["invocation"]["id"], e["tool"]["invocation"]["phase"])
            for e in events
        } == {
            ("synthetic-claude-session", identifier, phase)
            for identifier in ("toolu_synthetic_001", "toolu_synthetic_002")
            for phase in ("request", "result")
        }
        assert len({e["tool"]["input_hash"] for e in events}) == 1
        for event in events:
            if event["tool"]["invocation"]["phase"] == "result":
                assert event["tool"]["result"] == {"status": "reported_success"}
    assert _MARKER not in output.read_text()
    assert "printf synthetic" not in output.read_text()


def test_contract_failure_is_recorded_without_error_or_response_text(recorder):
    client, output = recorder
    payload = _payload("PostToolUseFailure", error=_MARKER, duration_ms=0, is_interrupt=False)
    assert client.post("/api/v1/audit/ingest", json=payload).status_code == 200
    event = _stored(output)[0]
    assert event["action"]["outcome"] == "error"
    assert event["action"]["reason"] == "tool_failed"
    assert event["tool"]["invocation"]["hook_event"] == "PostToolUseFailure"
    assert event["tool"]["result"] == {
        "status": "reported_failure",
        "duration_ms": 0,
        "is_interrupt": False,
        "error_kind": "tool_failure",
    }
    assert _MARKER not in json.dumps(payload)
    assert _MARKER not in output.read_text()


def test_contract_failure_hook_merge_preserves_user_hook_and_is_idempotent(tmp_path):
    user = {"hooks": [{"type": "command", "command": "echo synthetic-user-hook"}]}
    configuration = {"hooks": {"PostToolUseFailure": [copy.deepcopy(user)]}}
    for _ in range(2):
        merge_claude_hooks(
            configuration, python="/synthetic/python", ingest=tmp_path / "agentmetry_ingest.py"
        )
    groups = configuration["hooks"]["PostToolUseFailure"]
    assert len(groups) == 2
    assert user in groups
    owned = [g for g in groups if g != user]
    assert "claude hook PostToolUseFailure" in owned[0]["hooks"][0]["command"]


@pytest.mark.asyncio
async def test_spool_matches_http_metadata_and_does_not_hide_repeated_observations(
    recorder, tmp_path
):
    client, output = recorder
    payload = _payload("PostToolUseFailure", duration_ms=12, is_interrupt=True, error=_MARKER)
    assert client.post("/api/v1/audit/ingest", json=payload).status_code == 200
    spool = tmp_path / "synthetic-spool.jsonl"
    row = {"spooled_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
    spool.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert _MARKER not in spool.read_text()
    assert (await drain_spool(spool))["replayed"] == 1
    live, replayed = [e for e in _stored(output) if e["source"]["adapter"] == "claude_hook"]
    assert live["event_id"] != replayed["event_id"]
    assert live["tool"]["invocation"] == replayed["tool"]["invocation"]
    assert (
        live["tool"]["result"]
        == replayed["tool"]["result"]
        == {
            "status": "reported_failure",
            "duration_ms": 12,
            "is_interrupt": True,
            "error_kind": "interrupted",
        }
    )


@pytest.mark.parametrize("duration", [False, True, "12", 12.0, 0.5, -1, 1 << 53, None])
def test_invalid_optional_duration_is_absent_on_both_ingest_paths(duration):
    payload = _payload(duration_ms=1)
    payload["tool"]["result"]["duration_ms"] = duration
    for normalized in (payload, _http(payload)):
        tool = build_external_canonical(normalized)["tool"]
        assert tool["result"] == {"status": "reported_success"}


@pytest.mark.parametrize("duration", [0, 12, (1 << 53) - 1])
def test_valid_duration_is_preserved_without_coercion(duration):
    payload = _payload(duration_ms=duration)
    assert build_external_canonical(_http(payload))["tool"]["result"]["duration_ms"] == duration


@pytest.mark.parametrize("identifier", [None, "", " space", "a\nb", "é", "x" * 257, 12])
def test_invalid_source_id_is_omitted_not_replaced(identifier):
    payload = _payload(identifier=identifier)
    for normalized in (payload, _http(payload)):
        invocation = build_external_canonical(normalized)["tool"]["invocation"]
        assert "id" not in invocation
        assert invocation["phase"] == "result"


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_invalid_interruption_is_not_coerced(value):
    payload = _payload("PostToolUseFailure", is_interrupt=value)
    result = build_external_canonical(_http(payload))["tool"]["result"]
    assert result == {"status": "reported_failure", "error_kind": "tool_failure"}


@pytest.mark.parametrize("damage", ["phase", "event", "provenance", "status", "shape"])
def test_invalid_metadata_does_not_reject_legacy_event(recorder, damage):
    client, output = recorder
    payload = _payload()
    tool = payload["tool"]
    if damage == "phase":
        tool["invocation"]["phase"] = "request"
    elif damage == "event":
        tool["invocation"]["hook_event"] = "PermissionRequest"
    elif damage == "provenance":
        tool["invocation"]["provenance"] = "verified"
    elif damage == "status":
        tool["result"]["status"] = "reported_failure"
    else:
        tool["invocation"] = "wrong shape"
    assert client.post("/api/v1/audit/ingest", json=payload).status_code == 200
    for event in (_stored(output)[0], build_external_canonical(payload)):
        assert "invocation" not in event["tool"]
        assert "result" not in event["tool"]
        assert event["action"]["type"] == "tool_called"


def test_arbitrary_result_fields_do_not_cross_http_or_direct_ingest():
    payload = _payload("PostToolUseFailure", is_interrupt=False)
    payload["tool"]["result"].update({"error": _MARKER, "output": _MARKER, "exit_code": 0})
    payload["tool"]["invocation"]["path"] = _MARKER
    for normalized in (payload, _http(payload)):
        tool = build_external_canonical(normalized)["tool"]
        assert _MARKER not in json.dumps(tool)
        assert "exit_code" not in tool["result"]


@pytest.mark.parametrize("source", ["qwen", "kimi", "qoder", "codebuddy", "codex", "unknown"])
def test_other_sources_do_not_acquire_claude_coverage(monkeypatch, source):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", source)
    payload = _payload()
    assert "invocation" not in payload["tool"]
    payload["source_app"] = source
    payload["tool"]["invocation"] = {
        "id": "synthetic",
        "phase": "request",
        "hook_event": "PreToolUse",
        "provenance": "harness_reported",
    }
    assert "invocation" not in build_external_canonical(_http(payload))["tool"]


def test_adapter_override_and_shape_autodetection_are_not_claude_coverage(monkeypatch):
    monkeypatch.setenv("AGENTMETRY_ADAPTER", "synthetic_wrapper")
    assert "invocation" not in _payload()["tool"]
    monkeypatch.delenv("AGENTMETRY_ADAPTER")
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "")
    assert "invocation" not in _payload()["tool"]


def test_notification_is_not_an_invocation_or_human_decision():
    payload = _payload("Notification")
    assert "invocation" not in payload["tool"]
    assert ingest.map_hook("PermissionRequest", {"session_id": "synthetic"}) is None


def test_inferred_approval_does_not_gain_an_exact_invocation_link():
    from agentmetry.core.audit.ingest import infer_approval_payloads

    request = build_external_canonical(_http(_payload("PreToolUse")))
    result = build_external_canonical(_http(_payload()))
    assert infer_approval_payloads(request) == []
    inferred = infer_approval_payloads(result)
    assert len(inferred) == 1  # Existing heuristic behavior, not an observed click.
    canonical = build_external_canonical(inferred[0])
    assert canonical["source"]["adapter"].endswith("_inferred")
    assert "invocation" not in canonical.get("tool", {})


def test_a_failed_claude_call_is_not_recorded_as_a_denial():
    """PreToolUse, PostToolUseFailure, Stop: approved, ran, failed.

    Before, only PostToolUse closed the request, so Stop recorded this call as
    an inferred denial. Raised by a reader who keeps unresolved tool_use_ids
    in their own bucket rather than counting them as failures.
    """
    from agentmetry.core.audit.ingest import infer_approval_payloads, reset_pending_approvals

    reset_pending_approvals()
    request = build_external_canonical(_http(_payload("PreToolUse", "toolu_failed_001")))
    failure = build_external_canonical(
        _http(_payload("PostToolUseFailure", "toolu_failed_001", error="exit 1"))
    )
    stop = build_external_canonical(_http(_payload("Stop", "toolu_failed_001")))

    assert failure["action"]["outcome"] == "error"
    assert infer_approval_payloads(request) == []
    assert infer_approval_payloads(failure) == []
    assert infer_approval_payloads(stop) == []


def test_old_tool_events_remain_unchanged_when_metadata_is_absent():
    payload = _payload()
    payload["tool"].pop("invocation", None)
    payload["tool"].pop("result", None)
    canonical = build_external_canonical(_http(payload))
    assert canonical["action"]["type"] == "tool_called"
    assert canonical["action"]["outcome"] == "success"
    assert "invocation" not in canonical["tool"]
    assert "result" not in canonical["tool"]
