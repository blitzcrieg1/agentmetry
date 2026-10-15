"""GitHub Copilot: the CLI and VS Code agent mode, through one hooks file.

The two surfaces read the same `~/.copilot/hooks/*.json` and disagree on the
wire. The CLI sends camelCase input and reads a flat `permissionDecision`; VS
Code sends Claude-style snake_case and reads only the nested
`hookSpecificOutput.permissionDecision`. A JSON deny that is right for one is an
allow on the other, which is the Codex failure (#246) arriving twice.

So a Copilot deny is exit code 2 with the reason on stderr, the one signal both
document, and these tests pin that rather than a JSON shape. The VS Code facts
below are from microsoft/vscode at a113dd1: `hookExecutor.ts` maps exit 2 to a
blocking error and any other non-zero to a non-blocking one, and `hookTypes.ts`
lists the lowerCamel event names it accepts from a Copilot CLI file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402

from agentmetry.core.audit import hook_bootstrap as hb  # noqa: E402
from agentmetry.core.audit.tool_policy.evaluator import _extract_command  # noqa: E402
from agentmetry.core.diagnostics import hook_coverage  # noqa: E402

#: VS Code's Copilot-format event aliases (`hookTypes.ts`). An event key outside
#: this set would be silently ignored by VS Code even though the CLI runs it.
VSCODE_COPILOT_ALIASES = {
    "sessionStart", "sessionEnd", "userPromptSubmitted", "preToolUse",
    "postToolUse", "agentStop", "subagentStop", "errorOccurred",
}

CLI_PRE = {
    "sessionId": "s-cli",
    "timestamp": 1791900000000,
    "cwd": "/repo",
    "toolName": "bash",
    "toolArgs": json.dumps({"command": "rm -rf /tmp/x"}),
}
# Copilot CLI 1.0.97, run on 2026-10-14, sent toolArgs as an object, not a
# JSON string. The string form is still what the older docs show.
CLI_PRE_OBJECT = {**CLI_PRE, "toolArgs": {"command": "rm -rf /tmp/x"}}
VSCODE_PRE = {
    "timestamp": "2026-10-13T12:00:00Z",
    "hook_event_name": "PreToolUse",
    "session_id": "s-vsc",
    "tool_name": "run_in_terminal",
    "tool_input": {"command": "rm -rf /tmp/x"},
    "tool_use_id": "t1",
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.setattr(ingest, "tool_policy_eval", None)
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "copilot")
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)


def _block(monkeypatch, rule_id: str = "block_shell_rm"):
    monkeypatch.setattr(
        ingest,
        "tool_policy_eval",
        lambda *a, **k: SimpleNamespace(
            matched=True, blocked=True, mode="block",
            match=SimpleNamespace(rule_id=rule_id, action="deny"),
        ),
    )


def _run(monkeypatch, capsys, data: dict, hook: str = "PreToolUse") -> tuple[int, str, str]:
    monkeypatch.setattr(ingest, "read_hook_stdin", lambda: (dict(data), False))
    code = ingest.hook_main(hook)
    out = capsys.readouterr()
    return code, out.out, out.err


# --- mapping both payloads ---------------------------------------------------


@pytest.mark.parametrize("data", [CLI_PRE, CLI_PRE_OBJECT, VSCODE_PRE], ids=["cli-string", "cli-object", "vscode"])
def test_both_payloads_map_to_a_shell_call(data):
    payload = ingest.map_copilot_hook("PreToolUse", data)
    assert payload["source_app"] == "copilot"
    assert payload["event_type"] == "approval_request"
    assert payload["tool"]["qualified"] == "shell.run"
    assert payload["session_id"] in ("s-cli", "s-vsc")


def test_cli_tool_args_sent_as_a_json_string_are_parsed():
    payload = ingest.map_copilot_hook("PreToolUse", CLI_PRE)
    assert payload["tool"]["arguments"]["command"] == "rm -rf /tmp/x"


def test_a_failed_cli_result_is_not_recorded_as_success():
    data = {**CLI_PRE, "toolResult": {"resultType": "failure", "textResultForLlm": "boom"}}
    assert ingest.map_copilot_hook("PostToolUse", data)["outcome"] == "error"


def test_a_cli_result_the_user_denied_is_recorded_as_denied():
    data = {**CLI_PRE, "toolResult": {"resultType": "denied", "textResultForLlm": ""}}
    assert ingest.map_copilot_hook("PostToolUse", data)["outcome"] == "denied"


def test_session_lifecycle_maps():
    assert ingest.map_copilot_hook("SessionStart", {"sessionId": "s"})["event_type"] == "session_start"
    assert ingest.map_copilot_hook("SessionEnd", {"sessionId": "s"})["event_type"] == "session_end"
    assert ingest.map_copilot_hook("Stop", {"session_id": "s"})["event_type"] == "session_end"


def test_tool_policy_sees_the_command_in_cli_tool_args():
    """Copilot CLI's `toolArgs` was in none of the containers tool policy read,
    so a command_pattern rule would have matched nothing on it."""
    assert _extract_command(CLI_PRE) == "rm -rf /tmp/x"
    assert _extract_command(CLI_PRE_OBJECT) == "rm -rf /tmp/x"


# --- the deny is an exit code ------------------------------------------------


@pytest.mark.parametrize(
    "data", [CLI_PRE, CLI_PRE_OBJECT, VSCODE_PRE], ids=["cli-string", "cli-object", "vscode"]
)
def test_a_policy_block_exits_2_with_the_reason_on_stderr(monkeypatch, capsys, data):
    _block(monkeypatch)
    code, out, err = _run(monkeypatch, capsys, data)
    assert code == 2, "VS Code fails open on any other non-zero code"
    assert "tool_policy:block_shell_rm" in err
    assert "permission" not in out, "Cursor's key is read by neither Copilot surface"


def test_a_lower_camel_event_name_in_the_payload_still_enforces(monkeypatch, capsys):
    """The CLI names events in lowerCamel. Read as-is, `preToolUse` was not a
    pre-execution hook, and a block would have been recorded and not enforced."""
    _block(monkeypatch)
    code, _, _ = _run(monkeypatch, capsys, {**CLI_PRE, "hookEventName": "preToolUse"})
    assert code == 2


def test_a_cursor_event_is_still_judged_by_its_own_name():
    """The lowerCamel normalisation must not capitalise Cursor's names away."""
    assert ingest._is_blocking_hook("beforeShellExecution", {}) is True
    assert ingest._is_blocking_hook("afterShellExecution", {}) is False


