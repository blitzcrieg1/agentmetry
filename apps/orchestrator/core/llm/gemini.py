"""Google Gemini API client with streaming support."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from api.websocket import ws_manager
from core.config import settings
from core.llm.degraded import llm_degraded
from core.llm.pricing import cost_from_usage, fallback_token_estimate
from core.llm.quota import get_cached_health, set_cached_health, throttle_embed, throttle_flash
from core.llm.types import LLMResult, LLMUsage

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_MAX_RETRIES = 3


def _mock_fallback() -> str:
    """Health-status hint: mock is only a real fallback when explicitly allowed."""
    return "mock_llm" if settings.allow_mock else "none"


def _api_key() -> str:
    import os
    return (
        settings.gemini_api_key
        or os.getenv("BLACKBOX_GEMINI_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
        or os.getenv("GOOGLE_API_KEY", "")
    )


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


def _retry_after(resp: httpx.Response) -> int:
    header = resp.headers.get("Retry-After", "")
    try:
        return max(int(header), 5)
    except ValueError:
        return 30


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str],
    json_body: dict[str, Any],
    timeout: float,
    throttle: Any = None,
) -> httpx.Response | None:
    for attempt in range(_MAX_RETRIES):
        if throttle is not None:
            await throttle()
        resp = await client.post(url, params=params, json=json_body, timeout=timeout)
        if resp.status_code == 200:
            llm_degraded.clear()
            return resp
        if resp.status_code == 429:
            wait = _retry_after(resp) * (attempt + 1)
            llm_degraded.set_degraded("Gemini rate limited (HTTP 429)", retry_after=wait)
            logger.warning("Gemini 429 — retry %d/%d in %ds", attempt + 1, _MAX_RETRIES, wait)
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(wait)
                continue
            return resp
        logger.warning("Gemini HTTP %s: %s", resp.status_code, resp.text[:120])
        return resp
    return None


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
            resp = await _post_with_retry(
                client,
                f"{GEMINI_BASE}/models/{model}:generateContent",
                params={"key": api_key},
                json_body=payload,
                timeout=120.0,
                throttle=throttle_flash,
            )
            if resp is None or resp.status_code != 200:
                return None
            data = resp.json()
            text = _extract_text(data)
            if not text:
                return None
            return LLMResult(
                text=text,
                usage=_usage_from_response(data, prompt, text),
                provider="gemini",
            )
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
            for attempt in range(_MAX_RETRIES):
                await throttle_flash()
                async with client.stream(
                    "POST",
                    f"{GEMINI_BASE}/models/{model}:streamGenerateContent",
                    params={"key": api_key, "alt": "sse"},
                    json=payload,
                    timeout=120.0,
                ) as resp:
                    if resp.status_code == 429:
                        wait = _retry_after(resp) * (attempt + 1)
                        llm_degraded.set_degraded("Gemini rate limited (HTTP 429)", retry_after=wait)
                        if attempt < _MAX_RETRIES - 1:
                            await asyncio.sleep(wait)
                            continue
                        return None
                    if resp.status_code != 200:
                        return None

                    llm_degraded.clear()
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
                break
    except Exception:
        return None

    if not parts:
        return None

    text = "".join(parts)
    if usage.input_tokens == 0 and usage.output_tokens == 0:
        usage = _usage_from_response({}, prompt, text)
    return LLMResult(text=text, usage=usage, provider="gemini")


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
            resp = await _post_with_retry(
                client,
                f"{GEMINI_BASE}/models/{model}:embedContent",
                params={"key": api_key},
                json_body=payload,
                timeout=30.0,
                throttle=throttle_embed,
            )
            if resp is None or resp.status_code != 200:
                return None
            values = resp.json().get("embedding", {}).get("values")
            if not values:
                return None
            return values
    except Exception:
        return None


EMBED_BATCH_SIZE = 100  # batchEmbedContents request limit


async def embed_gemini_batch(
    texts: list[str],
    *,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]] | None:
    """Embed multiple texts in a single API call. Returns None on failure."""
    api_key = _api_key()
    if not api_key or not texts:
        return None

    model = settings.gemini_embedding_model
    payload: dict[str, Any] = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
                "outputDimensionality": settings.embedding_dimensions,
            }
            for text in texts
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await _post_with_retry(
                client,
                f"{GEMINI_BASE}/models/{model}:batchEmbedContents",
                params={"key": api_key},
                json_body=payload,
                timeout=60.0,
                throttle=throttle_embed,
            )
            if resp is None or resp.status_code != 200:
                return None
            embeddings = resp.json().get("embeddings") or []
            values = [e.get("values") for e in embeddings]
            if len(values) != len(texts) or any(not v for v in values):
                return None
            return values
    except Exception:
        return None


async def check_gemini_health() -> dict[str, Any]:
    """Verify Gemini API key and model access."""
    if llm_degraded.active:
        payload = {
            "status": "degraded",
            "model": settings.gemini_model,
            "provider": "gemini",
            "detail": llm_degraded.reason,
            "retry_after_seconds": llm_degraded.retry_after_seconds,
            "fallback": "none",
        }
        set_cached_health(payload)
        return payload

    cached = get_cached_health()
    if cached is not None:
        return cached

    api_key = _api_key()
    if not api_key:
        return {
            "status": "down",
            "detail": "GEMINI_API_KEY not set",
            "fallback": _mock_fallback(),
        }

    if not settings.gemini_health_probe:
        payload = {
            "status": "up",
            "model": settings.gemini_model,
            "provider": "gemini",
            "detail": "passive check (set BLACKBOX_GEMINI_HEALTH_PROBE=true to live-probe)",
        }
        set_cached_health(payload)
        return payload

    try:
        await throttle_flash()
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
                llm_degraded.clear()
                payload = {
                    "status": "up",
                    "model": settings.gemini_model,
                    "provider": "gemini",
                }
                set_cached_health(payload)
                return payload
            if resp.status_code == 429:
                wait = _retry_after(resp)
                llm_degraded.set_degraded("Gemini rate limited (HTTP 429)", retry_after=wait)
                payload = {
                    "status": "degraded",
                    "model": settings.gemini_model,
                    "detail": f"HTTP 429 — retry after ~{wait}s",
                    "retry_after_seconds": wait,
                    "fallback": "none",
                }
                set_cached_health(payload)
                return payload
            payload = {
                "status": "down",
                "model": settings.gemini_model,
                "detail": f"HTTP {resp.status_code}: {resp.text[:80]}",
                "fallback": _mock_fallback(),
            }
            set_cached_health(payload)
            return payload
    except Exception as exc:
        payload = {
            "status": "down",
            "model": settings.gemini_model,
            "detail": str(exc)[:120],
            "fallback": _mock_fallback(),
        }
        set_cached_health(payload)
        return payload
