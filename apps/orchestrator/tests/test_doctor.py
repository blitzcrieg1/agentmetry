"""Doctor must be green for a recorder-only install (no vault, no drivers).

Regression for the 2026-07-20 review: doctor hard-failed on a missing demo
vault / drivers.json — governed-runtime residue — while the SIEM captured
perfectly. Beta gate #2 is "doctor green on three Windows 11 machines", so the
exit code has to reflect the product, not the optional demo runtime.
"""

from __future__ import annotations

from pathlib import Path

from agentmetry.core.diagnostics.doctor import run_doctor


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
    from agentmetry.core.audit.detection.disposition import get_disposition_store

    get_disposition_store().record(
        correlation_id="s1", rule_id="r1", status="resolved", note="fixed"
    )
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    triage = next(f for f in report.findings if f.code == "triage")
    assert triage.severity == "ok"
    assert "0 still open" in triage.message


# --- exposure: the combination that shipped in the MSI ------------------------
#
# The API used to skip authentication when no key was set, and the enterprise
# MSI reached an open door by setting AGENTMETRY_HOST=0.0.0.0 without one. The
# per-install token is now on by default; conftest turns it off for the suite,
# so these tests run as an install with AGENTMETRY_AUTH_DISABLED=1 would.
# test_auth_default.py covers the default.

def _finding(report, code):
    return next(f for f in report.findings if f.code == code)


def test_loopback_with_auth_disabled_warns_rather_than_fails(tmp_path: Path, monkeypatch):
    """It used to be "[OK] (no API key needed)". Loopback is not a boundary."""
    monkeypatch.delenv("AGENTMETRY_HOST", raising=False)
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "warn"


def test_open_bind_without_a_key_fails_the_doctor(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "0.0.0.0")
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    finding = _finding(report, "exposure")
    assert finding.severity == "fail", "an unauthenticated remote API must fail"
    assert "NO API key" in finding.message


def test_open_bind_with_a_key_is_allowed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "0.0.0.0")
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "ok"


def test_a_lan_address_counts_as_exposed(tmp_path: Path, monkeypatch):
    """0.0.0.0 is not the only way to be reachable."""
    monkeypatch.setenv("AGENTMETRY_HOST", "192.168.1.50")
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "fail"


def test_ipv6_loopback_is_not_exposed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HOST", "::1")
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    assert _finding(report, "exposure").severity == "warn", "loopback, but authentication is off"


def test_doctor_output_is_ascii_safe():
    """`doctor` is now a command inside the MSI, run on a cp1252 console.

    An em-dash in a finding renders as a replacement character there, which
    makes a security warning look like a corrupted install. Same failure the
    enterprise build scripts had.
    """
    source = Path("agentmetry/core/diagnostics/doctor.py").resolve()
    offenders = sorted({c for c in source.read_text(encoding="utf-8") if ord(c) > 127})
    assert not offenders, f"doctor.py contains non-ASCII: {offenders}"


# ----------------------------------------------------------------------
# Anchor coverage
# ----------------------------------------------------------------------


def _anchor_report(trail: Path):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_anchors

    report = DoctorReport()
    _check_anchors(report, trail)
    return report


def _trail_with(tmp_path: Path, n: int) -> Path:
    from agentmetry.core.audit import trail_chain

    path = tmp_path / "t.jsonl"
    for i in range(n):
        trail_chain.append_chained_line(path, {"tool": "read_file", "n": i})
    return path


def test_unanchored_trail_says_nothing_at_all(tmp_path: Path, monkeypatch):
    """Silence is the feature.

    Every fresh install is unanchored and the chain still does real work, so a
    daily warning would nag about a legitimate choice. Nags are what teach an
    operator to stop reading doctor output, and this report only works if it is
    read.
    """
    monkeypatch.setattr("agentmetry.core.config.settings.anchor_log_path", "")
    assert _anchor_report(_trail_with(tmp_path, 4)).findings == []


def test_anchored_trail_reports_its_coverage(tmp_path: Path, monkeypatch):
    from agentmetry.core.audit import trail_anchor

    trail = _trail_with(tmp_path, 4)
    log = tmp_path / "elsewhere" / "a.jsonl"
    trail_anchor.FileAnchorSink(log).publish(trail_anchor.build_checkpoint(trail))
    monkeypatch.setattr("agentmetry.core.config.settings.anchor_log_path", str(log))

    findings = _anchor_report(trail).findings
    assert [f.severity for f in findings] == ["ok"]
    assert "anchored through record 4" in findings[0].message


