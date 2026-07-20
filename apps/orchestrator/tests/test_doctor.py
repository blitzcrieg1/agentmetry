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
