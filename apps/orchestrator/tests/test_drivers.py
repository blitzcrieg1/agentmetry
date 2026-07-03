"""Driver subsystem: spec loading, scrubbed env, permissions, live stdio mount."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.drivers.host import MCPHost
from core.drivers.permissions import (
    ToolExecApprovalRequired,
    ToolPermissionError,
    check_tool_allowed,
)
from core.drivers.spec import DriverSpec, load_driver_specs
from core.kernel.interrupts import InterruptVector, InterruptVectorTable

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


# ------------------------------------------------------------------- specs


def test_load_specs_skips_invalid_and_disabled(tmp_path: Path):
    config = tmp_path / "drivers.json"
    config.write_text(json.dumps({
        "drivers": [
            {"name": "good", "command": "python"},
            {"name": "BAD NAME!", "command": "python"},          # invalid pattern
            {"name": "off", "command": "python", "enabled": False},
            {"command": "python"},                               # missing name
        ]
    }), encoding="utf-8")

    specs = load_driver_specs(config)
    assert [s.name for s in specs] == ["good"]


def test_load_specs_survives_bad_json(tmp_path: Path):
    config = tmp_path / "drivers.json"
    config.write_text("{not json", encoding="utf-8")
    assert load_driver_specs(config) == []
    assert load_driver_specs(tmp_path / "missing.json") == []


def test_build_env_is_allowlist_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("MY_ALLOWED_VAR", "yes")

    spec = DriverSpec(name="d", command="x", env_allow=["MY_ALLOWED_VAR"], env={"LITERAL": "v"})
    env = spec.build_env()

    assert "GEMINI_API_KEY" not in env          # secrets never leak by default
    assert env["MY_ALLOWED_VAR"] == "yes"
    assert env["LITERAL"] == "v"


# ------------------------------------------------------------- permissions


def test_tools_closed_by_default():
    with pytest.raises(ToolPermissionError):
        check_tool_allowed({"name": "s"}, "fs.read_file", tags=[])


def test_allowlist_exact_and_wildcard():
    cfg = {"name": "s", "tools": ["fs.read_file", "search.*"]}
    check_tool_allowed(cfg, "fs.read_file", tags=[])
    check_tool_allowed(cfg, "search.web", tags=[])
    with pytest.raises(ToolPermissionError):
        check_tool_allowed(cfg, "fs.write_file", tags=[])


def test_exec_tag_denied_even_when_allowlisted():
    cfg = {"name": "s", "tools": ["shell.*"]}
    with pytest.raises(ToolExecApprovalRequired):
        check_tool_allowed(cfg, "shell.run", tags=["exec"])


# ------------------------------------------------- live stdio integration


@pytest.fixture
def ivt(tmp_path: Path) -> InterruptVectorTable:
    return InterruptVectorTable(f"sqlite:///{(tmp_path / 'ivt.db').as_posix()}")


async def test_mount_call_and_exec_gate(ivt: InterruptVectorTable):
    host = MCPHost(interrupt_table=ivt)
    spec = DriverSpec(
        name="fake",
        transport="stdio",
        command=sys.executable,
        args=[str(_FIXTURE)],
    )
    mounted = await host.mount(spec)
    assert mounted, host.snapshot()
    assert host.snapshot()["fake"]["state"] == "mounted"
    assert any(t["qualified"] == "fake.echo" for t in host.list_tools())

    # Allowed call round-trips through the real stdio server.
    result = await host.call_tool(
        "fake.echo", {"text": "blackbox"},
        skill_config={"name": "demo", "tools": ["fake.*"]},
    )
    text = "".join(getattr(c, "text", "") for c in result.content)
    assert text == "xobkcalb"

    # Closed by default.
    with pytest.raises(ToolPermissionError):
        await host.call_tool("fake.echo", {}, skill_config={"name": "demo"})

    # Unknown tool.
    with pytest.raises(ToolPermissionError):
        await host.call_tool("nope.tool", {}, skill_config={"name": "demo", "tools": ["*"]})

    await host.unmount_all()
    assert host.list_tools() == []


async def test_exec_gate_raises_interrupt(ivt: InterruptVectorTable):
    host = MCPHost(interrupt_table=ivt)
    spec = DriverSpec(
        name="fake",
        transport="stdio",
        command=sys.executable,
        args=[str(_FIXTURE)],
        tags=["exec"],  # driver-level exec tag gates every tool it exposes
    )
    assert await host.mount(spec)

    with pytest.raises(ToolExecApprovalRequired):
        await host.call_tool(
            "fake.echo", {"text": "rm -rf"},
            skill_config={"name": "demo", "tools": ["fake.*"]},
            session_id="sess-x",
        )

    rows = ivt.list_pending(InterruptVector.TOOL_EXEC_APPROVAL)
    assert len(rows) == 1
    assert rows[0]["payload"]["tool"] == "fake.echo"

    # Same denial again does not pile up duplicate interrupts.
    with pytest.raises(ToolExecApprovalRequired):
        await host.call_tool(
            "fake.echo", {"text": "again"},
            skill_config={"name": "demo", "tools": ["fake.*"]},
            session_id="sess-x",
        )
    assert len(ivt.list_pending(InterruptVector.TOOL_EXEC_APPROVAL)) == 1

    await host.unmount_all()


async def test_failed_mount_reports_and_does_not_raise():
    host = MCPHost()
    spec = DriverSpec(name="ghost", transport="stdio", command="definitely-not-a-command")
    mounted = await host.mount(spec)
    assert mounted is False
    assert host.snapshot()["ghost"]["state"] == "failed"
    await host.unmount_all()
