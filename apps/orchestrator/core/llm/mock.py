"""Mock LLM fallback when no provider is available."""

from __future__ import annotations

from api.websocket import ws_manager
from core.llm.pricing import cost_from_usage, fallback_token_estimate
from core.llm.types import LLMResult, LLMUsage


async def call_mock(
    prompt: str,
    *,
    session_id: str = "",
    node: str = "",
) -> LLMResult:
    mock = f"[Mock LLM Response for: {prompt[:100]}...]"
    if session_id and node:
        for word in mock.split(" "):
            await ws_manager.send_token_stream(session_id, word + " ", node)
    input_tokens = fallback_token_estimate(prompt)
    output_tokens = fallback_token_estimate(mock)
    return LLMResult(
        text=mock,
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost_from_usage(input_tokens, output_tokens),
        ),
    )
