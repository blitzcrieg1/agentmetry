"""Mock LLM fallback when no provider is available."""

from __future__ import annotations

from api.websocket import ws_manager


async def call_mock(
    prompt: str,
    *,
    session_id: str = "",
    node: str = "",
) -> str:
    mock = f"[Mock LLM Response for: {prompt[:100]}...]"
    if session_id and node:
        for word in mock.split(" "):
            await ws_manager.send_token_stream(session_id, word + " ", node)
    return mock
