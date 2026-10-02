"""Phase A of the ask-gate: a policy rule can ask, and the agent's own prompt asks.

The one failure this phase must not have is an ask that quietly becomes an
allow. Every vendor that does not recognise the ask value treats the hook as
having said nothing, and the tool runs. So most of these tests are about the
places an ask is NOT honoured, and that each of them is enforced as deny.

The loader tests cover the same failure from the other end. Until now an
unrecognised action was dropped and an unrecognised default became `allow`, so
writing `action: ask` before this release did nothing, and writing
`default: ask` allowed everything.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentmetry.core.audit.tool_policy import capability
from agentmetry.core.audit.tool_policy import evaluator as tp_evaluator
from agentmetry.core.audit.tool_policy.loader import load_tool_policy
from agentmetry.core.config import settings

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402


def _manifest(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --- loader: ask is a real action, and nothing unrecognised fails open --------


def test_ask_is_loaded_as_ask(tmp_path):
    rules, _ = load_tool_policy(
        _manifest(tmp_path, "default: allow\nrules:\n  - id: r\n    action: ask\n    tools: [Bash]\n")
    )
    assert [r.action for r in rules] == ["ask"]


def test_an_unrecognised_action_is_loaded_as_deny_not_dropped(tmp_path, caplog):
    """Dropping it meant a rule the operator wrote silently did nothing."""
    with caplog.at_level(logging.WARNING):
        rules, _ = load_tool_policy(
            _manifest(tmp_path, "default: allow\nrules:\n  - id: typo\n    action: aks\n    tools: [Bash]\n")
        )
    assert [(r.id, r.action) for r in rules] == [("typo", "deny")]
    assert "unrecognised action" in caplog.text


def test_an_unrecognised_default_is_deny_not_allow(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        _, default = load_tool_policy(_manifest(tmp_path, "default: alow\nrules: []\n"))
    assert default == "deny"
    assert "unrecognised default" in caplog.text


def test_default_ask_is_deny_until_phase_b(tmp_path, caplog):
    """A reasonable guess after reading the spec, which used to allow everything."""
    with caplog.at_level(logging.WARNING):
        _, default = load_tool_policy(_manifest(tmp_path, "default: ask\nrules: []\n"))
    assert default == "deny"
    assert "not supported" in caplog.text


def test_a_missing_default_is_still_allow(tmp_path):
    _, default = load_tool_policy(_manifest(tmp_path, "rules: []\n"))
    assert default == "allow"


def test_the_shipped_manifest_is_unaffected():
    """The fail-closed change must not alter a default install."""
    rules, default = load_tool_policy(Path(settings.tool_policy_path))
    assert default == "allow"
    assert rules and all(r.action in ("allow", "deny") for r in rules)


# --- evaluator: deny beats ask beats allow ------------------------------------


@pytest.fixture
def policy(tmp_path, monkeypatch):
    def _load(body: str):
        monkeypatch.setattr(settings, "tool_policy_path", _manifest(tmp_path, body))
        tp_evaluator.reset_policy()

    yield _load
    tp_evaluator.reset_policy()


def _bash(command: str) -> dict:
    return {"tool_input": {"command": command}}


def test_an_ask_rule_asks(policy):
    policy("default: allow\nrules:\n  - id: ask_curl\n    action: ask\n    tools: [Bash]\n"
           "    command_pattern: curl\n")
    v = tp_evaluator.evaluate("Bash", _bash("curl https://x"), mode="block")
    assert (v.matched, v.blocked, v.ask) == (True, False, True)
    assert v.match.rule_id == "ask_curl"


def test_deny_outranks_ask(policy):
    policy("default: allow\nrules:\n"
           "  - id: ask_curl\n    action: ask\n    tools: [Bash]\n    command_pattern: curl\n"
           "  - id: no_curl\n    action: deny\n    tools: [Bash]\n    command_pattern: curl\n")
    v = tp_evaluator.evaluate("Bash", _bash("curl https://x"), mode="block")
    assert (v.blocked, v.ask, v.match.rule_id) == (True, False, "no_curl")


def test_ask_outranks_a_broader_allow(policy):
    """Otherwise a general allow would quietly swallow the specific ask."""
    policy("default: deny\nrules:\n"
           "  - id: bash_ok\n    action: allow\n    tools: [Bash]\n"
           "  - id: ask_curl\n    action: ask\n    tools: [Bash]\n    command_pattern: curl\n")
    v = tp_evaluator.evaluate("Bash", _bash("curl https://x"), mode="block")
    assert (v.ask, v.match.rule_id) == (True, "ask_curl")


def test_unmatched_calls_are_unaffected(policy):
    policy("default: allow\nrules:\n  - id: ask_curl\n    action: ask\n    tools: [Bash]\n"
           "    command_pattern: curl\n")
    v = tp_evaluator.evaluate("Bash", _bash("ls"), mode="block")
    assert (v.matched, v.ask) == (False, False)


# --- the capability matrix ---------------------------------------------------


@pytest.mark.parametrize(
    ("source", "hook"),
    [("claude", "PreToolUse"), ("cursor", "beforeShellExecution"), ("cursor", "beforeMCPExecution")],
)
def test_where_an_ask_is_honoured(source, hook):
    assert capability.ask_honoured(source, hook) is True


@pytest.mark.parametrize(
    ("source", "hook", "why"),
    [
        ("cursor", "preToolUse", "documented: accepted by the schema, not enforced"),
        ("claude", "PermissionRequest", "documented: allow or deny only"),
        ("codex", "PermissionRequest", "documented: allow or deny only"),
        ("qwen", "PreToolUse", "Claude protocol, but the vendor is unverified"),
        ("antigravity", "PreToolUse", "unverified"),
        ("kimi", "PreToolUse", "unverified"),
    ],
)
def test_where_an_ask_is_not_honoured(source, hook, why):
    assert capability.ask_honoured(source, hook) is False, why


# --- through the real hook ---------------------------------------------------


@pytest.fixture
def run_hook(monkeypatch, capsys):
    posted: list[dict] = []
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda payload, **k: posted.append(dict(payload)) or True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)

    def _run(source: str, hook: str, data: dict, *, mode: str = "block"):
        monkeypatch.setenv("AGENTMETRY_SOURCE_APP", source)
        monkeypatch.setattr(
            ingest,
            "tool_policy_eval",
            lambda *a, **k: SimpleNamespace(
                matched=True,
                blocked=False,
                ask=True,
                mode=mode,
                match=SimpleNamespace(rule_id="ask_curl", action="ask"),
            ),
        )
        monkeypatch.setattr(ingest, "read_hook_stdin", lambda: (data, False))
        ingest.hook_main(hook)
        out = capsys.readouterr().out.strip()
        return (json.loads(out.splitlines()[-1]) if out else None), posted

    return _run


CLAUDE_CALL = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "curl https://x"}}
CURSOR_SHELL = {"conversation_id": "c1", "tool_name": "Shell", "command": "curl https://x"}


def test_claude_asks_through_its_own_prompt(run_hook):
    out, posted = run_hook("claude", "PreToolUse", CLAUDE_CALL)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "tool_policy:ask_curl"


def test_the_request_is_recorded_before_the_prompt(run_hook):
    """Spec 3.3. What the human decides is recorded afterwards, as today."""
    _, posted = run_hook("claude", "PreToolUse", CLAUDE_CALL)
    assert posted[-1]["event_type"] == "approval_request"
    assert posted[-1]["outcome"] == "pending"
    assert posted[-1]["reason"] == "tool_policy:ask_curl"


def test_cursor_shell_asks(run_hook):
    out, _ = run_hook("cursor", "beforeShellExecution", CURSOR_SHELL)
    assert out == {"permission": "ask"}


def test_cursor_pre_tool_use_is_enforced_as_deny(run_hook):
    """Cursor accepts ask on preToolUse and does not enforce it. That is an allow."""
    out, posted = run_hook("cursor", "preToolUse", CURSOR_SHELL)
    assert out == {"permission": "deny"}
    assert posted[-1]["outcome"] == "denied"
    assert "ask_unsupported:cursor/preToolUse" in posted[-1]["reason"]


def test_an_unverified_claude_protocol_agent_is_enforced_as_deny(run_hook):
    out, posted = run_hook("qwen", "PreToolUse", CLAUDE_CALL)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "ask_unsupported:qwen/PreToolUse" in posted[-1]["reason"]


def test_an_ask_on_an_after_hook_claims_nothing(run_hook):
    out, posted = run_hook("claude", "PostToolUse", {**CLAUDE_CALL, "exit_code": 0})
    assert out is None
    assert "tool_policy_ask_observed:ask_curl" in posted[-1]["reason"]


def test_log_mode_never_prompts(run_hook):
    out, _ = run_hook("claude", "PreToolUse", CLAUDE_CALL, mode="log")
    assert out is None


def test_without_the_matrix_every_ask_is_a_deny(run_hook, monkeypatch):
    """The import fallback fails closed."""
    monkeypatch.setattr(ingest, "ask_honoured", lambda *a: False)
    out, _ = run_hook("claude", "PreToolUse", CLAUDE_CALL)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- doctor ------------------------------------------------------------------


def _ask_findings(monkeypatch, body: str | None, tmp_path, mode: str = "block"):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_ask_gate

    if body is not None:
        monkeypatch.setattr(settings, "tool_policy_path", _manifest(tmp_path, body))
    monkeypatch.setattr(settings, "tool_policy_mode", mode)
    report = DoctorReport()
    _check_ask_gate(report)
    return [(f.severity, f.message) for f in report.findings]


def test_doctor_is_quiet_without_ask_rules(monkeypatch, tmp_path):
    findings = _ask_findings(monkeypatch, "default: allow\nrules: []\n", tmp_path)
    assert findings == [("ok", "No ask rules in the tool policy")]


def test_doctor_names_where_an_ask_prompts(monkeypatch, tmp_path):
    findings = _ask_findings(
        monkeypatch,
        "default: allow\nrules:\n  - id: r\n    action: ask\n    tools: [Bash]\n",
        tmp_path,
    )
    (severity, message), = findings
    assert severity == "ok"
    assert "claude PreToolUse" in message
    assert "never allowed" in message


def test_doctor_warns_when_ask_rules_cannot_fire(monkeypatch, tmp_path):
    findings = _ask_findings(
        monkeypatch,
        "default: allow\nrules:\n  - id: r\n    action: ask\n    tools: [Bash]\n",
        tmp_path,
        mode="log",
    )
    assert findings[-1][0] == "warn"
    assert "never prompt" in findings[-1][1]
