"""Telegram transport units — allowlist, callbacks, button markup, bus push."""

from __future__ import annotations

import pytest

import core.channels.telegram as telegram_module
from core.channels.base import ChannelReply, InboundMessage
from core.channels.telegram import TelegramChannel


@pytest.fixture
def channel(monkeypatch: pytest.MonkeyPatch):
    ch = TelegramChannel(token="test-token", allowed_chat_ids={"111"})
    calls: list[tuple[str, dict]] = []

    async def fake_api(method: str, payload: dict) -> dict:
        calls.append((method, payload))
        return {"ok": True, "result": []}

    monkeypatch.setattr(ch, "_api", fake_api)
    ch.calls = calls
    return ch


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch):
    """Capture what reaches the router and script its reply."""
    seen: list[InboundMessage] = []

    async def fake_route(msg: InboundMessage) -> ChannelReply:
        seen.append(msg)
        return ChannelReply(
            "ok", actions=[("Approve", "/approve abc12345"), ("Reject", "/reject abc12345")]
        )

    monkeypatch.setattr(telegram_module, "route_inbound", fake_route)
    return seen


def _text_update(chat_id: str, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 7,
            "chat": {"id": int(chat_id)},
            "text": text,
        },
    }


async def test_allowed_message_is_routed_and_answered(channel, routed):
    await channel._handle_update(_text_update("111", "/pending"))

    assert [m.text for m in routed] == ["/pending"]
    assert routed[0].sender_id == "111"
    methods = [m for m, _ in channel.calls]
    assert methods == ["sendMessage"]

    # Buttons render as one inline keyboard row of two.
    payload = channel.calls[0][1]
    keyboard = payload["reply_markup"]["inline_keyboard"]
    assert keyboard == [[
        {"text": "Approve", "callback_data": "/approve abc12345"},
        {"text": "Reject", "callback_data": "/reject abc12345"},
    ]]


async def test_non_allowlisted_chat_is_dropped(channel, routed):
    await channel._handle_update(_text_update("666", "/skill lead_gen x"))

    assert routed == []
    assert channel.calls == []


async def test_callback_button_press_routes_command(channel, routed):
    await channel._handle_update({
        "update_id": 2,
        "callback_query": {
            "id": "cb1",
            "data": "/approve abc12345",
            "message": {"chat": {"id": 111}},
        },
    })

    assert [m.text for m in routed] == ["/approve abc12345"]
    methods = [m for m, _ in channel.calls]
    assert methods == ["answerCallbackQuery", "sendMessage"]


async def test_callback_from_stranger_is_acked_but_not_routed(channel, routed):
    await channel._handle_update({
        "update_id": 3,
        "callback_query": {
            "id": "cb2",
            "data": "/approve abc12345",
            "message": {"chat": {"id": 666}},
        },
    })

    assert routed == []
    assert [m for m, _ in channel.calls] == ["answerCallbackQuery"]


async def test_push_approval_broadcasts_with_buttons(channel, monkeypatch):
    monkeypatch.setattr(
        telegram_module,
        "pending_threads",
        {"thread-abc-123": {"skill_name": "customer_reply"}},
    )

    await channel._push_approval({
        "thread_id": "thread-abc-123",
        "draft": "Dear customer, ...",
        "confidence": 0.42,
    })

    assert len(channel.calls) == 1
    method, payload = channel.calls[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == "111"
    assert "customer_reply" in payload["text"]
    assert "Dear customer" in payload["text"]
    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "/approve thread-a"


async def test_long_message_is_truncated(channel):
    await channel._send("111", ChannelReply("x" * 10_000))
    assert len(channel.calls[0][1]["text"]) == 4000


def test_constructor_requires_token_and_allowlist():
    with pytest.raises(ValueError):
        TelegramChannel(token="", allowed_chat_ids={"1"})
    with pytest.raises(ValueError):
        TelegramChannel(token="t", allowed_chat_ids=set())
