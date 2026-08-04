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


# ----------------------------------------------------------------------
# Registered is not the same claim as working
# ----------------------------------------------------------------------


def test_the_module_autostart_launches_actually_exists():
    """The bug this section exists for, in one assertion.

    A refactor moved every module under a top-level `agentmetry` package.
    `launch_command()` was updated; the already-registered scheduled task was
    not, so it kept running `-m cli serve`, exited 1 every sixty seconds for a
    day, and `status()` reported `configured=True` throughout. Sixty events
    spooled behind it.

    Asserting the literal string `agentmetry.cli` would not have caught it, so
    this resolves the module the same way the interpreter will.
    """
    import importlib.util

    _executable, args, _workdir = autostart.launch_command()
    module = args[args.index("-m") + 1]
    assert importlib.util.find_spec(module) is not None, (
        f"autostart would launch `-m {module}`, which is not importable"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Last Result:  0", 0),
        ("Last Result: 1", 1),
        ("Last Result:  267011", 267011),
        ("Last Result:  0x41303", 0x41303),
        ("Last Result:  -1", -1),
        ("Task Name: x\nLast Result:  2\nStatus: Ready", 2),
        ("Status: Ready", None),
        ("Last Result:  (not a number)", None),
    ],
)
def test_parse_last_result(text, expected):
    assert autostart._parse_last_result(text) == expected


def _fake_schtasks(monkeypatch, verbose_stdout: str) -> None:
    """Stub both the existence query and the verbose one."""
    monkeypatch.setattr(autostart.shutil, "which", lambda _n: "schtasks")

    class _Result:
        def __init__(self, stdout=""):
            self.returncode = 0
            self.stdout = stdout
            self.stderr = ""

    def fake_run(argv, **_kwargs):
        return _Result(verbose_stdout if "/V" in argv else "")

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)


@pytest.mark.skipif(os.name != "nt", reason="schtasks probe is Windows-only")
def test_status_reports_a_registered_task_that_keeps_failing(monkeypatch):
    _fake_schtasks(monkeypatch, "Status: Ready\nLast Result:  1")
    state = autostart.status()
    assert state.configured is True, "the task is registered; that part was never false"
    assert state.healthy is False
    assert state.last_result == 1
    assert "agentmetry install" in state.detail, "say how to fix it, not just that it broke"


@pytest.mark.skipif(os.name != "nt", reason="schtasks probe is Windows-only")
def test_a_running_recorder_is_healthy_whatever_the_last_result_says(monkeypatch):
    """The regression that nearly shipped inside the fix for the original bug.

    Last Result records the last *launch attempt*, not the health of a task
    that stays up. Every repeating trigger that fires while the recorder is
    alive is refused by MultipleInstancesPolicy=IgnoreNew and logged as a
    non-zero code, so a working recorder shows one almost all the time. The
    first draft of this check read that as a fault, which would have meant
    doctor failing permanently on a correct install. An alarm that is always on
    gets muted, and a muted alarm cannot warn about anything.

    -2147020576 (0x800710E0) is the code observed on a real machine while the
    recorder was up and serving on 127.0.0.1:8000.
    """
    _fake_schtasks(monkeypatch, "Status: Running\nLast Result:  -2147020576")
    state = autostart.status()
    assert state.healthy is True


@pytest.mark.skipif(os.name != "nt", reason="schtasks probe is Windows-only")
def test_a_task_that_has_never_run_is_not_a_failure(monkeypatch):
    """0x41303 is Task Scheduler for "no run history yet", which is the normal
    state between registering and the first trigger."""
    _fake_schtasks(monkeypatch, "Status: Ready\nLast Result:  267011")
    state = autostart.status()
    assert state.healthy is True


@pytest.mark.skipif(os.name != "nt", reason="schtasks probe is Windows-only")
def test_a_disabled_task_will_not_restart_anything(monkeypatch):
    """Registered, zero last result, and completely inert."""
    _fake_schtasks(
        monkeypatch,
        "Status: Ready\nLast Result:  0\nScheduled Task State: Disabled",
    )
    state = autostart.status()
    assert state.configured is True
    assert state.healthy is False
    assert "disabled" in state.detail.lower()


@pytest.mark.skipif(os.name != "nt", reason="schtasks probe is Windows-only")
def test_unreadable_run_history_is_unknown_rather_than_broken(monkeypatch):
    """Localized Windows will not print "Last Result". Reporting a fault we
    cannot see would teach the operator to ignore the field."""
    _fake_schtasks(monkeypatch, "Letzte Ausführung: 1")
    state = autostart.status()
    assert state.configured is True
    assert state.healthy is None


def test_doctor_fails_a_registration_that_does_not_work(monkeypatch):
    """Nobody chooses this state, and from the outside it looks identical to a
    working one. That makes it a failure rather than a warning."""
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_autostart

    monkeypatch.setattr(
        autostart,
        "status",
        lambda: autostart.AutostartStatus(
            True, "schtasks", "registered, but its last run exited 1", healthy=False, last_result=1
        ),
    )
    report = DoctorReport()
    _check_autostart(report)
    entry = [f for f in report.findings if f.code == "autostart"][0]
    assert entry.severity == "fail"


def test_doctor_still_passes_when_health_is_unknown(monkeypatch):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_autostart

    monkeypatch.setattr(
        autostart,
        "status",
        lambda: autostart.AutostartStatus(True, "schtasks", "registered", healthy=None),
    )
    report = DoctorReport()
    _check_autostart(report)
    entry = [f for f in report.findings if f.code == "autostart"][0]
    assert entry.severity == "ok"
