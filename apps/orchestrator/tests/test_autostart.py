"""Autostart — the recorder has to come back without a human.

`agentmetry install` existed for a while and nothing ever mentioned it. On the
machine where this suite was written it had never been run, so the hooks
captured into the spool for five days while the trail looked healthy. These
tests pin the two properties that would have caught it: the registration
actually asks for a restart policy, and `status()` tells the truth about whether
it exists.
"""

from __future__ import annotations

import os
import sys

import pytest

from agentmetry.core.diagnostics import autostart


def test_launch_command_avoids_a_shell_wrapper():
    """A cmd.exe in the middle means the restart policy watches the wrapper."""
    executable, args, workdir = autostart.launch_command()
    assert "cmd" not in os.path.basename(executable).lower()
    assert "127.0.0.1" in args, "an unattended recorder must not bind beyond loopback"
    assert (workdir / "agentmetry" / "api" / "main.py").is_file()


def test_autostart_runs_serve_not_uvicorn_directly():
    """Under pythonw.exe there is no console, so sys.stdout is None and
    uvicorn's logging setup dies before it serves anything. The task ran, exited
    1, and explained nothing. `cli serve` redirects the streams first."""
    _executable, args, _workdir = autostart.launch_command()
    assert args[:3] == ["-m", "agentmetry.cli", "serve"]
    assert "uvicorn" not in args


def test_packaged_builds_refuse_to_register_a_second_autostart(monkeypatch):
    """The installer already supervises a frozen build; racing it is worse than
    saying so."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(autostart.PackagedBuild):
        autostart.launch_command()

    ok, message = autostart.install()
    assert ok is False
    assert "packaged build" in message.lower()


def test_windows_task_keeps_alive_with_a_repeating_trigger():
    """The property that actually revives a dead recorder.

    RestartOnFailure does not do this, despite the name: it covers a task that
    fails to launch, not an action that starts fine and is killed later.
    Verified on a real machine — the recorder was killed, LastTaskResult was
    0xFFFFFFFF, and nothing came back. A repeating trigger plus IgnoreNew does
    the job: a repeat is a no-op while an instance lives, and a restart once it
    does not.
    """
    xml = autostart.render_windows_task_xml(user="EXAMPLE\\dev")
    assert "<Repetition>" in xml
    assert "<StopAtDurationEnd>false</StopAtDurationEnd>" in xml, (
        "a repetition that stops leaves the recorder dead after the window"
    )
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml, (
        "without IgnoreNew the repeat starts a second recorder every interval"
    )


def test_keepalive_does_not_wait_for_a_logon():
    """A logon trigger's repetition only engages once a logon fires.

    Someone installing autostart mid-session would otherwise have no keep-alive
    until they next logged out, which is precisely the window in which they
    decided they wanted one. The time trigger starts in the past so the repeat
    is live the moment the task is registered.
    """
    xml = autostart.render_windows_task_xml(user="EXAMPLE\\dev")
    assert "<TimeTrigger>" in xml
    assert f"<StartBoundary>{autostart.KEEPALIVE_EPOCH}</StartBoundary>" in xml
    assert xml.count("<Repetition>") == 2, "both triggers carry the repeat"


def test_windows_task_still_asks_for_restart_on_failure():
    """Kept as a second line for launch failures, which it does cover."""
    xml = autostart.render_windows_task_xml(user="EXAMPLE\\dev")
    assert "<RestartOnFailure>" in xml
    assert f"<Interval>PT{autostart.RESTART_INTERVAL_MINUTES}M</Interval>" in xml
    assert f"<Count>{autostart.RESTART_COUNT}</Count>" in xml
    # Unlimited runtime: a recorder that Task Scheduler kills after three days
    # is a recorder with a three-day memory.
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml
    assert "<LogonTrigger>" in xml
    assert "EXAMPLE\\dev" in xml


def test_windows_task_runs_unelevated_and_windowless():
    xml = autostart.render_windows_task_xml(user="EXAMPLE\\dev")
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml, (
        "an audit recorder should not ask for admin to watch one user's agents"
    )
    assert "<Hidden>true</Hidden>" in xml


def test_systemd_unit_restarts_always():
    unit = autostart.render_systemd_unit()
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit
    assert "cli serve" in unit and "--host 127.0.0.1" in unit


def test_launchd_plist_keeps_alive():
    plist = autostart.render_launchd_plist()
    assert "<key>KeepAlive</key>" in plist
    assert "<key>RunAtLoad</key>" in plist
    assert autostart.LAUNCH_LABEL in plist


def test_status_reports_absence_rather_than_guessing(monkeypatch):
    """The silent failure this whole module exists to prevent: not knowing."""
    if os.name == "nt":
        class _Result:
            returncode = 1
            stdout = ""
            stderr = "ERROR: The system cannot find the file specified."

        monkeypatch.setattr(autostart.shutil, "which", lambda _n: "schtasks")
        monkeypatch.setattr(autostart.subprocess, "run", lambda *_a, **_k: _Result())
    else:
        monkeypatch.setattr(
            autostart, "systemd_unit_path", lambda: autostart.Path("/nonexistent/x.service")
        )
        monkeypatch.setattr(
            autostart, "launchd_plist_path", lambda: autostart.Path("/nonexistent/x.plist")
        )

    state = autostart.status()
    assert state.configured is False
    assert state.detail, "an absent registration must say so, not return an empty string"


def test_doctor_warns_when_nothing_will_restart_the_recorder(monkeypatch):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_autostart

    monkeypatch.setattr(
        autostart, "status", lambda: autostart.AutostartStatus(False, "schtasks", "no task")
    )
    report = DoctorReport()
    _check_autostart(report)
    entry = [f for f in report.findings if f.code == "autostart"][0]
    assert entry.severity == "warn", "running by hand is a choice, not a failure"
    assert "agentmetry install" in entry.message


def test_doctor_is_quiet_when_autostart_is_configured(monkeypatch):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_autostart

    monkeypatch.setattr(
        autostart,
        "status",
        lambda: autostart.AutostartStatus(True, "schtasks", "registered"),
    )
    report = DoctorReport()
    _check_autostart(report)
    entry = [f for f in report.findings if f.code == "autostart"][0]
    assert entry.severity == "ok"
