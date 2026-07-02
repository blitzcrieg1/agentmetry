"""Tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient

from core.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-secret")
    from api.main import app

    return TestClient(app)


def test_execute_requires_api_key(client: TestClient):
    res = client.post(
        "/api/v1/skills/execute",
        json={"skill_name": "lead_gen", "user_input": "test", "session_id": "s1"},
    )
    assert res.status_code == 401


def test_execute_with_valid_key(client: TestClient):
    res = client.post(
        "/api/v1/skills/execute",
        json={"skill_name": "lead_gen", "user_input": "test", "session_id": "s1"},
        headers={"X-API-Key": "test-secret"},
    )
    assert res.status_code != 401


def test_health_open_without_key(client: TestClient):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
