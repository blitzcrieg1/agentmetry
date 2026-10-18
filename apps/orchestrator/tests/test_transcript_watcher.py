"""The Antigravity transcript watcher lives and dies with the orchestrator that starts it.

Each restart of the orchestrator used to leave its watcher running: a hard stop
never reaches the lifespan teardown, and on Windows `terminate()` reaches only
the venv launcher. Three were found at once, each recording every Antigravity
tool call.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "antigravity_transcript_watcher.py"


def _load_watcher():
    spec = importlib.util.spec_from_file_location("antigravity_transcript_watcher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _env_with_empty_home(tmp_path: Path) -> dict[str, str]:
    # No ~/.gemini here, so the watcher finds no transcript and only idles.
    return {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}


def _wait_exit(proc: subprocess.Popen, seconds: float) -> int | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        time.sleep(0.1)
    return None


def test_the_watcher_exits_when_its_parent_closes_the_lifeline(tmp_path: Path):
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**_env_with_empty_home(tmp_path), "AGENTMETRY_WATCHER_LIFELINE": "1"},
    )
    try:
        assert _wait_exit(proc, 1.5) is None  # still running while the parent holds the pipe
        assert proc.stdin is not None
        proc.stdin.close()  # what the parent's death does to the pipe
        assert _wait_exit(proc, 10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_without_the_lifeline_a_closed_stdin_does_not_stop_a_watcher_run_by_hand(tmp_path: Path):
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={k: v for k, v in _env_with_empty_home(tmp_path).items() if k != "AGENTMETRY_WATCHER_LIFELINE"},
    )
    try:
        assert proc.stdin is not None
        proc.stdin.close()
        assert _wait_exit(proc, 2) is None
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_the_orchestrator_starts_the_watcher_on_a_lifeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from agentmetry.api import main

    calls: list[dict] = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append({"args": args, **kwargs})
            self.pid = 4242
            self.stdin = None

    monkeypatch.setattr(main.subprocess, "Popen", FakePopen)
    main.start_transcript_watcher(tmp_path / "watcher.py")
    assert calls[0]["stdin"] is subprocess.PIPE
    assert calls[0]["env"]["AGENTMETRY_WATCHER_LIFELINE"] == "1"


def test_stopping_closes_the_lifeline_before_terminating():
    from agentmetry.api.main import stop_transcript_watcher

    events: list[str] = []

    class Pipe:
        def close(self):
            events.append("close")

    class Proc:
        stdin = Pipe()

        def terminate(self):
            events.append("terminate")

    stop_transcript_watcher(Proc())
    assert events == ["close", "terminate"]


def test_the_watcher_gives_its_hooks_a_longer_timeout_and_keeps_the_lifeline(monkeypatch: pytest.MonkeyPatch):
    watcher = _load_watcher()
    seen: list[dict[str, str]] = []

    class FakePopen:
        returncode = 0

        def __init__(self, args, **kwargs):
            seen.append(kwargs["env"])

        def communicate(self, input=None):  # noqa: A002
            return b"", b""

    monkeypatch.setattr(watcher.subprocess, "Popen", FakePopen)
    monkeypatch.delenv("AGENTMETRY_INGEST_TIMEOUT", raising=False)
    monkeypatch.setenv("AGENTMETRY_WATCHER_LIFELINE", "1")
    line = json.dumps({
        "type": "PLANNER_RESPONSE",
        "source": "MODEL",
        "tool_calls": [{"name": "default_api:search_web", "args": {"query": "x"}}],
    })
    watcher.process_line(line, "conv-1")
    assert seen[0]["AGENTMETRY_INGEST_TIMEOUT"] == watcher.INGEST_TIMEOUT_SECONDS
    assert seen[0]["AGENTMETRY_ADAPTER"] == "antigravity_transcript"
    assert "AGENTMETRY_WATCHER_LIFELINE" not in seen[0]


def test_an_operator_set_timeout_wins(monkeypatch: pytest.MonkeyPatch):
    watcher = _load_watcher()
    seen: list[dict[str, str]] = []

    class FakePopen:
        returncode = 0

        def __init__(self, args, **kwargs):
            seen.append(kwargs["env"])

        def communicate(self, input=None):  # noqa: A002
            return b"", b""

    monkeypatch.setattr(watcher.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("AGENTMETRY_INGEST_TIMEOUT", "30")
    line = json.dumps({"type": "PLANNER_RESPONSE", "source": "MODEL", "tool_calls": [{"name": "view_file", "args": {}}]})
    watcher.process_line(line, "conv-1")
    assert seen[0]["AGENTMETRY_INGEST_TIMEOUT"] == "30"
