"""Tests for Tier B external audit ingest."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.ingest import (
    ingest_external_event,
    infer_approval_payloads,
    reset_ingest_sink_cache,
    reset_pending_approvals,
)
from agentmetry.core.config import settings


def test_build_external_canonical_cursor_tool():
    out = build_external_canonical({
        "source_app": "cursor",
        "event_type": "tool_called",
        "correlation_id": "conv-123",
        "tool": {
            "qualified": "Shell.run",
            "server": "cursor",
            "arguments": {"command": "pytest -q"},
        },
    })
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["source"]["app"] == "cursor"
    assert out["source"]["tier"] == "external"
    assert out["agent"]["name"] == "cursor"
    assert out["tool"]["qualified"] == "Shell.run"
    assert len(out["tool"]["input_hash"]) == 64
    assert "claimed_app" not in out["source"]


def test_an_unlisted_agent_is_unknown_not_cursor():
    """An OpenClaw plugin posting to ingest used to land in the trail, the SIEM
    and the detections as Cursor. A confident wrong attribution in the record
    is worse than an honest `unknown`."""
    out = build_external_canonical({
        "source_app": "OpenClaw",
        "event_type": "tool_called",
        "tool": {"qualified": "shell.run", "arguments": {"command": "ls"}},
    })
    assert out["source"]["app"] == "unknown"
    assert out["agent"]["name"] == "unknown"
    assert out["source"]["claimed_app"] == "openclaw"
    assert out["source_topic"] == "external/unknown/tool_called"


def test_zcode_is_a_known_source():
    """ZCode is Claude-Code-derived, so its hook payload arrives in the Claude
    shape; the events must record under their own name, not be coerced to
    Claude by the unknown-source fallback."""
    out = build_external_canonical({
        "source_app": "zcode",
        "event_type": "tool_called",
        "tool": {"qualified": "Bash", "arguments": {"command": "ls"}},
    })
    assert out["source"]["app"] == "zcode"
    assert out["agent"]["name"] == "zcode"
    assert not out["source"].get("claimed_app")
    assert out["source_topic"] == "external/zcode/tool_called"


def test_a_claimed_name_cannot_carry_arbitrary_text():
    """The claim is kept so an operator can see who sent it, but only as a
    short identifier: SIEM rules group on this field."""
    out = build_external_canonical({
        "source_app": 'evil"} app\n' + "x" * 200,
        "event_type": "tool_called",
    })
    claimed = out["source"]["claimed_app"]
    assert out["source"]["app"] == "unknown"
    assert len(claimed) <= 64
    assert all(c.isalnum() or c in "_.-" for c in claimed)


def test_a_missing_source_app_still_means_cursor():
    """The default predates `source_app`; hooks installed before it may still
    post without one."""
    out = build_external_canonical({"event_type": "tool_called"})
    assert out["source"]["app"] == "cursor"
    assert "claimed_app" not in out["source"]


def test_build_external_canonical_with_command():
    out = build_external_canonical({
        "source_app": "antigravity",
        "event_type": "tool_called",
        "correlation_id": "ag-1",
        "tool": {
            "qualified": "antigravity.run_command",
            "server": "antigravity",
            "input_hash": "a" * 64,
            "command": "pytest -q",
        },
    })
    assert out["tool"]["command"] == "pytest -q"
    assert out["tool"]["input_redaction"] == "hash+command"
    assert out["tool"]["parameters_redacted"] is False


def test_build_external_claude_session():
    out = build_external_canonical({
        "source_app": "claude",
        "adapter": "claude_hook",
        "event_type": "session_start",
        "correlation_id": "claude-sess-1",
    })
    assert out["action"]["type"] == "session_start"
    assert out["source"]["app"] == "claude"


@pytest.fixture
def ingest_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    reset_trail_db()
    try:
        get_trail_db().insert_batch(events)
    except NameError:
        pass  # events not defined in this scope
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    monkeypatch.setattr(settings, "api_key", "")
    reset_ingest_sink_cache()

    from agentmetry.api.main import app

    yield TestClient(app), jsonl
    reset_ingest_sink_cache()


@pytest.mark.asyncio
async def test_ingest_service_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    reset_trail_db()
    try:
        get_trail_db().insert_batch(events)
    except NameError:
        pass  # events not defined in this scope
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    reset_ingest_sink_cache()

    canonical = await ingest_external_event({
        "source_app": "antigravity",
        "event_type": "tool_called",
        "correlation_id": "ag-1",
        "tool_qualified": "file.read",
        "input_hash": "abc" * 21 + "a",
    })
    assert canonical["source"]["app"] == "antigravity"
    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    parsed = unwrap_trail_record(json.loads(lines[0]))
    assert parsed["agent"]["name"] == "antigravity"


def test_ingest_api(ingest_client):
    client, jsonl = ingest_client
    resp = client.post(
        "/api/v1/audit/ingest",
        json={
            "source_app": "cursor",
            "event_type": "tool_called",
            "correlation_id": "c-99",
            "tool": {"qualified": "Read", "arguments": {"path": "foo.py"}},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    assert unwrap_trail_record(json.loads(lines[0]))["source"]["app"] == "cursor"


def test_tail_filters_by_source(ingest_client):
    client, jsonl = ingest_client
    events = [
        build_external_canonical({"source_app": "cursor", "event_type": "session_start", "correlation_id": "1"}),
        build_external_canonical({"source_app": "claude", "event_type": "session_start", "correlation_id": "2"}),
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    reset_trail_db()
    get_trail_db().insert_batch(events)

    body = client.get("/api/v1/audit/tail?sources=cursor&scope=runs").json()
    assert len(body["events"]) == 1
    assert body["events"][0]["source"]["app"] == "cursor"


def test_infer_grant_on_tool_run_after_ask():
    """ask → tool runs ⇒ inferred approval_response/granted, marked inferred (F2)."""
    reset_pending_approvals()
    req = build_external_canonical({
        "source_app": "cursor", "event_type": "approval_request", "outcome": "pending",
        "correlation_id": "conv-1",
        "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "a" * 64},
    })
    assert infer_approval_payloads(req) == []  # request just recorded

    ran = build_external_canonical({
        "source_app": "cursor", "event_type": "tool_called", "outcome": "success",
        "correlation_id": "conv-1",
        "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "a" * 64},
    })
    inferred = infer_approval_payloads(ran)
    assert len(inferred) == 1
    assert inferred[0]["event_type"] == "approval_response"
    assert inferred[0]["outcome"] == "success"
    assert inferred[0]["reason"] == "inferred:tool_ran_after_ask"
    assert inferred[0]["gated_action"]["tool"] == "shell.run"


def _ask(corr: str, tool: str = "shell.run", input_hash: str | None = None) -> dict:
    payload: dict = {
        "source_app": "cursor", "event_type": "approval_request", "outcome": "pending",
        "correlation_id": corr,
        "tool": {"qualified": tool, "server": "shell"},
    }
    if input_hash:
        payload["tool"]["input_hash"] = input_hash
    return build_external_canonical(payload)


def _ran(corr: str, tool: str = "shell.run", input_hash: str | None = None) -> dict:
    payload: dict = {
        "source_app": "cursor", "event_type": "tool_called", "outcome": "success",
        "correlation_id": corr,
        "tool": {"qualified": tool, "server": "shell"},
    }
    if input_hash:
        payload["tool"]["input_hash"] = input_hash
    return build_external_canonical(payload)


def test_approval_not_consumed_by_a_different_command_on_the_same_tool():
    """Approve `Bash(rm -rf /tmp/x)`, run `Bash(ls)`: that is NOT the approved action.

    The matcher used to compare tool names only, so any later call to the same
    tool silently consumed the approval and the trail asserted a human had
    approved something they never saw. This is the proposed-vs-executed gap.
    """
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-mismatch", input_hash="a" * 64))

    inferred = infer_approval_payloads(_ran("conv-mismatch", input_hash="b" * 64))
    assert inferred == [], "a different command must not satisfy the approval"

    # The approval was never satisfied, so it must still be pending and resolve
    # as denied at session end rather than vanishing.
    end = build_external_canonical({
        "source_app": "cursor", "event_type": "session_end", "correlation_id": "conv-mismatch",
    })
    closed = infer_approval_payloads(end)
    assert len(closed) == 1
    assert closed[0]["outcome"] == "denied"
    assert closed[0]["gated_action"]["input_hash"] == "a" * 64


def test_approval_binds_when_the_hash_matches():
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-exact", input_hash="c" * 64))

    inferred = infer_approval_payloads(_ran("conv-exact", input_hash="c" * 64))
    assert len(inferred) == 1
    assert inferred[0]["reason"] == "inferred:tool_ran_after_ask"
    assert inferred[0]["gated_action"]["input_hash"] == "c" * 64


def _failed(corr: str, tool: str = "shell.run", input_hash: str | None = None) -> dict:
    payload: dict = {
        "source_app": "cursor", "event_type": "tool_failed",
        "correlation_id": corr,
        "tool": {"qualified": tool, "server": "shell"},
    }
    if input_hash:
        payload["tool"]["input_hash"] = input_hash
    return build_external_canonical(payload)


def _end(corr: str) -> dict:
    return build_external_canonical({
        "source_app": "cursor", "event_type": "session_end", "correlation_id": corr,
    })


def test_a_failed_call_closes_its_ask_without_a_denial():
    """Ask, then the call runs and fails. That is not a refusal.

    Only a successful call closed an ask, so a failed one stayed pending and
    session end recorded it as an inferred denial: approved, ran, failed, and
    written down as refused. A failure says nothing about what a person
    decided, so nothing is inferred in either direction.
    """
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-failed", input_hash="e" * 64))

    assert infer_approval_payloads(_failed("conv-failed", input_hash="e" * 64)) == []
    assert infer_approval_payloads(_end("conv-failed")) == []


def test_a_failed_different_command_leaves_the_ask_open():
    """The same binding rule as a success: a failure of `Bash(ls)` is not the
    result of an ask for `Bash(rm -rf /tmp/x)`."""
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-failed-other", input_hash="a" * 64))
    infer_approval_payloads(_failed("conv-failed-other", input_hash="b" * 64))

    closed = infer_approval_payloads(_end("conv-failed-other"))
    assert len(closed) == 1
    assert closed[0]["reason"] == "inferred:session_ended_pending"


def test_an_ask_with_no_result_still_closes_at_session_end():
    """Unchanged: an ask that never got a result keeps its marker."""
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-open", input_hash="f" * 64))

    closed = infer_approval_payloads(_end("conv-open"))
    assert len(closed) == 1
    assert closed[0]["reason"] == "inferred:session_ended_pending"


def test_approval_falls_back_to_tool_name_when_a_hash_is_missing():
    """Pre-hash adapters send no input_hash; name matching must still work."""
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-nohash"))

    inferred = infer_approval_payloads(_ran("conv-nohash", input_hash="d" * 64))
    assert len(inferred) == 1
    assert inferred[0]["reason"] == "inferred:tool_ran_after_ask"


def test_approval_for_one_tool_is_not_consumed_by_another():
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-tools", tool="shell.run", input_hash="e" * 64))

    assert infer_approval_payloads(_ran("conv-tools", tool="fs.write", input_hash="e" * 64)) == []


def test_matching_approval_is_found_past_an_unrelated_pending_one():
    """The right approval binds even when a mismatched one is queued ahead of it."""
    reset_pending_approvals()
    infer_approval_payloads(_ask("conv-queue", input_hash="1" * 64))
    infer_approval_payloads(_ask("conv-queue", input_hash="2" * 64))

    inferred = infer_approval_payloads(_ran("conv-queue", input_hash="2" * 64))
    assert len(inferred) == 1
    assert inferred[0]["gated_action"]["input_hash"] == "2" * 64

    # The first approval is untouched and still resolves as denied.
    end = build_external_canonical({
        "source_app": "cursor", "event_type": "session_end", "correlation_id": "conv-queue",
    })
    closed = infer_approval_payloads(end)
    assert len(closed) == 1
    assert closed[0]["gated_action"]["input_hash"] == "1" * 64


def test_infer_denied_on_session_end_pending():
    """ask still pending at session end ⇒ inferred denied (F2)."""
    reset_pending_approvals()
    req = build_external_canonical({
        "source_app": "cursor", "event_type": "approval_request", "outcome": "pending",
        "correlation_id": "conv-2",
        "tool": {"qualified": "shell.run", "server": "shell"},
    })
    infer_approval_payloads(req)

    end = build_external_canonical({
        "source_app": "cursor", "event_type": "session_end", "correlation_id": "conv-2",
    })
    inferred = infer_approval_payloads(end)
    assert len(inferred) == 1
    assert inferred[0]["outcome"] == "denied"
    assert inferred[0]["reason"] == "inferred:session_ended_pending"


@pytest.mark.asyncio
async def test_ingest_emits_inferred_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End to end: approval_request then tool_called writes 3 JSONL lines."""
    jsonl = tmp_path / "audit-forward.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    reset_trail_db()
    try:
        get_trail_db().insert_batch(events)
    except NameError:
        pass  # events not defined in this scope
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    reset_ingest_sink_cache()
    reset_pending_approvals()

    await ingest_external_event({
        "source_app": "cursor", "event_type": "approval_request", "outcome": "pending",
        "correlation_id": "conv-3",
        "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "b" * 64},
    })
    await ingest_external_event({
        "source_app": "cursor", "event_type": "tool_called", "outcome": "success",
        "correlation_id": "conv-3",
        "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "b" * 64},
    })

    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3  # request + tool_called + inferred approval_response
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    types = [unwrap_trail_record(json.loads(ln))["action"]["type"] for ln in lines]
    assert types == ["approval_request", "tool_called", "approval_response"]
    assert unwrap_trail_record(json.loads(lines[2]))["action"]["reason"] == "inferred:tool_ran_after_ask"


