"""The four-week gate has to be cheap to check, or it never gets checked.

It went unstarted for weeks. Not because it was hard to pass, but because
answering "was this week green?" meant a twenty-minute manual pass, so nobody
asked. These tests pin the criteria so the answer stays a single command.

The verdict is harsh about capture gaps and lenient about volume, on purpose. A
slow week is fine. A week the recorder missed is the failure this gate exists to
catch, because an empty trail from a switched-off recorder looks exactly like an
empty trail from a quiet developer.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.audit.dogfood import (
    MIN_ACTIVE_DAYS,
    assess,
    read_marker,
    render,
    start_clock,
)

START = date(2026, 7, 1)


class _FakeTrail:
    def __init__(self, events):
        self._events = events

    def read_between(self, *_a, **_kw):
        return list(self._events)


def _event(day: date, *, corr="s1", action="tool_called", outcome="success",
           rule_id="", hour=10):
    event = {
        "event_id": f"{corr}-{day}-{action}-{rule_id}-{hour}",
        "correlation_id": corr,
        "timestamp_utc": f"{day.isoformat()}T{hour:02d}:00:00+00:00",
        "action": {"type": action, "outcome": outcome},
    }
    if rule_id:
        event["detection"] = {"rule_id": rule_id}
    return event


def _busy_week(start: date, days: int = 5, corr_prefix="s"):
    return [
        _event(start + timedelta(days=i), corr=f"{corr_prefix}{i}")
        for i in range(days)
    ]


@pytest.fixture(autouse=True)
def _clean_marker(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail.jsonl")
    yield


# --- the marker is an explicit commitment ------------------------------------

def test_no_marker_means_the_clock_has_not_started():
    report = assess(trail_db=_FakeTrail([]))
    assert report.started is None
    assert "has not started" in render(report)


def test_starting_records_the_date():
    marker = start_clock(START, operator="alex")
    assert marker["started_utc"] == "2026-07-01"
    assert read_marker()["operator"] == "alex"


def test_the_clock_is_not_inferred_from_the_first_event():
    """A commitment nobody made on a particular day is one nobody is keeping."""
    report = assess(trail_db=_FakeTrail(_busy_week(START)))
    assert report.started is None


# --- what makes a week green -------------------------------------------------

def test_a_busy_week_is_green():
    start_clock(START)
    report = assess(
        trail_db=_FakeTrail(_busy_week(START)), today=START + timedelta(days=8)
    )
    assert report.weeks[0].verdict == "GREEN"
    assert report.weeks[0].active_days == 5


def test_a_week_the_recorder_missed_is_red():
    start_clock(START)
    quiet = [_event(START, corr="s1")]  # one day only
    report = assess(trail_db=_FakeTrail(quiet), today=START + timedelta(days=8))
    week = report.weeks[0]
    assert week.verdict == "RED"
    assert any("active day" in r for r in week.reasons)


def test_a_slow_but_present_week_still_passes():
    """Volume is not the metric. Presence is."""
    start_clock(START)
    sparse = [_event(START + timedelta(days=i), corr=f"s{i}") for i in range(MIN_ACTIVE_DAYS)]
    report = assess(trail_db=_FakeTrail(sparse), today=START + timedelta(days=8))
    assert report.weeks[0].verdict == "GREEN"
    assert report.weeks[0].events == MIN_ACTIVE_DAYS


def test_an_untriaged_critical_makes_the_week_red():
    """A detection nobody answered means the loop is running open."""
    start_clock(START)
    events = _busy_week(START) + [
        _event(START + timedelta(days=1), corr="s1", action="detection",
               outcome="critical", rule_id="credential-exfil")
    ]
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=8))
    week = report.weeks[0]
    assert week.verdict == "RED"
    assert week.untriaged == 1
    assert any("dispositioned" in r for r in week.reasons)


def test_a_triaged_critical_leaves_the_week_green():
    start_clock(START)
    from core.audit.detection.disposition import get_disposition_store

    get_disposition_store().record(
        correlation_id="s1", rule_id="credential-exfil",
        status="false_positive", note="our own CI bot",
    )
    events = _busy_week(START) + [
        _event(START + timedelta(days=1), corr="s1", action="detection",
               outcome="critical", rule_id="credential-exfil")
    ]
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=8))
    assert report.weeks[0].untriaged == 0
    assert report.weeks[0].verdict == "GREEN"


def test_a_medium_detection_does_not_have_to_be_triaged():
    """The gate asks for critical and high. Medium noise must not block beta."""
    start_clock(START)
    events = _busy_week(START) + [
        _event(START + timedelta(days=1), corr="s1", action="detection",
               outcome="medium", rule_id="discovery-then-collect")
    ]
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=8))
    assert report.weeks[0].verdict == "GREEN"


# --- the run, not just the week ----------------------------------------------

def test_the_gate_needs_four_consecutive_weeks():
    start_clock(START)
    events = []
    for w in range(4):
        events += _busy_week(START + timedelta(days=7 * w), corr_prefix=f"w{w}s")
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=29))
    assert report.consecutive_green == 4
    assert report.passed is True


def test_a_red_week_resets_the_run():
    """Three green, one red, one green is not four consecutive."""
    start_clock(START)
    events = _busy_week(START, corr_prefix="a") + _busy_week(
        START + timedelta(days=7), corr_prefix="b"
    )
    # week 3 skipped entirely
    events += _busy_week(START + timedelta(days=21), corr_prefix="d")
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=29))
    assert report.weeks[2].verdict == "RED"
    assert report.consecutive_green == 1
    assert report.passed is False


def test_the_current_week_is_not_judged_yet():
    start_clock(START)
    report = assess(trail_db=_FakeTrail([_event(START)]), today=START + timedelta(days=2))
    assert report.weeks[0].verdict == "IN PROGRESS"
    assert report.weeks[0].complete is False


def test_an_incomplete_week_does_not_break_the_run():
    start_clock(START)
    events = _busy_week(START) + [_event(START + timedelta(days=7))]
    report = assess(trail_db=_FakeTrail(events), today=START + timedelta(days=9))
    assert report.weeks[0].verdict == "GREEN"
    assert report.weeks[1].verdict == "IN PROGRESS"
    assert report.consecutive_green == 1


# --- health signals that invalidate the whole run ----------------------------

def test_a_broken_chain_fails_every_week(monkeypatch):
    start_clock(START)
    import core.audit.dogfood as dogfood

    def _broken(report):
        report.chain_ok = False
        report.chain_message = "line 12 does not match"
        report.spooled = 0

    monkeypatch.setattr(dogfood, "_attach_health", _broken)
    report = assess(trail_db=_FakeTrail(_busy_week(START)), today=START + timedelta(days=8))
    assert report.weeks[0].verdict == "RED"
    assert "BROKEN" in render(report)


def test_render_names_what_is_missing():
    start_clock(START)
    report = assess(trail_db=_FakeTrail([_event(START)]), today=START + timedelta(days=8))
    out = render(report)
    assert "2026-07-01" in out
    assert "more green week(s) needed" in out
