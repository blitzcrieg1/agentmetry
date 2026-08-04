"""Keep the recorder running across logouts, reboots, and crashes.

A flight recorder that only records while someone remembers to start it is not a
flight recorder. This module registers the orchestrator with whatever the
platform uses for user-scoped background work, and — just as importantly —
reports whether that registration actually exists.

The reporting half is the part that was missing, and it is the part that cost
real data. `agentmetry install` has existed for a while and registers a logon
task on Windows. Nobody had run it on the machine where this was written, so the
hooks captured into a spool for five days while the recorder was not running.
Nothing said so: not the dashboard, not `doctor`, not the API. A capability
nobody is told about is indistinguishable from one that does not exist, so
`status()` is treated here as a first-class feature rather than a helper.

Three deliberate choices:

**User scope, not system scope.** A logon task running as the interactive user
can raise toasts, reads the user's own config, and needs no elevation to install.
A system service would survive logout, and would also mean an audit daemon
running as LocalSystem reading a developer's home directory. That trade is the
enterprise packaging's to make, not the OSS default's.

**Restart on failure, not just start on logon.** The original registration was
`ONLOGON` with no restart policy, so a crashed recorder stayed dead until the
next logon. On a workstation that is days.

**Never silently.** Installing a persistent background process is the user's
decision. Nothing here runs as a side effect of a normal install; `doctor` warns
that autostart is absent and names the command, and stops there.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TASK_NAME = "Agentmetry Orchestrator"
SERVICE_NAME = "agentmetry"
LAUNCH_LABEL = "ai.agentmetry.orchestrator"

# A crashed recorder should come back promptly and keep trying. The window that
# matters is the one where hooks are spooling because nothing is listening.
RESTART_INTERVAL_MINUTES = 1
RESTART_COUNT = 999

# Any boundary in the past works; the repetition is what carries the schedule
# forward. Fixed rather than "now" so a re-registration produces an identical
# task and diffs stay empty.
KEEPALIVE_EPOCH = "2020-01-01T00:00:00"


@dataclass(frozen=True)
class AutostartStatus:
    """Whether autostart is registered, and separately, whether it works.

    These are two different questions and conflating them cost real data. The
    registration survived a package rename that broke the command it launches,
    so the task ran every minute, exited 1 every minute, and `configured=True`
    reported success the whole time. Hooks spooled behind it.

    `healthy` is deliberately tri-state. `None` means the platform could not
    tell us, which is not the same as failing, and reporting an unknown as a
    fault would train an operator to ignore the field.
    """

    configured: bool
    backend: str
    detail: str
    healthy: bool | None = None
    last_result: int | None = None


def _orchestrator_dir() -> Path:
    """The directory containing the `agentmetry` package, which is the working
    directory an unattended `-m agentmetry.cli serve` needs."""
    return Path(__file__).resolve().parents[3]


class PackagedBuild(RuntimeError):
    """Raised when a frozen build asks to register its own autostart.

    Packaged builds are supervised by the service the installer registers, and a
    second registration would race it. Inventing a launch command here to look
    complete would produce a task that either fights the service or fails
    silently, which is worse than saying so.
    """


def launch_command() -> tuple[str, list[str], Path]:
    """(executable, arguments, working directory) for an unattended start.

    From source we run the module directly rather than through a shell wrapper,
    so there is no cmd.exe in the process tree for a restart policy to lose
    track of.
    """
    workdir = _orchestrator_dir()
    if getattr(sys, "frozen", False):
        raise PackagedBuild(
            "This is a packaged build; the installer registers a service to keep "
            "the orchestrator running. Manage it there rather than adding a "
            "second autostart entry."
        )

    executable = sys.executable
    if os.name == "nt":
        # pythonw.exe runs without a console window. Falling back to python.exe
        # is better than failing: a visible window is a papercut, not being
        # registered at all is data loss.
        candidate = Path(sys.executable).with_name("pythonw.exe")
        if candidate.is_file():
            executable = str(candidate)
    # `cli serve`, never `-m uvicorn` directly. Under pythonw.exe there is no
    # console, so sys.stdout is None and uvicorn's own logging setup dies before
    # it serves anything -- observed as a task that ran, exited 1, and explained
    # nothing. `serve` points the streams at the log file first.
    args = ["-m", "agentmetry.cli", "serve", "--host", "127.0.0.1", "--port", "8000"]
    return executable, args, workdir


# ----------------------------------------------------------------------
# Rendering — pure, so the shape of what we register is testable
# ----------------------------------------------------------------------


def render_windows_task_xml(user: str | None = None) -> str:
    """Task Scheduler definition: start at logon, restart on failure, no window."""
    executable, args, workdir = launch_command()
    account = user or f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
    arguments = " ".join(args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Agentmetry orchestrator. Records AI agent tool-use to the local audit trail.</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{account}</UserId>
      <Repetition>
        <Interval>PT{RESTART_INTERVAL_MINUTES}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
    <!-- The logon trigger's repetition only engages once a logon fires. Someone
         who installs autostart mid-session would therefore have no keep-alive
         until they next logged out, which is exactly the window where they
         just decided they wanted one. This trigger starts in the past, so the
         repeat is live the moment the task is registered. -->
    <TimeTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>{KEEPALIVE_EPOCH}</StartBoundary>
      <Repetition>
        <Interval>PT{RESTART_INTERVAL_MINUTES}M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{account}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowHardTerminate>true</AllowHardTerminate>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <!-- RestartOnFailure is not the keep-alive, despite the name. It covers a
         task that fails to launch, not an action that starts fine and dies an
         hour later. Verified: killing the recorder left LastTaskResult
         0xFFFFFFFF and nothing restarted it. The repeating trigger above is
         what actually brings it back, since IgnoreNew makes a repeat a no-op
         while an instance is alive and a restart once it is not. This stays as
         a second line for launch failures. -->
    <RestartOnFailure>
      <Interval>PT{RESTART_INTERVAL_MINUTES}M</Interval>
      <Count>{RESTART_COUNT}</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{executable}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def render_systemd_unit() -> str:
    executable, args, workdir = launch_command()
    exec_start = " ".join([executable, *args])
    return f"""[Unit]
