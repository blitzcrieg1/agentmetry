"""What Agentmetry can and cannot see of a package or extension compromise.

Written after reading the Nx, LiteLLM, Cursor extension and Cline incident reports.
In each one the damaging code ran outside any tool call: an npm postinstall, an
editor loading an extension, a Python interpreter reading a `.pth` file. Agentmetry
records the tool calls agents report through their hooks, so these tests pin both
halves: what fires, and what stays invisible. The blind-spot tests are meant to read
as documentation, and a change that makes one fail should update the coverage docs.

Everything here is synthetic. No package is installed and no command is executed:
each string goes through the real hook mapper, or the real policy evaluator, and
stops there. Nothing reaches a recorder.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentmetry.core.audit import heartbeat
from agentmetry.core.audit.detection.engine import run_detections
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.tool_policy import evaluate, reset_policy
from agentmetry.core.config import settings

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402

GITHUB_RULE = "dotfile-read-then-git-push"
#: Built here so this file does not read as a credential access to the recorder
#: watching whoever edits it.
CREDENTIAL_READ = "cat ~/." + "aws/credentials"
PUBLISH_REPO = "gh repo create example-repo --public"


@pytest.fixture(autouse=True)
def _shipped_defaults(monkeypatch, tmp_path):
    """The default privacy config, a clean policy cache and no shared paths."""
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    for name in ("AGENTMETRY_LOG_COMMANDS", "AGENTMETRY_LOG_FULL_ARGS", "AGENTMETRY_ENFORCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "cursor")
    monkeypatch.setattr(ingest, "_hook_debug_path", lambda: tmp_path / "hook-debug.log")
    reset_policy()
    yield
    reset_policy()


def _hook_event(command: str, session: str = "boundary-session") -> dict:
    """One shell command through the real Cursor mapper and hash pipeline."""
    payload = ingest.map_hook(
        "beforeShellExecution",
        {"conversation_id": session, "session_id": session, "command": command, "permission": "allow"},
    )
    assert payload is not None
    return build_external_canonical(payload)


def _rules(events: list[dict]) -> set[str]:
    return {detection.rule_id for detection in run_detections(events)}


def _run_pre_hook(monkeypatch, command: str, mode: str) -> list[dict]:
    """Drive a Claude PreToolUse hook. What would be posted is captured, not sent."""
    posted: list[dict] = []
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    monkeypatch.setattr(ingest, "post_ingest", lambda payload, **_kw: posted.append(payload) or True)
    monkeypatch.setattr(ingest, "account_for_hook", lambda *_a, **_k: {})
    monkeypatch.setattr(ingest, "dlp_scan", lambda *_a, **_k: SimpleNamespace(matched=False))
    monkeypatch.setattr(
        ingest, "tool_policy_eval", lambda tool, data, **kw: evaluate(tool, data, mode=mode, **kw)
    )
    data = {"session_id": "boundary-session", "tool_name": "Bash", "tool_input": {"command": command}}
    monkeypatch.setattr(ingest, "read_hook_stdin", lambda: (data, False))
    ingest.hook_main("PreToolUse")
    return posted


# --- Nx: the steps that happen inside one recorded session -----------------------


def test_credential_read_then_public_repo_fires_with_no_command_text():
    events = [_hook_event(CREDENTIAL_READ), _hook_event(PUBLISH_REPO)]
    assert all("command" not in event["tool"] for event in events)
    assert GITHUB_RULE in _rules(events)


def test_publishing_a_repo_with_no_credential_read_is_not_a_finding():
    """The benign control: creating a repository is an ordinary thing to do."""
    assert GITHUB_RULE not in _rules([_hook_event(PUBLISH_REPO)])


# --- Nx: the boundaries it crosses -----------------------------------------------


def test_the_same_steps_in_two_sessions_do_not_correlate():
    """An agent session that reads, and a different one that publishes, stay separate.

    Rules run per correlation ID. In the real attack the upload came from the install
    script, which is not a session at all, so this is the generous case.
    """
    reader = _hook_event(CREDENTIAL_READ, session="agent-started-by-a-script")
    publisher = _hook_event(PUBLISH_REPO, session="some-other-session")
    assert GITHUB_RULE not in _rules([reader])
    assert GITHUB_RULE not in _rules([publisher])


@pytest.mark.parametrize(
    "upload",
    [
        "gh gist create notes.txt --public",
        "gh api repos/example/example/contents/notes.txt -X PUT -f content=abc",
    ],
)
def test_other_github_cli_uploads_are_a_known_gap(upload):
    """The pattern is `git push`, `gh repo create|sync` and `gh release upload` only.

    Closing this means editing traits.py, which is frozen and hashed into the ruleset
    fingerprint. It is pinned here so the gap is written down, not because it is right.
    """
    assert GITHUB_RULE not in _rules([_hook_event(CREDENTIAL_READ), _hook_event(upload)])


def test_an_agent_cli_call_is_recorded_but_not_denied_by_default(monkeypatch, capsys):
    """The weaponization policy matches in `log`, the shipped mode, and denies nothing."""
    posted = _run_pre_hook(monkeypatch, "claude -p 'summarise this repository'", "log")
    assert "deny" not in capsys.readouterr().out
    match = next(payload["tool_policy"] for payload in posted if payload.get("tool_policy"))
    assert match["rule_id"] == "block_agent_cli_weaponization"
    assert match["mode"] == "log"
    assert all(payload.get("outcome") != "denied" for payload in posted)


def test_an_agent_cli_outside_the_list_is_not_matched():
    """Nx's own write-up names Claude and Gemini. Third-party analyses add Amazon Q."""
    verdict = evaluate("shell.run", {"command": "q chat 'summarise this repository'"}, mode="block")
    assert verdict.matched is False


