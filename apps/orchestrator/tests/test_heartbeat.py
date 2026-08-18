"""Heartbeat: making bypass loud, since it cannot be made impossible.

A hook lives in a file the developer owns. The honest answer to "what stops me
deleting it" is nothing, and the useful answer is that deleting it changes what
the recorder says about itself on the next beat.

`test_a_removed_hook_degrades_the_next_beat` is the test that carries the claim.
Everything else guards the ways a heartbeat can be worse than useless: a beat
that keeps saying healthy while capture is off, or one that only means something
if you already know Agentmetry's vocabulary.
"""

from __future__ import annotations

import json

import pytest

from agentmetry.core.audit import heartbeat as hb


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Point hook discovery at a scratch home with both hooks installed."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".cursor").mkdir(parents=True)
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".cursor" / "hooks.json").write_text(
        json.dumps({"hooks": [{"command": "agentmetry_ingest.py"}]}), encoding="utf-8"
    )
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": "agentmetry_ingest.py"}}), encoding="utf-8"
    )
    return tmp_path


# ----------------------------------------------------------------------
# The claim
# ----------------------------------------------------------------------


def test_a_healthy_recorder_attests_success(home, monkeypatch):
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    event = hb.build_heartbeat_event("2026-08-18T12:00:00+00:00")
    assert event["action"]["outcome"] == "success"
    assert event["heartbeat"]["hooks"] == {"cursor": True, "claude": True}


def test_a_removed_hook_degrades_the_next_beat(home, monkeypatch):
    """The whole point.

    Silence cannot distinguish a disabled recorder from a developer in meetings.
    A beat that keeps arriving with `hooks.cursor` false says exactly which of
    the two happened, and says it without any agent-side enforcement.
    """
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    (home / ".cursor" / "hooks.json").unlink()

    event = hb.build_heartbeat_event("2026-08-18T12:05:00+00:00")

    assert event["action"]["outcome"] == "degraded"
    assert event["heartbeat"]["hooks"]["cursor"] is False
    assert event["heartbeat"]["hooks"]["claude"] is True
    assert "cursor" in event["action"]["reason"]


def test_a_hook_file_that_no_longer_calls_us_counts_as_removed(home, monkeypatch):
    """Editing the hook out is quieter than deleting the file, and identical in
    effect. Presence of the file proves nothing."""
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": "something-else.py"}}), encoding="utf-8"
    )
    event = hb.build_heartbeat_event("2026-08-18T12:05:00+00:00")
    assert event["heartbeat"]["hooks"]["claude"] is False
    assert event["action"]["outcome"] == "degraded"


def test_hook_status_is_re_read_every_beat(home, monkeypatch):
    """A value cached at boot would keep asserting the configuration the machine
    had when it last rebooted, which is the lie this feature exists to prevent."""
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    assert hb.build_heartbeat_event("t")["heartbeat"]["hooks"]["cursor"] is True
    (home / ".cursor" / "hooks.json").unlink()
    assert hb.build_heartbeat_event("t")["heartbeat"]["hooks"]["cursor"] is False


def test_a_backed_up_spool_also_degrades(home, monkeypatch):
    """Hooks installed and events not reaching the trail is its own blind spot,
    and it is what an 8-day outage looked like from the outside."""
    monkeypatch.setattr(hb, "_spool_depth", lambda: 1713)
    event = hb.build_heartbeat_event("2026-08-18T12:00:00+00:00")
    assert event["action"]["outcome"] == "degraded"
    assert "1713" in event["action"]["reason"]


# ----------------------------------------------------------------------
# Usable by a SIEM that has never heard of Agentmetry
# ----------------------------------------------------------------------


def test_severity_rides_on_action_outcome(home, monkeypatch):
    """`action.type:heartbeat AND action.outcome:degraded` has to be the whole
    rule. A detection a customer must learn a vocabulary to write is one they do
    not write."""
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    healthy = hb.build_heartbeat_event("t")
    (home / ".claude" / "settings.json").unlink()
    broken = hb.build_heartbeat_event("t")
    assert healthy["action"]["type"] == broken["action"]["type"] == "heartbeat"
    assert (healthy["action"]["outcome"], broken["action"]["outcome"]) == ("success", "degraded")


def test_the_event_is_canonical_and_carries_identity(home, monkeypatch):
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    event = hb.build_heartbeat_event("2026-08-18T12:00:00+00:00")
    for field in ("schema_version", "event_id", "timestamp_utc", "host_id", "source", "action"):
        assert field in event, field
    assert event["source_topic"] == "agentmetry/heartbeat"


def test_no_developer_content_reaches_the_beat(home, monkeypatch):
    """It attests to configuration, not to work. A heartbeat that leaked file
    paths or commands would be a surveillance feed rather than a health signal,
    and would deserve every objection a works council could raise."""
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    facts = hb.build_heartbeat_event("t")["heartbeat"]
    assert set(facts) == {
        "hooks", "spool_depth", "trail_head_seq", "mcp_config_digest", "interval_seconds",
    }
    assert isinstance(facts["mcp_config_digest"], str)


def test_the_mcp_digest_names_no_server(home, monkeypatch):
    """It commits to the configured surface so a change is detectable, without
    shipping anybody's tool inventory to the SOC."""
    monkeypatch.setattr("os.path.expanduser", lambda p: str(home))
    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"very-secret-internal-tool": {"command": "x"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(hb, "_spool_depth", lambda: 0)
    blob = json.dumps(hb.build_heartbeat_event("t"))
    assert "very-secret-internal-tool" not in blob
    assert len(hb.build_heartbeat_event("t")["heartbeat"]["mcp_config_digest"]) == 16


# ----------------------------------------------------------------------
# Interval
# ----------------------------------------------------------------------


def test_interval_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("AGENTMETRY_HEARTBEAT_SECONDS", raising=False)
    assert hb.interval_seconds() == hb.DEFAULT_INTERVAL_SECONDS
    monkeypatch.setenv("AGENTMETRY_HEARTBEAT_SECONDS", "60")
    assert hb.interval_seconds() == 60


@pytest.mark.parametrize("raw", ["0", "-5", "banana"])
def test_a_bad_or_zero_interval_never_busy_loops(monkeypatch, raw):
    """Zero disables. Nonsense falls back to the default. Neither spins."""
    monkeypatch.setenv("AGENTMETRY_HEARTBEAT_SECONDS", raw)
    value = hb.interval_seconds()
    assert value == 0 or value >= 60


def test_a_disabled_heartbeat_returns_instead_of_looping(monkeypatch):
    import asyncio

    monkeypatch.setenv("AGENTMETRY_HEARTBEAT_SECONDS", "0")
    asyncio.run(asyncio.wait_for(hb.heartbeat_forever(), timeout=2))