def _stored_events(jsonl: Path) -> list[dict]:
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    return [unwrap_trail_record(json.loads(line)) for line in lines]


def _codex_hook_payload() -> dict:
    from agentmetry.hooks import ingest as hook

    payload = hook.map_codex_hook(
        "PostToolUse",
        {
            "session_id": "codex-model",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "model": "glm-5.3",
        },
    )
    assert payload is not None
    return hook._hash_tool_args(payload)


def test_codex_model_survives_the_real_route(ingest_client):
    """#389: the mapper had the model, and the stored event said `codex`."""
    client, jsonl = ingest_client
    resp = client.post("/api/v1/audit/ingest", json=_codex_hook_payload())
    assert resp.status_code == 200
    model = _stored_events(jsonl)[0]["model"]
    assert model == {"id": "glm-5.3", "provider": "codex"}


@pytest.mark.asyncio
async def test_a_spooled_call_records_the_same_model_as_a_live_one(ingest_client, tmp_path: Path):
    """The spool replay skips the HTTP model, so these two paths used to disagree."""
    from agentmetry.core.audit.spool import drain_spool

    client, jsonl = ingest_client
    payload = _codex_hook_payload()
    assert client.post("/api/v1/audit/ingest", json=payload).status_code == 200

    spool = tmp_path / "hook-spool.jsonl"
    line = {"spooled_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
    spool.write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert (await drain_spool(spool))["replayed"] == 1

    live, spooled = _stored_events(jsonl)[:2]
    assert spooled["model"] == live["model"] == {"id": "glm-5.3", "provider": "codex"}


def test_a_model_of_the_wrong_shape_is_not_a_422(ingest_client):
    client, jsonl = ingest_client
    resp = client.post(
        "/api/v1/audit/ingest",
        json={"source_app": "codex", "event_type": "tool_called", "model": "glm-5.3"},
    )
    assert resp.status_code == 200
    assert _stored_events(jsonl)[0]["model"] == {"id": "codex", "provider": "codex"}