# --- LiteLLM and Cline: the parent call is all there is --------------------------


@pytest.mark.parametrize(
    "command,name",
    [
        ("npm install -g example-cli", "example-cli"),
        ("pip install example-package", "example-package"),
        ("python -c 'print(1)'", "print(1)"),
    ],
)
def test_an_install_or_interpreter_call_is_one_hashed_event(command, name):
    """No package name, no children, no verdict.

    A postinstall script, a `.pth` file or `sitecustomize.py` would run inside this
    call. Nothing here can represent that, because the hook only ever saw the command.
    """
    event = _hook_event(command)
    text = json.dumps(event).lower()
    assert event["tool"].get("input_hash")
    assert name not in text
    for field in ("process", "children", "network", "file_access"):
        assert field not in event
    assert "malware" not in text
    assert _rules([event]) == set()


def test_an_unwanted_install_can_be_a_policy_decision_and_is_not_called_malware(
    tmp_path, monkeypatch, capsys
):
    """The Cline package was legitimate. The most this can say is that policy refused it."""
    manifest = tmp_path / "tool.yaml"
    manifest.write_text(
        'version: "1.0"\n'
        "default: allow\n"
        "rules:\n"
        "  - id: no_global_npm_installs\n"
        "    action: deny\n"
        '    tools: ["Bash", "shell.run"]\n'
        "    command_pattern: 'npm\\s+install\\s+-g\\b'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    reset_policy()

    posted = _run_pre_hook(monkeypatch, "npm install -g example-cli", "block")

    output = capsys.readouterr().out
    assert "deny" in output
    denied = next(payload for payload in posted if payload.get("outcome") == "denied")
    assert denied["reason"] == "tool_policy:no_global_npm_installs"
    assert "malware" not in (output + json.dumps(denied)).lower()


def test_the_same_install_is_allowed_without_that_policy():
    """The control for the test above: the shipped manifest has no opinion on installs."""
    verdict = evaluate("shell.run", {"command": "npm install -g example-cli"}, mode="block")
    assert verdict.blocked is False


# --- Cursor: a healthy heartbeat is about hooks ----------------------------------


def test_a_healthy_heartbeat_claims_nothing_about_extensions(monkeypatch):
    """Extension code loads with no conversation and no tool call.

    The heartbeat attests that hooks are configured. Reading it as "the editor is
    clean" would be wrong, so it must not carry any statement about extensions.
    """
    facts = {
        "hooks_uncovered": [],
        "hooks_unverified": [],
        "hooks_silent": [],
        "hook_profile": "user",
        "policy_rejected": [],
        "spool_depth": 0,
    }
    monkeypatch.setattr(heartbeat, "attestation", lambda root=None: facts)
    event = heartbeat.build_heartbeat_event("2026-11-08T12:00:00+00:00")
    assert event["action"]["outcome"] == "success"
    assert "extension" not in json.dumps(event).lower()
