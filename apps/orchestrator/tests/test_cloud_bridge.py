"""Tests for the Cloud Bridge mappers: Cursor Cloud Agents API and the
Claude Compliance API.

Fixtures are shaped from each vendor's documented payloads. The privacy
contract under test: tool arguments and results never appear in a mapped
payload — only their hash, size and shape.
"""

from __future__ import annotations

import json


from agentmetry.core.audit.cloud_bridge import (
    decode_maybe_encoded,
    hash_arguments,
    map_claude_messages,
    map_claude_session,
    map_claude_tool_use,
    map_cursor_agent,
    map_cursor_stream_tool_call,
    map_outbound_poll,
)


# --- Cursor: agent + runs ----------------------------------------------------


def test_cursor_agent_maps_lifecycle_and_outcome():
    payloads = map_cursor_agent(
        {"id": "ag_1", "name": "fix login", "status": "ACTIVE"},
        runs=[
            {"id": "run_1", "status": "FINISHED", "durationMs": 42000,
             "git": {"branches": [{"repoUrl": "https://github.com/acme/repo", "branch": "cursor/fix-1", "prUrl": "https://github.com/acme/repo/pull/9"}]}},
        ],
    )
    assert payloads[0]["source_app"] == "cursor_cloud"
    assert payloads[0]["event_type"] == "session_start"
    assert payloads[0]["reason"] == "cloud_agent:ACTIVE"
    run = payloads[1]
    assert run["event_type"] == "session_end"
    assert "pr:yes" in run["reason"] and "branches:1" in run["reason"]


def test_outbound_poll_keeps_the_host_and_drops_the_key():
    payload = map_outbound_poll(
        "cursor_cloud",
        "GET",
        "https://api.cursor.com/v1/agents?token=super-secret",
    )
    text = json.dumps(payload)
    assert payload["tool"]["command"] == "GET api.cursor.com/v1/agents"
    assert "super-secret" not in text
    assert "Bearer" not in text
    assert payload["reason"] == "outbound poll; key sent and not stored"


def test_cursor_run_status_passes_through_as_outcome():
    payloads = map_cursor_agent({"id": "ag_2", "status": "IDLE"}, runs=[{"id": "r", "status": "ERROR"}])
    assert payloads[1]["outcome"] == "error"


# --- Cursor: live stream tool calls ------------------------------------------


def test_stream_tool_call_hashes_arguments_and_drops_content():
    call = {"callId": "c1", "name": "run_terminal_cmd", "status": "completed",
            "args": {"command": "cat ~/.aws/credentials"}, "result": "the secret contents"}
    payload = map_cursor_stream_tool_call(call, "ag_1", "run_1")
    tool = payload["tool"]
    assert tool["qualified"] == "cursor_cloud.run_terminal_cmd"
    assert len(tool["input_hash"]) == 64
    assert "credentials" not in json.dumps(payload)
    assert "secret contents" not in json.dumps(payload)
    assert tool["input_size"] > 0


def test_stream_tool_call_accepts_encoded_string_args():
    """Some streams deliver args as an encoded string; decoding happens for
    classification, and the hash must match the same args as an object."""
    as_object = {"command": "pytest -q"}
    as_encoded = {"args": json.dumps(as_object), "name": "run_terminal_cmd", "status": "completed"}
    p1 = map_cursor_stream_tool_call({**as_encoded}, "ag", "run")
    p2 = map_cursor_stream_tool_call({"name": "run_terminal_cmd", "args": as_object}, "ag", "run")
    assert p1["tool"]["input_hash"] == p2["tool"]["input_hash"]


# --- Claude Compliance API ----------------------------------------------------


def test_claude_tool_use_decodes_json_encoded_input():
    """The Compliance API delivers tool_use.input as a JSON-encoded string,
    not an object (documented). The mapper must decode before hashing."""
    input_obj = {"file_path": "src/app.py", "edits": 2}
    block = {"type": "tool_use", "id": "t1", "name": "str_replace_editor",
             "input": json.dumps(input_obj), "truncated": False}
    payload = map_claude_tool_use(block, "sess-1")
    tool = payload["tool"]
    assert tool["qualified"] == "claude_cloud.str_replace_editor"
    assert tool["input_hash"] == hash_arguments(input_obj)
    assert tool["truncated"] is False
    dumped = json.dumps(payload)
    assert "src/app.py" not in dumped and "app.py" not in dumped


def test_claude_tool_use_with_unparseable_input_still_records():
    block = {"type": "tool_use", "id": "t2", "name": "weird_tool", "input": "not json at all"}
    payload = map_claude_tool_use(block, "sess-1")
    assert payload["tool"]["qualified"] == "claude_cloud.weird_tool"
    assert len(payload["tool"]["input_hash"]) == 64


