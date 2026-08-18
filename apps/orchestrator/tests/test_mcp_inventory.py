"""MCP configuration inventory, built from the 2026 disclosures rather than invented.

Each case below is a shape that actually happened:

* `postmark-mcp` shipped fifteen clean versions before adding exfiltration, so an
  unpinned entry is the finding even when today's package is fine.
* The STDIO transport runs an arbitrary OS command, which makes a config file an
  execution primitive rather than a preference.
* Claude Code nests `mcpServers` under `projects.<absolute path>`, so a reader
  that only checks the top level reports zero servers on a machine with several.
  That failure is silent and reassuring, which is the worst combination.
"""

from __future__ import annotations

import json

import pytest

from agentmetry.core.diagnostics.mcp_inventory import (
    McpServer,
    collect,
    summary_lines,
)


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _stdio(command="npx", args=("-y", "some-mcp"), **kw):
    return McpServer(
        agent="claude", scope="user", name="s", transport="stdio",
        command=command, args=tuple(args), **kw,
    )


# ----------------------------------------------------------------------
# The supply-chain shape
# ----------------------------------------------------------------------


def test_an_unpinned_fetch_and_run_entry_is_flagged():
    """The postmark-mcp shape. Clean today is not a property of the config."""
    findings = " ".join(_stdio(args=("-y", "postmark-mcp")).findings())
    assert "unpinned" in findings
    # The auto-confirm flag rides along on the unpinned finding rather than
    # standing alone. See test_a_pinned_version_is_not_flagged for why.
    assert "auto-confirm" in findings


def test_a_pinned_version_is_not_flagged():
    """Otherwise every correctly configured machine is red and the check is noise."""
    assert _stdio(args=("-y", "postmark-mcp@1.4.2")).findings() == []


def test_latest_is_not_a_pin():
    assert any("unpinned" in f for f in _stdio(args=("-y", "postmark-mcp@latest")).findings())


def test_a_scoped_package_pins_normally():
    assert _stdio(args=("-y", "@acme/mcp-server@2.0.1")).findings() == []
    assert any("unpinned" in f for f in _stdio(args=("-y", "@acme/mcp-server")).findings())


@pytest.mark.parametrize("launcher", ["npx", "uvx", "bunx", "pipx", "npx.cmd"])
def test_every_fetching_launcher_is_recognised(launcher):
    assert any("unpinned" in f for f in _stdio(command=launcher, args=("-y", "pkg")).findings())


def test_a_local_binary_is_not_a_fetch():
    """`/usr/local/bin/my-server` runs what is on disk; there is nothing to pin."""
    assert _stdio(command="/usr/local/bin/my-server", args=()).findings() == []


def test_plaintext_remote_transport_is_flagged():
    server = McpServer("cursor", "user", "s", "http", url="http://mcp.internal/sse")
    assert any("plaintext" in f for f in server.findings())
    ok = McpServer("cursor", "user", "s", "http", url="https://mcp.internal/sse")
    assert ok.findings() == []


def test_a_stdio_entry_with_no_command_is_reported():
    assert any("no command" in f for f in _stdio(command="", args=()).findings())


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def test_claude_nested_project_blocks_are_found(tmp_path, monkeypatch):
    """The failure this test exists for is silent: a top-level-only reader says
    zero servers on a machine that has several, which reads as reassuring."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(
        tmp_path / ".claude.json",
        {
            "numStartups": 3,
            "projects": {
                "C:/work/alpha": {"mcpServers": {"sentry": {"command": "npx", "args": ["-y", "sentry-mcp"]}}},
                "C:/work/beta": {"mcpServers": {"pg": {"command": "uvx", "args": ["pg-mcp@0.3.0"]}}},
            },
        },
    )
    inv = collect()
    assert sorted(s.name for s in inv.servers) == ["pg", "sentry"]
    assert len(inv.flagged) == 1 and inv.flagged[0].name == "sentry"


def test_absolute_project_paths_do_not_leak_into_output(tmp_path, monkeypatch):
    """Scope should locate a finding without pasting someone's directory tree
    into a report they may forward to a vendor."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(
        tmp_path / ".claude.json",
        {"projects": {"C:/Users/someone/secret-client-work": {"mcpServers": {"x": {"command": "npx", "args": ["-y", "p"]}}}}},
    )
    text = " ".join(summary_lines(collect()))
    assert "secret-client-work" in collect().servers[0].scope
    assert "C:/Users/someone" not in text


def test_a_flat_config_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "fs-mcp@1.0.0"]}}})
    inv = collect()
    assert [(s.agent, s.name) for s in inv.servers] == [("cursor", "fs")]


def test_missing_configs_are_not_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    inv = collect()
    assert (inv.servers, inv.unreadable) == ([], [])
    assert "No MCP configuration found" in summary_lines(inv)[0]


def test_an_unparseable_config_is_reported_not_swallowed(tmp_path, monkeypatch):
    """The agent may be running it regardless, so silence would be the wrong call."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    (tmp_path / ".cursor").mkdir(parents=True)
    (tmp_path / ".cursor" / "mcp.json").write_text("{not json", encoding="utf-8")
    inv = collect()
    assert len(inv.unreadable) == 1
    assert "unreadable" in " ".join(summary_lines(inv))


def test_transport_is_inferred_when_undeclared(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(
        tmp_path / ".cursor" / "mcp.json",
        {"mcpServers": {"a": {"command": "x"}, "b": {"url": "https://h/sse"}, "c": {}}},
    )
    got = {s.name: s.transport for s in collect().servers}
    assert got == {"a": "stdio", "b": "http", "c": "unknown"}


# ----------------------------------------------------------------------
# Fingerprint and digest
# ----------------------------------------------------------------------


def test_env_values_never_reach_the_fingerprint(tmp_path, monkeypatch):
    """Env values are routinely credentials. Keys change behaviour and are kept;
    values would end up in a hash an operator might paste into an issue."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    base = {"command": "npx", "args": ["-y", "p@1.0.0"], "env": {"TOKEN": "secret-aaa"}}
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": base}})
    first = collect().servers[0]

    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": {**base, "env": {"TOKEN": "secret-bbb"}}}})
    second = collect().servers[0]

    assert first.fingerprint() == second.fingerprint()
    assert "secret-aaa" not in json.dumps(summary_lines(collect()))


def test_a_renamed_env_key_does_change_the_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": {"command": "x", "env": {"A": "1"}}}})
    before = collect().servers[0].fingerprint()
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": {"command": "x", "env": {"B": "1"}}}})
    assert collect().servers[0].fingerprint() != before


def test_the_digest_moves_when_a_server_changes(tmp_path, monkeypatch):
    """This is what makes the inventory anchorable: publish the digest beside a
    trail root and a later config change is detectable without disclosing which
    servers the machine talks to."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": {"command": "npx", "args": ["-y", "p@1.0.0"]}}})
    before = collect().digest()
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"s": {"command": "npx", "args": ["-y", "p@1.0.1"]}}})
    assert collect().digest() != before


def test_the_digest_is_order_independent(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    a = {"command": "npx", "args": ["-y", "a@1.0.0"]}
    b = {"command": "npx", "args": ["-y", "b@1.0.0"]}
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"a": a, "b": b}})
    first = collect().digest()
    _write(tmp_path / ".cursor" / "mcp.json", {"mcpServers": {"b": b, "a": a}})
    assert collect().digest() == first
