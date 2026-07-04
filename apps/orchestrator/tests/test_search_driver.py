"""Search driver: provider selection, formatting, key handling — all HTTP mocked."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_SERVER = Path(__file__).resolve().parents[1] / "tools" / "search_server.py"

spec = importlib.util.spec_from_file_location("search_server", _SERVER)
search_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_server)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


def test_no_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No search API key"):
        search_server.search_web("anything")


def test_serper_preferred_and_formatted(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse({
            "organic": [
                {"title": "K-Beauty Wholesale", "link": "https://kb.example", "snippet": "MOQ 100"},
                {"title": "Seoul Suppliers", "link": "https://ss.example", "snippet": "B2B portal"},
            ]
        })

    monkeypatch.setattr(search_server.httpx, "post", fake_post)
    monkeypatch.setenv("SERPER_API_KEY", "fake-serper")
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily")

    out = search_server.search_web("snail mucin wholesale", count=2)

    assert calls == ["https://google.serper.dev/search"]  # serper wins when both set
    assert "### K-Beauty Wholesale" in out
    assert "https://kb.example" in out
    assert "MOQ 100" in out


def test_tavily_fallback(monkeypatch: pytest.MonkeyPatch):
    def fake_post(url, **kwargs):
        assert url == "https://api.tavily.com/search"
        return FakeResponse({
            "results": [{"title": "T", "url": "https://t.example", "content": "x" * 500}]
        })

    monkeypatch.setattr(search_server.httpx, "post", fake_post)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily")

    out = search_server.search_web("query")
    assert "https://t.example" in out
    assert len(out) < 500  # snippet truncated


def test_count_is_clamped(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, Any] = {}

    def fake_post(url, **kwargs):
        seen.update(kwargs.get("json") or {})
        return FakeResponse({"organic": []})

    monkeypatch.setattr(search_server.httpx, "post", fake_post)
    monkeypatch.setenv("SERPER_API_KEY", "fake")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert search_server.search_web("q", count=99) == "(no results)"
    assert seen["num"] == 10  # clamped to _MAX_RESULTS


def test_search_driver_ships_disabled():
    import json

    config = json.loads(
        (Path(__file__).resolve().parents[3] / "vault" / ".system" / "drivers.json")
        .read_text(encoding="utf-8")
    )
    search = next(d for d in config["drivers"] if d["name"] == "search")
    assert search["enabled"] is False
    assert set(search["env_allow"]) == {"SERPER_API_KEY", "TAVILY_API_KEY"}