def test_claude_messages_keep_only_tool_use_blocks():
    """Text, thinking and system content are dropped at the mapper: the
    transcript's words stay under the vendor's retention policy, while the
    sequence of tool calls belongs in the customer's trail."""
    messages = {"data": [
        {"id": "m1", "role": "user", "content": [{"type": "text", "text": "please fix the bug"}]},
        {"id": "m2", "role": "assistant", "content": [
            {"type": "text", "text": "On it."},
            {"type": "tool_use", "id": "t9", "name": "read_file", "input": "{\"path\": \"a.py\"}"},
        ]},
        {"id": "m3", "role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t9", "name": "read_file", "is_error": False,
             "content": [{"type": "text", "text": "file contents here"}]},
        ]},
    ]}
    payloads = map_claude_messages({"id": "sess-9"}, messages)
    assert len(payloads) == 1
    assert payloads[0]["tool"]["qualified"] == "claude_cloud.read_file"
    assert "file contents here" not in json.dumps(payloads)
    assert "please fix the bug" not in json.dumps(payloads)


def test_claude_session_maps_metadata_only():
    payload = map_claude_session({"id": "sess-3", "created_at": "2026-10-01T10:00:00Z"})
    assert payload["event_type"] == "session_start"
    assert payload["reason"] == "cloud_session:2026-10-01"


# --- Encoded payloads ---------------------------------------------------------


def test_decode_handles_base64_wrapped_json():
    import base64
    wrapped = base64.b64encode(json.dumps({"k": 1}).encode()).decode()
    assert decode_maybe_encoded(wrapped) == {"k": 1}


def test_decode_returns_plain_strings_untouched():
    assert decode_maybe_encoded("just a command") == "just a command"


# --- Hash sync with the hook client -------------------------------------------


def test_hash_arguments_matches_the_hook_client():
    """A cloud event and a local event carrying the same call must hash
    identically, or cross-surface sequence detection silently splits."""
    from agentmetry.hooks.ingest import hash_arguments as hook_hash

    args = {"command": "git push origin main", "path": "src/x.py"}
    assert hash_arguments(args) == hook_hash(args)


# --- The command itself ---------------------------------------------------------


def _drive_cloud_claude(monkeypatch, argv):
    """Run `agentmetry cloud claude` with the vendor and the ingest stubbed out.

    The mapper tests above never reached the command, which is how it shipped
    reading an `args.remote` the parser did not define: every run with a key
    set raised AttributeError before the first request.
    """
    import httpx

    import agentmetry.core.audit.cloud_bridge as bridge
    from agentmetry.cli import main

    kinds: list[str] = []

    def fake_sessions(api_key, kind="local", base=bridge.CLAUDE_DEFAULT_BASE, limit=20):
        kinds.append(kind)
        return [{"id": "sess-1", "created_at": "2026-10-20T09:00:00Z"}]

    def fake_messages(api_key, kind, session_id, base=bridge.CLAUDE_DEFAULT_BASE, limit=500):
        return {"data": [{"content": [{"type": "tool_use", "name": "Bash", "input": '{"command": "ls"}'}]}]}

    posted: list[dict] = []

    class _Resp:
        status_code = 200
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        posted.append(json)
        return _Resp()

    monkeypatch.setenv("ANTHROPIC_COMPLIANCE_KEY", "test-compliance-key")
    monkeypatch.setattr(bridge, "fetch_claude_sessions", fake_sessions)
    monkeypatch.setattr(bridge, "fetch_claude_messages", fake_messages)
    monkeypatch.setattr(httpx, "post", fake_post)
    return main(argv), kinds, posted


def test_cloud_claude_runs_and_reads_local_sessions_by_default(monkeypatch):
    code, kinds, posted = _drive_cloud_claude(monkeypatch, ["cloud", "claude"])
    assert code == 0
    assert kinds == ["local"]
    # The outbound poll, the session, and its one tool call.
    assert [p["event_type"] for p in posted] == ["tool_called", "session_start", "tool_called"]
    assert "test-compliance-key" not in json.dumps(posted)


def test_cloud_claude_remote_flag_reads_remote_sessions(monkeypatch):
    code, kinds, posted = _drive_cloud_claude(monkeypatch, ["cloud", "claude", "--remote"])
    assert code == 0
    assert kinds == ["remote"]
    assert posted[0]["tool"]["command"].endswith("/v1/compliance/apps/sessions/remote")
