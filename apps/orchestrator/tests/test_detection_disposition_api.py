"""Triage over HTTP — the surface the dashboard drives.

The API is where a bad disposition has to be rejected loudly: a UI that reports
"saved" over a decision the backend refused is worse than no triage at all,
because the operator believes the finding is closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings

_DISPOSITION_URL = "/api/v1/audit/detections/disposition"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail.jsonl")
    monkeypatch.setattr(settings, "detection_disposition_db_path", tmp_path / "disp.db")
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "api_key", "")

    from core.audit.detection.disposition import reset_disposition_store
    from core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_disposition_store()

    from api.main import app

    yield TestClient(app)

    reset_trail_db()
    reset_disposition_store()


def test_setting_a_disposition_returns_the_new_state(client: TestClient):
    resp = client.post(
        _DISPOSITION_URL,
        json={
            "correlation_id": "s1",
            "rule_id": "credential-exfil",
            "status": "acknowledged",
            "assignee": "alex",
            "decided_by": "alex",
        },
    )
    assert resp.status_code == 200
    current = resp.json()["disposition"]
    assert current["status"] == "acknowledged"
    assert current["assignee"] == "alex"
    assert current["closed"] is False


def test_an_unknown_status_is_a_400_not_a_500(client: TestClient):
    resp = client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "r1", "status": "probably_fine"},
    )
    assert resp.status_code == 400
    assert "probably_fine" in resp.json()["detail"]


def test_closing_without_a_reason_is_a_400(client: TestClient):
    resp = client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "r1", "status": "false_positive"},
    )
    assert resp.status_code == 400
    assert "requires a note" in resp.json()["detail"]


def test_rule_id_is_required(client: TestClient):
    resp = client.post(_DISPOSITION_URL, json={"status": "acknowledged"})
    assert resp.status_code == 422


def test_the_decision_lands_in_the_trail(client: TestClient):
    client.post(
        _DISPOSITION_URL,
        json={
            "correlation_id": "s1",
            "rule_id": "r1",
            "status": "risk_accepted",
            "note": "internal harness",
            "decided_by": "alex",
        },
    )
    from core.audit.trail_db import get_trail_db

    events = get_trail_db().events_by_action_type("detection_disposition")
    assert len(events) == 1
    assert events[0]["action"]["outcome"] == "risk_accepted"
    assert events[0]["disposition"]["note"] == "internal harness"


def test_the_decision_shows_in_the_session_feed(client: TestClient):
    """A disposition belongs next to the finding it answers."""
    client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "r1", "status": "acknowledged"},
    )
    body = client.get("/api/v1/audit/tail?limit=50&scope=runs").json()
    types = [e.get("action", {}).get("type") for e in body["events"]]
    assert "detection_disposition" in types


def test_listing_dispositions_reports_counts(client: TestClient):
    for corr in ("s1", "s2"):
        client.post(
            _DISPOSITION_URL,
            json={"correlation_id": corr, "rule_id": "r1", "status": "acknowledged"},
        )
    body = client.get("/api/v1/audit/detections/dispositions/all").json()
    assert body["counts"] == {"acknowledged": 2}
    assert len(body["dispositions"]) == 2
    assert "risk_accepted" in body["statuses"]


def test_detections_response_carries_triage_state(client: TestClient):
    body = client.get("/api/v1/audit/detections/s-empty").json()
    assert body["count"] == 0
    assert body["untriaged"] == 0


def test_superseding_over_http_keeps_history(client: TestClient):
    client.post(
        _DISPOSITION_URL,
        json={
            "correlation_id": "s1",
            "rule_id": "r1",
            "status": "false_positive",
            "note": "ci bot",
        },
    )
    resp = client.post(
        _DISPOSITION_URL,
        json={"correlation_id": "s1", "rule_id": "r1", "status": "in_progress"},
    )
    history = resp.json()["disposition"]["history"]
    assert [h["status"] for h in history] == ["false_positive", "in_progress"]
