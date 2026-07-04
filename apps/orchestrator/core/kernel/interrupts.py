"""Interrupt Vector Table — durable, resumable interrupts beyond HITL."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import Column, DateTime, Float, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import get_database_url


class InterruptVector(StrEnum):
    HITL_APPROVAL = "hitl_approval"
    BUDGET_DEFER = "budget_defer"
    LLM_DEGRADED = "llm_degraded"
    TOOL_EXEC_APPROVAL = "tool_exec_approval"


class Base(DeclarativeBase):
    pass


class InterruptVectorRow(Base):
    __tablename__ = "interrupt_vectors"

    interrupt_id = Column(String, primary_key=True)
    vector = Column(String, nullable=False, index=True)
    skill_name = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    user_input = Column(Text, nullable=False, default="")
    triggered_by = Column(String, nullable=False, default="manual")
    trigger_rule_id = Column(String, nullable=True)
    trigger_file_path = Column(String, nullable=True)
    config_json = Column(Text, nullable=True)
    active_loop_path = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    start_epoch = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InterruptVectorTable:
    """SQLite-backed IVT. HITL rows use thread_id as interrupt_id."""

    def __init__(self, database_url: str | None = None):
        url = database_url or get_database_url()
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, echo=False, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def raise_interrupt(
        self,
        interrupt_id: str,
        vector: InterruptVector | str,
        *,
        skill_name: str,
        session_id: str,
        user_input: str = "",
        triggered_by: str = "manual",
        trigger_rule_id: str | None = None,
        trigger_file_path: str | None = None,
        config: dict[str, Any] | None = None,
        active_loop_path: str | None = None,
        payload: dict[str, Any] | None = None,
        start: float = 0.0,
    ) -> dict[str, Any]:
        vec = str(vector)
        row = InterruptVectorRow(
            interrupt_id=interrupt_id,
            vector=vec,
            skill_name=skill_name,
            session_id=session_id,
            user_input=user_input,
            triggered_by=triggered_by,
            trigger_rule_id=trigger_rule_id,
            trigger_file_path=trigger_file_path,
            config_json=json.dumps(config) if config else None,
            active_loop_path=active_loop_path,
            payload_json=json.dumps(payload) if payload else None,
            start_epoch=start,
        )
        with Session(self.engine) as session:
            session.merge(row)
            session.commit()
        return self._row_to_dict(row)

    def get(self, interrupt_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.get(InterruptVectorRow, interrupt_id)
            if not row:
                return None
            return self._row_to_dict(row)

    def delete(self, interrupt_id: str) -> None:
        with Session(self.engine) as session:
            row = session.get(InterruptVectorRow, interrupt_id)
            if row:
                session.delete(row)
                session.commit()

    def list_pending(self, vector: InterruptVector | str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            q = session.query(InterruptVectorRow)
            if vector is not None:
                q = q.filter(InterruptVectorRow.vector == str(vector))
            rows = q.order_by(InterruptVectorRow.created_at).all()
            return [self._row_to_dict(r) for r in rows]

    def find_deferred(
        self,
        vector: InterruptVector,
        *,
        skill_name: str,
        trigger_rule_id: str | None,
        trigger_file_path: str | None,
    ) -> dict[str, Any] | None:
        """Return an existing defer interrupt for the same trigger intent."""
        for row in self.list_pending(vector):
            if row["skill_name"] != skill_name:
                continue
            if row.get("trigger_rule_id") != trigger_rule_id:
                continue
            if row.get("trigger_file_path") != trigger_file_path:
                continue
            return row
        return None

    def raise_budget_defer(
        self,
        *,
        skill_name: str,
        session_id: str,
        user_input: str,
        triggered_by: str,
        trigger_rule_id: str | None = None,
        trigger_file_path: str | None = None,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.find_deferred(
            InterruptVector.BUDGET_DEFER,
            skill_name=skill_name,
            trigger_rule_id=trigger_rule_id,
            trigger_file_path=trigger_file_path,
        )
        if existing:
            return existing
        return self.raise_interrupt(
            str(uuid.uuid4()),
            InterruptVector.BUDGET_DEFER,
            skill_name=skill_name,
            session_id=session_id,
            user_input=user_input,
            triggered_by=triggered_by,
            trigger_rule_id=trigger_rule_id,
            trigger_file_path=trigger_file_path,
            payload={"budget": budget_snapshot or {}},
        )

    def raise_tool_exec(
        self,
        *,
        skill_name: str,
        session_id: str,
        tool: str,
        arguments_summary: str = "",
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sandbox policy gate: exec-tagged tool calls are recorded and denied.

        Full arguments are preserved so an operator approval can execute the
        exact recorded request via Sandbox Tier 1.
        """
        for row in self.list_pending(InterruptVector.TOOL_EXEC_APPROVAL):
            if row["skill_name"] == skill_name and row["payload"].get("tool") == tool:
                return row
        return self.raise_interrupt(
            str(uuid.uuid4()),
            InterruptVector.TOOL_EXEC_APPROVAL,
            skill_name=skill_name,
            session_id=session_id,
            payload={
                "tool": tool,
                "arguments_summary": arguments_summary,
                "arguments": arguments or {},
            },
        )

    def raise_llm_degraded(
        self,
        *,
        skill_name: str,
        session_id: str,
        user_input: str,
        triggered_by: str,
        trigger_rule_id: str | None = None,
        trigger_file_path: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        existing = self.find_deferred(
            InterruptVector.LLM_DEGRADED,
            skill_name=skill_name,
            trigger_rule_id=trigger_rule_id,
            trigger_file_path=trigger_file_path,
        )
        if existing:
            return existing
        return self.raise_interrupt(
            str(uuid.uuid4()),
            InterruptVector.LLM_DEGRADED,
            skill_name=skill_name,
            session_id=session_id,
            user_input=user_input,
            triggered_by=triggered_by,
            trigger_rule_id=trigger_rule_id,
            trigger_file_path=trigger_file_path,
            payload={"reason": reason},
        )

    @staticmethod
    def _row_to_dict(row: InterruptVectorRow) -> dict[str, Any]:
        payload = json.loads(row.payload_json) if row.payload_json else {}
        result: dict[str, Any] = {
            "interrupt_id": row.interrupt_id,
            "vector": row.vector,
            "skill_name": row.skill_name,
            "session_id": row.session_id,
            "user_input": row.user_input,
            "triggered_by": row.triggered_by,
            "trigger_rule_id": row.trigger_rule_id,
            "trigger_file_path": row.trigger_file_path,
            "payload": payload,
            "start": row.start_epoch,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        if row.config_json:
            result["config"] = json.loads(row.config_json)
        if row.active_loop_path:
            result["active_loop_path"] = row.active_loop_path
        if row.vector == InterruptVector.HITL_APPROVAL:
            result["thread_id"] = row.interrupt_id
        return result

    def to_pending_meta(self, row: dict[str, Any]) -> dict[str, Any]:
        """Shape for pending_threads dict and approve_skill."""
        return {
            "config": row.get("config", {}),
            "session_id": row["session_id"],
            "skill_name": row["skill_name"],
            "active_loop_path": row.get("active_loop_path", ""),
            "start": row.get("start", 0.0),
        }
