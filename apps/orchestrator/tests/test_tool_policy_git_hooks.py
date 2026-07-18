"""Git hook persistence tool policy — shipped manifest, all IDE payload shapes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.audit.tool_policy import evaluate, reset_policy

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402

RULE_ID = "block_git_hook_persistence"


@pytest.fixture(autouse=True)
def _reset_tool_policy_cache():
    reset_policy()
    yield
    reset_policy()


@pytest.mark.parametrize(
    "ide,tool,payload",
    [
        (
            "cursor shell hooksPath",
            "shell.run",
            {"command": "git config core.hooksPath ./evil-hooks"},
        ),
        (
            "claude hook path write",
            "Edit",
            {"tool_input": {"file_path": "repo/.git/hooks/pre-commit", "content": "#!/bin/sh"}},
        ),
        (
            "codex post-merge hook",
            "Write",
            {"tool_input": {"path": ".git/hooks/post-merge"}},
        ),
        (
            "antigravity hook path write",
            "Write",
            {
                "toolCall": {
                    "name": "write_file",
                    "args": {"path": ".git/hooks/post-checkout"},
                }
            },
        ),
    ],
)
def test_git_hook_persistence_blocked(ide, tool, payload):
    verdict = evaluate(tool, payload, mode="block")
    assert verdict.blocked is True, f"not blocked for {ide}"
    assert verdict.match.rule_id == RULE_ID


@pytest.mark.parametrize(
    "label,tool,payload",
    [
        ("github workflow", "Edit", {"tool_input": {"file_path": ".github/workflows/ci.yml"}}),
        ("hooks readme", "Write", {"tool_input": {"path": "hooks/README.md"}}),
        ("normal commit", "Bash", {"command": "git commit -m 'fix'"}),
        ("pytest", "shell.run", {"tool_input": {"command": "pytest -q"}}),
    ],
)
def test_git_hook_benign_not_blocked(label, tool, payload):
    verdict = evaluate(tool, payload, mode="block")
    assert verdict.blocked is False, f"false positive: {label}"


def _run_hook(monkeypatch, hook_name: str, data: dict) -> None:
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    monkeypatch.setenv("AGENTMETRY_TOOL_POLICY_MODE", "block")
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.setattr(
        ingest,
        "tool_policy_eval",
        lambda tool, hook_data, **kw: evaluate(tool, hook_data, mode="block", **kw),
    )
    monkeypatch.setattr(ingest, "read_hook_stdin", lambda: (data, False))
    ingest.hook_main(hook_name)


def test_git_hook_denied_on_pre_hook(monkeypatch, capsys):
    _run_hook(
        monkeypatch,
        "PreToolUse",
        {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": ".git/hooks/pre-commit", "content": "#!/bin/sh"},
            "permissionDecision": "ask",
        },
    )
    assert '"permission": "deny"' in capsys.readouterr().out


def test_git_hook_not_denied_on_after_hook(monkeypatch, capsys):
    _run_hook(
        monkeypatch,
        "PostToolUse",
        {
            "session_id": "s1",
            "tool_name": "Edit",
            "tool_input": {"file_path": ".git/hooks/pre-commit", "content": "#!/bin/sh"},
            "exit_code": 0,
        },
    )
    assert "deny" not in capsys.readouterr().out
