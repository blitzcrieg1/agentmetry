"""YAML detection manifest — thresholds and count rules."""

from __future__ import annotations

from agentmetry.core.audit.detection.engine import run_detections
from agentmetry.core.audit.detection.yaml_config import clear_manifest_cache, threshold
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


def test_rapid_tool_denials_yaml_rule_fires():
    # The YAML rule itself still fires at five denials — it stays registered
    # under its own id — but the default engine reports the burst once, as
    # `repeated-denials`, instead of double-reporting it (PR #486 review).
    from agentmetry.core.audit.detection.yaml_rules import build_yaml_rules

    clear_manifest_cache()
    events = [
        _ev(event_id=f"d{i}", action={"type": "tool_called", "outcome": "denied", "reason": "x"})
        for i in range(5)
    ]
    yaml_rules = {rule.__name__: rule for rule in build_yaml_rules()}
    fired = yaml_rules["yaml_rapid_tool_denials"](events)
    assert [d.rule_id for d in fired] == ["rapid-tool-denials"]

    dets = [d for d in run_detections(events) if d.rule_id in {"repeated-denials", "rapid-tool-denials"}]
    assert [d.rule_id for d in dets] == ["repeated-denials"]


def test_custom_manifest_rule_with_shipped_id_is_not_suppressed(tmp_path, monkeypatch):
    # A custom manifest replaces the whole file, so a rule id in it is the
    # operator's own even when it collides with a shipped id. The denial
    # burst deduplication must only ever drop the *shipped*
    # `rapid-tool-denials` finding — a custom-manifest rule with the same id
    # keeps firing alongside the built-in `repeated-denials` finding
    # (PR #486 review, round 2). The custom rule is recognisable by its own
    # title and severity, proving the surviving finding came from it.
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
        dets = [d for d in run_detections(events) if d.rule_id in {"repeated-denials", "rapid-tool-denials"}]
        assert [d.rule_id for d in dets] == ["repeated-denials", "rapid-tool-denials"]
        custom = [d for d in dets if d.rule_id == "rapid-tool-denials"][0]
        assert custom.title == "Operator rapid tool denials"
        assert custom.severity == "low"
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
