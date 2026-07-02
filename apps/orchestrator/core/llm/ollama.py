"""Ollama LLM client with optional WebSocket token streaming."""

from __future__ import annotations

import json
from typing import Any

import httpx

from api.websocket import ws_manager
from core.config import settings


async def call_llm(
    prompt: str,
    system: str = "",
    *,
    session_id: str = "",
    node: str = "",
) -> str:
    """Call Ollama with streaming when session_id is set, mock fallback otherwise."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        if session_id and node:
            streamed = await _stream_chat(messages, session_id, node)
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
                return resp.json()["message"]["content"]
    except Exception:
        pass

    mock = f"[Mock LLM Response for: {prompt[:100]}...]"
    if session_id and node:
        for word in mock.split(" "):
            await ws_manager.send_token_stream(session_id, word + " ", node)
    return mock


async def _stream_chat(
    messages: list[dict[str, str]],
    session_id: str,
    node: str,
) -> str | None:
    """Stream tokens from Ollama to the dashboard via WebSocket."""
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
                        await ws_manager.send_token_stream(session_id, token, node)

                    if chunk.get("done"):
                        break
    except Exception:
        return None

    if not parts:
        return None
    return "".join(parts)
