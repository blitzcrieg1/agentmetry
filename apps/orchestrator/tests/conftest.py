"""Shared test guardrails."""

from __future__ import annotations

import pytest

from core.config import settings


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch: pytest.MonkeyPatch):
    """Tests must never reach the real Gemini API or burn free-tier quota.

    The dev machine's .env holds a real GEMINI_API_KEY; settings loads it at
    import. Tests that need a key set their own fake one (and stub httpx).
    Also isolates the global degraded flag so one test can't poison the next.
    """
    monkeypatch.setattr(settings, "gemini_api_key", "")
    yield
