"""The container files and the boot path carry no agent-runtime leftovers.

Pilot hardening item 22 and #209. docker-compose.yml started Qdrant, Postgres
(password "agentmetry"), Ollama and Gemini settings; the Dockerfile started
`uvicorn api.main:app`, a module that no longer exists; and every boot spawned
the removed runtime's MCP driver host. Docker is not installed on the machine
these were written on, so the image is checked by structure, not by building.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_the_compose_file_runs_only_the_recorder():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8").lower()
    for legacy in ("qdrant", "postgres", "ollama", "gemini", "agentic_os", "vault"):
        body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        assert legacy not in body, legacy


def test_the_compose_file_publishes_on_loopback_only():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    ports = re.findall(r'-\s*"([^"]+:\d+)"', text)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports), ports


def test_the_dockerfile_starts_a_module_that_exists():
    text = (ROOT / "apps" / "orchestrator" / "Dockerfile").read_text(encoding="utf-8")
    cmd = re.search(r'CMD \[(.+)\]', text).group(1)
    target = re.search(r'"([\w.]+):app"', cmd).group(1)
    assert target == "agentmetry.api.main"
    assert hasattr(importlib.import_module(target), "app")


def test_the_image_does_not_run_as_root_or_bake_an_api_key():
    raw = (ROOT / "apps" / "orchestrator" / "Dockerfile").read_text(encoding="utf-8")
    text = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"^USER (?!root)\S+", text, re.M)
    assert "NEXT_PUBLIC_AGENTMETRY_API_KEY" not in text
    assert "libpq" not in text


def test_the_build_context_excludes_secrets_and_local_data():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for pattern in ("**/.env", "**/data", "**/.venv", "**/node_modules"):
        assert pattern in text, pattern


def test_a_default_boot_mounts_no_legacy_driver(monkeypatch):
    from fastapi.testclient import TestClient

    from agentmetry.api.main import app
    from agentmetry.core.config import settings
    from agentmetry.core.drivers import host

    assert settings.legacy_drivers is False
    calls = []
    monkeypatch.setattr(host, "get_mcp_host", lambda: calls.append("mounted"))
    with TestClient(app):
        pass
    assert calls == []
