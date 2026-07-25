"""Doctor must be green for a recorder-only install (no vault, no drivers).

Regression for the 2026-07-20 review: doctor hard-failed on a missing demo
vault / drivers.json — governed-runtime residue — while the SIEM captured
perfectly. Beta gate #2 is "doctor green on three Windows 11 machines", so the
exit code has to reflect the product, not the optional demo runtime.
"""

from __future__ import annotations

from pathlib import Path

from core.diagnostics.doctor import run_doctor


def _codes(report, severity):
    return {f.code for f in report.findings if f.severity == severity}


def test_missing_vault_is_not_a_failure(tmp_path: Path):
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert "vault" not in _codes(report, "fail")
    assert "drivers" not in _codes(report, "fail")
    # The optional runtime being absent is reported as skipped, not broken.
    assert any(
        f.code == "vault" and f.severity == "ok" and "skipped" in f.message
        for f in report.findings
    )


def test_vault_findings_never_fail(tmp_path: Path):
    # A present-but-empty vault (no drivers.json) may warn, never fail.
    (tmp_path / ".system").mkdir(parents=True)
    report = run_doctor(vault_path=tmp_path)
    vault_codes = {"vault", "drivers", "drivers_portable", "drivers_absolute", "drivers_schema"}
    assert not (vault_codes & _codes(report, "fail"))


def test_siem_checks_present_and_ordered_first(tmp_path: Path):
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    codes = [f.code for f in report.findings]
    # The recorder's own health comes first; the optional vault comes last.
    assert codes.index("dlp") < codes.index("vault")
    assert codes.index("tool_policy") < codes.index("vault")
    for expected in ("orchestrator", "data", "dlp", "tool_policy", "detection", "trail", "hooks"):
        assert expected in codes, f"missing SIEM check: {expected}"


def test_manifests_load_in_repo_checkout(tmp_path: Path):
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    ok_codes = _codes(report, "ok")
    assert "dlp" in ok_codes, "shipped DLP manifest should load"
    assert "tool_policy" in ok_codes, "shipped tool policy manifest should load"
    assert "detection" in ok_codes, "shipped detection manifest should load"


def test_triage_backlog_is_reported_but_never_fatal(tmp_path: Path):
    """An unanswered detection is a task for the operator, not a broken install."""
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert "triage" not in _codes(report, "fail")
    assert "triage" in {f.code for f in report.findings}


def test_no_dispositions_at_all_is_called_out(tmp_path: Path):
    """The default state is the one worth naming: detection without response."""
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    triage = next(f for f in report.findings if f.code == "triage")
    assert triage.severity == "warn"
    assert "not that anyone acted" in triage.message


def test_a_dispositioned_finding_turns_the_check_green(tmp_path: Path):
    from core.audit.detection.disposition import get_disposition_store

    get_disposition_store().record(
        correlation_id="s1", rule_id="r1", status="resolved", note="fixed"
    )
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    triage = next(f for f in report.findings if f.code == "triage")
    assert triage.severity == "ok"
    assert "0 still open" in triage.message


# --- exposure: the combination that shipped in the MSI ------------------------
#
# `require_api_key` is a no-op when no key is set (core/auth.py). That is the
# right default on loopback and an open door on 0.0.0.0, and the enterprise MSI
# reached the second by setting AGENTMETRY_HOST without setting a key. Anyone
# who could reach the host could read the trail, export the evidence pack,
# inject forged events, and close findings as accepted risk.

def _finding(report, code):
    return next(f for f in report.findings if f.code == code)


def test_loopback_without_a_key_is_fine(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AGENTMETRY_HOST", raising=False)
    from core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "ok"


def test_open_bind_without_a_key_fails_the_doctor(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "0.0.0.0")
    from core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    finding = _finding(report, "exposure")
    assert finding.severity == "fail", "an unauthenticated remote API must fail"
    assert "NO API key" in finding.message


def test_open_bind_with_a_key_is_allowed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "0.0.0.0")
    from core.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "ok"


def test_a_lan_address_counts_as_exposed(tmp_path: Path, monkeypatch):
    """0.0.0.0 is not the only way to be reachable."""
    monkeypatch.setenv("AGENTMETRY_HOST", "192.168.1.50")
    from core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "fail"


def test_ipv6_loopback_is_not_exposed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "::1")
    from core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "ok"


def test_doctor_output_is_ascii_safe():
    """`doctor` is now a command inside the MSI, run on a cp1252 console.

    An em-dash in a finding renders as a replacement character there, which
    makes a security warning look like a corrupted install. Same failure the
    enterprise build scripts had.
    """
    source = Path("core/diagnostics/doctor.py").resolve()
    offenders = sorted({c for c in source.read_text(encoding="utf-8") if ord(c) > 127})
    assert not offenders, f"doctor.py contains non-ASCII: {offenders}"
