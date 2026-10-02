"""The MCP inventory as an opt-in event (#169).

The heartbeat names no server, on purpose, and these tests keep it that way.
The inventory is a separate event an operator turns on, and what it carries
about each server is reduced to what a fleet view needs and nothing that tends
to hold a secret.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agentmetry.core.audit import heartbeat as hb
from agentmetry.core.audit import mcp_inventory_event as mie
from agentmetry.core.config import settings
from agentmetry.core.diagnostics.mcp_inventory import McpServer, collect

#: Secret-shaped on purpose: the test is that these never leave the machine.
#: The token is synthetic and marked for gitleaks on its own line, as
#: .gitleaks.toml asks, rather than exempting the file.
SECRETS = (
    "ghp_SECRETTOKEN1234567890abcdefghijklmnop",  # gitleaks:allow
    "C:/Users/jdoe/private-repo",
    "sk-live-ENVVALUE",
    "apikey=QUERYSECRET",
    "SECRET_ENV_KEY_NAME",
)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    (tmp_path / ".cursor").mkdir(parents=True)
    _write_servers(tmp_path, {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github", "--token", SECRETS[0]],
            "env": {SECRETS[4]: SECRETS[2]},
        },
        "local-notes": {"command": "node", "args": [f"{SECRETS[1]}/server.js"]},
        "remote": {"url": f"http://mcp.example.com/sse?{SECRETS[3]}"},
    })
    return tmp_path


def _write_servers(home, servers: dict) -> None:
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _entries(home) -> dict[str, dict]:
    return {s.name: s.wire_entry() for s in collect().servers}


# ------------------------------------------------------- what leaves the machine


def test_no_argument_env_value_env_key_or_url_query_leaves_the_machine(home):
    event = mie.build_inventory_event("t", collect(), outcome="snapshot")
    blob = json.dumps(event)
    for secret in SECRETS:
        assert secret not in blob, secret


def test_a_fetch_and_run_server_keeps_its_package_name(home):
    """The registry name is public and is the thing a SOC wants to search for."""
    github = _entries(home)["github"]
    assert github["launcher"] == "npx"
    assert github["package"] == "@modelcontextprotocol/server-github"


def test_a_local_launcher_keeps_no_path(home):
    notes = _entries(home)["local-notes"]
    assert notes["launcher"] == "node"
    assert notes["package"] == ""


def test_a_url_keeps_only_its_host(home):
    assert _entries(home)["remote"]["url_host"] == "mcp.example.com"


def test_findings_go_out_as_codes(home):
    entries = _entries(home)
    assert entries["github"]["findings"] == ["unpinned_fetch", "auto_confirm"]
    assert entries["remote"]["findings"] == ["plaintext_http"]
    assert entries["local-notes"]["findings"] == []


def test_the_fingerprint_moves_when_an_argument_does(home):
    """The argument is withheld, and a change to it is still visible."""
    before = _entries(home)["github"]["fingerprint"]
    _write_servers(home, {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github", "--token", "other"]}})
    assert _entries(home)["github"]["fingerprint"] != before


def test_codes_match_the_operator_facing_findings():
    """Same logic, two renderings. One must not drift from the other."""
    cases = [
        McpServer("cursor", "user", "a", "stdio", command="npx", args=("-y", "pkg")),
        McpServer("cursor", "user", "b", "stdio", command="npx", args=("pkg@1.2.3",)),
        McpServer("cursor", "user", "c", "stdio"),
        McpServer("cursor", "user", "d", "http", url="http://x.example"),
        McpServer("cursor", "user", "e", "http", url="https://x.example"),
    ]
    for server in cases:
        assert bool(server.finding_codes()) == bool(server.findings()), server.name


# ------------------------------------------------------------- the heartbeat


def test_the_heartbeat_still_names_no_server_with_inventory_on(home, monkeypatch):
    monkeypatch.setattr(settings, "mcp_inventory_enabled", True)
    blob = json.dumps(hb.build_heartbeat_event("t"))
    for name in ("github", "local-notes", "remote", "server-github"):
        assert name not in blob, name


# ---------------------------------------------------------------- when it fires


def test_off_by_default(home):
    assert settings.mcp_inventory_enabled is False
    assert asyncio.run(mie.maybe_emit_inventory(mie.InventoryState())) is None


def test_on_it_fires_once_then_waits_for_news(home, monkeypatch):
    monkeypatch.setattr(settings, "mcp_inventory_enabled", True)
    state = mie.InventoryState()

    first = asyncio.run(mie.maybe_emit_inventory(state))
    assert first["action"] == {
        "type": "mcp_inventory", "outcome": "snapshot",
        "reason": "3 MCP server(s) configured, 2 flagged",
    }
    assert first["mcp_inventory"]["server_count"] == 3
    assert asyncio.run(mie.maybe_emit_inventory(state)) is None, "unchanged surface, same day"


def test_a_changed_surface_fires_changed(home, monkeypatch):
    monkeypatch.setattr(settings, "mcp_inventory_enabled", True)
    state = mie.InventoryState()
    asyncio.run(mie.maybe_emit_inventory(state))
    _write_servers(home, {"github": {"command": "npx", "args": ["@modelcontextprotocol/server-github@1.0.0"]}})
    changed = asyncio.run(mie.maybe_emit_inventory(state))
    assert changed["action"]["outcome"] == "changed"
    assert changed["mcp_inventory"]["server_count"] == 1


def test_an_unchanged_surface_resnapshots_daily(home, monkeypatch):
    """So a dashboard over the last 24 hours sees every host, not only the ones
    whose config moved."""
    monkeypatch.setattr(settings, "mcp_inventory_enabled", True)
    clock = [1000.0]
    monkeypatch.setattr(mie.time, "monotonic", lambda: clock[0])
    state = mie.InventoryState()
    asyncio.run(mie.maybe_emit_inventory(state))
    clock[0] += mie.SNAPSHOT_SECONDS - 1
    assert asyncio.run(mie.maybe_emit_inventory(state)) is None
    clock[0] += 2
    assert asyncio.run(mie.maybe_emit_inventory(state))["action"]["outcome"] == "snapshot"


def test_it_lands_in_the_trail(home, monkeypatch):
    from agentmetry.core.audit.trail_db import get_trail_db

    monkeypatch.setattr(settings, "mcp_inventory_enabled", True)
    event = asyncio.run(mie.maybe_emit_inventory(mie.InventoryState()))
    stored = [e for e in get_trail_db().read_between("0", "9999") if e.get("event_id") == event["event_id"]]
    assert stored and stored[0]["mcp_inventory"]["server_count"] == 3


def test_a_large_surface_is_cut_and_says_so(home, monkeypatch):
    monkeypatch.setattr(mie, "LIMIT", 2)
    event = mie.build_inventory_event("t", collect(), outcome="snapshot")
    assert len(event["mcp_inventory"]["servers"]) == 2
    assert event["mcp_inventory"]["server_count"] == 3
    assert event["mcp_inventory"]["truncated"] is True


def test_the_setting_reads_from_the_environment(monkeypatch):
    from agentmetry.core.config import Settings

    monkeypatch.setenv("AGENTMETRY_MCP_INVENTORY", "1")
    assert Settings(_env_file=None).mcp_inventory_enabled is True
