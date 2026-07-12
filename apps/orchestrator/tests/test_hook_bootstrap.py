"""Tests for global Tier B hook bootstrap."""

from __future__ import annotations

from pathlib import Path

from core.audit.hook_bootstrap import (
    bootstrap_tier_b_hooks,
    cursor_hooks_payload,
    install_cursor_global_hooks,
)


def test_cursor_hooks_payload_has_all_events(tmp_path: Path):
    ingest = tmp_path / "agentaudit_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    payload = cursor_hooks_payload(python="/usr/bin/python3", ingest=ingest)
    assert payload["version"] == 1
    assert "beforeShellExecution" in payload["hooks"]
    assert "cursor hook beforeShellExecution" in payload["hooks"]["beforeShellExecution"][0]["command"]


def test_install_cursor_global_hooks(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    ingest = repo / "scripts" / "agentaudit_ingest.py"
    ingest.parent.mkdir(parents=True)
    ingest.write_text("# stub", encoding="utf-8")

    home = tmp_path / "home"
    monkeypatch.setattr("core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_cursor_global_hooks(
        repo_root=repo,
        python="/usr/bin/python3",
        remove_project_hooks=False,
    )
    assert path == home / ".cursor" / "hooks.json"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "beforeShellExecution" in text
    assert "agentaudit_ingest.py" in text


def test_bootstrap_skips_when_ingest_missing(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("core.audit.hook_bootstrap.Path.home", lambda: tmp_path / "home")
    result = bootstrap_tier_b_hooks(repo_root=repo)
    assert result["cursor"] is None
