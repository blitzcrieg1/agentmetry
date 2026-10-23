"""Cursor cloud-agent tool calls read from the desktop app's cache.

The fixture database copies the shape read off a real Cursor state database on
2026-10-21: `composerData:<id>` rows, one of them carrying
`createdFromBackgroundAgent.bcId`, and `bubbleId:<composer>:<bubble>` rows
holding `toolFormerData` with JSON-string params and results. The contents are
invented; only the shape is real.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agentmetry.core.audit import cursor_cloud_cache as cache
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.hooks import ingest

BC_ID = "bc-11111111-2222-3333-4444-555555555555"
CLOUD = "c0ffee00-0000-0000-0000-000000000001"
LOCAL = "c0ffee00-0000-0000-0000-000000000002"
SECRET = "sk-test-abcdefghijklmnopqrstuvwx"


@pytest.fixture(autouse=True)
def _default_config(monkeypatch):
    """Run as a fresh install would: no command text, no full arguments."""
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    for name in ("AGENTMETRY_LOG_COMMANDS", "AGENTMETRY_LOG_FULL_ARGS", "AGENTMETRY_HASH_KEY",
                 "AGENTMETRY_SOURCE_APP", "AGENTMETRY_ADAPTER"):
        monkeypatch.delenv(name, raising=False)


def _tool(name, status, params=None, result=None, call_id=None):
    return {
        "toolFormerData": {
            "name": name,
            "status": status,
            "toolCallId": call_id or f"call-{name}-{status}",
            "params": json.dumps(params) if params is not None else None,
            "rawArgs": None,
            "result": json.dumps(result) if result is not None else None,
        },
        "createdAt": "2026-08-22T17:54:36.452Z",
        "type": 2,
    }


def _make_db(path: Path, bubbles: list[tuple[str, object]]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    con.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    con.execute(
        "INSERT INTO cursorDiskKV VALUES (?, ?)",
        (f"composerData:{CLOUD}", json.dumps({"createdFromBackgroundAgent": {"bcId": BC_ID, "shouldStreamMessages": True}})),
    )
    con.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"composerData:{LOCAL}", json.dumps({"name": "local chat"})))
    for i, (composer, body) in enumerate(bubbles):
        value = body if isinstance(body, str) else json.dumps(body)
        con.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"bubbleId:{composer}:b{i}", value))
    con.commit()
    con.close()
    return path


@pytest.fixture()
def db(tmp_path):
    return _make_db(tmp_path / "state.vscdb", [
        (CLOUD, _tool("run_terminal_command_v2", "completed",
                      {"command": f"curl -H 'Authorization: Bearer {SECRET}' https://example.com", "cwd": "/workspace"},
                      {"output": "secret output", "exitCode": 0})),
        (CLOUD, _tool("run_terminal_command_v2", "error", {"command": "make test"}, {"output": "boom", "exitCode": 2})),
        (CLOUD, _tool("read_file_v2", "completed", {"targetFile": "/workspace/.env", "path": "/workspace/.env"}, {"contents": SECRET})),
        (CLOUD, _tool("edit_file_v2", "completed", {"path": "/workspace/app.py", "streamContent": SECRET, "cloudAgentEdit": True})),
        (CLOUD, _tool("mcp-cursor-ide-browser-browser_navigate", "completed", {"url": "https://example.com"})),
        (CLOUD, _tool("run_terminal_command_v2", "cancelled", {"command": "sleep 100"}, {"rejected": False})),
        (CLOUD, _tool("web_fetch", "loading", {"url": "https://example.com"})),
        (CLOUD, {"text": "a plain message bubble, no tool"}),
        (CLOUD, "not json at all"),
        (LOCAL, _tool("run_terminal_command_v2", "completed", {"command": "ls"}, call_id="local-call")),
    ])


def _payloads(db_path):
    con = cache.open_readonly(db_path)
    try:
        return [cache.to_payload(c) for cid, bc in cache.iter_cloud_composers(con) for c in cache.iter_tool_calls(con, cid, bc)]
    finally:
        con.close()


def test_only_conversations_streamed_from_a_cloud_agent_are_read(db):
    con = cache.open_readonly(db)
    assert list(cache.iter_cloud_composers(con)) == [(CLOUD, BC_ID)]
    con.close()


def test_finished_calls_map_to_the_names_local_cursor_hooks_record(db):
    payloads = _payloads(db)
    assert [p["tool"]["qualified"] for p in payloads] == [
        "shell.run", "shell.run", "cursor.Read", "cursor.Write", "cursor.MCP:browser_navigate", "shell.run",
    ]
    for p in payloads:
        assert p["source_app"] == "cursor_cloud"
        assert p["adapter"] == "cursor_cloud_cache"
        assert p["correlation_id"] == f"cursor-cloud-{BC_ID}"
        assert p["session_id"] == BC_ID
        assert p["timestamp_utc"] == "2026-08-22T17:54:36.452Z"


def test_errors_and_cancellations_are_failures_not_successes(db):
    by_outcome = [(p["event_type"], p["outcome"], p.get("reason", "")) for p in _payloads(db)]
    assert by_outcome[1][:2] == ("tool_failed", "error")
    assert by_outcome[5] == ("tool_failed", "error", "cancelled")
    assert by_outcome[0][:2] == ("tool_called", "success")


def test_default_config_forwards_no_content(db):
    """Hashes, traits and ATT&CK labels leave the cache. Commands, paths'
    contents, results and edit bodies do not."""
    text = json.dumps(_payloads(db))
    assert SECRET not in text
    assert "secret output" not in text and "boom" not in text
    assert "make test" not in text and "curl" not in text
    for p in _payloads(db):
        assert "arguments" not in p["tool"]
        assert len(p["tool"]["input_hash"]) == 64


def test_the_command_still_drives_detection_labels(db):
    """Traits are computed from the command while it is still in this process."""
    curl = _payloads(db)[0]["tool"]
    assert curl.get("traits") or curl.get("mitre")


def test_an_edit_is_hashed_on_its_path_alone(db):
    """Two edits to one file with different bodies are the same input, as for a local `Write` hook."""
    edit = _payloads(db)[3]
    expected = ingest.hash_arguments({"path": "/workspace/app.py"})
    assert edit["tool"]["input_hash"] == expected


def test_payloads_survive_the_real_canonical_builder(db):
    for p in _payloads(db):
        event = build_external_canonical(dict(p))
        assert event["agent"]["name"] == "cursor_cloud"
        assert event["correlation_id"] == f"cursor-cloud-{BC_ID}"
        assert event["timestamp_utc"].startswith("2026-08-22T17:54:36")


def test_import_posts_once_and_a_second_run_posts_nothing(db, tmp_path):
    posted: list[dict] = []
    state = tmp_path / "data" / cache.STATE_FILE
    first = cache.import_cache(db, post=lambda p: posted.append(p) or True, state_path=state)
    assert (first.agents, first.calls, first.posted) == (1, 6, 6)
    assert first.skipped == {"not_finished": 1}
    second = cache.import_cache(db, post=lambda p: posted.append(p) or True, state_path=state)
    assert (second.posted, second.already_seen) == (0, 6)
    assert len(posted) == 6


def test_a_failed_post_is_retried_on_the_next_run(db, tmp_path):
    state = tmp_path / cache.STATE_FILE
    failed = cache.import_cache(db, post=lambda p: False, state_path=state)
    assert (failed.posted, failed.failed) == (0, 6)
    retried = cache.import_cache(db, post=lambda p: True, state_path=state)
    assert retried.posted == 6


def test_dry_run_posts_nothing_and_remembers_nothing(db, tmp_path):
    state = tmp_path / cache.STATE_FILE
    calls: list[dict] = []
    result = cache.import_cache(db, post=lambda p: calls.append(p) or True, state_path=state, dry_run=True)
    assert result.new == 6 and calls == [] and not state.exists()


def test_the_database_is_opened_read_only(db):
    con = cache.open_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO cursorDiskKV VALUES ('x', 'y')")
    con.close()


def test_cli_reports_a_missing_database(tmp_path, capsys):
    from agentmetry.cli import main

    assert main(["cloud", "cursor-cache", "--db", str(tmp_path / "nope.vscdb")]) == 2
    assert "No Cursor state database" in capsys.readouterr().out
