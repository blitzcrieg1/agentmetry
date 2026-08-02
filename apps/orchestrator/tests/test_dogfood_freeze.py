"""The gate has to know when the thing it is measuring changed underneath it.

Three detection changes shipped into week one on the day the clock started.
Each was an improvement. Together they meant the week measured three different
products, and nothing anywhere said so. A promise to freeze the rules is the
same kind of promise as an install command nobody runs.
"""

from __future__ import annotations

from core.audit import dogfood


def test_fingerprint_is_stable_across_calls():
    assert dogfood.ruleset_fingerprint() == dogfood.ruleset_fingerprint()


def test_fingerprint_moves_when_a_rule_source_changes(tmp_path, monkeypatch):
    """Whole-file hashing is blunt on purpose: it cannot miss a real change."""
    before = dogfood.ruleset_fingerprint()

    real_root = dogfood._orchestrator_root()
    fake_root = tmp_path / "orch"
    for rel in dogfood._RULESET_SOURCES:
        dst = fake_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((real_root / rel).read_bytes())
    monkeypatch.setattr(dogfood, "_orchestrator_root", lambda: fake_root)

    assert dogfood.ruleset_fingerprint() == before, "copying the sources changed nothing"

    tampered = fake_root / "core/audit/detection/rules.py"
    tampered.write_bytes(tampered.read_bytes() + b"\n# severity tuning\n")
    assert dogfood.ruleset_fingerprint() != before


def test_start_clock_records_the_ruleset(tmp_path, monkeypatch):
    monkeypatch.setattr(dogfood, "marker_path", lambda: tmp_path / "dogfood.json")
    marker = dogfood.start_clock(operator="test")
    assert marker["ruleset_fingerprint"] == dogfood.ruleset_fingerprint()


def test_a_changed_ruleset_stops_the_run_passing():
    """Weeks stay green: the operator's behaviour that week was real. The run
    does not pass, because four weeks against four rulesets is not evidence
    about one product."""
    report = dogfood.DogfoodReport(started=None)
    report.weeks = [
        dogfood.Week(index=i, start=None, end=None, active_days=5, complete=True)
        for i in range(1, 5)
    ]
    assert report.consecutive_green == 4
    assert report.passed is True

    report.ruleset_frozen = False
    assert report.consecutive_green == 4, "the weeks themselves are untouched"
    assert report.passed is False


def test_a_marker_without_a_fingerprint_is_not_treated_as_drift(tmp_path, monkeypatch):
    """Absence of evidence is not evidence of drift. A marker written before
    fingerprints existed must not invent a failure."""
    marker = tmp_path / "dogfood.json"
    marker.write_text('{"started_utc": "2026-08-01", "operator": ""}\n', encoding="utf-8")
    monkeypatch.setattr(dogfood, "marker_path", lambda: marker)

    class _EmptyDB:
        def read_between(self, *_a, **_k):
            return []

    report = dogfood.assess(trail_db=_EmptyDB())
    assert report.ruleset_frozen is True


def test_render_names_the_fix_when_the_ruleset_drifted():
    report = dogfood.DogfoodReport(started=None)
    report.ruleset_frozen = False
    from datetime import date

    report.started = date(2026, 8, 1)
    out = dogfood.render(report)
    assert "RULESET CHANGED" in out
    assert "--start --restart" in out, "say what to do, not just what is wrong"