Description=Agentmetry orchestrator (records AI agent tool-use to the local audit trail)
After=network.target

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={exec_start}
Restart=always
RestartSec={RESTART_INTERVAL_MINUTES * 60}

[Install]
WantedBy=default.target
"""


def render_launchd_plist() -> str:
    executable, args, workdir = launch_command()
    program_args = "\n".join(f"    <string>{a}</string>" for a in [executable, *args])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{program_args}
  </array>
  <key>WorkingDirectory</key><string>{workdir}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""


def systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service"


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


# ----------------------------------------------------------------------
# Status — safe to call from doctor on any platform
# ----------------------------------------------------------------------


def status() -> AutostartStatus:
    if os.name == "nt":
        return _windows_status()
    if sys.platform == "darwin":
        return _launchd_status()
    return _systemd_status()


def _run(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    """Best-effort probe. A probe that raises is a probe that makes `doctor` worse."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _parse_field(verbose_query: str, label: str) -> str | None:
    """Pull one labelled field out of `schtasks /V /FO LIST` output.

    Parsed rather than requested as CSV because the column names are localized
    on non-English Windows and the CSV header would be too; this at least fails
    to `None` (unknown) rather than to a wrong answer.
    """
    for line in verbose_query.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == label:
            return value.strip()
    return None


def _parse_last_result(verbose_query: str) -> int | None:
    text = _parse_field(verbose_query, "last result")
    if text is None:
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


#: Last-run codes that do not mean the recorder failed.
#:
#: 0x41303 is "has never run", the normal state between registering and the
#: first trigger. 0x41301 is "currently running". 0x800710E0 is Task Scheduler
#: declining to start a second instance because one is already alive, which is
#: `MultipleInstancesPolicy=IgnoreNew` doing its job.
_BENIGN_LAST_RESULTS = frozenset({0, 0x41303, 0x41301, -2147020576})


def _windows_status() -> AutostartStatus:
    if shutil.which("schtasks") is None:
        return AutostartStatus(False, "schtasks", "schtasks is not on PATH")
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    if result is None:
        return AutostartStatus(False, "schtasks", "could not query Task Scheduler")
    if result.returncode != 0:
        return AutostartStatus(False, "schtasks", f"no scheduled task named '{TASK_NAME}'")

    registered = f"scheduled task '{TASK_NAME}' is registered"
    verbose = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    if verbose is None or verbose.returncode != 0:
        return AutostartStatus(True, "schtasks", registered)

    last = _parse_last_result(verbose.stdout)
    state = (_parse_field(verbose.stdout, "scheduled task state") or "").lower()
    running = (_parse_field(verbose.stdout, "status") or "").lower() == "running"

    if state == "disabled":
        return AutostartStatus(
            True,
            "schtasks",
            f"{registered} but disabled, so nothing will restart the recorder. "
            "Re-enable it in Task Scheduler, or run `agentmetry install`.",
            healthy=False,
            last_result=last,
        )

    # Status beats Last Result, because Last Result is not a health signal for a
    # task that stays up. It records the last *launch attempt*, and every
    # repeating trigger that fires while the recorder is alive is refused by
    # IgnoreNew and recorded as a non-zero code. Reading that as a fault would
    # mean a correctly working recorder reports broken almost all the time,
    # which is a worse failure than the silence this check replaced: an alarm
    # that is always on gets muted, and then it cannot warn about anything.
    if running:
        return AutostartStatus(True, "schtasks", registered, healthy=True, last_result=last)

    if last is None:
        return AutostartStatus(True, "schtasks", registered)
    if last in _BENIGN_LAST_RESULTS:
        return AutostartStatus(True, "schtasks", registered, healthy=True, last_result=last)
    return AutostartStatus(
        True,
        "schtasks",
        f"{registered}, but it is not running and its last run exited {last}. "
        "It is registered and failing, so nothing is recording. "
        "`agentmetry install` re-registers it with the current launch command.",
        healthy=False,
        last_result=last,
    )


