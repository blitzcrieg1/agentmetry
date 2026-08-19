"""Which agent surfaces on this machine are actually recorded.

The heartbeat and `doctor` both hardcoded two paths, Cursor and Claude, while
`hook_bootstrap` shipped installers for six surfaces and the ingest script
mapped nine. So the recorder attested full coverage on a machine where Codex,
Qwen, Kimi, Qoder or CodeBuddy were running unrecorded. That is the same lie the
heartbeat exists to prevent, arriving from inside the recorder, which is why the
registry now lives in one place that both callers read.

## Four states, because "false" was answering two different questions

`hooks[name] = False` used to mean both "the hook was removed" and "this agent
was never on this machine". Those deserve opposite responses: the first is an
incident, the second is Tuesday. A developer who has never installed Claude Code
was permanently degrading their own heartbeat, and a fleet that learns to ignore
a degraded beat has no tamper signal left.

    covered    the agent is installed here and our hook is in its config
    uncovered  the agent is installed here and our hook is NOT  <- the incident
    absent     the agent is not on this machine
    unknown    we cannot check, and will not pretend otherwise

`unknown` is not a soft `covered`. Codex is mapped end to end at ingest and has
no installer and no confirmed config path, so asserting either answer would be
invention. Antigravity is captured by a transcript watcher rather than a hook
file, so a file check cannot speak to it at all. Both are reported, both are
queryable, and neither counts as coverage.

## The service-profile trap

Every path here hangs off `Path.home()`. Under the MSI the orchestrator runs as
LocalSystem, where that resolves to the SYSTEM profile: hooks get written there,
found there, and reported as installed, while no developer's IDE ever reads that
directory. A per-machine install would then attest full coverage for a fleet
recording nothing. So a service profile is a definite failure rather than an
unknown, and it degrades the beat.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Present in any config we wrote, JSON or TOML: the hook command invokes the
#: ingest script by path. Checking for our marker rather than for the file means
#: an IDE config the user owns and we merged into is judged on our half of it.
_MARKER = "agentmetry_ingest"

#: Pre-rename installs still on disk.
_MARKER_LEGACY = "agentaudit_ingest"

COVERED = "covered"
UNCOVERED = "uncovered"
ABSENT = "absent"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Surface:
    """One agent host, and how to tell whether we record it."""

    name: str
    #: Directory whose existence means the agent has run on this machine.
    home_env: str
    home_rel: str
    #: Config file we merge our hook into, relative to that directory.
    config: str
    #: Set when no file check can answer, carrying the reason an operator needs.
    unverifiable: str = ""

    def directory(self) -> Path:
        override = os.environ.get(self.home_env, "").strip() if self.home_env else ""
        if override:
            return Path(override).expanduser()
        return Path.home() / self.home_rel


#: Mirrors hook_bootstrap's installers, plus the two surfaces that have none.
#: Adding an installer without adding a row here is the drift this module exists
#: to stop, and test_hook_coverage.py fails when the two disagree.
SURFACES: tuple[Surface, ...] = (
    Surface("cursor", "", ".cursor", "hooks.json"),
    Surface("claude", "", ".claude", "settings.json"),
    Surface("qwen", "QWEN_HOME", ".qwen", "settings.json"),
    Surface("qoder", "", ".qoder", "settings.json"),
    Surface("codebuddy", "", ".codebuddy", "settings.json"),
    Surface("kimi", "KIMI_CODE_HOME", ".kimi-code", "config.toml"),
    Surface(
        "codex",
        "",
        ".codex",
        "config.toml",
        unverifiable=(
            "mapped at ingest but has no installer and no confirmed config path; "
            "coverage cannot be asserted from disk"
        ),
    ),
    Surface(
        "antigravity",
        "",
        ".antigravity",
        "",
        unverifiable=(
            "captured by the transcript watcher rather than a hook file; "
            "a file check cannot speak to it"
        ),
    ),
)


def is_service_profile(home: Path | None = None) -> bool:
    """True when `Path.home()` is a service account's profile, not a person's.

    Windows LocalSystem lands in System32/config/systemprofile; LocalService and
    NetworkService land under Windows/ServiceProfiles. Matching on the path
    rather than on the account name means this also catches a service running
    under a profile nobody anticipated.
    """
    text = str(home if home is not None else Path.home()).replace("\\", "/").lower()
    return "/config/systemprofile" in text or "/windows/serviceprofiles/" in text


def _has_marker(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _MARKER in body or _MARKER_LEGACY in body


def coverage() -> dict[str, str]:
    """Per-surface state, re-read from disk on every call.

    Deliberately not cached. A hook removed at 11am must show in the 11:05 beat;
    a value captured at boot keeps asserting the configuration the machine had
    when it last restarted, which is precisely the lie being hunted.
    """
    if is_service_profile():
        # Every path below would describe the service's own profile. Reporting
        # confident per-agent answers from it is worse than reporting none.
        return {s.name: UNKNOWN for s in SURFACES}

    result: dict[str, str] = {}
    for surface in SURFACES:
        try:
            present = surface.directory().is_dir()
        except OSError:
            present = False
        if surface.unverifiable:
            # An agent we cannot check is unknown when it is here and absent
            # when it is not. Absent is a fact a directory check can support.
            result[surface.name] = UNKNOWN if present else ABSENT
            continue
        if not present:
            result[surface.name] = ABSENT
            continue
        result[surface.name] = (
            COVERED if _has_marker(surface.directory() / surface.config) else UNCOVERED
        )
    return result


def hook_flags(states: dict[str, str] | None = None) -> dict[str, bool]:
    """The legacy `heartbeat.hooks` shape: name -> "our hook is in that file".

    Kept because `heartbeat.hooks.cursor` is written into published Splunk and
    Sigma rules, the enterprise TA, and whatever customers wrote themselves. The
    keys never disappear and never change meaning; the surfaces they never
    covered are added alongside. What changed is that nothing decides `degraded`
    from this dict any more, because a bool cannot separate a removed hook from
    an agent that was never installed.
    """
    states = states if states is not None else coverage()
    return {name: state == COVERED for name, state in states.items()}


def uncovered(states: dict[str, str] | None = None) -> list[str]:
    """Agents running on this machine whose calls are not being recorded."""
    states = states if states is not None else coverage()
    return sorted(n for n, s in states.items() if s == UNCOVERED)


def unverified(states: dict[str, str] | None = None) -> list[str]:
    """Agents present that no file check can answer for.

    Neither coverage nor an incident. Surfacing them is the point: silence here
    is how Codex stayed missing from the attestation while being named in the
    README as a supported IDE.
    """
    states = states if states is not None else coverage()
    return sorted(n for n, s in states.items() if s == UNKNOWN)


def summary_lines(states: dict[str, str] | None = None) -> list[str]:
    states = states if states is not None else coverage()
    if is_service_profile():
        return [
            "  hooks: UNKNOWN, running under a service profile "
            f"({Path.home()}); no developer's configuration is visible from here"
        ]
    lines = []
    for label, names in (
        ("recorded", sorted(n for n, s in states.items() if s == COVERED)),
        ("NOT recorded", uncovered(states)),
        ("unverifiable", unverified(states)),
        ("not installed", sorted(n for n, s in states.items() if s == ABSENT)),
    ):
        if names:
            lines.append(f"  {label}: {', '.join(names)}")
    return lines
