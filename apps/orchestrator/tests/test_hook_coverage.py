"""Coverage attestation across every agent surface, not just the two we bootstrap.

The heartbeat existed to make a removed hook loud, and it checked Cursor and
Claude while the ingest script mapped nine agents and six had installers. On a
machine running Codex that beat said `success`, which is the failure this whole
feature was built to prevent, produced by the feature itself.

Two classes of test here. One pins the semantics: absent is not uncovered, and
unknown is not covered. The other pins the registry against `hook_bootstrap`, so
adding an installer without adding a surface fails here rather than silently
shipping another blind spot.
"""

from __future__ import annotations

import json

import pytest

from agentmetry.core.audit import heartbeat
from agentmetry.core.diagnostics import hook_coverage


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """An empty home: every agent absent until the test installs one."""
    monkeypatch.setattr(hook_coverage.Path, "home", staticmethod(lambda: tmp_path))
    for var in ("QWEN_HOME", "KIMI_CODE_HOME"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _install(home, rel, config, *, hooked=True):
    d = home / rel
    d.mkdir(parents=True, exist_ok=True)
    if config:
        body = {"hooks": {"cmd": "python agentmetry_ingest.py cursor hook"}} if hooked else {}
        (d / config).write_text(json.dumps(body), encoding="utf-8")
    return d


# ----------------------------------------------------------------------
# absent is not uncovered
# ----------------------------------------------------------------------


def test_an_agent_that_was_never_installed_is_absent_not_missing(home):
    """The bug that trained everyone to ignore a degraded beat.

    `hooks[name] = False` meant both "removed" and "never here", so a developer
    who does not use Claude Code degraded their own heartbeat forever. A fleet
    that learns the tamper signal is always on has no tamper signal.
    """
    _install(home, ".cursor", "hooks.json")
    states = hook_coverage.coverage()
    assert states["cursor"] == hook_coverage.COVERED
    assert states["claude"] == hook_coverage.ABSENT
    assert hook_coverage.uncovered(states) == []


def test_an_installed_agent_without_our_hook_is_the_incident(home):
    _install(home, ".cursor", "hooks.json")
    _install(home, ".qwen", "settings.json", hooked=False)
    assert hook_coverage.coverage()["qwen"] == hook_coverage.UNCOVERED
    assert hook_coverage.uncovered() == ["qwen"]


def test_a_config_we_never_touched_does_not_count_as_coverage(home):
    """The user owns settings.json. Presence of the file proves nothing; our
    marker inside it is the only thing that does."""
    d = _install(home, ".claude", "settings.json", hooked=False)
    (d / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    assert hook_coverage.coverage()["claude"] == hook_coverage.UNCOVERED


def test_a_pre_rename_install_still_counts(home):
    d = _install(home, ".cursor", "hooks.json", hooked=False)
    (d / "hooks.json").write_text(
        json.dumps({"hooks": {"cmd": "python agentaudit_ingest.py cursor hook"}}),
        encoding="utf-8",
    )
    assert hook_coverage.coverage()["cursor"] == hook_coverage.COVERED


def test_env_overrides_are_honoured(home, monkeypatch, tmp_path):
    """Qwen and Kimi relocate their config. Checking the default path on a
    machine that moved it would report absent for an agent that is running."""
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "settings.json").parent.mkdir(parents=True, exist_ok=True)
    (elsewhere / "settings.json").write_text(
        json.dumps({"hooks": {"cmd": "agentmetry_ingest.py qwen hook"}}), encoding="utf-8"
    )
    monkeypatch.setenv("QWEN_HOME", str(elsewhere))
    assert hook_coverage.coverage()["qwen"] == hook_coverage.COVERED


# ----------------------------------------------------------------------
# unknown is not covered
# ----------------------------------------------------------------------


def test_codex_present_is_unknown_and_never_covered(home):
    """The gap that prompted this file.

    Codex is mapped end to end at ingest and named in the README as supported,
    and has no installer and no confirmed config path. Reporting it covered
    would be a lie; reporting it absent while its directory sits on disk would
    be a quieter one.
    """
    _install(home, ".cursor", "hooks.json")
    _install(home, ".codex", None)
    states = hook_coverage.coverage()
    assert states["codex"] == hook_coverage.UNKNOWN
    assert hook_coverage.hook_flags(states)["codex"] is False
    assert hook_coverage.unverified(states) == ["codex"]
    # An unknown is not an incident either: it must not claim capture is impaired.
    assert hook_coverage.uncovered(states) == []


def test_an_unverifiable_agent_that_is_not_here_is_absent(home):
    assert hook_coverage.coverage()["codex"] == hook_coverage.ABSENT
    assert hook_coverage.unverified() == []


# ----------------------------------------------------------------------
# the service-profile trap
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile",
    [
        r"C:\Windows\System32\config\systemprofile",
        r"C:\Windows\ServiceProfiles\LocalService",
        "/c/windows/system32/config/systemprofile",
    ],
)
def test_a_service_profile_reports_unknown_not_healthy(monkeypatch, profile):
    """The failure a 25-seat MSI rollout would hit on day one.

    The MSI runs the service as LocalSystem, so Path.home() is the SYSTEM
    profile. Hooks get written there, found there, and reported installed, while
    no developer's IDE reads that directory. Answering confidently from that
    profile would attest full coverage for a fleet recording nothing.
    """
    from pathlib import Path as _P

    monkeypatch.setattr(hook_coverage.Path, "home", staticmethod(lambda: _P(profile)))
    assert hook_coverage.is_service_profile()
    states = hook_coverage.coverage()
    assert set(states.values()) == {hook_coverage.UNKNOWN}
    assert not any(hook_coverage.hook_flags(states).values())


