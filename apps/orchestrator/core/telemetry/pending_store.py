"""Persist pending approval threads across orchestrator restarts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_database_url


class Base(DeclarativeBase):
    pass


class PendingThread(Base):
    __tablename__ = "pending_threads"

    thread_id = Column(String, primary_key=True)
    skill_name = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    active_loop_path = Column(String, nullable=False)
    config_json = Column(Text, nullable=False)
    start_monotonic = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PendingThreadStore:
    def __init__(self, database_url: str | None = None):
        url = database_url or get_database_url()
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

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
        with Session(self.engine) as session:
            row = PendingThread(
                thread_id=thread_id,
                skill_name=skill_name,
                session_id=session_id,
                active_loop_path=active_loop_path,
                config_json=json.dumps(config),
                start_monotonic=start,
            )
            session.merge(row)
            session.commit()

    def get(self, thread_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(PendingThread, thread_id)
            if not row:
                return None
            return {
                "config": json.loads(row.config_json),
                "session_id": row.session_id,
                "skill_name": row.skill_name,
                "active_loop_path": row.active_loop_path,
                "start": row.start_monotonic,
            }

    def delete(self, thread_id: str) -> None:
        with Session(self.engine) as session:
            row = session.get(PendingThread, thread_id)
            if row:
                session.delete(row)
                session.commit()

    def list_all(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.query(PendingThread).all()
            return [
                {
                    "thread_id": row.thread_id,
                    "skill_name": row.skill_name,
                    "session_id": row.session_id,
                    "active_loop_path": row.active_loop_path,
                    "config": json.loads(row.config_json),
                    "start": row.start_monotonic,
                }
                for row in rows
            ]
