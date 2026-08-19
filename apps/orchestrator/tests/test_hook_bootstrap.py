"""Tests for global Tier B hook bootstrap."""

from __future__ import annotations

from pathlib import Path

import json

from agentmetry.core.audit.hook_bootstrap import (
    bootstrap_tier_b_hooks,
    cursor_hooks_payload,
    install_claude_global_hooks,
    install_codex_global_hooks,
    install_cursor_global_hooks,
    merge_claude_hook_env,
    merge_claude_hooks,
    merge_codex_hooks,
)


def test_cursor_hooks_payload_has_all_events(tmp_path: Path):
    ingest = tmp_path / "agentmetry_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    payload = cursor_hooks_payload(python="/usr/bin/python3", ingest=ingest)
    assert payload["version"] == 1
    assert "beforeShellExecution" in payload["hooks"]
    assert "cursor hook beforeShellExecution" in payload["hooks"]["beforeShellExecution"][0]["command"]


def test_install_cursor_global_hooks(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    ingest = repo / "scripts" / "agentmetry_ingest.py"
    ingest.parent.mkdir(parents=True)
    ingest.write_text("# stub", encoding="utf-8")

    home = tmp_path / "home"
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_cursor_global_hooks(
        repo_root=repo,
        python="/usr/bin/python3",
        remove_project_hooks=False,
    )
    assert path == home / ".cursor" / "hooks.json"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "beforeShellExecution" in text
    assert "agentmetry_ingest.py" in text


def test_bootstrap_skips_when_ingest_missing(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: tmp_path / "home")
    result = bootstrap_tier_b_hooks(repo_root=repo)
    assert result["cursor"] is None
    assert result["claude"] is None


def _repo_with_ingest(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    ingest = repo / "scripts" / "agentmetry_ingest.py"
    ingest.parent.mkdir(parents=True)
    ingest.write_text("# stub", encoding="utf-8")
    return repo


def test_merge_claude_hooks_preserves_other_keys(tmp_path: Path):
    """Merging must NOT wipe theme/permissions/mcpServers (F: non-destructive)."""
    settings = {"theme": "dark", "permissions": {"allow": ["Bash"]}}
    merge_claude_hooks(settings, python="/usr/bin/python3", ingest=tmp_path / "x.py")
    assert settings["theme"] == "dark"
    assert settings["permissions"] == {"allow": ["Bash"]}
    assert "PreToolUse" in settings["hooks"]
    assert "claude hook PreToolUse" in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def test_merge_claude_hooks_preserves_user_hooks_and_is_idempotent(tmp_path: Path):
    ingest = tmp_path / "agentmetry_ingest.py"
    user_hook = {"hooks": [{"type": "command", "command": "echo mine"}]}
    settings = {"hooks": {"PreToolUse": [user_hook]}}

    merge_claude_hooks(settings, python="/py", ingest=ingest)
    pre = settings["hooks"]["PreToolUse"]
    assert user_hook in pre  # user's own hook survives
    assert len(pre) == 2

    # Running again must not duplicate our entry.
    merge_claude_hooks(settings, python="/py", ingest=ingest)
    pre2 = settings["hooks"]["PreToolUse"]
    ours = [g for g in pre2 if "agentmetry_ingest.py" in str(g)]
    assert len(ours) == 1
    assert user_hook in pre2


def test_install_claude_global_hooks_merges_existing_file(tmp_path: Path, monkeypatch):
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"theme": "dark"}), encoding="utf-8"
    )
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_claude_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path == home / ".claude" / "settings.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["theme"] == "dark"           # preserved
    assert "Stop" in written["hooks"]
    assert "agentmetry_ingest.py" in str(written["hooks"]["SessionStart"])


def test_install_claude_creates_file_when_absent(tmp_path: Path, monkeypatch):
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_claude_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path.is_file()
    assert "PreToolUse" in json.loads(path.read_text(encoding="utf-8"))["hooks"]


def test_install_claude_skips_unparseable_settings(tmp_path: Path, monkeypatch):
    """Never clobber a settings.json we cannot parse."""
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bad = home / ".claude" / "settings.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_claude_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path is None
    assert bad.read_text(encoding="utf-8") == "{ not valid json"  # untouched


def test_merge_claude_hook_env_from_orchestrator_dotenv(tmp_path: Path):
    repo = tmp_path / "repo"
    env_path = repo / "apps" / "orchestrator" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("AGENTMETRY_TOOL_POLICY_MODE=block\n", encoding="utf-8")
    settings = {"theme": "dark"}
    merge_claude_hook_env(settings, repo_root=repo)
    assert settings["env"]["AGENTMETRY_TOOL_POLICY_MODE"] == "block"
    assert settings["theme"] == "dark"


# ----------------------------------------------------------------------
# Codex, the surface that had no installer at all
# ----------------------------------------------------------------------


def test_codex_hooks_carry_absolute_paths(tmp_path: Path, monkeypatch):
    """The shipped adapter template says `python scripts/agentmetry_ingest.py`,
    which only resolves when Codex happens to start in the repo root. An
    installer that copied that verbatim would work on the maintainer's machine
    and nowhere else."""
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_codex_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path == home / ".codex" / "hooks.json"
    cmd = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert str(repo) in cmd and "codex hook PreToolUse" in cmd


def test_codex_install_preserves_user_groups_and_is_idempotent(tmp_path: Path):
    """~/.codex/hooks.json is the developer's file. Re-running the installer must
    not duplicate our groups, and must not evict theirs."""
    ingest = tmp_path / "agentmetry_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    theirs = {"matcher": ".*", "hooks": [{"type": "command", "command": "their-own-linter"}]}
    doc = {"hooks": {"PreToolUse": [theirs]}}

    merge_codex_hooks(doc, python="/usr/bin/python3", ingest=ingest)
    merge_codex_hooks(doc, python="/usr/bin/python3", ingest=ingest)

    groups = doc["hooks"]["PreToolUse"]
    assert theirs in groups
    ours = [g for g in groups if "agentmetry_ingest" in json.dumps(g)]
    assert len(ours) == 1


def test_codex_stop_has_no_matcher_but_the_rest_do(tmp_path: Path):
    ingest = tmp_path / "agentmetry_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    doc = merge_codex_hooks({}, python="/usr/bin/python3", ingest=ingest)
    assert doc["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear"
    assert "matcher" not in doc["hooks"]["Stop"][0]


def test_codex_install_skips_an_unparseable_file(tmp_path: Path, monkeypatch):
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "hooks.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    assert install_codex_global_hooks(repo_root=repo, python="/usr/bin/python3") is None
    assert (home / ".codex" / "hooks.json").read_text(encoding="utf-8") == "{not json"


def test_codex_is_not_installed_at_orchestrator_boot(tmp_path: Path, monkeypatch):
    """Codex trusts hooks by hash and skips untrusted ones silently, so a boot
    install nobody asked for would look installed and capture nothing. Cursor
    and Claude self-install; Codex is a decision with a human step attached."""
    repo = _repo_with_ingest(tmp_path)
    home = tmp_path / "home"
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    bootstrap_tier_b_hooks(repo_root=repo)
    assert not (home / ".codex").exists()
