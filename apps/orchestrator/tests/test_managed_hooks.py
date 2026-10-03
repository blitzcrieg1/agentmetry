"""Hooks in the vendors' admin-managed locations (pilot hardening item 26).

Every test writes under tmp_path: `managed_paths` is patched, so nothing here
can touch Program Files, ProgramData or /etc on the machine running the suite.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from agentmetry.core.audit import hook_bootstrap as hb
from agentmetry.core.audit import managed_hooks as mh


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    p = {
        "claude": tmp_path / "ClaudeCode" / "managed-settings.d" / mh.CLAUDE_DROPIN,
        "cursor": tmp_path / "Cursor" / "hooks.json",
        "codex": tmp_path / "OpenAI" / "Codex" / "requirements.toml",
    }
    monkeypatch.setattr(mh, "managed_paths", lambda: p)
    return p


def _ours(command: str, app: str) -> bool:
    return mh._is_ours(command, app)


# --- where the vendors read them ---------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows locations")
def test_the_windows_locations_are_the_documented_ones(monkeypatch):
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    assert str(mh.claude_managed_dir()) == r"C:\Program Files\ClaudeCode", "ProgramData is the legacy path Claude no longer reads"
    assert str(mh.cursor_enterprise_hooks()) == r"C:\ProgramData\Cursor\hooks.json"
    assert str(mh.codex_requirements()) == r"C:\ProgramData\OpenAI\Codex\requirements.toml"


# --- Claude Code -------------------------------------------------------------


def test_the_claude_dropin_hooks_every_event(paths):
    path = mh.install("claude")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc["hooks"]) == set(hb.CLAUDE_HOOK_EVENTS)
    for groups in doc["hooks"].values():
        assert any(_ours(h["command"], "claude") for g in groups for h in g["hooks"])
    assert "allowManagedHooksOnly" not in doc, "locking out other hooks is the administrator's call"


def test_lock_allows_managed_hooks_only(paths):
    doc = json.loads(mh.install("claude", lock=True).read_text(encoding="utf-8"))
    assert doc["allowManagedHooksOnly"] is True


def test_the_dropin_is_its_own_file_not_the_shared_policy(paths):
    assert paths["claude"].parent.name == "managed-settings.d"
    assert paths["claude"].name != "managed-settings.json"


# --- Cursor ------------------------------------------------------------------


def test_cursor_keeps_other_enterprise_hooks_and_is_idempotent(paths):
    paths["cursor"].parent.mkdir(parents=True)
    paths["cursor"].write_text(json.dumps({
        "version": 1, "hooks": {"beforeShellExecution": [{"command": "C:/corp/dlp.exe"}]},
    }), encoding="utf-8")
    mh.install("cursor")
    mh.install("cursor")
    doc = json.loads(paths["cursor"].read_text(encoding="utf-8"))
    shell = doc["hooks"]["beforeShellExecution"]
    assert {"command": "C:/corp/dlp.exe"} in shell, "another team's hook survives"
    assert sum(_ours(e["command"], "cursor") for e in shell) == 1, "a re-run replaces ours"
    assert set(hb.CURSOR_HOOK_EVENTS) <= set(doc["hooks"])


def test_an_unparseable_cursor_file_is_never_clobbered(paths):
    paths["cursor"].parent.mkdir(parents=True)
    paths["cursor"].write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        mh.install("cursor")
    assert paths["cursor"].read_text(encoding="utf-8") == "{ not json"


# --- Codex -------------------------------------------------------------------


def _codex_commands(doc: dict) -> dict[str, list[str]]:
    return {event: [h["command"] for g in groups for h in g["hooks"]] for event, groups in doc["hooks"].items()}


def test_a_new_codex_requirements_file_parses_and_hooks_every_event(paths):
    doc = tomllib.loads(mh.install("codex", lock=True).read_text(encoding="utf-8"))
    assert doc["allow_managed_hooks_only"] is True
    assert doc["features"]["hooks"] is True
    commands = _codex_commands(doc)
    assert {e for e, _ in hb.CODEX_HOOK_EVENTS} <= set(commands)
    assert all(any(_ours(c, "codex") for c in cs) for cs in commands.values())


def test_an_existing_codex_policy_is_kept_and_not_duplicated(paths):
    paths["codex"].parent.mkdir(parents=True)
    paths["codex"].write_text(
        'allowed_approval_policies = ["on-request"]\n\n[features]\nweb_search = false\n\n'
        '[[hooks.PreToolUse]]\nmatcher = "^Bash$"\n[[hooks.PreToolUse.hooks]]\n'
        'type = "command"\ncommand = "corp-check"\n',
        encoding="utf-8",
    )
    mh.install("codex", lock=True)
    mh.install("codex", lock=True)
    text = paths["codex"].read_text(encoding="utf-8")
    doc = tomllib.loads(text)
    assert doc["allowed_approval_policies"] == ["on-request"]
    assert doc["features"] == {"web_search": False}, "someone else's [features] table is not edited"
    pre = _codex_commands(doc)["PreToolUse"]
    assert "corp-check" in pre
    assert sum(_ours(c, "codex") for c in pre) == 1
    assert text.count(mh.CODEX_BEGIN) == 1
    assert text.count("allow_managed_hooks_only") == 1


def test_a_codex_file_that_does_not_parse_is_left_alone(paths):
    paths["codex"].parent.mkdir(parents=True)
    paths["codex"].write_text("[broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        mh.install("codex")
    assert paths["codex"].read_text(encoding="utf-8") == "[broken\n"


# --- status and the CLI ------------------------------------------------------


def test_status_tells_absent_from_managed_from_broken(paths):
    assert mh.status("claude") == "absent"
    mh.install("claude")
    assert mh.status("claude") == "managed"
    paths["claude"].write_text("{", encoding="utf-8")
    assert mh.status("claude") == "broken"


def test_the_cli_installs_and_reports(paths, capsys):
    from agentmetry.cli import main

    assert main(["hooks", "install", "--managed"]) == 0
    assert main(["hooks", "status", "--managed"]) == 0
    out = capsys.readouterr().out
    assert out.count("managed ") >= 3
    assert main(["hooks", "install", "--managed", "--agent", "kimi"]) == 2


def test_no_admin_rights_is_reported_not_crashed(paths, monkeypatch, capsys):
    from agentmetry.cli import main

    def denied(*_a, **_k):
        raise PermissionError("access denied")

    monkeypatch.setattr(mh, "_write", denied)
    assert main(["hooks", "install", "--managed", "--agent", "claude"]) == 1
    assert "administrator" in capsys.readouterr().err
