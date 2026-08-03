"""YAML-defined session count rules (policies/detection/manifest.yaml)."""

from __future__ import annotations

from typing import Any, Callable

from .models import Detection
from .rules import (
    _action,
    _action_type,
    _correlation_id,
    _event_id,
    _outcome,
    _tool_qualified,
    _ts,
)
from .yaml_config import count_rules


def _event_matches(event: dict[str, Any], match: dict[str, Any]) -> bool:
    if not match:
        return True
    if (want := match.get("action_type")) and _action_type(event) != str(want):
        return False
    if (want := match.get("outcome")) and _outcome(event) != str(want):
        return False
    if prefix := match.get("tool_qualified_prefix"):
        if not _tool_qualified(event).startswith(str(prefix)):
            return False
    if contains := match.get("tool_qualified_contains"):
        if str(contains) not in _tool_qualified(event):
            return False
    if prefix := match.get("reason_prefix"):
        reason = str(_action(event).get("reason") or "")
        if not reason.startswith(str(prefix)):
            return False
    if trait := match.get("trait"):
        tool = event.get("tool") if isinstance(event.get("tool"), dict) else {}
        traits = tool.get("traits") if isinstance(tool.get("traits"), list) else []
        if str(trait) not in {str(t) for t in traits}:
            return False
    initiator = event.get("initiator") if isinstance(event.get("initiator"), dict) else {}
    if (want := match.get("initiator_actor_type")) and str(initiator.get("actor_type") or "") != str(want):
        return False
    return True


def _make_count_rule(spec: dict[str, Any]) -> Callable[[list[dict[str, Any]]], list[Detection]]:
    rule_id = str(spec["id"])
    title = str(spec.get("title") or rule_id)
    severity = str(spec.get("severity") or "medium")
    summary_tpl = str(spec.get("summary") or "{count} matching events in one session")
    min_count = int(spec.get("min_count") or 1)
    match = spec.get("match") if isinstance(spec.get("match"), dict) else {}
    tactic_ids = [str(t) for t in (spec.get("tactic_ids") or []) if t]
    technique_ids = [str(t) for t in (spec.get("technique_ids") or []) if t]

    def rule(events: list[dict[str, Any]]) -> list[Detection]:
        hits = [e for e in events if _event_matches(e, match)]
        if len(hits) < min_count:
            return []
        summary = summary_tpl.replace("{count}", str(len(hits)))
        return [
            Detection(
                rule_id=rule_id,
                title=title,
                severity=severity,
                summary=summary,
                correlation_id=_correlation_id(events),
                tactic_ids=tactic_ids,
                technique_ids=technique_ids,
                event_ids=[_event_id(e) for e in hits[:20]],
                first_seen_utc=_ts(hits[0]),
                last_seen_utc=_ts(hits[-1]),
            )
        ]

    rule.__name__ = f"yaml_{rule_id.replace('-', '_')}"
    return rule


def build_yaml_rules() -> list[Callable[[list[dict[str, Any]]], list[Detection]]]:
    return [_make_count_rule(spec) for spec in count_rules() if spec.get("id")]
