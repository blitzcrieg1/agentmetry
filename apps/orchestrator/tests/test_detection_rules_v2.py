"""Tests for destructive-delete-burst, off-hours-activity, and policy annotation.

Both rules shipped with no tests. Every bug fixed here was one a does-not-fire
test would have caught, which is exactly why CONTRIBUTING.md requires one.
"""

from __future__ import annotations

import pytest

from core.audit.detection.rules import (
    rule_destructive_delete_burst,
    rule_off_hours_activity,
)
from core.audit.policy import annotate, evaluate_policy
from core.config import settings


def _ev(
    *,
    ts: str = "2026-07-14T12:00:00+00:00",
    tool: str = "fs.delete_file",
    tactic: str = "TA0040",
    technique: str = "T1485",
    outcome: str = "success",
    actor: str = "autonomous",
    trigger: str = "ingress",
    command: str = "",
    event_id: str = "e1",
) -> dict:
    event: dict = {
        "event_id": event_id,
        "correlation_id": "sess-1",
        "timestamp_utc": ts,
        "initiator": {"actor_type": actor, "trigger": trigger, "operator_id": "local"},
        "action": {"type": "tool_called", "outcome": outcome, "reason": ""},
        "tool": {"qualified": tool, "mitre": {"tactic_id": tactic, "technique_id": technique}},
    }
    if command:
        event["tool"]["command"] = command
    return event


def _rule_ids(dets) -> set[str]:
    return {d.rule_id for d in dets}


# --- destructive-delete-burst -------------------------------------------------

def test_delete_burst_fires_on_real_deletes():
    events = [_ev(event_id=f"d{i}") for i in range(5)]
    d = next(d for d in rule_destructive_delete_burst(events) if d.rule_id == "destructive-delete-burst")
    assert d.severity == "high"
    assert len(d.event_ids) == 5


def test_delete_burst_below_threshold_is_silent():
    assert rule_destructive_delete_burst([_ev(event_id=f"d{i}") for i in range(4)]) == []


def test_delete_burst_ignores_tools_that_merely_contain_delete_or_remove():
    """`"remove" in tool` made 5 refactor edits a critical data-destruction alert."""
    for name in ("editor.remove_whitespace", "editor.remove_import", "fs.undelete", "ui.delete_preview"):
        events = [
            _ev(event_id=f"x{i}", tool=name, tactic="TA0009", technique="T1005")
            for i in range(6)
        ]
        assert rule_destructive_delete_burst(events) == [], f"false positive on {name}"


def test_delete_burst_counts_shell_rm_by_command():
    """`bash: rm -rf build/` is a deletion even though the tool is named Bash."""
    events = [
        _ev(event_id=f"r{i}", tool="Bash", tactic="TA0002", technique="T1059", command="rm -rf build/")
        for i in range(5)
    ]
    assert "destructive-delete-burst" in _rule_ids(rule_destructive_delete_burst(events))


def test_delete_burst_ignores_failed_deletes():
    events = [_ev(event_id=f"d{i}", outcome="error") for i in range(6)]
    assert rule_destructive_delete_burst(events) == []


# --- off-hours-activity -------------------------------------------------------

@pytest.fixture
def off_hours_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "detect_off_hours", True)
    monkeypatch.setattr(settings, "business_hours", "09-18")
    monkeypatch.setattr(settings, "business_tz", "UTC")


def test_off_hours_is_opt_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "detect_off_hours", False)
    assert rule_off_hours_activity([_ev(ts="2026-07-14T03:00:00+00:00")]) == []


def test_off_hours_fires_for_unscheduled_agent(off_hours_on):
    d = next(
        d
        for d in rule_off_hours_activity([_ev(ts="2026-07-14T03:00:00+00:00")])
        if d.rule_id == "off-hours-activity"
    )
    assert d.severity == "medium"


def test_off_hours_respects_the_source_timezone(off_hours_on):
    """02:00+09:00 is 17:00 UTC on a Tuesday: business hours, not off-hours.

    Reading .hour off the parsed timestamp reported the source offset and
    claimed it was UTC.
    """
    assert rule_off_hours_activity([_ev(ts="2026-07-14T02:00:00+09:00")]) == []


def test_off_hours_ignores_scheduled_jobs(off_hours_on):
    """Cron runs at night. That is the point of cron."""
    for trigger in ("cron", "schedule", "timer"):
        events = [_ev(ts="2026-07-14T02:30:00+00:00", trigger=trigger)]
        assert rule_off_hours_activity(events) == [], f"false positive on trigger={trigger}"


def test_off_hours_ignores_humans(off_hours_on):
    events = [_ev(ts="2026-07-14T03:00:00+00:00", actor="human")]
    assert rule_off_hours_activity(events) == []


def test_off_hours_window_is_configurable(monkeypatch: pytest.MonkeyPatch):
    """A US team's evening is not suspicious just because UTC says 23:00."""
    monkeypatch.setattr(settings, "detect_off_hours", True)
    monkeypatch.setattr(settings, "business_hours", "09-18")
    monkeypatch.setattr(settings, "business_tz", "America/New_York")
    # 23:00 UTC == 19:00 New York: outside 09-18, so it fires...
    assert rule_off_hours_activity([_ev(ts="2026-07-14T23:00:00+00:00")]) != []
    # ...while 18:00 UTC == 14:00 New York is squarely business hours.
    assert rule_off_hours_activity([_ev(ts="2026-07-14T18:00:00+00:00")]) == []


def test_off_hours_survives_a_malformed_timestamp(off_hours_on):
    assert rule_off_hours_activity([_ev(ts="not-a-timestamp")]) == []


# --- policy annotation --------------------------------------------------------

def test_policy_never_rewrites_what_happened():
    """The trail must record the tool ran, because it did."""
    event = _ev(tool="shell.rm")
    annotate(event)
    assert event["action"]["outcome"] == "success"
    assert event["policy"]["decision"] == "deny"
    assert event["policy"]["enforced"] is False


def test_policy_does_not_blind_the_detection_engine():
    """Marking outcome=denied hid a burst of shell.rm from delete-burst."""
    events = [_ev(event_id=f"r{i}", tool="shell.rm") for i in range(6)]
    for e in events:
        annotate(e)
    assert "destructive-delete-burst" in _rule_ids(rule_destructive_delete_burst(events))


def test_policy_allows_unrestricted_tools():
    event = _ev(tool="fs.read_file")
    annotate(event)
    assert "policy" not in event


def test_policy_matching_is_spelling_insensitive():
    assert evaluate_policy(_ev(tool="shell.RM")).allowed is False
    assert evaluate_policy(_ev(tool="kubectl.exec")).allowed is False


def test_policy_allows_an_approved_restricted_tool():
    event = _ev(tool="shell.rm")
    event["action"] = {"type": "approval_response", "outcome": "success"}
    assert evaluate_policy(event).allowed is True
