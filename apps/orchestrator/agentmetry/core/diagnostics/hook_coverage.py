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

`unknown` is not a soft `covered`. It is reserved for the case where the answer
is not merely negative but unobtainable, which today means the service profile
below.

Getting the surfaces right took two passes, and the first pass is worth naming.
Codex and Antigravity were initially recorded as uncheckable on the grounds that
neither has a PowerShell installer. That was a conclusion drawn from searching
`hook_bootstrap` and `scripts/` alone. Both are in fact documented and checkable:
`adapters/codex/hooks.agentmetry.json` merges into `~/.codex/hooks.json`, and
`install_antigravity_hooks.ps1` writes `~/.gemini/config/hooks.json`. Missing
installer is not the same fact as missing support, and reporting `unknown` for a
surface that can be checked hides a real `uncovered`, which is the finding.

One caveat a file check genuinely cannot cover: Codex uses a hash-based trust
prompt and skips untrusted hooks silently. A `covered` Codex is configured, not
proven to be firing.

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

#: What our hook command looks like in a config we merged into. Checking for the
#: marker rather than for the file means an IDE config the user owns is judged on
#: our half of it. `agentaudit_ingest` is the pre-rename name, still on disk for
#: anyone who installed before 0.4.0.
#:
#: Matched case-sensitively and in lower case on purpose: `AGENTMETRY_API_KEY` in
#: an `env` block is not a hook, and an installed-looking config that captures
#: nothing is the exact failure this module exists to catch.
_DEFAULT_MARKERS = ("agentmetry_ingest", "agentaudit_ingest")

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
    #: Config files we merge our hook into, relative to that directory. More than
    #: one because Antigravity loads from whichever of its locations applies, and
    #: a machine hooked in only the scratch profile is still recorded.
    configs: tuple[str, ...]
    #: Overridden where our command is not the ingest script itself.
    markers: tuple[str, ...] = _DEFAULT_MARKERS

    def directory(self) -> Path:
        override = os.environ.get(self.home_env, "").strip() if self.home_env else ""
        if override:
            return Path(override).expanduser()
        return Path.home() / self.home_rel


#: Mirrors hook_bootstrap's installers, plus the two surfaces that have none.
#: Adding an installer without adding a row here is the drift this module exists
#: to stop, and test_hook_coverage.py fails when the two disagree.
SURFACES: tuple[Surface, ...] = (
    Surface("cursor", "", ".cursor", ("hooks.json",)),
    Surface("claude", "", ".claude", ("settings.json",)),
    Surface("qwen", "QWEN_HOME", ".qwen", ("settings.json",)),
    Surface("qoder", "", ".qoder", ("settings.json",)),
    Surface("codebuddy", "", ".codebuddy", ("settings.json",)),
    Surface("kimi", "KIMI_CODE_HOME", ".kimi-code", ("config.toml",)),
    # Codex has no PowerShell installer, which is not the same as having no
    # supported path: `adapters/codex/hooks.agentmetry.json` merges into
    # ~/.codex/hooks.json and docs/agentmetry-external-ingest.md documents it.
    # Coverage here is a file check like any other. What it cannot see is
    # Codex's hash-based trust prompt, which skips untrusted hooks silently, so
    # a covered Codex is configured rather than proven to be firing.
    Surface("codex", "", ".codex", ("hooks.json",)),
    # Antigravity 2.0 usually runs from ~/.gemini/antigravity/scratch rather
    # than the repo, so scripts/install_antigravity_hooks.ps1 writes both. Either
    # one means the agent is recorded. Its command is a .cmd wrapper, not the
    # ingest script, hence the marker override.
    Surface(
        "antigravity",
        "",
        ".gemini",
        ("config/hooks.json", "antigravity/scratch/.agents/hooks.json"),
        markers=("agentmetry_antigravity_hook", *_DEFAULT_MARKERS),
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


def _has_marker(path: Path, markers: tuple[str, ...]) -> bool:
    try:
        if not path.is_file():
            return False
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in body for marker in markers)


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
        if not present:
            result[surface.name] = ABSENT
            continue
        hooked = any(
            _has_marker(surface.directory() / rel, surface.markers)
            for rel in surface.configs
        )
        result[surface.name] = COVERED if hooked else UNCOVERED
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
    """Agents whose state could not be determined at all.

    Neither coverage nor an incident, and today only produced by the service
    profile. Kept as a distinct field because "we could not look" and "we looked
    and found nothing" are different claims, and collapsing them is how a fleet
    dashboard turns green over a blind spot.
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
