"""YAML detection manifest — thresholds and count rules."""

from __future__ import annotations

from agentmetry.core.audit.detection.engine import run_detections
from agentmetry.core.audit.detection.yaml_config import clear_manifest_cache, count_rules, threshold
from agentmetry.core.config import settings


def _ev(**kwargs) -> dict:
    base = {
        "event_id": "e1",
        "correlation_id": "sess-yaml",
        "timestamp_utc": "2026-07-20T12:00:00+00:00",
        "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        "action": {"type": "tool_called", "outcome": "denied", "reason": "tool_policy:block"},
        "tool": {"qualified": "shell.run", "server": "shell"},
    }
    base.update(kwargs)
    return base


def test_threshold_reads_manifest():
    clear_manifest_cache()
    assert threshold("session_tool_burst") == 40
    assert threshold("subagent_burst") == 5


def test_packaged_manifest_has_no_duplicate_denial_rule():
    clear_manifest_cache()
    assert "rapid-tool-denials" not in {rule["id"] for rule in count_rules()}


def test_custom_manifest_controls_the_denial_rule(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "count_rules:\n"
        "  - id: rapid-tool-denials\n"
        '    title: Operator rapid tool denials\n'
        '    severity: low\n'
        '    summary: "{count} denied tool calls (operator rule)"\n'
        "    min_count: 2\n"
        "    match:\n"
        "      action_type: tool_called\n"
        "      outcome: denied\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "detection_rules_path", manifest)
    clear_manifest_cache()
    try:
        events = [
            _ev(event_id=f"d{i}", action={"type": "tool_called", "outcome": "denied", "reason": "x"})
            for i in range(5)
        ]
        assert not any(d.rule_id == "rapid-tool-denials" for d in run_detections(events[:1]))
        for sample in (events[:2], events):
            dets = [d for d in run_detections(sample) if d.rule_id in {"repeated-denials", "rapid-tool-denials"}]
            assert [d.rule_id for d in dets] == ["rapid-tool-denials"]
            assert dets[0].title == "Operator rapid tool denials"
            assert dets[0].severity == "low"
    finally:
        clear_manifest_cache()


def test_custom_manifest_can_omit_the_denial_rule(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("count_rules: []\n", encoding="utf-8")
    monkeypatch.setattr(settings, "detection_rules_path", manifest)
    clear_manifest_cache()
    try:
        events = [_ev(event_id=f"d{i}") for i in range(5)]
        assert not any(d.rule_id in {"repeated-denials", "rapid-tool-denials"} for d in run_detections(events))
    finally:
        clear_manifest_cache()


def test_rapid_dlp_blocks_yaml_rule_fires():
    clear_manifest_cache()
    events = [
        _ev(
            event_id=f"dlp{i}",
            action={"type": "tool_called", "outcome": "denied", "reason": "dlp:aws_access_key"},
        )
        for i in range(3)
    ]
    rule_ids = {d.rule_id for d in run_detections(events)}
    assert "rapid-dlp-blocks" in rule_ids
