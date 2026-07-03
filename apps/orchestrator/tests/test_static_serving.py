"""Single-process serving: the orchestrator hosts the built dashboard export."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import mount_dashboard


def _fake_export(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / "_next").mkdir(parents=True)
    (out / "index.html").write_text("<!DOCTYPE html><title>BLACKBOX</title>", encoding="utf-8")
    (out / "_next" / "app.js").write_text("console.log('bb')", encoding="utf-8")
    return out


def test_mount_serves_index_and_assets(tmp_path: Path):
    app = FastAPI()

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    assert mount_dashboard(app, _fake_export(tmp_path)) is True
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "<!DOCTYPE html>" in root.text

    asset = client.get("/_next/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    # API routes registered before the mount still take precedence.
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_mount_is_noop_without_build(tmp_path: Path):
    app = FastAPI()
    assert mount_dashboard(app, tmp_path / "does-not-exist") is False
    assert not any(getattr(r, "name", "") == "dashboard" for r in app.routes)
