"""The event signing extension point (pilot hardening item 24).

The core signs nothing itself. It gives an extension a place to sign, sends the
signature beside each batched event, and never changes the event or the trail.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agentmetry.core.audit import signing
from agentmetry.core.audit.sinks import WebhookAuditSink
from agentmetry.core.audit.trail_chain import canonical_event_json


@pytest.fixture(autouse=True)
def _no_signer():
    signing.unregister_event_signer()
    yield
    signing.unregister_event_signer()


def _event(n: int = 1) -> dict:
    return {"event_id": f"e{n}", "action": {"type": "tool_called"}, "host_id": "h1"}


def test_the_message_is_the_chain_canonical_form_with_a_domain_prefix():
    event = _event()
    assert signing.signing_message(event) == b"agentmetry-event-v1\n" + canonical_event_json(event).encode()


def test_without_a_signer_events_go_bare():
    assert signing.wrap_for_batch(_event()) == _event()


def test_a_signer_wraps_the_event_without_changing_it():
    signing.register_event_signer(lambda e: {"alg": "test", "sig": e["event_id"]})
    wrapped = signing.wrap_for_batch(_event())
    assert wrapped == {"event": _event(), "signature": {"alg": "test", "sig": "e1"}}


def test_a_failing_signer_sends_unsigned_rather_than_nothing():
    def boom(_e):
        raise RuntimeError("keystore locked")

    signing.register_event_signer(boom)
    assert signing.wrap_for_batch(_event()) == _event()


async def test_the_console_batch_carries_signatures():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"accepted": 2})

    signing.register_event_signer(lambda e: {"alg": "test", "sig": e["event_id"]})
    sink = WebhookAuditSink("https://console.example/ingest/v1/events", format="batch")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await sink.send_batch(client, [_event(1), _event(2)])
    items = json.loads(seen[0].content)["events"]
    assert [i["signature"]["sig"] for i in items] == ["e1", "e2"]
    assert items[0]["event"] == _event(1)
