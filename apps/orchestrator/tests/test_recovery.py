"""Crash recovery: stale active-loop notes are classified and resolvable."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.execution.recovery import (
    archive_stale_resolved_loops,
    resolve_recovery,
    scan_archivable_loops,
    scan_recovery,
)
from core.memory.obsidian_client import ObsidianClient

_OLD = "2026-06-20T10:00:00+00:00"
_RECENT = "2026-07-06T10:00:00+00:00"
_NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def vault(tmp_path: Path) -> ObsidianClient:
    client = ObsidianClient(tmp_path)

    def loop_note(
        name: str,
        status: str,
        thread_id: str,
        *,
        created: str = _OLD,
        resolved: str = "",
    ) -> None:
        resolved_line = f"resolved: '{resolved}'\n" if resolved else ""
        (client.active_path / name).write_text(
            f"---\ntype: active-loop\nskill: lead_gen\nthread_id: {thread_id}\n"
            f"status: {status}\ncreated: '{created}'\n{resolved_line}---\n\n# Task\n",
            encoding="utf-8",
        )

    loop_note("crashed.md", "running", "t-crashed")
    loop_note("waiting-live.md", "awaiting_approval", "t-live")
    loop_note("waiting-stale.md", "awaiting_approval", "t-stale")
    loop_note("done-old.md", "completed", "t-done-old", resolved=_OLD)
    loop_note("done-recent.md", "completed", "t-done-recent", resolved=_RECENT)
    loop_note("failed.md", "failed", "t-failed", resolved=_OLD)
    return client


def test_scan_classifies_orphans_and_stale_approvals(vault: ObsidianClient):
    items = scan_recovery(client=vault, pending={"t-live": {}})
    by_thread = {item["thread_id"]: item["classification"] for item in items}

    assert by_thread == {
        "t-crashed": "orphan",
        "t-stale": "stale_approval",
    }
    # Healthy approval and terminal notes are untouched.
    assert "t-live" not in by_thread
    assert "t-done-recent" not in by_thread


def test_scan_archivable_selects_old_terminal_loops(vault: ObsidianClient):
    items = scan_archivable_loops(client=vault, max_age_days=7, now=_NOW)
    paths = {item["path"] for item in items}

    assert "20-Active-Loops/done-old.md" in paths
    assert "20-Active-Loops/failed.md" in paths
    assert "20-Active-Loops/done-recent.md" not in paths
    assert "20-Active-Loops/crashed.md" not in paths


def test_archive_stale_resolved_moves_to_archive(vault: ObsidianClient):
    archived = archive_stale_resolved_loops(client=vault, max_age_days=7, now=_NOW)

    assert set(archived) == {
        "20-Active-Loops/done-old.md",
        "20-Active-Loops/failed.md",
    }
    assert not (vault.active_path / "done-old.md").exists()
    assert (vault.archive_path / "active-loops" / "done-old.md").exists()
    assert (vault.archive_path / "active-loops" / "failed.md").exists()
    assert (vault.active_path / "done-recent.md").exists()
    assert scan_archivable_loops(client=vault, max_age_days=7, now=_NOW) == []


def test_resolve_mark_failed_rewrites_frontmatter(vault: ObsidianClient):
    items = scan_recovery(client=vault, pending={})
    orphan = next(i for i in items if i["classification"] == "orphan")

    assert resolve_recovery(orphan["path"], "mark_failed", client=vault) is True

    content = (vault.vault_path / orphan["path"]).read_text(encoding="utf-8")
    assert "status: failed" in content
    assert "Orphaned by crash" in content
    # Resolved notes disappear from the next scan.
    remaining = scan_recovery(client=vault, pending={})
    assert all(i["path"] != orphan["path"] for i in remaining)


def test_resolve_dismiss_and_unknown_inputs(vault: ObsidianClient):
    assert resolve_recovery("20-Active-Loops/waiting-stale.md", "dismiss", client=vault)
    content = (vault.vault_path / "20-Active-Loops/waiting-stale.md").read_text(
        encoding="utf-8"
    )
    assert "status: dismissed" in content

    assert resolve_recovery("20-Active-Loops/nope.md", "dismiss", client=vault) is False
    with pytest.raises(ValueError):
        resolve_recovery("20-Active-Loops/crashed.md", "explode", client=vault)


def test_relative_vault_path_still_resolves_loop_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: BLACKBOX_VAULT_PATH=../../vault orphaned every loop note.

    write_active_loop returned a relative path containing "..", and
    resolve_active_loop's traversal guard silently rejected it — so notes
    stayed 'running' forever, even for completed runs (32 accumulated live).
    """
    (tmp_path / "vault").mkdir()
    workdir = tmp_path / "app"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    client = ObsidianClient(Path("../vault"))  # relative, dot-dot — like .env.example
    loop = client.write_active_loop("t-rel", "lead_gen", "hello")
    client.resolve_active_loop(str(loop), "completed")

    assert "status: completed" in loop.read_text(encoding="utf-8")
