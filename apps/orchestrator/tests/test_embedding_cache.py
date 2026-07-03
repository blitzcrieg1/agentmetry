"""Tests for the persistent embedding cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.memory.embedding_cache import EmbeddingCache


@pytest.fixture
def cache(tmp_path: Path) -> EmbeddingCache:
    return EmbeddingCache(tmp_path / "embeddings.db")


def test_roundtrip(cache: EmbeddingCache):
    cache.put("model-a", 3, "RETRIEVAL_DOCUMENT", "hello world", [0.1, 0.2, 0.3])
    assert cache.get("model-a", 3, "RETRIEVAL_DOCUMENT", "hello world") == [0.1, 0.2, 0.3]


def test_miss_returns_none(cache: EmbeddingCache):
    assert cache.get("model-a", 3, "RETRIEVAL_DOCUMENT", "never stored") is None


def test_key_isolation(cache: EmbeddingCache):
    cache.put("model-a", 3, "RETRIEVAL_DOCUMENT", "text", [1.0])
    assert cache.get("model-b", 3, "RETRIEVAL_DOCUMENT", "text") is None
    assert cache.get("model-a", 4, "RETRIEVAL_DOCUMENT", "text") is None
    assert cache.get("model-a", 3, "RETRIEVAL_QUERY", "text") is None
    assert cache.get("model-a", 3, "RETRIEVAL_DOCUMENT", "other text") is None


def test_put_overwrites(cache: EmbeddingCache):
    cache.put("m", 1, "RETRIEVAL_DOCUMENT", "t", [1.0])
    cache.put("m", 1, "RETRIEVAL_DOCUMENT", "t", [2.0])
    assert cache.get("m", 1, "RETRIEVAL_DOCUMENT", "t") == [2.0]


def test_persists_across_instances(tmp_path: Path):
    db = tmp_path / "embeddings.db"
    EmbeddingCache(db).put("m", 1, "RETRIEVAL_DOCUMENT", "t", [0.5])
    assert EmbeddingCache(db).get("m", 1, "RETRIEVAL_DOCUMENT", "t") == [0.5]
