"""The MCP proxy ships in the wheel (pilot hardening item 21).

It lived in the repository's `tools/` and imported the hook client from
`scripts/`, so MCP capture existed only on a git checkout. A `pip install
agentmetry` or an MSI host had none. These tests build the wheel and run the
proxy from a clean virtual environment, outside the repository, against a tiny
stdio MCP server, with no orchestrator listening: the call must still reach the
server, the response must come back, and the event must be spooled.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

from agentmetry.hooks.mcp_proxy import server_name

_ORCH = Path(__file__).resolve().parents[1]

_FAKE_SERVER = """
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" in msg:
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "pong"}]}}
        sys.stdout.write(json.dumps(reply) + "\\n")
        sys.stdout.flush()
"""


@pytest.mark.parametrize(("cmd", "expected"), [
    (["npx", "-y", "@modelcontextprotocol/server-filesystem", "/repo"], "server-filesystem"),
    (["python", "my_server.py"], "my_server"),
    (["uvx", "mcp-server-git@1.2"], "mcp-server-git"),
    (["docker", "run", "-i", "--rm", "ghcr.io/acme/mcp"], "mcp"),
    (["./bin/thing.exe", "--stdio"], "thing"),
])
def test_a_server_name_is_derived_from_the_command(cmd, expected):
    assert server_name(cmd) == expected


def test_the_cli_hands_everything_after_the_separator_to_the_proxy(monkeypatch):
    from agentmetry import cli
    from agentmetry.hooks import mcp_proxy

    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(mcp_proxy, "main", fake)
    assert cli.main(["mcp-proxy", "--server", "fs", "--", "node", "srv.js", "--port", "1"]) == 0
    assert seen["argv"] == ["--server", "fs", "--", "node", "srv.js", "--port", "1"]


def test_the_old_tools_path_is_the_same_module():
    sys.path.insert(0, str(_ORCH / "tools"))
    try:
        import mcp_audit_proxy
        from agentmetry.hooks import mcp_proxy

        assert mcp_audit_proxy is mcp_proxy
    finally:
        sys.path.remove(str(_ORCH / "tools"))


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("wheel")
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(_ORCH), "--no-deps", "-q", "-w", str(out)],
        capture_output=True, text=True, timeout=300, check=False, cwd=out,
    )
    if built.returncode != 0:
        pytest.skip(f"cannot build a wheel here (offline without hatchling?): {built.stderr[-300:]}")
    return next(out.glob("agentmetry-*.whl"))


def test_the_wheel_contains_the_proxy_and_its_alias_is_not_needed(wheel: Path):
    names = zipfile.ZipFile(wheel).namelist()
    assert "agentmetry/hooks/mcp_proxy.py" in names
    assert "agentmetry/hooks/ingest.py" in names


def test_the_proxy_runs_from_a_clean_venv_outside_the_repo(wheel: Path, tmp_path: Path):
    env_dir = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    python = env_dir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    # --no-deps: the proxy path must be standard library only. The full
    # install with dependencies is exercised by release.yml.
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "-q", str(wheel)],
                   check=True, timeout=300, capture_output=True, cwd=tmp_path)

    server = tmp_path / "fake_server.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    data = tmp_path / "data"
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("AGENTMETRY_", "PYTHON")) and k != "VIRTUAL_ENV"
    }
    # Port 9 (discard): nothing listens. Both names the hook honours are set.
    # Leaving them out once sent this test's event to the real orchestrator on
    # :8000, into a live dogfood trail, because the default is loopback:8000.
    dead = "http://127.0.0.1:9"
    env.update({
        "AGENTMETRY_DATA_DIR": str(data),
        "AGENTMETRY_URL": dead,
        "AGENTMETRY_AUDIT_INGEST_URL": dead,
        "AGENTMETRY_INGEST_TIMEOUT": "0.5",
    })
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
               "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}}}
    run = subprocess.run(
        [str(python), "-m", "agentmetry.hooks.mcp_proxy", "--", sys.executable, str(server)],
        input=json.dumps(request) + "\n", capture_output=True, text=True,
        cwd=tmp_path, env=env, timeout=60, check=False,
    )
    assert run.returncode == 0, run.stderr
    reply = json.loads(run.stdout.strip().splitlines()[-1])
    assert reply["id"] == 7 and reply["result"]["content"][0]["text"] == "pong"
    spool = data / "hook-spool.jsonl"
    assert spool.is_file(), f"the event must be spooled when the API is down: {run.stderr}"
    spooled = [json.loads(line) for line in spool.read_text(encoding="utf-8").splitlines()]
    assert any((p.get("tool") or {}).get("name") == "read_file" or "read_file" in json.dumps(p) for p in spooled)
    assert "/etc/hosts" not in spool.read_text(encoding="utf-8"), "arguments leave the proxy hashed"
