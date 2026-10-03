"""The identity extension point (pilot hardening item 6).

Agentmetry Enterprise used to monkeypatch `identity_fields` in four modules
that had imported it by name. These tests pin the replacement: a provider
registered once is seen by every call site, with no patching.
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit import identity


@pytest.fixture(autouse=True)
def _clean_providers():
    saved = list(identity._PROVIDERS)
    identity._PROVIDERS.clear()
    yield
    identity._PROVIDERS[:] = saved


def test_without_a_provider_the_machine_answers():
    assert identity.identity_fields()["host_id"] == identity.host_id()


def test_a_provider_answers_for_every_call_site():
    """The modules import the function by name. A provider must reach them all
    without anything being replaced in their namespaces."""
    from agentmetry.core.audit import canonical, external, heartbeat
    from agentmetry.core.audit.detection import disposition, live

    identity.register_identity_provider(lambda: {"host_id": "token-host", "fleet_id": "acme"})
    for module in (canonical, external, heartbeat, disposition, live):
        assert module.identity_fields is identity.identity_fields, module.__name__
        assert module.identity_fields() == {"host_id": "token-host", "fleet_id": "acme"}


def test_a_provider_returning_none_defers_to_the_machine():
    identity.register_identity_provider(lambda: None)
    assert identity.identity_fields()["host_id"] == identity.host_id()


def test_a_failing_provider_is_skipped_not_fatal(caplog):
    def broken():
        raise RuntimeError("boom")

    identity.register_identity_provider(broken)
    assert identity.identity_fields()["host_id"] == identity.host_id()
    assert "identity provider" in caplog.text


def test_registration_is_idempotent_and_reversible():
    def provider():
        return {"host_id": "x"}

    identity.register_identity_provider(provider)
    identity.register_identity_provider(provider)
    assert identity._PROVIDERS == [provider]
    identity.unregister_identity_provider(provider)
    assert identity._PROVIDERS == []


def test_the_returned_mapping_is_a_copy():
    shared = {"host_id": "x"}
    identity.register_identity_provider(lambda: shared)
    identity.identity_fields()["host_id"] = "mutated"
    assert shared["host_id"] == "x"
