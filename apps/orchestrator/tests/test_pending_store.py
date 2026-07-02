"""Tests for pending thread persistence."""

from core.telemetry.pending_store import PendingThreadStore


def test_pending_thread_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'pending.db'}"
    store = PendingThreadStore(db_url)

    store.save(
        "thread-1",
        skill_name="lead_gen",
        session_id="session-1",
        active_loop_path="/tmp/loop.md",
        config={"configurable": {"thread_id": "thread-1"}},
        start=123.0,
    )

    row = store.get("thread-1")
    assert row is not None
    assert row["skill_name"] == "lead_gen"
    assert row["config"]["configurable"]["thread_id"] == "thread-1"

    store.delete("thread-1")
    assert store.get("thread-1") is None
