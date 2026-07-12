"""Tests for GET /api/v1/audit/tail."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings


@pytest.fixture
def audit_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.0.0", "correlation_id": "t1", "action": {"type": "tool_called", "outcome": "success"}},
        {"schema_version": "1.0.0", "correlation_id": "t2", "action": {"type": "session_end", "outcome": "success"}},
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)

    from api.main import app

    return TestClient(app)


def test_audit_tail_returns_last_events(audit_client: TestClient):
    resp = audit_client.get("/api/v1/audit/tail?limit=10&scope=runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert len(body["events"]) == 2
    assert body["events"][0]["correlation_id"] == "t1"
    assert body["events"][1]["correlation_id"] == "t2"


def test_audit_tail_excludes_config_change_by_default(audit_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.1.0", "session_id": "s1", "correlation_id": "t1", "action": {"type": "config_change", "outcome": "success"}, "mcp": {"server_id": "gmail"}},
        {"schema_version": "1.1.0", "session_id": "s1", "correlation_id": "t2", "action": {"type": "tool_called", "outcome": "success"}, "agent": {"skill_id": "audit_demo"}},
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)

    from api.main import app

    client = TestClient(app)
    body = client.get("/api/v1/audit/tail?scope=runs").json()
    assert len(body["events"]) == 1
    assert body["events"][0]["action"]["type"] == "tool_called"

    all_body = client.get("/api/v1/audit/tail?scope=all").json()
    assert len(all_body["events"]) == 2


def test_audit_tail_filters_by_session(audit_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.1.0", "session_id": "sess-a", "correlation_id": "t1", "action": {"type": "session_start", "outcome": "success"}, "agent": {"skill_id": "audit_demo"}},
        {"schema_version": "1.1.0", "session_id": "sess-b", "correlation_id": "t2", "action": {"type": "session_start", "outcome": "success"}, "agent": {"skill_id": "lead_gen"}},
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)

    from api.main import app

    client = TestClient(app)
    body = client.get("/api/v1/audit/tail?session_id=sess-a&scope=runs").json()
    assert len(body["events"]) == 1
    assert body["events"][0]["agent"]["skill_id"] == "audit_demo"


def test_audit_tail_empty_when_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "missing.jsonl")
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    from api.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/audit/tail")
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_audit_status_reports_freshness_and_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Status endpoint powers the freshness badge / selftest (F5)."""
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.1.0", "correlation_id": "t1", "timestamp_utc": "2026-07-12T09:00:00+00:00",
         "action": {"type": "tool_called", "outcome": "success"}, "source": {"app": "cursor"}},
        {"schema_version": "1.1.0", "correlation_id": "t2", "timestamp_utc": "2026-07-12T09:05:00+00:00",
         "action": {"type": "tool_called", "outcome": "success"}, "agent": {"name": "blackbox"}},
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    from api.main import app

    body = TestClient(app).get("/api/v1/audit/status").json()
    assert body["enabled"] is True
    assert body["last_event_utc"] == "2026-07-12T09:05:00+00:00"
    assert body["recent"] == 2
    assert body["by_source"]["cursor"] == 1
    assert body["by_source"]["blackbox"] == 1


def test_audit_status_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "x.jsonl")
    monkeypatch.setattr(settings, "audit_export_enabled", False)
    from api.main import app

    body = TestClient(app).get("/api/v1/audit/status").json()
    assert body["enabled"] is False
    assert body["last_event_utc"] is None


def test_audit_tail_pagination_before_utc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.1.0", "event_id": f"e{i}", "correlation_id": f"t{i}",
         "timestamp_utc": f"2026-07-12T10:0{i}:00+00:00",
         "action": {"type": "tool_called", "outcome": "success"}}
        for i in range(5)
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    from api.main import app

    client = TestClient(app)
    latest = client.get("/api/v1/audit/tail?limit=2&scope=runs").json()
    assert len(latest["events"]) == 2
    assert latest["events"][-1]["event_id"] == "e4"
    assert latest["pagination"]["has_older"] is True
    assert latest["pagination"]["has_newer"] is False

    older = client.get(
        "/api/v1/audit/tail",
        params={"limit": 2, "scope": "runs", "before_utc": "2026-07-12T10:03:00+00:00"},
    ).json()
    assert len(older["events"]) == 2
    assert older["events"][0]["event_id"] == "e1"
    assert older["events"][1]["event_id"] == "e2"
    assert older["pagination"]["has_older"] is True
    assert older["pagination"]["has_newer"] is True


def test_audit_tail_pagination_after_utc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    jsonl = tmp_path / "audit-forward.jsonl"
    events = [
        {"schema_version": "1.1.0", "event_id": f"e{i}", "correlation_id": f"t{i}",
         "timestamp_utc": f"2026-07-12T10:0{i}:00+00:00",
         "action": {"type": "tool_called", "outcome": "success"}}
        for i in range(4)
    ]
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    from api.main import app

    newer = TestClient(app).get(
        "/api/v1/audit/tail",
        params={"limit": 2, "scope": "runs", "after_utc": "2026-07-12T10:01:00+00:00"},
    ).json()
    assert len(newer["events"]) == 2
    assert newer["events"][0]["event_id"] == "e2"
    assert newer["events"][1]["event_id"] == "e3"
    assert newer["pagination"]["has_newer"] is False
    assert newer["pagination"]["has_older"] is True
