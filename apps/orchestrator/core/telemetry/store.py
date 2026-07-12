"""Telemetry store — PostgreSQL or SQLite agent performance metrics."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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

            successes = sum(1 for log in logs if log.status in ("completed", "approved"))
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
                "total_cost": sum(log.cost for log in logs),
                "avg_latency_ms": sum(log.latency_ms for log in logs) // len(logs),
                "total_input_tokens": sum(log.input_tokens for log in logs),
                "total_output_tokens": sum(log.output_tokens for log in logs),
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

    # A skill "counts" toward dogfooding only when it produced a real result.
    _DOGFOOD_MIN_SKILLS = 3
    _SUCCESS_STATUSES = ("completed", "approved")

    @staticmethod
    def _as_naive_utc(dt: datetime | None) -> datetime | None:
        """SQLite returns naive datetimes; Postgres may return aware ones.

        Normalize both to naive UTC so a single cutoff comparison works on
        either backend.
        """
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    def get_skill_stats(self, window_days: int = 7) -> dict[str, Any]:
        """Per-skill run counts within a trailing window, plus the go/no-go answer.

        Answers "have I used >=3 skills this week?" — legacy dogfooding metric
        (Path B inbox ritual removed; endpoint kept for optional stats).
        """
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
        per_skill: dict[str, dict[str, int]] = {}

        with Session(self.engine) as session:
            for log in session.query(ExecutionLog).all():
                created = self._as_naive_utc(log.created_at)
                if created is None or created < cutoff:
                    continue
                bucket = per_skill.setdefault(
                    log.skill_name or "unknown",
                    {"runs": 0, "successful": 0},
                )
                bucket["runs"] += 1
                if log.status in self._SUCCESS_STATUSES:
                    bucket["successful"] += 1

        by_skill = sorted(
            (
                {"skill": name, "runs": c["runs"], "successful": c["successful"]}
                for name, c in per_skill.items()
            ),
            key=lambda row: (row["successful"], row["runs"]),
            reverse=True,
        )
        # Dogfooding is about breadth of *successful* use, not raw attempts.
        distinct_successful = sum(1 for row in by_skill if row["successful"] > 0)

        return {
            "window_days": window_days,
            "by_skill": by_skill,
            "distinct_skills": len(by_skill),
            "distinct_skills_successful": distinct_successful,
            "go_no_go": {
                "criterion": f">={self._DOGFOOD_MIN_SKILLS} skills with a completed/approved run",
                "min_skills": self._DOGFOOD_MIN_SKILLS,
                "dogfooding_met": distinct_successful >= self._DOGFOOD_MIN_SKILLS,
            },
        }

    def detect_drift(self, messages: list[str], threshold: float = 0.8) -> bool:
        """Detect if agent is repeating the same output cyclically."""
        if len(messages) < 3:
            return False
        recent = messages[-3:]
        unique_ratio = len(set(recent)) / len(recent)
        return unique_ratio < (1 - threshold)