def _systemd_status() -> AutostartStatus:
    path = systemd_unit_path()
    if not path.is_file():
        return AutostartStatus(False, "systemd (user)", f"no unit at {path}")
    if shutil.which("systemctl") is None:
        return AutostartStatus(True, "systemd (user)", str(path))
    result = _run(["systemctl", "--user", "is-active", f"{SERVICE_NAME}.service"])
    if result is None:
        return AutostartStatus(True, "systemd (user)", str(path))
    state = result.stdout.strip() or "unknown"
    if state == "active":
        return AutostartStatus(True, "systemd (user)", str(path), healthy=True)
    if state in ("activating", "reloading", "unknown"):
        return AutostartStatus(True, "systemd (user)", f"{path} ({state})")
    return AutostartStatus(
        True,
        "systemd (user)",
        f"{path} is installed but the unit is {state}, so nothing is recording. "
        "`systemctl --user status agentmetry` has the reason.",
        healthy=False,
    )


def _launchd_status() -> AutostartStatus:
    path = launchd_plist_path()
    if not path.is_file():
        return AutostartStatus(False, "launchd", f"no launch agent at {path}")
    if shutil.which("launchctl") is None:
        return AutostartStatus(True, "launchd", str(path))
    result = _run(["launchctl", "list", LAUNCH_LABEL])
    if result is None or result.returncode != 0:
        return AutostartStatus(True, "launchd", str(path))
    # `launchctl list <label>` prints a plist-ish dict; LastExitStatus is the
    # field that distinguishes "loaded" from "loaded and working".
    last: int | None = None
    for line in result.stdout.splitlines():
        if '"LastExitStatus"' in line:
            digits = "".join(c for c in line.split("=")[-1] if c.isdigit() or c == "-")
            last = int(digits) if digits.strip("-") else None
            break
    if last is None or last == 0:
        return AutostartStatus(True, "launchd", str(path), healthy=last == 0, last_result=last)
    return AutostartStatus(
        True,
        "launchd",
        f"{path} is loaded but last exited {last}, so nothing is recording. "
        "`agentmetry install` re-registers it with the current launch command.",
        healthy=False,
        last_result=last,
    )


# ----------------------------------------------------------------------
# Install / remove
# ----------------------------------------------------------------------


def install() -> tuple[bool, str]:
    try:
        launch_command()
    except PackagedBuild as exc:
        return False, str(exc)
    if os.name == "nt":
        return _install_windows()
    if sys.platform == "darwin":
        return _install_launchd()
    return _install_systemd()


def remove() -> tuple[bool, str]:
    if os.name == "nt":
        return _remove_windows()
    if sys.platform == "darwin":
        return _remove_launchd()
    return _remove_systemd()


def _install_windows() -> tuple[bool, str]:
    import tempfile

    xml = render_windows_task_xml()
    # schtasks reads the definition as UTF-16, and silently misparses UTF-8.
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".xml", delete=False, encoding="utf-16"
    )
    try:
        handle.write(xml)
        handle.close()
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", handle.name, "/F"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not register the scheduled task: {exc}"
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    if result.returncode != 0:
        return False, (result.stderr.strip() or result.stdout.strip() or "schtasks failed")
    return True, (
        f"Registered '{TASK_NAME}'. It starts at logon and is re-checked every "
        f"{RESTART_INTERVAL_MINUTES}m, so a recorder that dies comes back within "
        "about a minute."
    )


def _remove_windows() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not remove the scheduled task: {exc}"
    if result.returncode != 0:
        return False, (result.stderr.strip() or result.stdout.strip() or "schtasks failed")
    return True, f"Removed scheduled task '{TASK_NAME}'."


def _install_systemd() -> tuple[bool, str]:
    if shutil.which("systemctl") is None:
        return False, "systemctl not found; register the orchestrator with your init system by hand"
    path = systemd_unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_systemd_unit(), encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {path}: {exc}"

    for argv in (
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"],
    ):
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"{' '.join(argv)} failed: {exc}"
        if result.returncode != 0:
            return False, (result.stderr.strip() or f"{' '.join(argv)} failed")

    return True, (
        f"Installed and started {SERVICE_NAME}.service ({path}). A user unit stops at "
        "logout; run `loginctl enable-linger $USER` if the recorder should keep "
        "running while you are logged out."
    )


def _remove_systemd() -> tuple[bool, str]:
    path = systemd_unit_path()
    if shutil.which("systemctl") is not None:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"could not remove {path}: {exc}"
    return True, f"Removed {path}."


def _install_launchd() -> tuple[bool, str]:
    path = launchd_plist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_launchd_plist(), encoding="utf-8")
    except OSError as exc:
        return False, f"could not write {path}: {exc}"
    try:
        subprocess.run(
            ["launchctl", "load", "-w", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"launchctl load failed: {exc}"
    return True, f"Installed launch agent {LAUNCH_LABEL} ({path})."


def _remove_launchd() -> tuple[bool, str]:
    path = launchd_plist_path()
    try:
        subprocess.run(
            ["launchctl", "unload", "-w", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return False, f"could not remove {path}: {exc}"
    return True, f"Removed launch agent {LAUNCH_LABEL}."
