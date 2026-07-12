"""Audit payload for gmail.send_draft includes SHA-256 of arguments."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bus.events import TOOL_CALLED
from core.bus.bus import bus
from core.drivers.host import MCPHost
from core.drivers.spec import DriverSpec

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


async def test_send_draft_tool_call_includes_hash(monkeypatch: pytest.MonkeyPatch):
    captured: list[tuple] = []
    original = bus.publish

    def capture_publish(topic, payload, *, session_id="", thread_id=""):
        captured.append((topic, payload, session_id, thread_id))
        return original(topic, payload, session_id=session_id, thread_id=thread_id)

    monkeypatch.setattr(bus, "publish", capture_publish)

    host = MCPHost()
    spec = DriverSpec(
        name="fake",
        transport="stdio",
        command=sys.executable,
        args=[str(_FIXTURE)],
    )
    assert await host.mount(spec)

    meta = host._tools["fake.echo"]
    host._tools["gmail.send_draft"] = type(meta)(
        driver="fake",
        name="send_draft",
        qualified="gmail.send_draft",
        description="shadow",
        tags=[],
    )
    driver = host._drivers["fake"]
    driver.session = MagicMock()
    driver.session.call_tool = AsyncMock(return_value=MagicMock(content=[]))

    args = {"draft_id": "draft-abc"}
    await host.call_tool(
        "gmail.send_draft",
        args,
        skill_config={"name": "customer_reply", "tools": ["gmail.*"]},
        session_id="s1",
        thread_id="t1",
    )

    sent = [p for topic, p, _, _ in captured if topic == TOOL_CALLED]
    assert len(sent) == 1
    payload = sent[0]
    expected = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert payload["arguments_sha256"] == expected
    assert payload["draft_id"] == "draft-abc"

    captured.clear()
    await host.call_tool(
        "fake.echo",
        {"message": "hi"},
        skill_config={"name": "customer_reply", "tools": ["fake.*"]},
        session_id="s2",
        thread_id="t2",
    )
    echo_payload = [p for topic, p, _, _ in captured if topic == TOOL_CALLED][0]
    assert "arguments_sha256" in echo_payload

    await host.unmount_all()
