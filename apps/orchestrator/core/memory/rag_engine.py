"""RAG engine — hybrid semantic + keyword search over Obsidian vault via Qdrant."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from core.config import settings
from core.llm.gemini import EMBED_BATCH_SIZE, embed_gemini, embed_gemini_batch
from core.memory.embedding_cache import EmbeddingCache, get_embedding_cache
from core.memory.obsidian_client import ObsidianClient


@dataclass
class ChunkResult:
    text: str
    source_path: str
    score: float
    tags: list[str]
    chunk_index: int


@dataclass
class _MemoryPoint:
    vector: list[float]
    payload: dict[str, Any]


class RAGEngine:
  CHUNK_SIZE = 512
  CHUNK_OVERLAP = 64
  _shared_memory: ClassVar[dict[str, list[_MemoryPoint]]] = {}

  def __init__(
      self,
      vector_db_url: str | None = None,
      collection_name: str | None = None,
      vault_path: str | Path | None = None,
      embedding_cache: EmbeddingCache | None = None,
  ):
      self.client = QdrantClient(
          url=vector_db_url or settings.qdrant_url,
          timeout=5,
          check_compatibility=False,
      )
      self.collection_name = collection_name or settings.collection_name
      self.obsidian = ObsidianClient(vault_path or settings.vault_path)
      self.cache = embedding_cache or get_embedding_cache()
      self._ensure_collection()

  def _memory_key(self) -> str:
      return f"{self.collection_name}:{self.obsidian.vault_path.resolve()}"

  def _ensure_collection(self) -> None:
      try:
          collections = [c.name for c in self.client.get_collections().collections]
          if self.collection_name not in collections:
              self.client.create_collection(
                  collection_name=self.collection_name,
                  vectors_config=VectorParams(
                      size=settings.embedding_dimensions,
                      distance=Distance.COSINE,
                  ),
              )
      except Exception:
          pass  # Qdrant may not be running yet — index on demand

  def _chunk_text(self, text: str) -> list[str]:
      """Split text into overlapping chunks."""
      words = text.split()
      chunks = []
      step = self.CHUNK_SIZE - self.CHUNK_OVERLAP
      for i in range(0, len(words), step):
          chunk = " ".join(words[i : i + self.CHUNK_SIZE])
          if chunk.strip():
              chunks.append(chunk)
      return chunks

  def _simple_embed(self, text: str) -> list[float]:
      """Deterministic pseudo-embedding for dev without external embedders."""
      h = hashlib.sha256(text.encode()).digest()
      dim = settings.embedding_dimensions
      vec = []
      for i in range(dim):
          vec.append((h[i % 32] / 255.0) * 2 - 1)
      return vec

  async def embed_text(self, text: str, *, for_query: bool = False) -> list[float]:
      """Embed text using the cache, Gemini, Ollama, or pseudo-embed fallback."""
      task_type = "RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT"

      if settings.gemini_api_key:
          model = settings.gemini_embedding_model
          dims = settings.embedding_dimensions
          cached = self.cache.get(model, dims, task_type, text)
          if cached is not None:
              return cached
          embedding = await embed_gemini(text, task_type=task_type)
          if embedding is not None:
              self.cache.put(model, dims, task_type, text, embedding)
              return embedding

      cached = self.cache.get(
          settings.embedding_model, settings.embedding_dimensions, task_type, text
      )
      if cached is not None:
          return cached
      try:
          import httpx

          async with httpx.AsyncClient() as client:
              resp = await client.post(
                  f"{settings.ollama_base_url}/api/embeddings",
                  json={"model": settings.embedding_model, "prompt": text},
                  timeout=3.0,
              )
              if resp.status_code == 200:
                  embedding = resp.json()["embedding"]
                  self.cache.put(
                      settings.embedding_model,
                      settings.embedding_dimensions,
                      task_type,
                      text,
                      embedding,
                  )
                  return embedding
      except Exception:
          pass
      # Pseudo-embeddings are deterministic and free — never cached.
      return self._simple_embed(text)

  async def _embed_chunks(self, chunks: list[str]) -> list[list[float]]:
      """Embed document chunks: cache first, then one batch API call per 100 misses."""
      vectors: list[list[float] | None] = [None] * len(chunks)

      if settings.gemini_api_key:
          model = settings.gemini_embedding_model
          dims = settings.embedding_dimensions
          for i, chunk in enumerate(chunks):
              vectors[i] = self.cache.get(model, dims, "RETRIEVAL_DOCUMENT", chunk)
          missing = [i for i, v in enumerate(vectors) if v is None]
          for start in range(0, len(missing), EMBED_BATCH_SIZE):
              group = missing[start : start + EMBED_BATCH_SIZE]
              embedded = await embed_gemini_batch([chunks[i] for i in group])
              if embedded is None:
                  break
              for i, vector in zip(group, embedded):
                  self.cache.put(model, dims, "RETRIEVAL_DOCUMENT", chunks[i], vector)
                  vectors[i] = vector

      for i, vector in enumerate(vectors):
          if vector is None:
              vectors[i] = await self.embed_text(chunks[i])
      return vectors  # type: ignore[return-value]

  def _point_id(self, source_path: str, chunk_index: int) -> str:
      raw = f"{source_path}:{chunk_index}"
      return hashlib.md5(raw.encode()).hexdigest()

  @staticmethod
  def _cosine_similarity(a: list[float], b: list[float]) -> float:
      dot = sum(x * y for x, y in zip(a, b))
      norm_a = math.sqrt(sum(x * x for x in a))
      norm_b = math.sqrt(sum(x * x for x in b))
      if norm_a == 0 or norm_b == 0:
          return 0.0
      return dot / (norm_a * norm_b)

  def _matches_filter(
      self,
      payload: dict[str, Any],
      filter_metadata: dict[str, Any] | None,
      path_prefix: str | None,
  ) -> bool:
      if path_prefix and not str(payload.get("source_path", "")).startswith(path_prefix):
          return False
      if filter_metadata and "tags" in filter_metadata:
          required = filter_metadata["tags"]
          if isinstance(required, str):
              required = [required]
          note_tags = payload.get("tags", [])
          if not any(tag in note_tags for tag in required):
              return False
      return True

  def _memory_search(
      self,
      query_vector: list[float],
      top_k: int,
      filter_metadata: dict[str, Any] | None = None,
      path_prefix: str | None = None,
  ) -> list[ChunkResult]:
      points = self._shared_memory.get(self._memory_key(), [])
      scored: list[tuple[float, _MemoryPoint]] = []
      for point in points:
          if not self._matches_filter(point.payload, filter_metadata, path_prefix):
              continue
          score = self._cosine_similarity(query_vector, point.vector)
          scored.append((score, point))

      scored.sort(key=lambda item: item[0], reverse=True)
      return [
          ChunkResult(
              text=point.payload["text"],
              source_path=point.payload["source_path"],
              score=score,
              tags=point.payload.get("tags", []),
              chunk_index=point.payload.get("chunk_index", 0),
          )
          for score, point in scored[:top_k]
      ]

  @classmethod
  def memory_chunk_count(cls, vault_path: str | Path | None = None) -> int:
      vault = Path(vault_path or settings.vault_path).resolve()
      key = f"{settings.collection_name}:{vault}"
      return len(cls._shared_memory.get(key, []))

  def _file_in_memory(self, rel_path: str) -> bool:
      key = self._memory_key()
      return any(
          point.payload.get("source_path") == rel_path
          for point in self._shared_memory.get(key, [])
      )

  def _manifest_path(self) -> Path:
      root = Path(__file__).resolve().parents[2] / "data"
      root.mkdir(parents=True, exist_ok=True)
      return root / "vault-index-manifest.json"

  def _load_manifest(self) -> dict[str, int]:
      path = self._manifest_path()
      if not path.exists():
          return {}
      import json
      try:
          return json.loads(path.read_text(encoding="utf-8"))
      except Exception:
          return {}

  def _save_manifest(self, manifest: dict[str, int]) -> None:
      import json
      self._manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")

  async def index_file(self, file_path: Path) -> int:
      """Index or re-index a single markdown file."""
      if not file_path.exists() or file_path.suffix != ".md":
          return 0
      if ".system" in file_path.parts:
          return 0

      rel_path = str(file_path.relative_to(self.obsidian.vault_path))
      await self.remove_file(rel_path)

      content = file_path.read_text(encoding="utf-8")
      meta, body = self.obsidian.parse_frontmatter(content)
      tags = meta.get("tags", [])
      if isinstance(tags, str):
          tags = [tags]

      points: list[PointStruct] = []
      memory_points: list[_MemoryPoint] = []
      indexed = 0

      chunks = self._chunk_text(body)
      vectors = await self._embed_chunks(chunks)
      for idx, (chunk, embedding) in enumerate(zip(chunks, vectors)):
          payload = {
              "text": chunk,
              "source_path": rel_path,
              "tags": tags,
              "chunk_index": idx,
          }
          points.append(
              PointStruct(
                  id=self._point_id(rel_path, idx),
                  vector=embedding,
                  payload=payload,
              )
          )
          memory_points.append(_MemoryPoint(vector=embedding, payload=payload))
          indexed += 1

      key = self._memory_key()
      existing = self._shared_memory.get(key, [])
      self._shared_memory[key] = existing + memory_points

      if points:
          try:
              self.client.upsert(collection_name=self.collection_name, points=points)
          except Exception:
              pass
      return indexed

  async def remove_file(self, rel_path: str) -> None:
      """Remove all indexed chunks for a vault-relative file path."""
      key = self._memory_key()
      self._shared_memory[key] = [
          point
          for point in self._shared_memory.get(key, [])
          if point.payload.get("source_path") != rel_path
      ]
      try:
          self.client.delete(
              collection_name=self.collection_name,
              points_selector=Filter(
                  must=[FieldCondition(key="source_path", match=MatchValue(value=rel_path))]
              ),
          )
      except Exception:
          pass

  async def index_vault(self, *, force: bool = False) -> int:
      """Index markdown files; skip unchanged files when manifest is current."""
      if settings.startup_index_skip_unchanged and not force:
          return await self.index_vault_incremental()
      return await self._index_vault_full()

  async def index_vault_incremental(self) -> int:
      """Index new or modified files; rehydrate unchanged ones from the embedding cache."""
      import logging
      logger = logging.getLogger(__name__)

      manifest = self._load_manifest()
      new_manifest: dict[str, int] = {}
      indexed = 0
      restored = 0

      for file_path in self.obsidian.list_markdown_files():
          rel_path = str(file_path.relative_to(self.obsidian.vault_path))
          mtime_ns = file_path.stat().st_mtime_ns
          new_manifest[rel_path] = mtime_ns
          if manifest.get(rel_path) != mtime_ns:
              indexed += await self.index_file(file_path)
          elif not self._file_in_memory(rel_path):
              # After a restart the in-memory store is empty; unchanged files
              # re-index through the embedding cache with zero API calls.
              restored += await self.index_file(file_path)

      if restored:
          logger.info(
              "Semantic memory rehydrated from embedding cache: %d chunks", restored
          )
      if indexed:
          logger.info("Vault changes indexed: %d chunks", indexed)

      self._save_manifest(new_manifest)
      return indexed + restored

  async def _index_vault_full(self) -> int:
      """Index all markdown files in the vault into Qdrant and in-memory store."""
      files = self.obsidian.list_markdown_files()
      self._shared_memory[self._memory_key()] = []
      indexed = 0

      for file_path in files:
          indexed += await self.index_file(file_path)

      manifest = {
          str(f.relative_to(self.obsidian.vault_path)): f.stat().st_mtime_ns
          for f in files
      }
      self._save_manifest(manifest)
      return indexed

  async def query(
      self,
      query_text: str,
      top_k: int = 5,
      filter_metadata: dict[str, Any] | None = None,
      path_prefix: str | None = None,
  ) -> list[ChunkResult]:
      """Hybrid search: semantic vector search + optional tag/path filters."""
      embedding = await self.embed_text(query_text, for_query=True)

      conditions = []
      if filter_metadata and "tags" in filter_metadata:
          tags = filter_metadata["tags"]
          if isinstance(tags, str):
              tags = [tags]
          conditions.append(
              FieldCondition(key="tags", match=MatchAny(any=tags))
          )
      if path_prefix:
          conditions.append(
              FieldCondition(key="source_path", match=MatchValue(value=path_prefix))
          )

      query_filter = Filter(must=conditions) if conditions else None

      try:
          results = self.client.search(
              collection_name=self.collection_name,
              query_vector=embedding,
              limit=top_k,
              query_filter=query_filter,
          )
          return [
              ChunkResult(
                  text=r.payload["text"],
                  source_path=r.payload["source_path"],
                  score=r.score,
                  tags=r.payload.get("tags", []),
                  chunk_index=r.payload.get("chunk_index", 0),
              )
              for r in results
          ]
      except Exception:
          memory_results = self._memory_search(
              embedding, top_k, filter_metadata, path_prefix
          )
          if memory_results:
              return memory_results
          return self.keyword_search(query_text)

  async def summarize_context(self, chunks: list[ChunkResult], max_tokens: int = 500) -> str:
      """Compress retrieved chunks into a concise context block."""
      if not chunks:
          return ""

      combined = "\n\n".join(
          f"[Source: {c.source_path}]\n{c.text}" for c in chunks
      )

      # Truncate to approximate token budget (4 chars ≈ 1 token)
      max_chars = max_tokens * 4
      if len(combined) <= max_chars:
          return combined
      return combined[:max_chars] + "\n...[truncated]"

  def keyword_search(self, query: str, files: list[Path] | None = None) -> list[ChunkResult]:
      """Fallback keyword search across vault markdown files."""
      if files is None:
          files = self.obsidian.list_markdown_files()

      results: list[ChunkResult] = []
      pattern = re.compile(re.escape(query), re.IGNORECASE)

      for file_path in files:
          content = file_path.read_text(encoding="utf-8")
          _, body = self.obsidian.parse_frontmatter(content)
          if pattern.search(body):
              rel_path = str(file_path.relative_to(self.obsidian.vault_path))
              results.append(
                  ChunkResult(
                      text=body[:512],
                      source_path=rel_path,
                      score=1.0,
                      tags=[],
                      chunk_index=0,
                  )
              )
      return results
