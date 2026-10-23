"""Codex hooks must launch on Windows, whichever shell Codex uses.

The installer wrote `"C:\\...\\python.exe" "C:\\...\\agentmetry_ingest.py" codex
hook <Event>`. On the dogfood machine Codex reported every hook run as
completed while no Codex event arrived for three months: run through `cmd /c`
or `powershell -Command`, that quoted form exits 1 before Python starts. Codex
does not document which shell it uses, so on Windows the installer now writes
a command that runs under cmd, PowerShell and direct execution alike.

It writes it into `command` itself. The first version used Codex's
`commandWindows` override, and Codex then skipped every hook: its review
dialog hashes a hook without the override and its runtime hashes it with it,
so the approval never matches.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentmetry.core.audit import hook_bootstrap
from agentmetry.core.audit.hook_bootstrap import (
    CODEX_HOOK_EVENTS,
    merge_codex_hooks,
    windows_hook_command,
)

# --- the rewrite -------------------------------------------------------------------


def test_quoted_paths_without_spaces_lose_their_quotes():
    cmd = r'"C:\Python314\python.exe" "C:\repo\scripts\agentmetry_ingest.py" codex hook PreToolUse'
    assert windows_hook_command(cmd) == (
        r"C:\Python314\python.exe C:\repo\scripts\agentmetry_ingest.py codex hook PreToolUse"
    )


def test_the_frozen_and_console_forms_are_rewritten_too():
    assert windows_hook_command(r'"C:\Agentmetry\agentmetry.exe" hook codex Stop') == (
        r"C:\Agentmetry\agentmetry.exe hook codex Stop"
    )
    assert windows_hook_command(r'"C:\tools\agentmetry-ingest.exe" codex hook Stop') == (
        r"C:\tools\agentmetry-ingest.exe codex hook Stop"
    )


def test_a_path_with_a_space_takes_its_short_name(monkeypatch):
    monkeypatch.setattr(hook_bootstrap, "_short_path", lambda p: p.replace("Program Files", "PROGRA~1"))
    cmd = r'"C:\Program Files\Agentmetry\agentmetry.exe" hook codex Stop'
    assert windows_hook_command(cmd) == r"C:\PROGRA~1\Agentmetry\agentmetry.exe hook codex Stop"


def test_a_path_with_no_short_name_keeps_its_quotes(monkeypatch):
    """No worse than before: the original form, not a broken one."""
    monkeypatch.setattr(hook_bootstrap, "_short_path", lambda p: p)
    cmd = r'"C:\Program Files\Agentmetry\agentmetry.exe" hook codex Stop'
    assert windows_hook_command(cmd) == cmd


# --- the installer -----------------------------------------------------------------


def _merged(windows: bool) -> dict:
    return merge_codex_hooks(
        {}, python=r"C:\Python314\python.exe", ingest=Path(r"C:\repo\scripts\agentmetry_ingest.py"), windows=windows
    )


def test_on_windows_the_command_itself_is_the_unquoted_form():
    doc = _merged(windows=True)
    for event, _ in CODEX_HOOK_EVENTS:
        [handler] = doc["hooks"][event][0]["hooks"]
        assert '"' not in handler["command"]
        assert handler["command"].endswith(f"codex hook {event}")


def test_no_commandwindows_override_is_ever_written():
    """Codex's review dialog hashes a hook without `commandWindows`; its runtime
    hashes it with it. A hook carrying the override reads as modified after
    every approval and never runs. Measured against Codex 0.163 on Windows."""
    for windows in (True, False):
        doc = _merged(windows=windows)
        for event, _ in CODEX_HOOK_EVENTS:
            assert "commandWindows" not in doc["hooks"][event][0]["hooks"][0]


def test_elsewhere_the_command_keeps_its_quotes():
    doc = _merged(windows=False)
    [handler] = doc["hooks"]["Stop"][0]["hooks"]
    assert handler["command"].startswith('"')


def test_reinstalling_over_an_old_override_drops_it():
    doc = {"hooks": {"Stop": [{"hooks": [{
        "type": "command",
        "command": r'"C:\Python314\python.exe" "C:\repo\scripts\agentmetry_ingest.py" codex hook Stop',
        "commandWindows": r"C:\Python314\python.exe C:\repo\scripts\agentmetry_ingest.py codex hook Stop",
    }]}]}}
    merge_codex_hooks(
        doc, python=r"C:\Python314\python.exe", ingest=Path(r"C:\repo\scripts\agentmetry_ingest.py"), windows=True
    )
    [group] = doc["hooks"]["Stop"]
    assert "commandWindows" not in group["hooks"][0]


def test_reinstalling_replaces_rather_than_duplicates():
    doc = _merged(windows=True)
    merge_codex_hooks(
        doc, python=r"C:\Python314\python.exe", ingest=Path(r"C:\repo\scripts\agentmetry_ingest.py"), windows=True
    )
    for event, _ in CODEX_HOOK_EVENTS:
        assert len(doc["hooks"][event]) == 1


# --- it actually launches ---------------------------------------------------------


def _probe(tmp_path: Path, folder: str) -> tuple[Path, Path]:
    where = tmp_path / folder
    where.mkdir()
    marker = where / "ran.txt"
    script = where / "probe.py"
    script.write_text(
        "import sys, pathlib\n"
        f"pathlib.Path(r'{marker}').write_text(' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return script, marker


_SHELLS = {
    "cmd": lambda c: ["cmd", "/d", "/s", "/c", c],
    "powershell": lambda c: ["powershell", "-NoProfile", "-NonInteractive", "-Command", c],
}


@pytest.mark.skipif(os.name != "nt", reason="Windows shells")
@pytest.mark.parametrize("shell", sorted(_SHELLS))
def test_the_windows_command_runs_under_each_shell(tmp_path, shell):
    script, marker = _probe(tmp_path, "plain")
    command = windows_hook_command(f'"{sys.executable}" "{script}" codex hook SessionStart')
    done = subprocess.run(_SHELLS[shell](command), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.read_text(encoding="utf-8") == "codex hook SessionStart"


@pytest.mark.skipif(os.name != "nt", reason="Windows shells")
@pytest.mark.parametrize("shell", sorted(_SHELLS))
def test_a_path_with_a_space_still_runs(tmp_path, shell):
    script, marker = _probe(tmp_path, "with space")
    command = windows_hook_command(f'"{sys.executable}" "{script}" codex hook SessionStart')
    if '"' in command:
        pytest.skip("8.3 short names are disabled on this volume")
    done = subprocess.run(_SHELLS[shell](command), capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert marker.read_text(encoding="utf-8") == "codex hook SessionStart"
