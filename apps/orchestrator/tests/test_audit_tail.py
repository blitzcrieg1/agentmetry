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
    resp = audit_client.get("/api/v1/audit/tail?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert len(body["events"]) == 2
    assert body["events"][0]["correlation_id"] == "t1"
    assert body["events"][1]["correlation_id"] == "t2"


def test_audit_tail_empty_when_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "missing.jsonl")
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    from api.main import app

    client = TestClient(app)
    resp = client.get("/api/v1/audit/tail")
    assert resp.status_code == 200
    assert resp.json()["events"] == []
