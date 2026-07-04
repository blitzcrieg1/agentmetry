"""Per-skill weekly stats — the measurable answer to the dogfooding go/no-go."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.telemetry.store import ExecutionLog, TelemetryStore
from sqlalchemy.orm import Session


@pytest.fixture
def store(tmp_path: Path) -> TelemetryStore:
    return TelemetryStore(f"sqlite:///{(tmp_path / 'telemetry.db').as_posix()}")


def _log(store: TelemetryStore, skill: str, status: str, *, days_ago: float = 0.0) -> None:
    with Session(store.engine) as session:
        session.add(
            ExecutionLog(
                thread_id=f"t-{skill}-{status}-{days_ago}",
                skill_name=skill,
                status=status,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(days=days_ago),
            )
        )
        session.commit()


def test_empty_store_reports_not_met(store: TelemetryStore):
    stats = store.get_skill_stats(7)
    assert stats["by_skill"] == []
    assert stats["distinct_skills_successful"] == 0
    assert stats["go_no_go"]["dogfooding_met"] is False


def test_three_successful_skills_meets_dogfooding(store: TelemetryStore):
    _log(store, "summarize_note", "completed")
    _log(store, "inbox_triage", "completed")
    _log(store, "follow_up_draft", "approved")
    stats = store.get_skill_stats(7)
    assert stats["distinct_skills_successful"] == 3
    assert stats["go_no_go"]["dogfooding_met"] is True


def test_failed_only_skill_does_not_count(store: TelemetryStore):
    _log(store, "summarize_note", "completed")
    _log(store, "inbox_triage", "completed")
    _log(store, "lead_gen", "failed")       # attempted but never succeeded
    _log(store, "lead_gen", "budget_exceeded")
    stats = store.get_skill_stats(7)
    # lead_gen shows up with runs but 0 successful, so it doesn't count.
    lead = next(r for r in stats["by_skill"] if r["skill"] == "lead_gen")
    assert lead["runs"] == 2 and lead["successful"] == 0
    assert stats["distinct_skills_successful"] == 2
    assert stats["go_no_go"]["dogfooding_met"] is False


def test_window_excludes_old_runs(store: TelemetryStore):
    _log(store, "summarize_note", "completed", days_ago=10)
    _log(store, "inbox_triage", "completed", days_ago=1)
    week = store.get_skill_stats(7)
    assert week["distinct_skills"] == 1
    assert week["by_skill"][0]["skill"] == "inbox_triage"
    # A wider window sees both.
    month = store.get_skill_stats(30)
    assert month["distinct_skills"] == 2


def test_repeated_use_aggregates_per_skill(store: TelemetryStore):
    for _ in range(4):
        _log(store, "summarize_note", "completed")
    stats = store.get_skill_stats(7)
    row = stats["by_skill"][0]
    assert row["skill"] == "summarize_note"
    assert row["runs"] == 4 and row["successful"] == 4
    assert stats["distinct_skills"] == 1
