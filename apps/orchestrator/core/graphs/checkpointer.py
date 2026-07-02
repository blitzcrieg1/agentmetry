"""Durable LangGraph checkpointer — SQLite by default, Postgres when enabled."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.config import settings

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


def create_checkpointer():
    if settings.use_postgres:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            return PostgresSaver.from_conn_string(settings.postgres_url)
        except Exception:
            pass

    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = _DATA_DIR / "checkpoints.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)


checkpointer = create_checkpointer()
