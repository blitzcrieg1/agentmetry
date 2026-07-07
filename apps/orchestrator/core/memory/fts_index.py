"""SQLite FTS5 index over vault markdown — fast keyword retrieval alongside Qdrant RAG."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from threading import Lock

from core.config import settings

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

_SYSTEM_CONTEXT_FILES = frozenset({"GOALS.md", "AGENTS.md"})
_SKIP_PREFIXES = (
    "20-Active-Loops/",
    ".system/skill-definitions/",
    ".system/trigger-rules/",
)
_MAX_BODY_CHARS = 12_000

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
    path UNINDEXED,
    title,
    body,
    tokenize='porter unicode61'
);
"""


def should_index(rel: str) -> bool:
    """Decide whether a vault-relative markdown path belongs in the FTS index."""
    return _should_index(rel)


def _should_index(rel: str) -> bool:
    """Decide whether a vault-relative markdown path belongs in the FTS index."""
    if not rel.endswith(".md"):
        return False
    for prefix in _SKIP_PREFIXES:
        if rel == prefix.rstrip("/") or rel.startswith(prefix):
            return False
    if "/.system/" in rel or rel.startswith(".system/"):
        name = Path(rel).name
        return name in _SYSTEM_CONTEXT_FILES
    return True


def _escape_fts_query(query: str) -> str:
    tokens = re.findall(r"\w{2,}", query)
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens[:12])


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip("\n")
    return text


class VaultFTSIndex:
    def __init__(self, db_path: Path | None = None, vault_root: Path | None = None):
        self.db_path = Path(db_path) if db_path else _DATA_DIR / "vault_fts.db"
        self.vault_root = Path(vault_root or settings.vault_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def _read_body(self, path: Path) -> str | None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("FTS skip unreadable %s: %s", path, exc)
            return None
        body = _strip_frontmatter(raw).strip()
        if not body:
            return None
        return body[:_MAX_BODY_CHARS]

    def reindex(self) -> int:
        """Full vault scan — called at startup and on demand."""
        count = 0
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM vault_fts")
            for md in sorted(self.vault_root.rglob("*.md")):
                rel = md.relative_to(self.vault_root).as_posix()
                if not _should_index(rel):
                    continue
                body = self._read_body(md)
                if body is None:
                    continue
                title = md.stem.replace("-", " ")
                conn.execute(
                    "INSERT INTO vault_fts(path, title, body) VALUES (?, ?, ?)",
                    (rel, title, body),
                )
                count += 1
            conn.commit()
        logger.info("FTS reindex complete: %d notes", count)
        return count

    def upsert_file(self, absolute_path: Path) -> bool:
        """Index or remove a single file after a vault watch event."""
        path = absolute_path.resolve()
        try:
            rel = path.relative_to(self.vault_root).as_posix()
        except ValueError:
            return False

        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM vault_fts WHERE path = ?", (rel,))
            if not path.is_file() or not _should_index(rel):
                conn.commit()
                return False
            body = self._read_body(path)
            if body is None:
                conn.commit()
                return False
            title = path.stem.replace("-", " ")
            conn.execute(
                "INSERT INTO vault_fts(path, title, body) VALUES (?, ?, ?)",
                (rel, title, body),
            )
            conn.commit()
        return True

    def search(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        if not query.strip():
            return []
        fts_query = _escape_fts_query(query)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            try:
                rows = conn.execute(
                    "SELECT path, snippet(vault_fts, 2, '[', ']', '...', 24) "
                    "FROM vault_fts WHERE vault_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        return [{"path": r[0], "snippet": r[1]} for r in rows]


_fts: VaultFTSIndex | None = None


def get_fts_index(vault_path: Path | None = None) -> VaultFTSIndex:
    global _fts
    if _fts is None:
        _fts = VaultFTSIndex(vault_root=vault_path or settings.vault_path)
    return _fts
