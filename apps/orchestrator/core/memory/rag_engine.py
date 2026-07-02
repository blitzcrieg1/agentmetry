"""RAG engine — hybrid semantic + keyword search over Obsidian vault via Qdrant."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from core.memory.obsidian_client import ObsidianClient


@dataclass
class ChunkResult:
    text: str
    source_path: str
    score: float
    tags: list[str]
    chunk_index: int


class RAGEngine:
  CHUNK_SIZE = 512
  CHUNK_OVERLAP = 64

  def __init__(
      self,
      vector_db_url: str | None = None,
      collection_name: str | None = None,
      vault_path: str | Path | None = None,
  ):
      self.client = QdrantClient(
          url=vector_db_url or settings.qdrant_url,
          timeout=5,
          check_compatibility=False,
      )
      self.collection_name = collection_name or settings.collection_name
      self.obsidian = ObsidianClient(vault_path or settings.vault_path)
      self._ensure_collection()

  def _ensure_collection(self) -> None:
      try:
          collections = [c.name for c in self.client.get_collections().collections]
          if self.collection_name not in collections:
              self.client.create_collection(
                  collection_name=self.collection_name,
                  vectors_config=VectorParams(size=768, distance=Distance.COSINE),
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
      """Deterministic pseudo-embedding for dev without Ollama running.
      Production path uses Ollama nomic-embed-text via embed_text()."""
      h = hashlib.sha256(text.encode()).digest()
      vec = []
      for i in range(768):
          vec.append((h[i % 32] / 255.0) * 2 - 1)
      return vec

  async def embed_text(self, text: str) -> list[float]:
      """Embed text using Ollama, falling back to pseudo-embed."""
      try:
          import httpx

          async with httpx.AsyncClient() as client:
              resp = await client.post(
                  f"{settings.ollama_base_url}/api/embeddings",
                  json={"model": settings.embedding_model, "prompt": text},
                  timeout=3.0,
              )
              if resp.status_code == 200:
                  return resp.json()["embedding"]
      except Exception:
          pass
      return self._simple_embed(text)

  def _point_id(self, source_path: str, chunk_index: int) -> str:
      raw = f"{source_path}:{chunk_index}"
      return hashlib.md5(raw.encode()).hexdigest()

  async def index_vault(self) -> int:
      """Index all markdown files in the vault into Qdrant."""
      files = self.obsidian.list_markdown_files()
      points: list[PointStruct] = []
      indexed = 0

      for file_path in files:
          content = file_path.read_text(encoding="utf-8")
          meta, body = self.obsidian.parse_frontmatter(content)
          tags = meta.get("tags", [])
          if isinstance(tags, str):
              tags = [tags]

          rel_path = str(file_path.relative_to(self.obsidian.vault_path))
          chunks = self._chunk_text(body)

          for idx, chunk in enumerate(chunks):
              embedding = await self.embed_text(chunk)
              points.append(
                  PointStruct(
                      id=self._point_id(rel_path, idx),
                      vector=embedding,
                      payload={
                          "text": chunk,
                          "source_path": rel_path,
                          "tags": tags,
                          "chunk_index": idx,
                      },
                  )
              )
              indexed += 1

      if points:
          try:
              self.client.upsert(collection_name=self.collection_name, points=points)
          except Exception:
              return 0
      return indexed

  async def query(
      self,
      query_text: str,
      top_k: int = 5,
      filter_metadata: dict[str, Any] | None = None,
      path_prefix: str | None = None,
  ) -> list[ChunkResult]:
      """Hybrid search: semantic vector search + optional tag/path filters."""
      embedding = await self.embed_text(query_text)

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
      except Exception:
          return self.keyword_search(query_text)

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
