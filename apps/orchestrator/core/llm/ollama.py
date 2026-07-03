"""Ollama LLM client with optional WebSocket token streaming."""

from __future__ import annotations

import json

import httpx

from core.bus.bus import bus
from core.bus.events import LLM_TOKEN
from core.config import settings
from core.llm.pricing import cost_from_usage, fallback_token_estimate
from core.llm.types import LLMResult, LLMUsage


async def call_ollama(
    prompt: str,
    system: str = "",
    *,
    session_id: str = "",
    node: str = "",
) -> LLMResult | None:
    """Call Ollama. Returns None on failure."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        if session_id and node:
            streamed = await _stream_chat(messages, prompt, system, session_id, node)
            if streamed is not None:
                return streamed

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=120.0,
            )
            if resp.status_code == 200:
                text = resp.json()["message"]["content"]
                input_tokens = fallback_token_estimate(f"{system}\n{prompt}")
                output_tokens = fallback_token_estimate(text)
                return LLMResult(
                    text=text,
                    usage=LLMUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost=cost_from_usage(input_tokens, output_tokens),
                    ),
                    provider="ollama",
                )
    except Exception:
        pass
    return None


async def _stream_chat(
    messages: list[dict[str, str]],
    prompt: str,
    system: str,
    session_id: str,
    node: str,
) -> LLMResult | None:
    parts: list[str] = []
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_base_url}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    return None

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        parts.append(token)
                        bus.publish(
                            LLM_TOKEN,
                            {"type": "token", "token": token, "node": node},
                            session_id=session_id,
                        )

                    if chunk.get("done"):
                        break
    except Exception:
        return None

    if not parts:
        return None

    text = "".join(parts)
    input_tokens = fallback_token_estimate(f"{system}\n{prompt}")
    output_tokens = fallback_token_estimate(text)
    return LLMResult(
        text=text,
        usage=LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost_from_usage(input_tokens, output_tokens),
        ),
        provider="ollama",
    )
