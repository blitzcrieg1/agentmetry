"""Telemetry store — PostgreSQL or SQLite agent performance metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, desc
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_database_url


class Base(DeclarativeBase):
    pass


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, index=True)
    skill_name = Column(String, index=True)
    status = Column(String)
    confidence_score = Column(Float, default=0.0)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TelemetryStore:
    def __init__(self, database_url: str | None = None):
        url = database_url or get_database_url()
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.backend = "postgres" if url.startswith("postgresql") else "sqlite"

    def log_execution(
        self,
        thread_id: str,
        skill_name: str,
        status: str,
        *,
        confidence_score: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> str:
        with Session(self.engine) as session:
            log = ExecutionLog(
                thread_id=thread_id,
                skill_name=skill_name,
                status=status,
                confidence_score=confidence_score,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                latency_ms=latency_ms,
                error=error,
            )
            session.add(log)
            session.commit()
            return log.id

    def get_stats(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            logs = session.query(ExecutionLog).all()
            if not logs:
                return {
                    "backend": self.backend,
                    "total_runs": 0,
                    "success_rate": 0.0,
                    "total_cost": 0.0,
                    "avg_latency_ms": 0,
                    "recent_runs": [],
                }

            successes = sum(1 for l in logs if l.status in ("completed", "approved"))
            recent = (
                session.query(ExecutionLog)
                .order_by(desc(ExecutionLog.created_at))
                .limit(10)
                .all()
            )
            return {
                "backend": self.backend,
                "total_runs": len(logs),
                "success_rate": successes / len(logs),
                "total_cost": sum(l.cost for l in logs),
                "avg_latency_ms": sum(l.latency_ms for l in logs) // len(logs),
                "total_input_tokens": sum(l.input_tokens for l in logs),
                "total_output_tokens": sum(l.output_tokens for l in logs),
                "recent_runs": [
                    {
                        "skill": r.skill_name,
                        "status": r.status,
                        "cost": r.cost,
                        "latency_ms": r.latency_ms,
                        "created": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in recent
                ],
            }

    def detect_drift(self, messages: list[str], threshold: float = 0.8) -> bool:
        """Detect if agent is repeating the same output cyclically."""
        if len(messages) < 3:
            return False
        recent = messages[-3:]
        unique_ratio = len(set(recent)) / len(recent)
        return unique_ratio < (1 - threshold)
