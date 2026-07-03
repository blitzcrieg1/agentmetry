"""Qdrant circuit breaker: one failure pauses Qdrant use instead of re-paying timeouts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.memory.embedding_cache import EmbeddingCache
from core.memory.rag_engine import RAGEngine, _QdrantUnavailable


@pytest.fixture(autouse=True)
def _reset_breaker():
    RAGEngine._qdrant_down_until = 0.0
    yield
    RAGEngine._qdrant_down_until = 0.0


@pytest.fixture
def engine(tmp_path: Path) -> RAGEngine:
    (tmp_path / "vault").mkdir()
    return RAGEngine(
        vault_path=tmp_path / "vault",
        embedding_cache=EmbeddingCache(tmp_path / "emb.db"),
    )


async def test_breaker_opens_after_first_failure(engine: RAGEngine):
    calls = {"n": 0}

    def failing_op():
        calls["n"] += 1
        raise ConnectionError("black-holed port")

    with pytest.raises(ConnectionError):
        await engine._qdrant_call(failing_op)
    assert calls["n"] == 1

    # Second attempt short-circuits without touching the network.
    with pytest.raises(_QdrantUnavailable):
        await engine._qdrant_call(failing_op)
    assert calls["n"] == 1


async def test_breaker_is_shared_across_instances(engine: RAGEngine, tmp_path: Path):
    def failing_op():
        raise ConnectionError

    with pytest.raises(ConnectionError):
        await engine._qdrant_call(failing_op)

    other = RAGEngine(
        vault_path=tmp_path / "vault",
        embedding_cache=EmbeddingCache(tmp_path / "emb2.db"),
    )
    with pytest.raises(_QdrantUnavailable):
        await other._qdrant_call(lambda: pytest.fail("must not reach the client"))


async def test_success_resets_breaker(engine: RAGEngine):
    with pytest.raises(ConnectionError):
        await engine._qdrant_call(lambda: (_ for _ in ()).throw(ConnectionError()))

    RAGEngine._qdrant_down_until = 0.0  # window elapsed
    assert await engine._qdrant_call(lambda: "ok") == "ok"
    assert RAGEngine._qdrant_down_until == 0.0
