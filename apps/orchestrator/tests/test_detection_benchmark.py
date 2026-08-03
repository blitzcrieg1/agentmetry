"""The detection corpus is a CI gate, not a report you read when you remember.

Two defects shipped past 546 passing tests on 2026-07-25: sequence ordering
decided by a random UUID on a timestamp tie, and off-hours detection silently
using UTC on Windows. Neither was catchable by the existing suite, because every
unit test hand-builds events with distinct timestamps in a clean environment.

These tests replay whole recorded sessions instead. A missed rule or a false
positive fails the build.
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.detection.benchmark import load_corpus, render_report, run_benchmark


@pytest.fixture(scope="module")
def report():
    return run_benchmark()


def test_no_expected_detection_is_missed(report):
    """A rule that does not fire is the entire product failing quietly."""
    missed = {
        result.case.name: sorted(result.missed)
        for result in report.results
        if result.missed
    }
    assert not missed, f"rules went silent on recorded sessions: {missed}"


def test_no_false_positives(report):
    """Noise is how a detection feed gets ignored, which is how it stops working."""
    spurious = {
        result.case.name: sorted(result.spurious)
        for result in report.results
        if result.spurious
    }
    assert not spurious, f"unexpected firings: {spurious}"


def test_benign_sessions_stay_silent(report):
    """Stated separately because this is the number worth publishing."""
    noisy = [r.case.name for r in report.benign_cases if r.fired]
    assert not noisy, f"benign sessions produced detections: {noisy}"


def test_the_corpus_covers_the_hard_cases():
    """Guard against the corpus quietly losing the cases that caught real bugs."""
    names = {case.path.stem for case in load_corpus()}
    assert "attack_timestamp_collision" in names, "tie-break regression case removed"
    assert "attack_hashed_only_no_command" in names, "hashed-only case removed"
    assert "benign_reversed_order_is_not_exfil" in names, "ordering case removed"


def test_the_corpus_has_both_attack_and_benign_sides(report):
    """An attack-only corpus measures recall and calls it quality."""
    assert len(report.attack_cases) >= 8
    assert len(report.benign_cases) >= 4


def test_the_corpus_exercises_a_meaningful_share_of_the_rules(report):
    """Not every rule, but enough that the number means something."""
    from agentmetry.core.audit.detection.rules import REGISTRY

    assert len(report.rules_covered) >= 8, sorted(report.rules_covered)
    assert len(report.rules_covered) <= len(REGISTRY)


def test_every_case_carries_a_real_session():
    for case in load_corpus():
        events = case.events
        assert events, f"{case.name} has no events"
        for event in events:
            assert event.get("correlation_id"), f"{case.name} event missing correlation_id"
            assert event.get("timestamp_utc"), f"{case.name} event missing timestamp"
            assert (event.get("action") or {}).get("type"), f"{case.name} event missing action"


def test_the_corpus_holds_no_plaintext_secrets():
    """These files are committed and public. Nothing recorded here may be real."""
    import re

    leaky = re.compile(
        r"(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-|-----BEGIN [A-Z ]*PRIVATE KEY)"
    )
    for case in load_corpus():
        text = case.path.read_text(encoding="utf-8")
        assert not leaky.search(text), f"{case.path.name} contains something secret-shaped"


def test_report_renders_without_a_failure_section(report):
    rendered = render_report(report)
    assert "All cases behaved as recorded." in rendered
    assert "false positives  0" in rendered
