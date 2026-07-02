"""Durable LangGraph checkpointer — async SQLite by default."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import settings

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

checkpointer: Any = None
_saver_cm: Any = None


async def init_checkpointer() -> Any:
    """Initialize async checkpointer — must run before graph compilation."""
    global checkpointer, _saver_cm

    if checkpointer is not None:
        return checkpointer

    if settings.use_postgres:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            _saver_cm = AsyncPostgresSaver.from_conn_string(settings.postgres_url)
            checkpointer = await _saver_cm.__aenter__()
            return checkpointer
        except Exception:
            pass

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = _DATA_DIR / "checkpoints.db"
    _saver_cm = AsyncSqliteSaver.from_conn_string(str(db_path))
    checkpointer = await _saver_cm.__aenter__()
    return checkpointer


async def shutdown_checkpointer() -> None:
    global checkpointer, _saver_cm
    if _saver_cm is not None:
        await _saver_cm.__aexit__(None, None, None)
    _saver_cm = None
    checkpointer = None


def get_checkpointer() -> Any:
    if checkpointer is None:
        raise RuntimeError("Checkpointer not initialized — call init_checkpointer() at startup")
    return checkpointer
