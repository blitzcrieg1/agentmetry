"""Semantic memory must survive an orchestrator restart without new embed API calls."""

from __future__ import annotations

from pathlib import Path

import pytest

import core.memory.rag_engine as rag_module
from core.config import settings
from core.memory.embedding_cache import EmbeddingCache
from core.memory.rag_engine import RAGEngine


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    knowledge = root / "10-Knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "note.md").write_text(
        "---\ntags: [brand]\n---\n\nBrand guidelines: keep a technical peer tone.",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def api_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, int]:
    calls = {"batch": 0, "single": 0}

    async def fake_batch(texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT"):
        calls["batch"] += 1
        return [[1.0, 0.0, 0.5] for _ in texts]

    async def fake_single(text: str, *, task_type: str = "RETRIEVAL_DOCUMENT"):
        calls["single"] += 1
        return [1.0, 0.0, 0.5]

    monkeypatch.setattr(rag_module, "embed_gemini_batch", fake_batch)
    monkeypatch.setattr(rag_module, "embed_gemini", fake_single)
    # Instantly-refused port so swallowed Qdrant calls don't slow the test down.
    monkeypatch.setattr(settings, "qdrant_url", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_embedding_model", "test-embed")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    monkeypatch.setattr(
        RAGEngine, "_manifest_path", lambda self: tmp_path / "manifest.json"
    )
    monkeypatch.setattr(RAGEngine, "_shared_memory", {})
    return calls


async def test_restart_rehydrates_from_cache(
    vault: Path, tmp_path: Path, api_calls: dict[str, int], monkeypatch: pytest.MonkeyPatch
):
    cache = EmbeddingCache(tmp_path / "embeddings.db")

    engine = RAGEngine(vault_path=vault, embedding_cache=cache)
    first = await engine.index_vault()
    assert first >= 1
    assert api_calls["batch"] == 1
    assert RAGEngine.memory_chunk_count(vault) >= 1

    # Simulate a restart: in-memory store gone, manifest and cache on disk intact.
    monkeypatch.setattr(RAGEngine, "_shared_memory", {})
    assert RAGEngine.memory_chunk_count(vault) == 0

    engine2 = RAGEngine(vault_path=vault, embedding_cache=cache)
    restored = await engine2.index_vault()
    assert restored >= 1
    assert RAGEngine.memory_chunk_count(vault) >= 1

    # The whole point: rehydration made zero embedding API calls.
    assert api_calls["batch"] == 1
    assert api_calls["single"] == 0


async def test_modified_file_is_reembedded(
    vault: Path, tmp_path: Path, api_calls: dict[str, int], monkeypatch: pytest.MonkeyPatch
):
    cache = EmbeddingCache(tmp_path / "embeddings.db")
    engine = RAGEngine(vault_path=vault, embedding_cache=cache)
    await engine.index_vault()
    assert api_calls["batch"] == 1

    note = vault / "10-Knowledge" / "note.md"
    note.write_text("---\ntags: [brand]\n---\n\nCompletely new content.", encoding="utf-8")

    monkeypatch.setattr(RAGEngine, "_shared_memory", {})
    engine2 = RAGEngine(vault_path=vault, embedding_cache=cache)
    await engine2.index_vault()
    # Changed content is a cache miss and must hit the API again.
    assert api_calls["batch"] == 2
