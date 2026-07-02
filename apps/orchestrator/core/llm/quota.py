"""Gemini quota helpers — throttle requests and cache health probes."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.config import settings

_embed_lock = asyncio.Lock()
_last_embed_at: float = 0.0

_flash_lock = asyncio.Lock()
_last_flash_at: float = 0.0

_health_cache: dict[str, Any] | None = None
_health_cache_at: float = 0.0


async def throttle_embed() -> None:
    """Space embedding calls to stay under free-tier RPM (~100/min)."""
    global _last_embed_at
    interval = settings.gemini_embed_min_interval_seconds
    async with _embed_lock:
        now = time.monotonic()
        wait = interval - (now - _last_embed_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_embed_at = time.monotonic()


async def throttle_flash() -> None:
    """Space Flash generateContent calls (free tier ≈ 5 RPM)."""
    global _last_flash_at
    interval = settings.gemini_flash_min_interval_seconds
    async with _flash_lock:
        now = time.monotonic()
        wait = interval - (now - _last_flash_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_flash_at = time.monotonic()


def get_cached_health() -> dict[str, Any] | None:
    if _health_cache is None:
        return None
    age = time.monotonic() - _health_cache_at
    if age < settings.gemini_health_cache_seconds:
        return _health_cache
    return None


def set_cached_health(payload: dict[str, Any]) -> None:
    global _health_cache, _health_cache_at
    _health_cache = payload
    _health_cache_at = time.monotonic()
