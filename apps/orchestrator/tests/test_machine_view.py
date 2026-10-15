"""The local dashboard's view of this machine, and what it must not contain."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core.diagnostics.machine_view import snapshot
from agentmetry.core.diagnostics.mcp_inventory import McpInventory, McpServer
from agentmetry.core.diagnostics.mcp_schema import FINGERPRINT_VERSION, SchemaRecord, SchemaStore
from agentmetry.core.diagnostics.posture import Finding, Posture


class _FakePosture(Posture):
    def sorted(self):
        return self.findings


def test_snapshot_drops_commands_paths_and_secrets(monkeypatch: pytest.MonkeyPatch):
    secret = "sk-ant-api03-should-not-appear"
    server = McpServer(
        agent="cursor",
        scope="user",
        name="mail",
        transport="stdio",
        command="npx",
        args=("-y", "some-mail-server", secret),
        url="",
        env_keys=("API_TOKEN",),
        source=str(Path.home() / ".cursor" / "mcp.json"),
    )
    inventory = McpInventory(servers=[server], files_read=[server.source])

    posture = _FakePosture(findings=[
        Finding("claude", "user", "permissions.defaultMode", "bypassPermissions", "high", "skips the prompt"),
    ])

    store = SchemaStore(servers={
        "mail": SchemaRecord(
            fingerprint="a" * 64,
            tool_count=4,
            observed_at="2026-10-14T00:00:00+00:00",
            previous="b" * 64,
            fingerprint_version=FINGERPRINT_VERSION,
        ),
    })

    monkeypatch.setattr(
        "agentmetry.core.diagnostics.hook_coverage.coverage",
        lambda: {"cursor": "uncovered", "claude": "covered", "codex": "absent"},
    )
    monkeypatch.setattr("agentmetry.core.diagnostics.posture.collect", lambda project=None: posture)
    monkeypatch.setattr("agentmetry.core.diagnostics.mcp_inventory.collect", lambda project=None: inventory)
    monkeypatch.setattr("agentmetry.core.diagnostics.mcp_schema.load_store", lambda path=None: store)

    body = snapshot()
    rendered = str(body)
    assert secret not in rendered
    assert "mcp.json" not in rendered
    assert "API_TOKEN" not in rendered
    assert "args" not in body["mcp"]["servers"][0]

    assert body["profile"] == "user"
    assert body["agents"][0]["name"] == "cursor"
    assert {row["state"] for row in body["agents"]} >= {"uncovered", "covered", "absent"}
    assert body["posture"]["findings"][0]["setting"] == "permissions.defaultMode"
    assert body["posture"]["not_checked"][0]["agent"] == "cursor"

    listed = body["mcp"]["servers"][0]
    assert listed["name"] == "mail"
    assert listed["launcher"] == "npx"
    assert listed["package"] == "some-mail-server"
    assert "unpinned_fetch" in listed["findings"]
    assert listed["listing"] == "changed"
    assert listed["tool_count"] == 4
    assert secret not in listed["package"]

    assert body["policy"]["rules"]
    assert all("command_pattern" not in rule for rule in body["policy"]["rules"])
    assert {pair["agent"] for pair in body["policy"]["ask_reaches"]} == {"claude", "cursor"}
    assert body["policy"]["dlp_rules"] > 0


def test_an_unlisted_server_is_not_observed(monkeypatch: pytest.MonkeyPatch):
    server = McpServer(agent="claude", scope="user", name="fs", transport="stdio", command="python", args=("server.py",))
    monkeypatch.setattr(
        "agentmetry.core.diagnostics.mcp_inventory.collect",
        lambda project=None: McpInventory(servers=[server]),
    )
    monkeypatch.setattr(
        "agentmetry.core.diagnostics.mcp_schema.load_store",
        lambda path=None: SchemaStore(),
    )
    listed = snapshot()["mcp"]["servers"][0]
    assert listed["observed"] is False
    assert listed["listing"] == "not_observed"
    assert listed["findings"] == []


def test_machine_route_is_authenticated_json(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "agentmetry.core.diagnostics.machine_view.snapshot",
        lambda: {"host_id": "test-host", "agents": [], "profile": "user"},
    )
    from agentmetry.api.main import app

    response = TestClient(app).get("/api/v1/audit/machine")
    assert response.status_code == 200
    assert response.json()["host_id"] == "test-host"
