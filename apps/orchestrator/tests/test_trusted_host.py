"""DNS-rebinding guard (pilot hardening item 9).

A page can make its own hostname resolve to 127.0.0.1 and read the local API
as same-origin. Its requests still carry its own Host header, which is what the
guard refuses.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentmetry.api.trusted_host import host_of
from agentmetry.core.config import settings


@pytest.fixture()
def client():
    from agentmetry.api.main import app

    return TestClient(app)


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST", "127.0.0.1"])
def test_loopback_names_are_served(client, host):
    assert client.get("/api/v1/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example", "localhost.evil.example"])
def test_a_rebinding_hostname_is_refused(client, host):
    r = client.get("/api/v1/health", headers={"Host": host})
    assert r.status_code == 400 and "Invalid host" in r.text


def test_a_rebinding_page_cannot_read_the_trail(client):
    assert client.get("/api/v1/audit/tail", headers={"Host": "attacker.example"}).status_code == 400


def test_a_configured_name_is_served(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_hosts", "testserver, devbox.corp.example")
    assert client.get("/api/v1/health", headers={"Host": "devbox.corp.example:8000"}).status_code == 200


def test_star_disables_the_check(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_hosts", "*")
    assert client.get("/api/v1/health", headers={"Host": "anything.example"}).status_code == 200


def test_a_websocket_from_a_foreign_host_is_refused(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/s1", headers={"Host": "evil.example"}):
            pass


@pytest.mark.parametrize("header,expected", [
    ("localhost:8000", "localhost"), ("[::1]:8000", "::1"), ("::1", "::1"),
    ("Example.COM", "example.com"), ("", ""),
])
def test_host_parsing(header, expected):
    assert host_of(header) == expected
