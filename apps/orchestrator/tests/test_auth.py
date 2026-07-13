"""Tests for API key authentication."""

import pytest
from fastapi.testclient import TestClient

from core.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-secret")
    from api.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_audit_tail_requires_api_key(client: TestClient):
    res = client.get("/api/v1/audit/tail")
    assert res.status_code == 401


def test_audit_tail_with_valid_key(client: TestClient):
    res = client.get(
        "/api/v1/audit/tail",
        headers={"X-API-Key": "test-secret"},
    )
    assert res.status_code != 401


def test_health_open_without_key(client: TestClient):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
