"""Tests for Gemini throttle routing — embeds must not consume Flash pacing."""

from __future__ import annotations

from typing import Any

import pytest

import core.llm.gemini as gemini
from core.config import settings
from core.llm.gemini import _post_with_retry, embed_gemini, embed_gemini_batch


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any] | None = None):
        self._payload = payload or {}
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, params=None, json=None, timeout=None):
        return self._response


async def test_post_with_retry_awaits_provided_throttle():
    calls: list[int] = []

    async def fake_throttle():
        calls.append(1)

    response = FakeResponse()
    result = await _post_with_retry(
        FakeClient(response),
        "http://example/generateContent",
        params={},
        json_body={},
        timeout=1.0,
        throttle=fake_throttle,
    )
    assert result is response
    assert len(calls) == 1


async def test_post_with_retry_works_without_throttle():
    response = FakeResponse()
    result = await _post_with_retry(
        FakeClient(response),
        "http://example/embedContent",
        params={},
        json_body={},
        timeout=1.0,
    )
    assert result is response


async def test_embed_uses_embed_throttle_not_flash(monkeypatch: pytest.MonkeyPatch):
    embed_calls: list[int] = []
    flash_calls: list[int] = []

    async def fake_embed():
        embed_calls.append(1)

    async def fake_flash():
        flash_calls.append(1)

    monkeypatch.setattr(gemini, "throttle_embed", fake_embed)
    monkeypatch.setattr(gemini, "throttle_flash", fake_flash)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    response = FakeResponse({"embedding": {"values": [0.1, 0.2, 0.3]}})
    monkeypatch.setattr(gemini.httpx, "AsyncClient", lambda: FakeClient(response))

    values = await embed_gemini("some chunk text")
    assert values == [0.1, 0.2, 0.3]
    assert len(embed_calls) == 1
    assert len(flash_calls) == 0


async def test_embed_batch_is_one_call_on_embed_throttle(monkeypatch: pytest.MonkeyPatch):
    embed_calls: list[int] = []
    flash_calls: list[int] = []

    async def fake_embed():
        embed_calls.append(1)

    async def fake_flash():
        flash_calls.append(1)

    monkeypatch.setattr(gemini, "throttle_embed", fake_embed)
    monkeypatch.setattr(gemini, "throttle_flash", fake_flash)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    response = FakeResponse(
        {"embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3, 0.4]}]}
    )
    monkeypatch.setattr(gemini.httpx, "AsyncClient", lambda: FakeClient(response))

    values = await embed_gemini_batch(["chunk one", "chunk two"])
    assert values == [[0.1, 0.2], [0.3, 0.4]]
    assert len(embed_calls) == 1
    assert len(flash_calls) == 0


async def test_embed_batch_rejects_mismatched_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    async def fake_embed():
        pass

    monkeypatch.setattr(gemini, "throttle_embed", fake_embed)
    response = FakeResponse({"embeddings": [{"values": [0.1]}]})  # one result for two texts
    monkeypatch.setattr(gemini.httpx, "AsyncClient", lambda: FakeClient(response))

    assert await embed_gemini_batch(["a", "b"]) is None
