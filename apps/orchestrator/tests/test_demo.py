"""`agentmetry demo` is the first command a stranger runs, so it is tested as one.

It moved into the package because `pip install` does not ship `scripts/`. It
had also broken silently: 0.9.3's per-install token and host guard refused its
in-process client, and the script only redirected the trail file, so the
live-detection, disposition and audit databases it wrote (and the live store it
cleared) were the user's real ones.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from agentmetry import demo
from agentmetry.core.config import settings

_REPO = Path(__file__).resolve().parents[3]


def test_every_scenario_catches_the_attack_and_the_edit(capsys):
    assert demo.run("all", fast=True) == 0
    out = capsys.readouterr().out
    for rule_id in ("credential-exfil", "credential-read-then-cloud-api", "remote-staging-then-execute"):
        assert f"[CRITICAL] {rule_id}" in out
    assert "Secret value in the trail?   NO" in out
    assert "FAIL, record_sha256 mismatch" in out
    # The honest half: a re-hashed chain verifies, and only the head differs.
    assert "not the head recorded above" in out
    assert "agentmetry hooks install" in out


def test_the_demo_writes_nothing_outside_its_own_temp_dir(tmp_path: Path, monkeypatch, capsys):
    sentinel = tmp_path / "real-data-dir"
    sentinel.mkdir()
    monkeypatch.setenv("AGENTMETRY_DATA_DIR", str(sentinel))
    names = (*demo._PATH_SETTINGS, "auth_disabled", "trusted_hosts", "audit_sink", "dlp_mode")
    before = {name: getattr(settings, name) for name in names}

    assert demo.run("classic", fast=True) == 0

    assert list(sentinel.iterdir()) == []
    assert not Path(before["audit_export_path"]).exists()
    assert {name: getattr(settings, name) for name in names} == before
    assert os.environ["AGENTMETRY_DATA_DIR"] == str(sentinel)


def test_the_demo_runs_with_the_per_install_token_on(monkeypatch, capsys):
    # The default since 0.9.3, and what broke the script: every ingest was
    # refused and the failure surfaced later as a missing file.
    monkeypatch.setattr(settings, "auth_disabled", False)
    monkeypatch.setattr(settings, "trusted_hosts", "")
    assert demo.run("classic", fast=True) == 0
    assert settings.auth_disabled is False
    assert settings.trusted_hosts == ""


def test_the_cli_runs_it_and_lists_it_first(capsys):
    from agentmetry.cli import main

    assert main(["demo", "--fast"]) == 0
    assert "[CRITICAL] credential-exfil" in capsys.readouterr().out


def test_the_clone_wrapper_still_runs(tmp_path: Path):
    # scripts/make_demo_gif.py renders the README GIF from this script's output.
    env = {**os.environ, "AGENTMETRY_DATA_DIR": str(tmp_path), "AGENTMETRY_DEMO_FAST": "1"}
    done = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "demo.py")],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "[CRITICAL] credential-exfil" in done.stdout
    assert list(tmp_path.iterdir()) == []
