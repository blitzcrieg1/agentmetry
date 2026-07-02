"""Google Gemini API client with streaming support."""

from __future__ import annotations

import json
from typing import Any

import httpx

from api.websocket import ws_manager
from core.config import settings
from core.llm.pricing import cost_from_usage, fallback_token_estimate
from core.llm.types import LLMResult, LLMUsage


def _api_key() -> str:
    import os
    return (
        settings.gemini_api_key
        or os.getenv("BLACKBOX_GEMINI_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
        or os.getenv("GOOGLE_API_KEY", "")
    )

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _build_payload(prompt: str, system: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    return payload


def _extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if "text" in p)


def _usage_from_response(data: dict[str, Any], prompt: str, text: str) -> LLMUsage:
    meta = data.get("usageMetadata") or {}
    input_tokens = int(meta.get("promptTokenCount") or 0)
    output_tokens = int(meta.get("candidatesTokenCount") or 0)
    if input_tokens == 0 and output_tokens == 0:
        input_tokens = fallback_token_estimate(f"{prompt}")
        output_tokens = fallback_token_estimate(text)
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost_from_usage(input_tokens, output_tokens),
    )


async def call_gemini(
    prompt: str,
    system: str = "",
    *,
    session_id: str = "",
    node: str = "",
) -> LLMResult | None:
    """Call Gemini API. Returns None on failure so caller can fallback."""
    api_key = _api_key()
    if not api_key:
        return None

    model = settings.gemini_model
    payload = _build_payload(prompt, system)

    try:
        if session_id and node:
            streamed = await _stream_generate(model, payload, api_key, session_id, node, prompt)
            if streamed is not None:
                return streamed

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GEMINI_BASE}/models/{model}:generateContent",
                params={"key": api_key},
                json=payload,
                timeout=120.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            text = _extract_text(data)
            if not text:
                return None
            return LLMResult(text=text, usage=_usage_from_response(data, prompt, text))
    except Exception:
        return None


async def _stream_generate(
    model: str,
    payload: dict[str, Any],
    api_key: str,
    session_id: str,
    node: str,
    prompt: str,
) -> LLMResult | None:
    parts: list[str] = []
    usage = LLMUsage()
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{GEMINI_BASE}/models/{model}:streamGenerateContent",
                params={"key": api_key, "alt": "sse"},
                json=payload,
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    return None

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if chunk.get("usageMetadata"):
                        usage = _usage_from_response(chunk, prompt, "".join(parts))

                    token = _extract_text(chunk)
                    if token:
                        parts.append(token)
                        await ws_manager.send_token_stream(session_id, token, node)
    except Exception:
        return None

    if not parts:
        return None

    text = "".join(parts)
    if usage.input_tokens == 0 and usage.output_tokens == 0:
        usage = _usage_from_response({}, prompt, text)
    return LLMResult(text=text, usage=usage)


async def embed_gemini(
    text: str,
    *,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float] | None:
    """Embed text via Gemini API. Returns None on failure."""
    api_key = _api_key()
    if not api_key:
        return None

    model = settings.gemini_embedding_model
    payload: dict[str, Any] = {
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
        "outputDimensionality": settings.embedding_dimensions,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GEMINI_BASE}/models/{model}:embedContent",
                params={"key": api_key},
                json=payload,
                timeout=30.0,
            )
            if resp.status_code != 200:
                return None
            values = resp.json().get("embedding", {}).get("values")
            if not values:
                return None
            return values
    except Exception:
        return None


async def check_gemini_health() -> dict[str, Any]:
    """Verify Gemini API key and model access."""
    api_key = _api_key()
    if not api_key:
        return {
            "status": "down",
            "detail": "GEMINI_API_KEY not set",
            "fallback": "mock_llm",
        }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GEMINI_BASE}/models/{settings.gemini_model}:generateContent",
                params={"key": api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
                timeout=15.0,
            )
            if resp.status_code == 200:
                return {
                    "status": "up",
                    "model": settings.gemini_model,
                    "provider": "gemini",
                }
            return {
                "status": "down",
                "model": settings.gemini_model,
                "detail": f"HTTP {resp.status_code}: {resp.text[:80]}",
                "fallback": "mock_llm",
            }
    except Exception as exc:
        return {
            "status": "down",
            "model": settings.gemini_model,
            "detail": str(exc)[:120],
            "fallback": "mock_llm",
        }
