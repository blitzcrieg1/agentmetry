"""Tests for the Interrupt Vector Table and deferred-run resume."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import core.execution.service as service
from core.config import settings
from core.execution.service import resume_deferred_interrupts, run_skill
from core.kernel.interrupts import InterruptVector, InterruptVectorTable


@pytest.fixture
def ivt(tmp_path: Path) -> InterruptVectorTable:
    return InterruptVectorTable(f"sqlite:///{(tmp_path / 'ivt.db').as_posix()}")


def test_budget_defer_dedup(ivt: InterruptVectorTable):
    first = ivt.raise_budget_defer(
        skill_name="lead_gen",
        session_id="sess-1",
        user_input="draft",
        triggered_by="vault_watch",
        trigger_rule_id="rule-a",
        trigger_file_path="inbox/note.md",
        budget_snapshot={"flash_used": 12},
    )
    second = ivt.raise_budget_defer(
        skill_name="lead_gen",
        session_id="sess-1",
        user_input="draft",
        triggered_by="vault_watch",
        trigger_rule_id="rule-a",
        trigger_file_path="inbox/note.md",
        budget_snapshot={"flash_used": 13},
    )
    assert first["interrupt_id"] == second["interrupt_id"]
    assert len(ivt.list_pending(InterruptVector.BUDGET_DEFER)) == 1


def test_hitl_roundtrip_via_thread_id(ivt: InterruptVectorTable):
    ivt.raise_interrupt(
        "thread-42",
        InterruptVector.HITL_APPROVAL,
        skill_name="lead_gen",
        session_id="sess-1",
        active_loop_path="/loops/active.md",
        config={"configurable": {"thread_id": "thread-42"}},
        start=100.0,
    )
    row = ivt.get("thread-42")
    assert row is not None
    assert row["thread_id"] == "thread-42"
    meta = ivt.to_pending_meta(row)
    assert meta["skill_name"] == "lead_gen"
    assert meta["config"]["configurable"]["thread_id"] == "thread-42"


async def test_autonomous_defers_on_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    table = InterruptVectorTable(f"sqlite:///{(tmp_path / 'ivt.db').as_posix()}")
    monkeypatch.setattr(service, "interrupt_table", table)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(service, "log_run", lambda event: None)

    class ExhaustedLedger:
        def autonomous_allowed(self) -> bool:
            return False

        def snapshot(self) -> dict:
            return {"flash_used": 12, "flash_limit": 20, "flash_remaining": 8}

    monkeypatch.setattr(service, "get_budget_ledger", lambda: ExhaustedLedger())

    result = await run_skill(
        "lead_gen",
        "draft outreach",
        "autonomous-rule-a",
        triggered_by="vault_watch",
        trigger_rule_id="rule-a",
        trigger_file_path="inbox/prospect.md",
    )

    assert result["status"] == "deferred_budget"
    assert result["resumable"] is True
    assert "interrupt_id" in result
    pending = table.list_pending(InterruptVector.BUDGET_DEFER)
    assert len(pending) == 1
    assert pending[0]["trigger_file_path"] == "inbox/prospect.md"


async def test_resume_budget_deferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    table = InterruptVectorTable(f"sqlite:///{(tmp_path / 'ivt.db').as_posix()}")
    monkeypatch.setattr(service, "interrupt_table", table)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(service, "llm_degraded", SimpleNamespace(active=False, reason=""))

    table.raise_budget_defer(
        skill_name="lead_gen",
        session_id="autonomous-rule-a",
        user_input="draft outreach",
        triggered_by="vault_watch",
        trigger_rule_id="rule-a",
        trigger_file_path="inbox/prospect.md",
    )

    calls: list[tuple] = []

    async def fake_run_skill(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "completed", "thread_id": "t-1"}

    monkeypatch.setattr(service, "run_skill", fake_run_skill)

    class AllowingLedger:
        def autonomous_allowed(self) -> bool:
            return True

    monkeypatch.setattr(service, "get_budget_ledger", lambda: AllowingLedger())

    counts = await resume_deferred_interrupts()

    assert counts["budget"] == 1
    assert len(calls) == 1
    assert calls[0][0][0] == "lead_gen"
    assert calls[0][1]["triggered_by"] == "vault_watch"
    assert table.list_pending(InterruptVector.BUDGET_DEFER) == []


async def test_autonomous_defers_on_llm_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    table = InterruptVectorTable(f"sqlite:///{(tmp_path / 'ivt.db').as_posix()}")
    monkeypatch.setattr(service, "interrupt_table", table)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(service, "log_run", lambda event: None)
    monkeypatch.setattr(
        service,
        "llm_degraded",
        SimpleNamespace(active=True, reason="429 rate limit", retry_elapsed=lambda: False),
    )

    result = await run_skill(
        "lead_gen",
        "draft outreach",
        "autonomous-cron",
        triggered_by="cron",
        trigger_rule_id="daily-digest",
    )

    assert result["status"] == "deferred_degraded"
    assert result["resumable"] is True
    assert len(table.list_pending(InterruptVector.LLM_DEGRADED)) == 1
