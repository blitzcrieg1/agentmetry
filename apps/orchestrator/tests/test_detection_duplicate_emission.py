"""One finding, one row, even when an inferred approval re-runs the engine.

Issue #48. `process_external_event` synthesizes `approval_response` events from
the stream, then ran the detection engine over the real event and every
synthetic one. The synthetic event carries the correlation id of the event it
was derived from, so sequence rules re-evaluated the same session state and
returned the same finding twice.

The existing emitted-checkpoint could not catch it: the collection loop gathers
every detection before the emission loop writes any checkpoint, so both copies
were raised while the checkpoint was still unset. Observed in the trail as two
adjacent rows about 50 ms apart, distinct `event_id`, identical rule,
correlation, `event_ids` and both timestamps, differing only in
`source.adapter`: `claude_hook` against `claude_inferred`.

It inflated the dogfood detection count, double counted every SIEM dashboard
panel, and handed an operator two identical alerts to reconcile.
"""

from __future__ import annotations

import pytest

from agentmetry.core.config import settings
from agentmetry.core.audit.detection.live import reset_live_state
from agentmetry.core.audit.ingest import (
    ingest_external_event,
    reset_ingest_sink_cache,
    reset_pending_approvals,
)


class _CollectingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)

    def of_type(self, action_type: str) -> list[dict]:
        return [e for e in self.events if (e.get("action") or {}).get("type") == action_type]


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _CollectingSink:
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from agentmetry.core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_live_state()
    reset_pending_approvals()
    reset_ingest_sink_cache()
    s = _CollectingSink()
    monkeypatch.setattr("agentmetry.core.audit.ingest._get_sink", lambda: s)
    return s


def _trail_detections(corr: str) -> list[dict]:
    from agentmetry.core.audit.trail_db import get_trail_db

    return [
        e
        for e in get_trail_db().session(corr)
        if (e.get("action") or {}).get("type") == "detection"
    ]


def _cred_read(corr: str) -> dict:
    return {
        "source_app": "claude",
        "event_type": "tool_called",
        "outcome": "success",
        "correlation_id": corr,
        "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"},
    }


def _approval_pending(corr: str) -> dict:
    return {
        "source_app": "claude",
        "event_type": "approval_request",
        "outcome": "pending",
        "correlation_id": corr,
        "tool": {"qualified": "WebFetch", "server": "claude"},
    }


def _egress(corr: str) -> dict:
    return {
        "source_app": "claude",
        "event_type": "tool_called",
        "outcome": "success",
        "correlation_id": corr,
        "tool": {"qualified": "WebFetch", "command": "fetch https://example.com"},
    }


async def _session_where_the_rule_completes_on_an_approved_call(corr: str) -> None:
    """Land the finding on the same ingest call that closes a pending approval.

    Order matters more than it looks. `WebFetch` is C2-mapped by tool name, so
    the approval *request* is itself an egress-shaped event. Put the credential
    read first and credential-exfil completes at the request, one event before
    the approval is consumed, and the checkpoint is already set by the time the
    inferred event appears. That was the first version of this test, and it
    passed against the unfixed code for that reason.

    With the request first there is no credential read behind it yet, so the
    rule stays dormant until the read and then the real call arrive. The finding
    then lands on the same batch that synthesizes the approval_response, which
    is the production shape.
    """
    await ingest_external_event(_approval_pending(corr))
    await ingest_external_event(_cred_read(corr))
    await ingest_external_event(_egress(corr))


@pytest.mark.asyncio
async def test_inferred_approval_does_not_duplicate_the_finding(sink: _CollectingSink):
    corr = "sess-dup"
    # The last call both closes the pending approval, which synthesizes an
    # inferred approval_response, and completes credential-exfil. Before the fix
    # the engine ran over the real event and the synthetic one and emitted the
    # finding twice, as `claude_hook` and `claude_inferred`.
    await _session_where_the_rule_completes_on_an_approved_call(corr)

    # The inferred approval itself is still produced. It is a real signal about
    # what a human consented to and nothing here should suppress it.
    inferred = [
        e
        for e in sink.events
        if (e.get("source") or {}).get("adapter", "").endswith("_inferred")
    ]
    assert len(inferred) == 1

    forwarded = [d for d in sink.of_type("detection") if d["detection"]["rule_id"] == "credential-exfil"]
    assert len(forwarded) == 1

    trail = [d for d in _trail_detections(corr) if d["detection"]["rule_id"] == "credential-exfil"]
    assert len(trail) == 1


@pytest.mark.asyncio
async def test_surviving_copy_is_attributed_to_the_real_capture_path(sink: _CollectingSink):
    """The hook saw this happen. The synthetic event only inferred it.

    `canonical` leads the iteration and the inferred events trail it, so keeping
    the first occurrence attributes the finding to the adapter that actually
    observed the tool call rather than to an event the recorder made up.
    """
    corr = "sess-attrib"
    await _session_where_the_rule_completes_on_an_approved_call(corr)

    trail = [d for d in _trail_detections(corr) if d["detection"]["rule_id"] == "credential-exfil"]
    assert len(trail) == 1
    assert not str((trail[0].get("source") or {}).get("adapter", "")).endswith("_inferred")


@pytest.mark.asyncio
async def test_a_later_session_event_still_cannot_refire_it(sink: _CollectingSink):
    """Dedup within the batch must not weaken the checkpoint across batches."""
    corr = "sess-once"
    await _session_where_the_rule_completes_on_an_approved_call(corr)
    await ingest_external_event(_egress(corr))
    await ingest_external_event(_egress(corr))

    forwarded = [d for d in sink.of_type("detection") if d["detection"]["rule_id"] == "credential-exfil"]
    assert len(forwarded) == 1


@pytest.mark.asyncio
async def test_distinct_rules_in_one_batch_are_all_kept(sink: _CollectingSink):
    """The key is (scope, rule_id), so deduping never collapses two findings."""
    corr = "sess-multi"
    await _session_where_the_rule_completes_on_an_approved_call(corr)

    rule_ids = {d["detection"]["rule_id"] for d in _trail_detections(corr)}
    # Whatever else fired alongside it, each rule appears exactly once.
    counts: dict[str, int] = {}
    for d in _trail_detections(corr):
        rid = d["detection"]["rule_id"]
        counts[rid] = counts.get(rid, 0) + 1
    assert rule_ids, "expected at least one finding"
    assert all(n == 1 for n in counts.values()), counts