def test_a_configured_anchor_log_that_is_missing_warns(tmp_path: Path, monkeypatch):
    """An intention that stopped working is not a choice.

    The operator believes they are covered. Staying quiet here would be the
    one silence that costs something.
    """
    monkeypatch.setattr(
        "agentmetry.core.config.settings.anchor_log_path", str(tmp_path / "gone.jsonl")
    )
    findings = _anchor_report(_trail_with(tmp_path, 4)).findings
    assert [f.severity for f in findings] == ["warn"]
    assert "does not exist" in findings[0].message


def test_a_contradicted_anchor_is_a_hard_failure(tmp_path: Path, monkeypatch):
    import json

    from agentmetry.core.audit import trail_anchor

    trail = _trail_with(tmp_path, 4)
    log = tmp_path / "a.jsonl"
    forged = trail_anchor.build_checkpoint(trail)
    log.write_text(
        json.dumps({**forged.to_dict(), "root_sha256": "0" * 64}) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr("agentmetry.core.config.settings.anchor_log_path", str(log))

    report = _anchor_report(trail)
    assert [f.severity for f in report.findings] == ["fail"]
    assert report.exit_code == 1


# ----------------------------------------------------------------------
# MCP inventory
# ----------------------------------------------------------------------


def _mcp_report(tmp_path, monkeypatch, document):
    import json as _json

    from agentmetry.core.config import settings
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_mcp

    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(_json.dumps(document), encoding="utf-8")
    report = DoctorReport()
    _check_mcp(report)
    return report


def test_no_mcp_servers_reports_nothing(tmp_path, monkeypatch):
    """The common case. A machine with no MCP servers has nothing to say."""
    from agentmetry.core.config import settings
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_mcp

    monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path))
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    report = DoctorReport()
    _check_mcp(report)
    assert report.findings == []


def test_pinned_servers_report_ok(tmp_path, monkeypatch):
    report = _mcp_report(
        tmp_path, monkeypatch,
        {"mcpServers": {"a": {"command": "npx", "args": ["-y", "a@1.0.0"]}}},
    )
    assert [f.severity for f in report.findings] == ["ok"]
    assert "all pinned" in report.findings[0].message


def test_an_unpinned_server_warns_and_never_fails(tmp_path, monkeypatch):
    """A risk posture is not a broken install.

    Failing the exit code over somebody else's packaging decision would make
    doctor unusable as the health check an MDM rollout wires into.
    """
    report = _mcp_report(
        tmp_path, monkeypatch,
        {"mcpServers": {"a": {"command": "npx", "args": ["-y", "sentry-mcp"]}}},
    )
    assert [f.severity for f in report.findings] == ["warn"]
    assert report.exit_code == 0


# ---------------------------------------------------------------- first-run hints
#
# A fresh `pip install agentmetry` was told to run `python scripts/demo.py` and
# to "copy from .env.example". Neither file ships in the wheel, so the first two
# instructions a stranger read were ones they could not follow.


def test_a_pip_install_is_not_told_to_copy_a_file_it_does_not_have(tmp_path: Path, monkeypatch):
    from agentmetry.core import paths

    monkeypatch.setattr(paths, "is_checkout", lambda: False)
    monkeypatch.setattr(paths, "env_file", lambda: tmp_path / ".env")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    env = [f for f in report.findings if f.code == "env"]
    assert env and env[0].severity == "ok"
    assert ".env.example" not in env[0].message
    assert "defaults" in env[0].message


def test_a_checkout_without_a_env_is_pointed_at_its_example(tmp_path: Path, monkeypatch):
    from agentmetry.core import paths

    monkeypatch.setattr(paths, "is_checkout", lambda: True)
    monkeypatch.setattr(paths, "env_file", lambda: tmp_path / ".env")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    env = [f for f in report.findings if f.code == "env"]
    assert env and env[0].severity == "warn"
    assert str(paths.PACKAGE_PARENT / ".env.example") in env[0].message


def test_no_trail_names_commands_an_install_actually_has(tmp_path: Path, monkeypatch):
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    report = run_doctor(vault_path=tmp_path / "no-such-vault")
    trail = [f for f in report.findings if f.code == "trail"]
    assert trail and trail[0].severity == "warn"
    assert "agentmetry demo" in trail[0].message
    assert "agentmetry hooks install" in trail[0].message
    assert "scripts/" not in trail[0].message
