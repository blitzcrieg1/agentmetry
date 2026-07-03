"""Backup/restore: the ledger and data stores survive a round trip; zip-slip is refused."""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import pytest

from cli import create_backup, restore_backup


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    vault = repo / "vault"
    (vault / "10-Knowledge").mkdir(parents=True)
    (vault / "10-Knowledge" / "note.md").write_text("# knowledge", encoding="utf-8")
    (vault / "30-Archive").mkdir()
    (vault / "30-Archive" / "run.md").write_text("closeout", encoding="utf-8")

    data = repo / "apps" / "orchestrator" / "data"
    (data / "logs").mkdir(parents=True)
    (data / "logs" / "orchestrator.log").write_text("noise", encoding="utf-8")
    (data / "runs.jsonl").write_text('{"skill": "x"}\n', encoding="utf-8")
    (data / "blackbox.pid").write_text("123", encoding="utf-8")

    conn = sqlite3.connect(str(data / "telemetry.db"))
    with conn:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('alive')")
    conn.close()
    return repo


def test_backup_contents(fake_repo: Path, tmp_path: Path):
    out = create_backup(fake_repo, tmp_path / "b.zip")
    names = set(zipfile.ZipFile(out).namelist())

    assert "vault/10-Knowledge/note.md" in names
    assert "vault/30-Archive/run.md" in names          # gitignored runtime dir IS backed up
    assert "apps/orchestrator/data/runs.jsonl" in names
    assert "apps/orchestrator/data/telemetry.db" in names
    assert not any("logs" in n for n in names)          # log noise excluded
    assert not any(n.endswith(".pid") for n in names)


def test_roundtrip_restores_sqlite_and_vault(fake_repo: Path, tmp_path: Path):
    out = create_backup(fake_repo, tmp_path / "b.zip")

    target = tmp_path / "fresh"
    (target / "vault").mkdir(parents=True)
    restored = restore_backup(out, target)
    assert restored >= 4

    assert (target / "vault" / "30-Archive" / "run.md").read_text(encoding="utf-8") == "closeout"
    conn = sqlite3.connect(str(target / "apps" / "orchestrator" / "data" / "telemetry.db"))
    assert conn.execute("SELECT v FROM t").fetchone() == ("alive",)
    conn.close()


def test_restore_rejects_zip_slip(tmp_path: Path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("vault/../evil.txt", "pwned")

    target = tmp_path / "repo"
    target.mkdir()
    with pytest.raises(ValueError, match="outside allowed roots"):
        restore_backup(evil, target)
    assert not (target / "evil.txt").exists()


def test_restore_rejects_foreign_paths(tmp_path: Path):
    stray = tmp_path / "stray.zip"
    with zipfile.ZipFile(stray, "w") as zf:
        zf.writestr("apps/orchestrator/core/config.py", "malicious = True")

    with pytest.raises(ValueError, match="outside allowed roots"):
        restore_backup(stray, tmp_path / "repo2")
