"""Tests for Tier B external audit ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.audit.external import build_external_canonical
from core.audit.ingest import (
    ingest_external_event,
    infer_approval_payloads,
    reset_ingest_sink_cache,
    reset_pending_approvals,
)
from core.config import settings


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
    assert out["schema_version"] == "1.1.0"
    assert out["source"]["app"] == "cursor"
    assert out["source"]["tier"] == "external"
    assert out["agent"]["name"] == "cursor"
    assert out["tool"]["qualified"] == "Shell.run"
    assert len(out["tool"]["input_hash"]) == 64


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
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    monkeypatch.setattr(settings, "api_key", "")
    reset_ingest_sink_cache()

    from api.main import app

    yield TestClient(app), jsonl
    reset_ingest_sink_cache()


@pytest.mark.asyncio
async def test_ingest_service_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
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
    parsed = json.loads(lines[0])
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
    assert json.loads(lines[0])["source"]["app"] == "cursor"


def test_tail_filters_by_source(ingest_client):
    client, jsonl = ingest_client
    events = [
        build_external_canonical({"source_app": "cursor", "event_type": "session_start", "correlation_id": "1"}),
        build_external_canonical({"source_app": "claude", "event_type": "session_start", "correlation_id": "2"}),
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")

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
    types = [json.loads(ln)["action"]["type"] for ln in lines]
    assert types == ["approval_request", "tool_called", "approval_response"]
    assert json.loads(lines[2])["action"]["reason"] == "inferred:tool_ran_after_ask"
