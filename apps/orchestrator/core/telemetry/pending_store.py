"""Persist pending approval threads across orchestrator restarts.

HITL rows live in the Interrupt Vector Table; this facade keeps the legacy API.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text, inspect
from sqlalchemy.orm import DeclarativeBase, Session

from core.config import get_database_url
from core.kernel.interrupts import InterruptVector, InterruptVectorTable


class _LegacyBase(DeclarativeBase):
    pass


class _LegacyPendingThread(_LegacyBase):
    __tablename__ = "pending_threads"

    thread_id = Column(String, primary_key=True)
    skill_name = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    active_loop_path = Column(String, nullable=False)
    config_json = Column(Text, nullable=False)
    start_epoch = Column("start_monotonic", Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PendingThreadStore:
    def __init__(self, database_url: str | None = None):
        url = database_url or get_database_url()
        self._ivt = InterruptVectorTable(url)
        self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        insp = inspect(self._ivt.engine)
        if "pending_threads" not in insp.get_table_names():
            return
        with Session(self._ivt.engine) as session:
            rows = session.query(_LegacyPendingThread).all()
            for row in rows:
                self._ivt.raise_interrupt(
                    row.thread_id,
                    InterruptVector.HITL_APPROVAL,
                    skill_name=row.skill_name,
                    session_id=row.session_id,
                    active_loop_path=row.active_loop_path,
                    config=json.loads(row.config_json),
                    start=row.start_epoch,
                )
                session.delete(row)
            session.commit()

    def save(
        self,
        thread_id: str,
        *,
        skill_name: str,
        session_id: str,
        active_loop_path: str,
        config: dict[str, Any],
        start: float,
    ) -> None:
        self._ivt.raise_interrupt(
            thread_id,
            InterruptVector.HITL_APPROVAL,
            skill_name=skill_name,
            session_id=session_id,
            active_loop_path=active_loop_path,
            config=config,
            start=start,
        )

    def get(self, thread_id: str) -> dict[str, Any] | None:
        row = self._ivt.get(thread_id)
        if not row or row.get("vector") != InterruptVector.HITL_APPROVAL:
            return None
        return self._ivt.to_pending_meta(row)

    def delete(self, thread_id: str) -> None:
        self._ivt.delete(thread_id)

    def list_all(self) -> list[dict[str, Any]]:
        return [
            {
                "thread_id": row["interrupt_id"],
                **self._ivt.to_pending_meta(row),
            }
            for row in self._ivt.list_pending(InterruptVector.HITL_APPROVAL)
        ]
