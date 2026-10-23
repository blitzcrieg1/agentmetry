"""The dashboard demo holds seeded events only, and can be seeded again.

An outside audit (21 October) ran the demo twice and found both problems:
re-seeding left the old `.chain` sidecar behind, so the fresh trail continued
from the old head and verified as broken; and every recorder started the
Antigravity transcript watcher, which reads the presenter's real transcripts
into a trail that is supposed to be synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agentmetry.api import main as api_main
from agentmetry.core.audit.trail_chain import GENESIS_SHA256, chain_sidecar_path, verify_trail_file
from agentmetry.core.config import settings

_REPO = Path(__file__).resolve().parents[3]


def _seed(path: Path, data_dir: Path) -> None:
    env = {**os.environ, "AGENTMETRY_DATA_DIR": str(data_dir)}
    done = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "seed_demo.py"), "--path", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=180, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_seeding_twice_still_verifies(tmp_path):
    trail = tmp_path / "demo" / "demo-trail.jsonl"
    _seed(trail, tmp_path / "data")
    first = verify_trail_file(trail)
    assert first.ok, first
    assert chain_sidecar_path(trail).is_file()

    _seed(trail, tmp_path / "data")
    second = verify_trail_file(trail)
    assert second.ok, second
    first_line = json.loads(trail.read_text(encoding="utf-8").splitlines()[0])
    assert first_line["trail"]["prev_sha256"] == GENESIS_SHA256, "a reseed must start the chain over"


# --- the transcript watcher ----------------------------------------------------


def test_the_watcher_runs_on_a_recorder_that_accepts_ingest(monkeypatch):
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.delenv("AGENTMETRY_ANTIGRAVITY_WATCHER", raising=False)
    assert api_main.antigravity_watcher_wanted() is True


def test_the_watcher_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    for value in ("0", "false", "no", "off", " OFF "):
        monkeypatch.setenv("AGENTMETRY_ANTIGRAVITY_WATCHER", value)
        assert api_main.antigravity_watcher_wanted() is False, value


def test_a_recorder_that_refuses_ingest_starts_no_watcher(monkeypatch):
    """The static demo runs with ingest off; a watcher there has nowhere honest to send."""
    monkeypatch.setattr(settings, "audit_ingest_enabled", False)
    monkeypatch.delenv("AGENTMETRY_ANTIGRAVITY_WATCHER", raising=False)
    assert api_main.antigravity_watcher_wanted() is False


def test_the_demo_launcher_turns_the_watcher_off():
    """Live or static, the demo's trail is synthetic, so the launcher says so explicitly."""
    source = (_REPO / "scripts" / "demo_dashboard.py").read_text(encoding="utf-8")
    assert '"AGENTMETRY_ANTIGRAVITY_WATCHER": "0"' in source