def test_a_block_on_an_after_hook_is_recorded_not_enforced(monkeypatch, capsys):
    _block(monkeypatch)
    code, out, err = _run(monkeypatch, capsys, {**CLI_PRE, "toolResult": {"resultType": "success"}}, "PostToolUse")
    assert code == 0
    assert err == ""


@pytest.mark.parametrize("enforce,expected", [("deny", 2), ("ask", 2), ("allow", 0)])
def test_the_enforce_override_never_sends_an_ask(monkeypatch, capsys, enforce, expected):
    """Neither surface is trusted to honour an ask from here, and an ask that is
    not honoured is an allow, so ask is enforced as deny."""
    monkeypatch.setenv("AGENTMETRY_ENFORCE", enforce)
    code, out, _ = _run(monkeypatch, capsys, VSCODE_PRE)
    assert code == expected
    assert out.strip() == ""


def test_an_unremarkable_call_exits_0_and_prints_nothing(monkeypatch, capsys):
    code, out, err = _run(monkeypatch, capsys, VSCODE_PRE)
    assert (code, out.strip(), err) == (0, "", "")


# --- the installer -------------------------------------------------------------


def test_every_installed_event_is_one_vs_code_accepts():
    keys = {key for key, _ in hb.COPILOT_HOOK_EVENTS}
    assert keys <= VSCODE_COPILOT_ALIASES, keys - VSCODE_COPILOT_ALIASES


def test_the_document_is_copilot_cli_format_with_both_shells():
    doc = hb.copilot_hooks_document(python="/usr/bin/python3", ingest=Path("/x/agentmetry_ingest.py"))
    assert doc["version"] == 1, "VS Code detects the CLI format by this field"
    for key, event in hb.COPILOT_HOOK_EVENTS:
        (entry,) = doc["hooks"][key]
        assert entry["type"] == "command", "VS Code skips an entry without it"
        assert entry["bash"].endswith(f"copilot hook {event}")
        # Under `powershell -Command`, a leading quoted path is a string, not a
        # call. Without `&` the hook exits non-zero and VS Code fails open.
        assert entry["powershell"] == "& " + entry["bash"]
        assert entry["timeoutSec"] == 10


def test_the_pre_tool_hook_passes_the_name_enforcement_keys_on():
    """The installed argument must be PascalCase: `PreToolUse` is in the set of
    pre-execution hooks, and the payload may carry no event name at all."""
    doc = hb.copilot_hooks_document(python="py", ingest=Path("i.py"))
    assert doc["hooks"]["preToolUse"][0]["bash"].endswith("copilot hook PreToolUse")


def test_install_writes_its_own_file_and_coverage_attests_it(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path / ".copilot"))
    monkeypatch.setattr(hb, "hook_target", lambda *_a, **_k: "repo")
    mine = tmp_path / ".copilot" / "hooks" / "mine.json"
    mine.parent.mkdir(parents=True)
    mine.write_text('{"version": 1, "hooks": {}}', encoding="utf-8")

    path = hb.install_copilot_global_hooks(repo_root=tmp_path)
    assert path == tmp_path / ".copilot" / "hooks" / "agentmetry.json"
    assert mine.read_text(encoding="utf-8") == '{"version": 1, "hooks": {}}', "a user's own file is not ours"
    assert hook_coverage.coverage()["copilot"] == hook_coverage.COVERED
