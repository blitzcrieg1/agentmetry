"""Burst rules need a clock, and host checkpoints must re-arm.

Regression for F5 (2026-07-20 review), two halves of the same defect:

* A count with no time bound is a total, not a burst. Forty tool calls is an
  ordinary long coding session; eight subagent starts is two quiet weeks of
  light use. Both fired as "autonomous campaign".
* `live_host_emitted` never expired, so after that first (probably false) alert
  the rule was silent on that host forever — a recorder that goes permanently
  blind after one alert.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agentmetry.core.audit.detection.live_store import (
    HOST_EMIT_TTL_SECONDS,
    LiveDetectionStore,
    _is_expired,
)
from agentmetry.core.audit.detection.rules import (
    rule_host_subagent_swarm_burst,
    rule_session_tool_burst,
    rule_subagent_swarm_burst,
)

_BASE = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _tool_event(i: int, *, minutes: float, corr: str = "sess-1") -> dict:
    return {
        "event_id": f"e-{i}",
        "correlation_id": corr,
        "host_id": "workstation-1",
        "timestamp_utc": (_BASE + timedelta(minutes=minutes)).isoformat(),
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "tool": {"qualified": "cursor.Read"},
    }


def _subagent_event(i: int, *, minutes: float, corr: str = "sess-1") -> dict:
    event = _tool_event(i, minutes=minutes, corr=corr)
    event["action"]["reason"] = "subagent_start:worker"
    event["tool"] = {"qualified": "kimi.subagent.worker"}
    return event


# --- session-tool-burst -------------------------------------------------------

def test_slow_session_of_many_calls_does_not_fire():
    """A long working day is not a campaign — 60 calls over 6 hours."""
    events = [_tool_event(i, minutes=i * 6) for i in range(60)]
    assert rule_session_tool_burst(events) == []


def test_rapid_burst_fires():
    events = [_tool_event(i, minutes=i * 0.1) for i in range(45)]
    detections = rule_session_tool_burst(events)
    assert len(detections) == 1
    assert detections[0].rule_id == "session-tool-burst"


def test_burst_is_found_even_when_it_follows_slow_activity():
    """The dense window is what matters, not where it sits in the session."""
    slow = [_tool_event(i, minutes=i * 30) for i in range(10)]
    fast = [_tool_event(100 + i, minutes=300 + i * 0.1) for i in range(45)]
    detections = rule_session_tool_burst(slow + fast)
    assert len(detections) == 1


def test_below_threshold_never_fires():
    events = [_tool_event(i, minutes=i * 0.1) for i in range(5)]
    assert rule_session_tool_burst(events) == []


def test_unparsable_timestamps_do_not_disable_the_rule():
    """A broken clock should not silently switch detection off."""
    events = [_tool_event(i, minutes=i * 0.1) for i in range(45)]
    for event in events:
        event["timestamp_utc"] = "not-a-timestamp"
    assert len(rule_session_tool_burst(events)) == 1


# --- subagent swarm -----------------------------------------------------------

def test_subagent_swarm_needs_density():
    spread = [_subagent_event(i, minutes=i * 60) for i in range(8)]
    assert rule_subagent_swarm_burst(spread) == []

    dense = [_subagent_event(i, minutes=i * 0.5) for i in range(8)]
    assert len(rule_subagent_swarm_burst(dense)) == 1


def test_host_swarm_over_two_weeks_does_not_fire():
    """The original defect: 8 starts across a fortnight read as a campaign."""
    events = [
        _subagent_event(i, minutes=i * 60 * 40, corr=f"sess-{i}") for i in range(9)
    ]
    assert rule_host_subagent_swarm_burst(events) == []


def test_host_swarm_within_the_hour_fires():
    events = [
        _subagent_event(i, minutes=i * 3, corr=f"sess-{i}") for i in range(9)
    ]
    detections = rule_host_subagent_swarm_burst(events)
    assert len(detections) == 1
    assert "workstation-1" in detections[0].summary


# --- host checkpoint expiry ---------------------------------------------------

def test_is_expired_boundaries():
    fresh = datetime.now(timezone.utc).isoformat()
    stale = (
        datetime.now(timezone.utc) - timedelta(seconds=HOST_EMIT_TTL_SECONDS + 60)
    ).isoformat()
    assert not _is_expired(fresh)
    assert _is_expired(stale)
    assert _is_expired("garbage"), "an unreadable clock must re-arm, not silence"


@pytest.fixture
def store(tmp_path):
    return LiveDetectionStore(tmp_path / "live.db")


def test_fresh_host_mark_suppresses(store):
    store.mark_host_emitted("host-1", "host-subagent-swarm-burst")
    assert store.is_host_emitted("host-1", "host-subagent-swarm-burst")


def test_expired_host_mark_re_arms_the_rule(store):
    old = (
        datetime.now(timezone.utc) - timedelta(seconds=HOST_EMIT_TTL_SECONDS + 60)
    ).isoformat()
    store.mark_host_emitted("host-1", "host-subagent-swarm-burst", emitted_at=old)
    assert not store.is_host_emitted("host-1", "host-subagent-swarm-burst")


def test_legacy_row_without_a_timestamp_re_arms(store):
    """Upgrades must not inherit permanent silence from pre-expiry rows."""
    conn = store._get_conn()
    conn.execute(
        "INSERT INTO live_host_emitted (host_id, rule_id, emitted_at) VALUES (?, ?, '')",
        ("host-1", "host-subagent-swarm-burst"),
    )
    conn.commit()
    assert not store.is_host_emitted("host-1", "host-subagent-swarm-burst")


def test_re_marking_refreshes_the_suppression_clock(store):
    old = (
        datetime.now(timezone.utc) - timedelta(seconds=HOST_EMIT_TTL_SECONDS + 60)
    ).isoformat()
    store.mark_host_emitted("host-1", "rule-x", emitted_at=old)
    assert not store.is_host_emitted("host-1", "rule-x")
    store.mark_host_emitted("host-1", "rule-x")
    assert store.is_host_emitted("host-1", "rule-x"), "upsert must move the clock forward"


def test_session_marks_stay_permanent(store):
    """Sessions end; their checkpoints should not expire the way host ones do."""
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store.mark_emitted("sess-1", "credential-exfil", emitted_at=old)
    assert store.is_emitted("sess-1", "credential-exfil")
