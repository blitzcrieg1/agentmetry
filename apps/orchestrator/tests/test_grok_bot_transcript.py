"""Grok Bot chat lines record as grok_bot, not cursor."""

from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.grok_bot_transcript import payloads_for_entries


def test_grok_bot_is_a_known_source_not_cursor():
    out = build_external_canonical({
        "source_app": "grok_bot",
        "event_type": "tool_called",
        "correlation_id": "ab2996c5-04be-419f-a343-f9ef34089e81",
        "tool": {
            "qualified": "grok_bot.assistant",
            "command": "I'll search your PC for AEON",
        },
    })
    assert out["source"]["app"] == "grok_bot"
    assert out["agent"]["name"] == "grok_bot"
    assert not out["source"].get("claimed_app")
    assert out["tool"]["command"].startswith("I'll search")


def test_transcript_entries_keep_the_grok_bot_source():
    entries = [
        {
            "kind": "message",
            "id": "t29u",
            "role": "user",
            "content": "try to find for AEON videography",
            "timestampMs": 1792090910340,
        },
        {
            "kind": "send-message",
            "id": "t29s0",
            "message": {"type": "text", "content": "I'll search your PC."},
            "timestampMs": 1792090913265,
        },
    ]
    payloads = payloads_for_entries(entries, agent_id="ab2996c5-04be-419f-a343-f9ef34089e81")
    assert [p["source_app"] for p in payloads] == ["grok_bot", "grok_bot"]
    assert payloads[0]["tool"]["qualified"] == "grok_bot.user"
    assert payloads[1]["tool"]["qualified"] == "grok_bot.assistant"
    assert payloads[0]["correlation_id"] == "ab2996c5-04be-419f-a343-f9ef34089e81"
    assert payloads[0]["timestamp_utc"].startswith("2026-")