# ----------------------------------------------------------------------
# what the heartbeat publishes
# ----------------------------------------------------------------------


def test_the_beat_keeps_the_published_field_names(home):
    """`heartbeat.hooks.cursor` is written into shipped Splunk and Sigma rules,
    the enterprise TA, and whatever customers wrote themselves. New surfaces are
    added beside those keys; the keys themselves do not move or change meaning."""
    _install(home, ".cursor", "hooks.json")
    facts = heartbeat.attestation()
    assert facts["hooks"]["cursor"] is True
    assert facts["hooks"]["claude"] is False
    assert set(facts["hook_coverage"]) == {s.name for s in hook_coverage.SURFACES}
    assert facts["hook_profile"] == "user"


def test_an_uninstalled_agent_does_not_degrade_the_beat(home):
    _install(home, ".cursor", "hooks.json")
    event = heartbeat.build_heartbeat_event("2026-08-19T10:00:00+00:00")
    assert event["action"]["outcome"] == "success"


def test_a_removed_hook_degrades_and_names_the_agent(home):
    _install(home, ".cursor", "hooks.json")
    _install(home, ".qoder", "settings.json", hooked=False)
    event = heartbeat.build_heartbeat_event("2026-08-19T10:00:00+00:00")
    assert event["action"]["outcome"] == "degraded"
    assert "qoder" in event["action"]["reason"]


def test_an_unverifiable_agent_is_named_without_degrading(home):
    """Silence is how Codex stayed missing from the attestation. It has to appear
    in the reason a responder reads, without claiming capture is impaired."""
    _install(home, ".cursor", "hooks.json")
    _install(home, ".codex", None)
    event = heartbeat.build_heartbeat_event("2026-08-19T10:00:00+00:00")
    assert event["action"]["outcome"] == "success"
    assert "codex" in event["action"]["reason"]


def test_a_service_profile_degrades_the_beat(monkeypatch):
    from pathlib import Path as _P

    monkeypatch.setattr(
        hook_coverage.Path,
        "home",
        staticmethod(lambda: _P(r"C:\Windows\System32\config\systemprofile")),
    )
    event = heartbeat.build_heartbeat_event("2026-08-19T10:00:00+00:00")
    assert event["action"]["outcome"] == "degraded"
    assert "service profile" in event["action"]["reason"]


# ----------------------------------------------------------------------
# the anti-drift pin
# ----------------------------------------------------------------------


def test_every_installer_has_a_surface():
    """The registry must not fall behind hook_bootstrap again.

    Cursor and Claude were checked for months while installers shipped for four
    more agents. Nothing failed, because nothing compared the two lists. This
    does.
    """
    import agentmetry.core.audit.hook_bootstrap as bootstrap

    installers = {
        name[len("install_") : -len("_global_hooks")]
        for name in dir(bootstrap)
        if name.startswith("install_") and name.endswith("_global_hooks")
    }
    known = {s.name for s in hook_coverage.SURFACES}
    assert installers <= known, f"installer with no coverage surface: {installers - known}"
