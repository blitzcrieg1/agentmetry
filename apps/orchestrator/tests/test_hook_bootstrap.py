"""Tests for global Tier B hook bootstrap."""

from __future__ import annotations

from pathlib import Path

import json
import sys as bootstrap_sys

from agentmetry.core.audit.hook_bootstrap import (
    bootstrap_tier_b_hooks,
    cursor_hooks_payload,
    hook_command,
    hook_target,
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


def test_bootstrap_skips_when_no_target_is_reachable(tmp_path: Path, monkeypatch):
    """An absent repo script is no longer enough to make ingest unreachable.

    This asserted only that `scripts/agentmetry_ingest.py` was missing, which
    was the whole story when `repo` was the only target. `hook_target` now also
    answers `frozen` and `console`, so the test silently became a test of the
    developer's install shape: green on a venv predating the console-script
    entry point, red on any fresh `pip install -e .` where `agentmetry-hook`
    exists and bootstrap correctly installs.

    Neutralise all three the way `test_no_reachable_ingest_installs_nothing`
    does, so the test asserts what its name claims on any machine.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(bootstrap_sys, "frozen", False, raising=False)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap._console_script", lambda: None)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: tmp_path / "home")
    assert hook_target(repo) == "none"
    result = bootstrap_tier_b_hooks(repo_root=repo)
    assert result["cursor"] is None
    assert result["claude"] is None


def test_bootstrap_installs_from_a_wheel_with_only_the_console_script(
    tmp_path: Path, monkeypatch
):
    """The wheel case, which had no test of its own.

    A machine installed from a wheel has no checkout and no frozen binary, and
    before the console-script target it had no way to reach ingest at all: every
    installer bailed and the recorder ran unhooked. Nothing asserted the new
    path works. The only thing demonstrating it was a CI failure in the test
    above, which is not a test, it is a coincidence.
    """
    empty = tmp_path / "no-repo"
    empty.mkdir()
    home = tmp_path / "home"
    console = tmp_path / "bin" / "agentmetry-hook"
    console.parent.mkdir(parents=True)
    console.write_text("# stub", encoding="utf-8")

    monkeypatch.setattr(bootstrap_sys, "frozen", False, raising=False)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap._console_script", lambda: console)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)

    assert hook_target(empty) == "console"
    result = bootstrap_tier_b_hooks(repo_root=empty)
    # bootstrap_tier_b_hooks reports paths as strings, not Path objects.
    assert result["cursor"] == str(home / ".cursor" / "hooks.json")
    assert result["claude"] == str(home / ".claude" / "settings.json")

    # The command has to name the console script, or the config claims coverage
    # while invoking nothing, which is the failure this area keeps producing.
    written = (home / ".cursor" / "hooks.json").read_text(encoding="utf-8")
    assert "agentmetry-hook" in written


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


# ----------------------------------------------------------------------
# Reaching ingest from somewhere that is not a git checkout
# ----------------------------------------------------------------------


def test_a_checkout_still_writes_the_script_command(tmp_path: Path):
    """Unchanged for every developer machine, deliberately.

    On a checkout with an editable install all three targets resolve. Switching
    those machines to a different invocation would rewrite hook configs that
    already work, for no gain.
    """
    repo = _repo_with_ingest(tmp_path)
    assert hook_target(repo) == "repo"
    cmd = hook_command("cursor", "PreToolUse", python="/usr/bin/python3", repo_root=repo)
    assert cmd.endswith("cursor hook PreToolUse")
    assert "agentmetry_ingest.py" in cmd


def test_a_frozen_install_names_the_installed_binary(tmp_path: Path, monkeypatch):
    """The case that made fleet deployment impossible.

    An MSI machine has no checkout, so every installer bailed and the recorder
    ran with nothing able to reach it.
    """
    empty = tmp_path / "no-repo"
    empty.mkdir()
    monkeypatch.setattr(bootstrap_sys, "frozen", True, raising=False)
    monkeypatch.setattr(bootstrap_sys, "executable", "C:/Program Files/Agentmetry/agentmetry.exe")
    assert hook_target(empty) == "frozen"
    cmd = hook_command("cursor", "PreToolUse", repo_root=empty)
    assert "agentmetry.exe" in cmd
    assert cmd.endswith("hook cursor PreToolUse")


def test_no_reachable_ingest_installs_nothing(tmp_path: Path, monkeypatch):
    """Writing a config whose command cannot run would look exactly like
    coverage while recording nothing, which is the failure this whole area of
    the codebase keeps turning up."""
    empty = tmp_path / "no-repo"
    empty.mkdir()
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    monkeypatch.setattr(bootstrap_sys, "frozen", False, raising=False)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap._console_script", lambda: None)
    monkeypatch.setattr("agentmetry.core.audit.hook_bootstrap.Path.home", lambda: home)
    assert hook_target(empty) == "none"
    assert install_cursor_global_hooks(repo_root=empty) is None
    assert not (home / ".cursor" / "hooks.json").exists()


def test_every_invocation_form_is_recognised_as_ours(tmp_path: Path):
    """Idempotency and coverage both key on recognising our own command.

    A form the marker table does not know means a re-run duplicates our groups
    and `hook_coverage` reports a hooked agent as uncovered. The frozen form
    also puts the app name after `hook` rather than before it, so a marker
    keyed on "<app> hook" would miss it.
    """
    from agentmetry.core.audit.hook_bootstrap import _is_our_hook_group

    for cmd in (
        '"/usr/bin/python3" "/repo/scripts/agentmetry_ingest.py" cursor hook PreToolUse',
        '"/repo/scripts/agentaudit_ingest.py" cursor hook PreToolUse',
        '"/usr/bin/agentmetry-hook" cursor hook PreToolUse',
        '"C:/Program Files/Agentmetry/agentmetry.exe" hook cursor PreToolUse',
    ):
        group = {"hooks": [{"type": "command", "command": cmd}]}
        assert _is_our_hook_group(group), cmd
        assert _is_our_hook_group(group, source_app="cursor"), cmd
        assert not _is_our_hook_group(group, source_app="claude"), cmd


def test_coverage_shares_the_marker_table():
    """Two lists of what our command looks like is the drift that let the
    heartbeat check two agents while six installers existed."""
    from agentmetry.core.audit.hook_bootstrap import HOOK_COMMAND_TOKENS
    from agentmetry.core.diagnostics import hook_coverage

    assert hook_coverage._DEFAULT_MARKERS == HOOK_COMMAND_TOKENS
