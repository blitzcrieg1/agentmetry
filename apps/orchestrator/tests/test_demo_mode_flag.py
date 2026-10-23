"""The dashboard labels a trail as synthetic only when the server says so.

It used to read `?demo=1` from the page URL. The demo server opened without it
called itself "This machine", and a real recorder opened with it called real
events synthetic. `/audit/status` now carries `demo`, set by `demo_mode`, which
only scripts/demo_dashboard.py turns on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core.config import settings


@pytest.fixture
def status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentmetry.core.audit.trail_db import reset_trail_db

    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail.jsonl")
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    reset_trail_db()
    from agentmetry.api.main import app

    def read(*, demo: bool, export: bool = True) -> dict:
        monkeypatch.setattr(settings, "demo_mode", demo)
        monkeypatch.setattr(settings, "audit_export_enabled", export)
        return TestClient(app).get("/api/v1/audit/status").json()

    yield read
    reset_trail_db()


def test_a_real_install_is_not_a_demo(status):
    assert status(demo=False)["demo"] is False


def test_the_demo_server_says_it_is_one(status):
    assert status(demo=True)["demo"] is True


def test_the_flag_is_there_with_the_trail_export_off(status):
    assert status(demo=True, export=False)["demo"] is True


def test_off_unless_the_environment_turns_it_on(monkeypatch: pytest.MonkeyPatch):
    from agentmetry.core.config import Settings

    monkeypatch.delenv("AGENTMETRY_DEMO_MODE", raising=False)
    assert Settings().demo_mode is False
    monkeypatch.setenv("AGENTMETRY_DEMO_MODE", "1")
    assert Settings().demo_mode is True


def test_the_demo_launcher_turns_it_on():
    script = Path(__file__).resolve().parents[3] / "scripts" / "demo_dashboard.py"
    assert '"AGENTMETRY_DEMO_MODE": "1"' in script.read_text(encoding="utf-8")
