"""Gemini health-probe cache.

Request pacing moved to the kernel token scheduler (core/kernel/scheduler.py),
which grants slots by priority instead of FIFO locks.
"""

from __future__ import annotations

import time
from typing import Any

from core.config import settings

_health_cache: dict[str, Any] | None = None
_health_cache_at: float = 0.0


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
