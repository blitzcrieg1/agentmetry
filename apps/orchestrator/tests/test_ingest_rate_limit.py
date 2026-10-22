"""Ingest is rate limited per source app and per session (#312).

Before, one runaway or prompt-injected agent holding the ingest token could
write without limit and bury every other agent's events. Past a cap the route
now answers 429; the hook spools that (test_hook_spool.py covers it) and the
recorder's drain replays it, so a burst is late, not lost.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core.audit import ingest_quota
from agentmetry.core.audit.ingest_quota import IngestLimiter
from agentmetry.core.audit.trail_chain import verify_trail_file
from agentmetry.core.config import settings


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _limiter(clock: Clock, **kw) -> IngestLimiter:
    args = {"source_rate": 1.0, "source_burst": 3, "session_rate": 0.0, "session_burst": 1, "clock": clock}
    args.update(kw)
    return IngestLimiter(**args)


# --- the buckets -------------------------------------------------------------------


def test_a_burst_past_the_allowance_is_refused_then_refills():
    clock = Clock()
    lim = _limiter(clock)
    assert [lim.allow("cursor", "s") for _ in range(4)] == [True, True, True, False]
    clock.now = 2.0
    assert [lim.allow("cursor", "s") for _ in range(3)] == [True, True, False]


def test_one_source_flooding_does_not_throttle_another():
    lim = _limiter(Clock())
    for _ in range(10):
        lim.allow("cursor", "s")
    assert lim.allow("claude", "s") is True


def test_the_session_cap_holds_inside_a_generous_source_cap():
    lim = _limiter(Clock(), source_rate=100.0, source_burst=100, session_rate=1.0, session_burst=2)
    assert [lim.allow("cursor", "a") for _ in range(3)] == [True, True, False]
    assert lim.allow("cursor", "b") is True


def test_a_refused_event_spends_nothing():
    """Refusing on the session cap must not drain the source bucket too."""
    lim = _limiter(Clock(), source_rate=1.0, source_burst=3, session_rate=1.0, session_burst=1)
    assert lim.allow("cursor", "a") is True
    assert lim.allow("cursor", "a") is False
    assert lim.allow("cursor", "b") is True
    assert lim.allow("cursor", "c") is True
    assert lim.allow("cursor", "d") is False


def test_a_rate_of_zero_turns_the_limit_off():
    lim = _limiter(Clock(), source_rate=0.0, session_rate=0.0)
    assert all(lim.allow("cursor", "s") for _ in range(1000))


def test_inventing_a_session_per_event_cannot_grow_memory(monkeypatch):
    monkeypatch.setattr(ingest_quota, "MAX_SESSION_BUCKETS", 5)
    lim = _limiter(Clock(), source_rate=0.0, session_rate=1.0, session_burst=1)
    for i in range(50):
        lim.allow("cursor", f"s{i}")
    assert len(lim._sessions) == 5


def test_throttling_is_counted_per_source():
    lim = _limiter(Clock(), source_burst=1)
    lim.allow("cursor", "s")
    lim.allow("cursor", "s")
    lim.allow("cursor", "s")
    snap = lim.snapshot()
    assert snap["total"] == 2
    assert snap["by_source"] == {"cursor": 2}
    assert snap["last_utc"]


# --- the route ---------------------------------------------------------------------


_EVENT = {
    "source_app": "cursor",
    "event_type": "tool_called",
    "correlation_id": "rate-limit-test",
    "tool": {"qualified": "shell.run", "server": "shell", "input_hash": "0" * 64},
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "audit_ingest_source_rate", 0.001)
    monkeypatch.setattr(settings, "audit_ingest_source_burst", 3.0)
    monkeypatch.setattr(settings, "audit_ingest_session_rate", 0.0)
    ingest_quota.reset_limiter()
    from agentmetry.api.main import app

    return TestClient(app)


def test_past_the_cap_ingest_answers_429_and_the_trail_stays_whole(client: TestClient):
    codes = [client.post("/api/v1/audit/ingest", json=_EVENT).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]

    refused = client.post("/api/v1/audit/ingest", json=_EVENT)
    assert int(refused.headers["retry-after"]) >= 1

    trail = Path(settings.audit_export_path)
    assert verify_trail_file(trail).ok
    assert sum(1 for line in trail.read_text(encoding="utf-8").splitlines() if line.strip()) == 3


def test_inventing_an_agent_name_per_event_does_not_get_a_fresh_bucket(client: TestClient):
    """Unlisted names are recorded as `unknown`, and the limit keys on that.
    Keyed on the raw name, each invented name was a new, full bucket."""
    codes = [
        client.post("/api/v1/audit/ingest", json={**_EVENT, "source_app": f"made-up-{i}"}).status_code
        for i in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]
    throttled = client.get("/api/v1/audit/status").json()["ingest_throttled"]
    assert throttled["by_source"] == {"unknown": 2}


def test_status_reports_the_throttling(client: TestClient):
    for _ in range(5):
        client.post("/api/v1/audit/ingest", json=_EVENT)
    throttled = client.get("/api/v1/audit/status").json()["ingest_throttled"]
    assert throttled["total"] == 2
    assert throttled["by_source"] == {"cursor": 2}


def test_the_default_allowance_takes_the_whole_demo_seed_at_once(monkeypatch: pytest.MonkeyPatch):
    """The demo seeder posts every session as fast as it can. With the shipped
    defaults, not the suite's "off", none of it may be refused."""
    import importlib.util

    defaults = type(settings).model_fields
    for name in ("source_rate", "source_burst", "session_rate", "session_burst"):
        monkeypatch.setattr(settings, f"audit_ingest_{name}", defaults[f"audit_ingest_{name}"].default)
    ingest_quota.reset_limiter()
    seed = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo_for_rate_limit", seed)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from agentmetry.api.main import app

    client = TestClient(app)
    codes = {client.post("/api/v1/audit/ingest", json=e).status_code for e in module.build()}
    assert 429 not in codes
