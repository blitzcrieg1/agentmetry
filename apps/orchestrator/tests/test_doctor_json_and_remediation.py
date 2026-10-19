"""`doctor --json` for deployment scripts, and `hook_remediation` as a config change.

Intune Remediations and LaunchAgents decide from exit codes and fields. Parsing
doctor's sentences works until somebody rewords one, and a compliance check that
breaks on a wording change fails silently. Cursor's #282 added both pieces; this
is them without the fleet installers, which live in agentmetry-enterprise.

A remediation notice used to have no mapping, so it was stored as `tool_called`
with no tool. Tool-sequence rules count those, so a daily Intune run could
feed `session-tool-burst`. It is now `config_change`, alone in its session.
"""

from __future__ import annotations

import json

import pytest

from agentmetry.core.audit.detection.engine import run_detections, run_host_detections
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.diagnostics import doctor


def _report() -> doctor.DoctorReport:
    report = doctor.DoctorReport()
    report.hooks = {"claude": "covered", "cursor": "absent"}
    report.hook_profile = "user"
    report.orchestrator_reachable = True
    report.policy_locked = ["dlp_mode"]
    report.policy_pinned = ["dlp_rules_path"]
    report.ok("hooks", "Hooks installed for: claude")
    return report


def test_the_payload_is_fields_not_sentences():
    payload = doctor.report_payload(_report())
    assert payload["schema"] == doctor.JSON_SCHEMA == 1
    assert payload["exit_code"] == 0
    assert payload["orchestrator_reachable"] is True
    assert payload["hook_profile"] == "user"
    assert payload["hooks"] == {"claude": "covered", "cursor": "absent"}
    assert payload["policy"] == {"locked": ["dlp_mode"], "pinned": ["dlp_rules_path"], "rejected": []}
    assert payload["findings"] == [
        {"severity": "ok", "code": "hooks", "message": "Hooks installed for: claude"}
    ]


def test_a_fail_sets_the_exit_code_in_the_payload_too():
    report = _report()
    report.fail("managed_policy", "refused")
    assert doctor.report_payload(report)["exit_code"] == 1


def test_json_output_is_only_json(capsys):
    """A script pipes this into ConvertFrom-Json; one banner line breaks it."""
    doctor.print_report(_report(), as_json=True)
    assert json.loads(capsys.readouterr().out)["hooks"]["claude"] == "covered"


def test_the_hooks_check_fills_the_coverage_map(monkeypatch):
    from agentmetry.core.diagnostics import hook_coverage

    monkeypatch.setattr(hook_coverage, "profile_blind", lambda: False)
    monkeypatch.setattr(hook_coverage, "coverage", lambda: {"claude": "uncovered", "cursor": "absent"})
    report = doctor.DoctorReport()
    doctor._check_hooks_installed(report)
    assert report.hooks == {"claude": "uncovered", "cursor": "absent"}


def test_a_blind_service_profile_reports_every_agent_unknown(monkeypatch):
    """Not an empty map: a script that loops over `hooks` must see the
    unknowns, or a blind service install reads as compliant."""
    from agentmetry.core.diagnostics import hook_coverage

    monkeypatch.setattr(hook_coverage, "profile_blind", lambda: True)
    monkeypatch.setattr(hook_coverage, "attestation_profile", lambda: "service")
    report = doctor.DoctorReport()
    doctor._check_hooks_installed(report)
    assert set(report.hooks.values()) == {hook_coverage.UNKNOWN}
    assert set(report.hooks) == {s.name for s in hook_coverage.SURFACES}
    assert report.hook_profile == "service"


def test_the_cli_flag_reaches_the_printer(monkeypatch, capsys):
    from agentmetry import cli

    monkeypatch.setattr(doctor, "run_doctor", lambda **_: _report())
    assert cli.main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == 1


# ----------------------------------------------------------------------
# hook_remediation
# ----------------------------------------------------------------------


def _remediation(**extra) -> dict:
    return build_external_canonical({
        "event_type": "hook_remediation",
        "source_app": "agentmetry",
        "reason": "intune remediation reinstalled hooks",
        **extra,
    })


def test_a_remediation_is_a_config_change():
    event = _remediation()
    assert event["action"] == {
        "type": "config_change", "outcome": "success",
        "reason": "intune remediation reinstalled hooks",
    }
    assert event["source_topic"] == "external/agentmetry/hook_remediation"


def test_a_remediation_drops_whatever_would_join_it_to_an_agents_work():
    event = _remediation(
        correlation_id="sess-1", session_id="ws-1",
        tool={"qualified": "Bash", "command": "rm -rf ~"},
        dlp={"rule_id": "aws-key"}, gated_action={"tool": "Bash"}, skill_id="x",
    )
    assert event["correlation_id"] == event["session_id"] == ""
    for key in ("tool", "dlp", "gated_action"):
        assert key not in event
    assert event["agent"]["skill_id"] == ""


@pytest.mark.parametrize("given, recorded", [
    ("success", "success"), ("error", "error"), ("failed", "error"), ("denied", "error"),
])
def test_only_success_is_success(given, recorded):
    """A fleet alerting on failed remediations must not lose one to a spelling."""
    assert _remediation(outcome=given)["action"]["outcome"] == recorded


def test_a_daily_remediation_run_raises_no_detection():
    """Fifty notices in a minute, the worst a broken scheduler could do, through
    the real (frozen) engine: nothing fires."""
    events = [
        _remediation(timestamp_utc=f"2026-10-19T09:00:{i:02d}+00:00") for i in range(50)
    ]
    assert run_detections(events) == []
    assert run_host_detections(events) == []
    # The same notices under the old fallback, to show this test bites.
    unmapped = [
        build_external_canonical({"event_type": "unmapped", "source_app": "agentmetry",
                                  "timestamp_utc": f"2026-10-19T09:00:{i:02d}+00:00"})
        for i in range(50)
    ]
    assert "session-tool-burst" in {d.rule_id for d in run_detections(unmapped)}


def test_an_unknown_event_type_is_still_a_tool_call():
    """The fallback the remediation used to hit, unchanged for everything else."""
    assert build_external_canonical({"event_type": "whatever", "tool_name": "Bash"})["action"]["type"] == "tool_called"
