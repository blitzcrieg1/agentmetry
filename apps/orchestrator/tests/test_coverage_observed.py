"""Configured is not recorded (#300).

`hook_coverage.coverage()` says `covered` when the hook entry exists. Codex sat
on that for a week while recording nothing. These tests hold the second half:
coverage, doctor and the heartbeat now name every configured agent that has not
actually sent an event inside the observed window, without turning an unused
agent into a failure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentmetry.core.audit import heartbeat
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.trail_db import AuditTrailDB
from agentmetry.core.config import settings
from agentmetry.core.diagnostics import doctor, hook_coverage
from agentmetry.core.diagnostics.hook_coverage import ABSENT, COVERED, UNCOVERED

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).isoformat()


# --- the rule -------------------------------------------------------------------


def test_a_configured_agent_with_a_recent_event_is_not_silent():
    states = {"claude": COVERED}
    assert hook_coverage.silent(states, {"claude": _iso(timedelta(hours=1))}, NOW) == []


def test_a_configured_agent_with_no_event_at_all_is_silent():
    assert hook_coverage.silent({"codex": COVERED}, {}, NOW) == ["codex"]


def test_a_configured_agent_whose_last_event_is_stale_is_silent():
    states = {"cursor": COVERED}
    assert hook_coverage.silent(states, {"cursor": _iso(timedelta(days=8))}, NOW) == ["cursor"]


def test_only_configured_agents_are_judged():
    """Not installed, or installed without hooks, is a different finding with its own field."""
    states = {"codex": UNCOVERED, "kimi": ABSENT, "claude": COVERED}
    assert hook_coverage.silent(states, {"claude": _iso(timedelta(minutes=5))}, NOW) == []


def test_a_cloud_source_does_not_vouch_for_the_local_agent():
    """`cursor_cloud` events say nothing about whether the local Cursor hooks fire."""
    states = {"cursor": COVERED}
    assert hook_coverage.silent(states, {"cursor_cloud": _iso(timedelta(minutes=1))}, NOW) == ["cursor"]


def test_timestamp_forms_the_index_holds_are_all_read():
    states = {"a": COVERED, "b": COVERED, "c": COVERED}
    last = {
        "a": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "b": (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat(),
        "c": "not a time",
    }
    assert hook_coverage.silent(states, last, NOW) == ["c"]


# --- the index ------------------------------------------------------------------


def _index(path: Path, events: list[tuple[str, str]]) -> Path:
    db = AuditTrailDB(path)
    for source, ts in events:
        db.insert(build_external_canonical({
            "source_app": source,
            "event_type": "tool_called",
            "timestamp_utc": ts,
            "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "0" * 64},
        }))
    return path


def test_the_index_reports_the_newest_event_per_source(tmp_path):
    path = _index(tmp_path / "audit.db", [
        ("claude", "2026-10-20T10:00:00+00:00"),
        ("claude", "2026-10-21T09:00:00+00:00"),
        ("cursor", "2026-10-01T00:00:00+00:00"),
    ])
    last = AuditTrailDB(path).last_event_by_source()
    assert last["claude"].startswith("2026-10-21T09:00")
    assert last["cursor"].startswith("2026-10-01")


# --- doctor -----------------------------------------------------------------------


def _report(states: dict[str, str]) -> doctor.DoctorReport:
    report = doctor.DoctorReport()
    report.hooks = dict(states)
    return report


def test_doctor_names_a_configured_agent_that_sent_nothing(tmp_path, monkeypatch):
    recent = datetime.now(timezone.utc).isoformat()
    path = _index(tmp_path / "audit.db", [("claude", recent)])
    monkeypatch.setattr(settings, "audit_db_path", path)
    report = _report({"claude": COVERED, "codex": COVERED, "kimi": ABSENT})
    doctor._check_observed(report)
    findings = {f.severity: f.message for f in report.findings if f.code == "hooks_observed"}
    assert "codex" in findings["warn"] and "claude" not in findings["warn"]
    assert "claude" in findings["ok"]
    assert report.hooks_silent == ["codex"]
    payload = doctor.report_payload(report)
    assert payload["hooks_silent"] == ["codex"]
    assert payload["hooks_last_seen"]["codex"] is None
    assert payload["hooks_last_seen"]["claude"] == recent


def test_silence_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    """An agent nobody used is silent too; only the person at the machine can tell."""
    monkeypatch.setattr(settings, "audit_db_path", _index(tmp_path / "audit.db", []))
    report = _report({"codex": COVERED})
    doctor._check_observed(report)
    assert report.exit_code == 0
    assert [f.severity for f in report.findings] == ["warn"]


def test_doctor_says_so_when_there_is_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "missing.db")
    report = _report({"claude": COVERED})
    doctor._check_observed(report)
    [finding] = report.findings
    assert finding.severity == "warn" and "No readable trail index" in finding.message
    assert not (tmp_path / "missing.db").exists(), "doctor must never create the index"


def test_doctor_says_nothing_when_no_agent_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "missing.db")
    report = _report({"codex": UNCOVERED})
    doctor._check_observed(report)
    assert report.findings == []


# --- heartbeat ---------------------------------------------------------------------


def _facts(**overrides):
    facts = {
        "hooks_uncovered": [], "hooks_unverified": [], "hooks_silent": [],
        "hook_profile": "user", "policy_rejected": [], "spool_depth": 0,
    }
    facts.update(overrides)
    return facts


def test_the_heartbeat_names_silent_agents_without_degrading(monkeypatch):
    monkeypatch.setattr(heartbeat, "attestation", lambda root=None: _facts(hooks_silent=["codex"]))
    event = heartbeat.build_heartbeat_event(NOW.isoformat())
    assert event["action"]["outcome"] == "success"
    assert "configured but not observed in 7 days: codex" in event["action"]["reason"]
    assert event["heartbeat"]["hooks_silent"] == ["codex"]


def test_a_quiet_heartbeat_says_nothing_about_silence(monkeypatch):
    monkeypatch.setattr(heartbeat, "attestation", lambda root=None: _facts())
    event = heartbeat.build_heartbeat_event(NOW.isoformat())
    assert "not observed" not in event["action"]["reason"]


def test_an_unreadable_index_never_breaks_the_beat(monkeypatch):
    class _Broken:
        def last_event_by_source(self):
            raise OSError("locked")

    import agentmetry.core.audit.trail_db as trail_db

    monkeypatch.setattr(trail_db, "get_trail_db", lambda: _Broken())
    assert heartbeat._silent_agents({"codex": COVERED}) == []
