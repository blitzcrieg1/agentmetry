"""Persistent embedding cache — semantic memory survives restarts without re-burning quota.

Vectors are keyed by sha256(model:dims:task_type:text), so unchanged content is
never re-embedded: restarts, renames, and force reindexes are served locally.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Personal-vault scale: prune the oldest rows past this on startup.
_MAX_ROWS = 50_000


class EmbeddingCache:
    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path else _DATA_DIR / "embeddings.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    key TEXT PRIMARY KEY,
                    vector TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        self._prune()

    @staticmethod
    def _key(model: str, dims: int, task_type: str, text: str) -> str:
        raw = f"{model}:{dims}:{task_type}:{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, model: str, dims: int, task_type: str, text: str) -> list[float] | None:
        key = self._key(model, dims, task_type, text)
        with self._lock:
            row = self._conn.execute(
                "SELECT vector FROM embeddings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def put(self, model: str, dims: int, task_type: str, text: str, vector: list[float]) -> None:
        key = self._key(model, dims, task_type, text)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO embeddings (key, vector, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(vector), datetime.now(timezone.utc).isoformat()),
            )

    def _prune(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM embeddings WHERE key NOT IN "
                "(SELECT key FROM embeddings ORDER BY created_at DESC LIMIT ?)",
                (_MAX_ROWS,),
            )


_cache: EmbeddingCache | None = None


def get_embedding_cache() -> EmbeddingCache:
    global _cache
    if _cache is None:
        _cache = EmbeddingCache()
    return _cache
