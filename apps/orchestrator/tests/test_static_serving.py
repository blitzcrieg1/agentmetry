"""Single-process serving: the orchestrator hosts the built dashboard export."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentmetry.api.main import mount_dashboard


def _fake_export(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    (out / "_next").mkdir(parents=True)
    (out / "index.html").write_text("<!DOCTYPE html><title>Agentmetry</title>", encoding="utf-8")
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


def test_pages_must_be_revalidated_and_scripts_are_left_alone(tmp_path: Path):
    """An upgraded recorder kept serving the old dashboard to an open browser:
    the page carried no cache header, so an ordinary reload could reuse it, and
    it named the previous build's scripts."""
    app = FastAPI()
    mount_dashboard(app, _fake_export(tmp_path))
    client = TestClient(app)

    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/index.html").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/_next/app.js").headers


def test_mount_is_noop_without_build(tmp_path: Path):
    app = FastAPI()
    assert mount_dashboard(app, tmp_path / "does-not-exist") is False
    assert not any(getattr(r, "name", "") == "dashboard" for r in app.routes)


def test_without_an_export_the_root_says_so_instead_of_a_json_404(tmp_path: Path):
    """0.10.0 from PyPI: the sign-in link redirected to /, which had nothing
    mounted, and the browser showed {"detail":"Not Found"}."""
    app = FastAPI()

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    mount_dashboard(app, tmp_path / "does-not-exist")
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert "Agentmetry is recording" in root.text
    assert "pip install --upgrade agentmetry" in root.text
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_the_packaged_export_is_found_when_there_is_no_checkout(tmp_path: Path, monkeypatch):
    """An installed wheel has no apps/dashboard/out above it; the release build
    bundles the export as agentmetry/dashboard_static instead."""
    from agentmetry.api import main

    packaged = _fake_export(tmp_path / "pkg")
    monkeypatch.setattr(main, "_CHECKOUT_DASHBOARD_DIR", tmp_path / "no-checkout")
    monkeypatch.setattr(main, "_PACKAGED_DASHBOARD_DIR", packaged)
    assert main.dashboard_dir() == packaged

    checkout = _fake_export(tmp_path / "checkout")
    monkeypatch.setattr(main, "_CHECKOUT_DASHBOARD_DIR", checkout)
    assert main.dashboard_dir() == checkout, "a checkout's own build wins"

    monkeypatch.setattr(main, "_CHECKOUT_DASHBOARD_DIR", tmp_path / "none-a")
    monkeypatch.setattr(main, "_PACKAGED_DASHBOARD_DIR", tmp_path / "none-b")
    assert main.dashboard_dir() is None
