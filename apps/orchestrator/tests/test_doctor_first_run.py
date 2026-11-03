"""Doctor on a second install, and on a trail of months.

#340: a `pip install` beside a checkout found the checkout's recorder on the
port and reported on its own empty data directory as if it were that
recorder's, including a false FAIL that Codex events were being lost.

#366: doctor walked the whole trail before printing anything. On a 179 MB
trail it was killed at 90 s and at 400 s with no output, which reads as hung.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentmetry.core import api_token
from agentmetry.core.audit import trail_chain
from agentmetry.core.diagnostics import doctor, hook_coverage


def _trail_with(tmp_path: Path, n: int) -> Path:
    path = tmp_path / "t.jsonl"
    for i in range(n):
        trail_chain.append_chained_line(path, {"tool": "read_file", "n": i})
    return path


def _edit_line(path: Path, line_no: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[line_no - 1])
    record["event"]["n"] = "edited"
    lines[line_no - 1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- the tail check ----------------------------------------------------------


def test_the_tail_check_verifies_the_newest_records(tmp_path: Path):
    result = trail_chain.verify_trail_tail(_trail_with(tmp_path, 50), 10)
    assert result.ok
    assert result.lines_chained == 10
    assert "seq 41 to 50" in result.message


def test_an_edit_inside_the_window_breaks_it(tmp_path: Path):
    trail = _trail_with(tmp_path, 50)
    _edit_line(trail, 45)
    result = trail_chain.verify_trail_tail(trail, 10)
    assert not result.ok
    assert "tampered" in result.message


def test_an_edit_older_than_the_window_is_not_seen(tmp_path: Path):
    """The limit, pinned so nobody reads the quick check as a full one."""
    trail = _trail_with(tmp_path, 50)
    _edit_line(trail, 5)
    assert trail_chain.verify_trail_tail(trail, 10).ok
    assert not trail_chain.verify_trail_file(trail).ok


def test_a_cut_tail_still_fails_against_the_sidecar(tmp_path: Path):
    trail = _trail_with(tmp_path, 20)
    lines = trail.read_text(encoding="utf-8").splitlines()
    trail.write_text("\n".join(lines[:-2]) + "\n", encoding="utf-8")
    result = trail_chain.verify_trail_tail(trail, 10)
    assert not result.ok
    assert "truncated" in result.message


def test_a_window_larger_than_the_trail_reads_all_of_it(tmp_path: Path):
    result = trail_chain.verify_trail_tail(_trail_with(tmp_path, 3), 5000)
    assert result.ok and result.lines_chained == 3


def test_reading_from_the_end_crosses_block_boundaries(tmp_path: Path):
    trail = _trail_with(tmp_path, 40)
    assert len(trail_chain._last_lines(trail, 25, block=64)) == 25


# --- doctor's trail check ----------------------------------------------------


def _trail_report(trail: Path, monkeypatch, *, full: bool) -> doctor.DoctorReport:
    monkeypatch.setattr("agentmetry.core.config.settings.audit_export_path", str(trail))
    monkeypatch.setattr("agentmetry.core.config.settings.anchor_log_path", "")
    monkeypatch.setattr(doctor, "TRAIL_FULL_VERIFY_BYTES", 0)
    monkeypatch.setattr(doctor, "TRAIL_TAIL_RECORDS", 10)
    report = doctor.DoctorReport()
    doctor._check_trail(report, full=full)
    return report


def test_a_large_trail_gets_the_quick_check_and_says_so(tmp_path: Path, monkeypatch):
    report = _trail_report(_trail_with(tmp_path, 30), monkeypatch, full=False)
    [finding] = report.findings
    assert report.trail_scope == "tail"
    assert finding.severity == "ok"
    assert "--full" in finding.message and "verify --trail" in finding.message


def test_full_walks_the_whole_chain(tmp_path: Path, monkeypatch):
    trail = _trail_with(tmp_path, 30)
    _edit_line(trail, 2)
    report = _trail_report(trail, monkeypatch, full=True)
    assert report.trail_scope == "full"
    assert [f.severity for f in report.findings] == ["fail"]


def test_a_small_trail_is_still_walked_in_full(tmp_path: Path, monkeypatch):
    trail = _trail_with(tmp_path, 5)
    monkeypatch.setattr("agentmetry.core.config.settings.audit_export_path", str(trail))
    monkeypatch.setattr("agentmetry.core.config.settings.anchor_log_path", "")
    report = doctor.DoctorReport()
    doctor._check_trail(report)
    assert report.trail_scope == "full"
    assert "Trail chain verified" in report.findings[0].message


# --- a second install --------------------------------------------------------


class _Health:
    status = 200

    def __init__(self, path: str):
        self._body = json.dumps({"audit_export": {"path": path}}).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _health_report(tmp_path: Path, monkeypatch, recorder_trail: str) -> doctor.DoctorReport:
    import urllib.request

    monkeypatch.setattr(
        "agentmetry.core.config.settings.audit_export_path", str(tmp_path / "ours" / "trail.jsonl")
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: _Health(recorder_trail))
    report = doctor.DoctorReport()
    doctor._check_health_endpoint(report)
    return report


def test_another_installs_recorder_is_named(tmp_path: Path, monkeypatch):
    theirs = str(tmp_path / "checkout" / "data" / "trail.jsonl")
    report = _health_report(tmp_path, monkeypatch, theirs)
    assert report.orchestrator_reachable
    assert report.other_install_trail == theirs
    [warning] = [f for f in report.findings if f.code == "other_install"]
    assert warning.severity == "warn" and theirs in warning.message


def test_our_own_recorder_raises_nothing(tmp_path: Path, monkeypatch):
    report = _health_report(tmp_path, monkeypatch, str(tmp_path / "ours" / "trail.jsonl"))
    assert report.other_install_trail == ""
    assert [f.code for f in report.findings] == ["orchestrator_up"]


def test_codex_is_not_failed_on_a_token_that_belongs_to_another_install(tmp_path: Path, monkeypatch):
    """The false FAIL from #340: a missing token that was only missing here."""
    report = _health_report(tmp_path, monkeypatch, str(tmp_path / "checkout" / "trail.jsonl"))
    report.hooks["codex"] = hook_coverage.COVERED
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline"])
    monkeypatch.setattr(api_token, "ingest_token_path", lambda: tmp_path / "ours" / "ingest-token")
    doctor._check_codex_sandbox(report)
    [finding] = [f for f in report.findings if f.code == "codex_sandbox"]
    assert finding.severity == "warn"
    assert report.exit_code == 0


