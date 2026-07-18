"""The shape a SIEM actually receives from the file sink.

This exists because the hash-chain envelope silently broke Loki forwarding. The
file sink wraps every line as {"trail":{...},"event":{...}}, but the Alloy
pipeline extracted action.type from the top level, so every label came out empty
and every documented LogQL query returned nothing. No test caught it: they all
build canonical dicts in memory and never round-trip through the sink to a
consumer.

These tests read a real line written by FileAuditSink and validate it against the
extraction paths in the shipped infra/loki/alloy.config, so changing the envelope
breaks a test instead of the homelab pipeline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from core.audit.external import build_external_canonical
from core.audit.sinks import FileAuditSink

_REPO = Path(__file__).resolve().parents[3]
ALLOY_CONFIG = _REPO / "infra" / "loki" / "alloy.config"


def _payload(corr: str = "sess-shape") -> dict[str, Any]:
    return {
        "source_app": "cursor",
        "event_type": "tool_called",
        "correlation_id": corr,
        "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"},
    }


def _unwrap(record: dict[str, Any]) -> dict[str, Any]:
    """Mirror the Alloy expression `event || @`.

    Returns the nested canonical event for a chained envelope and the record
    itself for a legacy unchained line.
    """
    event = record.get("event")
    return event if isinstance(event, dict) else record


def _resolve(obj: dict[str, Any], dotted: str) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _eval(doc: Any, expr: str) -> Any:
    """Evaluate a JMESPath expression limited to what alloy.config uses.

    Supports dotted paths and the `a || b` fallback, where `@` is the whole
    document.
    """
    for alt in (part.strip() for part in expr.split("||")):
        value = doc if alt == "@" else _resolve(doc, alt)
        if value not in (None, ""):
            return value
    return None


def _simulate_alloy(record: dict[str, Any]) -> dict[str, Any]:
    """Run the shipped alloy.config stages against a line, in order.

    Models enough of the pipeline to catch the real failure: stage.json extracts,
    and if stage.output names one of those extractions the log line is replaced
    by it before later stages run. Without the unwrap stage, extraction happens
    against the envelope and every field comes out empty, which is exactly the
    bug this file guards.
    """
    text = ALLOY_CONFIG.read_text(encoding="utf-8")
    blocks = re.findall(r"expressions\s*=\s*\{(.*?)\}", text, re.DOTALL)
    out = re.search(r'stage\.output\s*\{[^}]*?source\s*=\s*"(\w+)"', text, re.DOTALL)
    output_source = out.group(1) if out else None

    line: Any = record
    labels: dict[str, Any] = {}
    for block in blocks:
        extracted = {
            name: _eval(line, expr)
            for name, expr in re.findall(r'(\w+)\s*=\s*"([^"]+)"', block)
        }
        if output_source and output_source in extracted:
            replacement = extracted[output_source]
            if isinstance(replacement, dict):
                line = replacement
            continue
        labels.update(extracted)
    return labels


@pytest.mark.asyncio
async def test_file_sink_writes_chained_envelope(tmp_path):
    """The contract Alloy depends on: canonical event lives under .event."""
    trail = tmp_path / "audit-forward.jsonl"
    await FileAuditSink(trail).emit(build_external_canonical(_payload()))

    record = json.loads(trail.read_text(encoding="utf-8").strip().splitlines()[-1])

    assert set(record.keys()) == {"trail", "event"}, (
        "file sink envelope changed; infra/loki/alloy.config must be updated too"
    )
    assert "action" not in record, "canonical fields must NOT be at the top level"
    assert record["event"]["action"]["type"] == "tool_called"


@pytest.mark.asyncio
async def test_alloy_pipeline_extracts_labels_from_a_real_chained_line(tmp_path):
    """The shipped Alloy config must produce non-empty labels on a real line.

    Fails if the unwrap stage is removed: extraction then runs against the
    envelope, every label is empty, and every documented LogQL query in
    docs/integrations/loki-homelab.md silently returns nothing.
    """
    trail = tmp_path / "audit-forward.jsonl"
    await FileAuditSink(trail).emit(build_external_canonical(_payload()))
    record = json.loads(trail.read_text(encoding="utf-8").strip().splitlines()[-1])

    labels = _simulate_alloy(record)
    assert labels, "no extraction expressions found in alloy.config"

    for name, value in labels.items():
        assert value not in (None, ""), (
            f"alloy.config label {name!r} is empty on a real chained trail line. "
            "Loki labels and the documented LogQL queries break."
        )
    assert labels["action_type"] == "tool_called"
    assert labels["tool_qualified"] == "cursor.Read"


def test_alloy_pipeline_is_safe_for_legacy_unchained_lines():
    """`event || @` must pass a pre-chain line through instead of blanking it.

    91% of the operator's own trail is legacy unchained lines, so an unwrap that
    dropped them would erase most of the history from Loki.
    """
    legacy = build_external_canonical(_payload("sess-legacy"))
    assert "trail" not in legacy

    labels = _simulate_alloy(legacy)
    for name, value in labels.items():
        assert value not in (None, ""), f"legacy line lost label {name!r}"
    assert labels["correlation_id"] == "sess-legacy"


@pytest.mark.asyncio
async def test_non_file_sinks_receive_unwrapped_canonical(tmp_path):
    """Only the file sink wraps. Webhook/Elastic/Splunk get bare canonical.

    This is why the Sigma pack's top-level `action.type` selectors are correct,
    and why the unwrap belongs in Alloy rather than in the rules.
    """
    seen: list[dict[str, Any]] = []

    class _Capture:
        async def emit(self, event: dict[str, Any]) -> None:
            seen.append(event)

    canonical = build_external_canonical(_payload("sess-direct"))
    await _Capture().emit(canonical)

    assert "trail" not in seen[0]
    assert seen[0]["action"]["type"] == "tool_called"
