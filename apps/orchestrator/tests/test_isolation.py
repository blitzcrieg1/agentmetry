"""The test suite must not write to operator data.

Found while verifying the triage loop on 2026-07-24: development runs of the
suite had appended detection events to the developer's real `audit.db` and
`audit-forward.jsonl`, because every store is a module singleton created on
first use and a test that forgets to patch its path gets the real one.

For a product whose claim is an evidence file you can trust, a test suite that
edits that file is a correctness bug, not untidiness. `conftest.py` now
redirects every store per test; this pins that guarantee so a future settings
field cannot quietly escape it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import settings

_ORCHESTRATOR = Path(__file__).resolve().parents[1]
_REAL_DATA = _ORCHESTRATOR / "data"

#: Every settings field naming a store the suite could write to.
_STORE_PATHS = (
    "audit_export_path",
    "audit_db_path",
    "detection_live_db_path",
    "detection_disposition_db_path",
)


@pytest.mark.parametrize("field", _STORE_PATHS)
def test_store_paths_are_redirected_away_from_operator_data(field):
    value = Path(getattr(settings, field)).resolve()
    assert _REAL_DATA not in value.parents, (
        f"settings.{field} points at the operator's real data directory; "
        "a test writing through it would edit their audit trail"
    )


def test_writing_a_detection_does_not_touch_the_real_trail():
    from core.audit.trail_db import get_trail_db

    real_db = _REAL_DATA / "audit.db"
    before = real_db.stat().st_mtime_ns if real_db.exists() else None

    get_trail_db().insert({
        "event_id": "isolation-probe",
        "correlation_id": "isolation",
        "timestamp_utc": "2026-07-24T00:00:00+00:00",
        "action": {"type": "tool_called", "outcome": "success"},
    })

    assert get_trail_db().count() == 1, "wrote into a shared store"
    if before is not None:
        assert real_db.stat().st_mtime_ns == before, "operator trail was modified"


def test_each_test_starts_from_an_empty_trail():
    """Proves the previous test's write did not survive into this one."""
    from core.audit.trail_db import get_trail_db

    assert get_trail_db().count() == 0