def test_the_same_missing_token_still_fails_on_a_single_install(tmp_path: Path, monkeypatch):
    report = _health_report(tmp_path, monkeypatch, str(tmp_path / "ours" / "trail.jsonl"))
    report.hooks["codex"] = hook_coverage.COVERED
    monkeypatch.setattr(api_token, "codex_sandbox_accounts", lambda: ["CodexSandboxOffline"])
    monkeypatch.setattr(api_token, "ingest_token_path", lambda: tmp_path / "ours" / "ingest-token")
    doctor._check_codex_sandbox(report)
    [finding] = [f for f in report.findings if f.code == "codex_sandbox"]
    assert finding.severity == "fail"


def test_this_installs_index_is_not_read_for_another_installs_recorder(tmp_path: Path, monkeypatch):
    report = _health_report(tmp_path, monkeypatch, str(tmp_path / "checkout" / "trail.jsonl"))
    report.hooks["claude"] = hook_coverage.COVERED
    monkeypatch.setattr("agentmetry.core.config.settings.audit_db_path", str(tmp_path / "missing.db"))
    doctor._check_observed(report)
    assert not [f for f in report.findings if f.code == "hooks_observed"]


def test_the_json_report_carries_both_facts(tmp_path: Path, monkeypatch):
    report = _health_report(tmp_path, monkeypatch, str(tmp_path / "checkout" / "trail.jsonl"))
    payload = doctor.report_payload(report)
    assert payload["other_install_trail"].endswith("trail.jsonl")
    assert "trail_scope" in payload
