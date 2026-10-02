"""Claude Code's native OTel stream, mapped onto canonical events.

The fixture is one Claude Code session in the wire format the vendor documents
(code.claude.com/docs/en/monitoring-usage): `success` is the string "true" or
"false", and `tool_input` and `tool_parameters` are JSON strings. The prototype
receiver read both as Python values, so on real traffic every failed call was a
success and no call was ever enriched. Its end-to-end check passed because it
fed objects the exporter never sends.
"""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core.audit import otel_ingest
from agentmetry.core.audit.detection.engine import run_detections
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.hooks.ingest import _hash_tool_args, map_claude_hook

FIXTURE = Path(__file__).parent / "fixtures" / "otel_claude_code_session.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
SESSION = "5f0c9a52-7a51-4c3e-9a0e-1c2d3e4f5a6b"


def _export() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _session() -> tuple[list[dict[str, Any]], otel_ingest.ReceiverStats]:
    stats = otel_ingest.ReceiverStats()
    return otel_ingest.translate(_export(), stats), stats


def _through_ingest_route(payload: dict[str, Any]) -> dict[str, Any]:
    """What the ingest route does with a body: validate, dump, canonicalise.

    A field the body model does not declare is dropped here, which is how the
    detection features were lost once before.
    """
    body = ExternalIngestBody(**payload).model_dump(exclude_none=True)
    return build_external_canonical(body)


def _record(name: str, **attrs: str) -> dict[str, Any]:
    items = [{"key": "event.name", "value": {"stringValue": name}},
             {"key": "session.id", "value": {"stringValue": SESSION}}]
    items += [{"key": k, "value": {"stringValue": v}} for k, v in attrs.items()]
    return {"resourceLogs": [{"scopeLogs": [{"logRecords": [
        {"timeUnixNano": "1790000000000000000", "attributes": items}
    ]}]}]}


def _one(name: str, **attrs: str) -> dict[str, Any] | None:
    out = otel_ingest.translate(_record(name, **attrs), otel_ingest.ReceiverStats())
    return out[0] if out else None


# ------------------------------------------------------------- the wire format


def test_a_failed_call_is_recorded_as_failed():
    """`success` is the string "false", and `bool("false")` is True."""
    events, _ = _session()
    failed = [e for e in events if e.get("tool", {}).get("input_hash")
              and e["event_type"] == "tool_failed"]

    assert len(failed) == 1
    assert failed[0]["outcome"] == "error"
    assert failed[0]["reason"] == "ExitCodeError"


@pytest.mark.parametrize("value,expected", [
    ("true", "tool_called"), ("false", "tool_failed"), ("False", "tool_failed"),
    ("0", "tool_failed"), ("1", "tool_called"),
])
def test_success_is_read_as_text(value: str, expected: str):
    event = _one("tool_result", tool_name="Read", success=value)
    assert event is not None
    assert event["event_type"] == expected


def test_arguments_sent_as_a_json_string_are_enriched():
    events, _ = _session()
    read = next(e for e in events if "credential_access" in e["tool"].get("traits", []))

    assert len(read["tool"]["input_hash"]) == 64
    assert read["tool"]["mitre"]["technique_id"].startswith("T1552")
    assert "arguments" not in read["tool"], "plaintext arguments must not leave the receiver"


def test_an_event_matches_the_hook_path_for_the_same_call():
    """The README's claim is the same enrichment, not similar enrichment."""
    command = "cat ~/.aws/credentials"
    hook = _hash_tool_args(map_claude_hook("PostToolUse", {
        "hook_event_name": "PostToolUse",
        "session_id": SESSION,
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "run it"},
        "tool_response": {"stdout": "", "stderr": ""},
    }))
    otel = _one("tool_result", tool_name="Bash", success="true",
                tool_input=json.dumps({"command": command, "description": "run it"}))

    assert otel is not None
    for key in ("qualified", "server", "input_hash", "traits", "mitre"):
        assert otel["tool"].get(key) == hook["tool"].get(key), key
    assert otel["correlation_id"] == hook["correlation_id"]
    assert otel["session_id"] == hook["session_id"]


def test_bash_summary_is_enough_for_traits_when_tool_input_is_absent():
    event = _one("tool_result", tool_name="Bash", success="true",
                 tool_parameters=json.dumps({"bash_command": "cat",
                                             "full_command": "cat ~/.aws/credentials"}))
    assert event is not None
    assert "credential_access" in event["tool"]["traits"]


def test_an_mcp_summary_is_not_hashed_as_if_it_were_arguments():
    """It names the server and tool only. A hash of that is a hash of nothing."""
    event = _one("tool_result", tool_name="mcp__github__create_issue", success="true",
                 tool_parameters=json.dumps({"mcp_server_name": "github",
                                             "mcp_tool_name": "create_issue"}))
    assert event is not None
    assert not event["tool"].get("input_hash")


def test_no_tool_details_means_no_hash_rather_than_a_hash_of_nothing():
    """OTEL_LOG_TOOL_DETAILS off: the prototype stamped sha256({}) on every call,
    which makes unrelated calls look identical to anything binding on the hash."""
    event = _one("tool_result", tool_name="Bash", success="true")
    assert event is not None
    assert not event["tool"].get("input_hash")
    assert not event["tool"].get("traits")


def test_a_task_spawn_carries_the_hook_paths_subagent_marker():
    event = _one("tool_result", tool_name="Task", success="true",
                 tool_input=json.dumps({"subagent_type": "Explore", "prompt": "x"}))
    assert event is not None
    assert event["reason"] == "subagent_start:Explore"


# ----------------------------------------------------------- what is forwarded


def test_prompt_and_error_text_are_never_forwarded():
    events, _ = _session()
    blob = json.dumps(events)
    assert "MUST-NEVER-BE-FORWARDED" not in blob


def test_a_human_yes_is_an_approval():
    event = _one("tool_decision", tool_name="Bash", decision="accept", source="user_temporary")
    assert event is not None
    assert event["event_type"] == "approval_response"
    assert event["outcome"] == "success"
    assert event["initiator"]["actor_type"] == "human"
    assert event["reason"] == "otel_decision:user_temporary"


@pytest.mark.parametrize("source", ["config", "hook"])
def test_an_automatic_yes_is_not_recorded_as_an_approval(source: str):
    """A settings rule or a hook decided. Recording it as approved would say a
    person had, and `success` resets the unapproved-write gate."""
    stats = otel_ingest.ReceiverStats()
    out = otel_ingest.translate(
        _record("tool_decision", tool_name="Bash", decision="accept", source=source), stats
    )
    assert out == []
    assert stats.snapshot()["unmapped_by_event"] == {f"tool_decision:{source}": 1}


def test_a_human_no_is_counted_and_never_arms_the_bypass_rule():
    """A denial with no hash or command binds by tool name, so forwarding it
    would convict every later Bash call. Counted, not forwarded, until the rule
    can bind on tool_use_id after the freeze."""
    events, stats = _session()

    assert stats.snapshot()["unmapped_by_event"]["tool_decision:human_reject"] == 1
    canonical = [_through_ingest_route(e) for e in events]
    fired = {d.rule_id for d in run_detections(canonical)}
    assert "approval-denied-then-executed" not in fired


def test_every_documented_unmapped_type_is_counted_by_name():
    stats = otel_ingest.ReceiverStats()
    for name in otel_ingest.KNOWN_UNMAPPED:
        assert otel_ingest.translate(_record(name), stats) == []
    counted = stats.snapshot()["unmapped_by_event"]

    assert len(otel_ingest.KNOWN_UNMAPPED) == 23
    assert set(counted) == set(otel_ingest.KNOWN_UNMAPPED)
    assert stats.snapshot()["undocumented_by_event"] == {}


def test_an_undocumented_type_is_counted_separately():
    _, stats = _session()
    assert stats.snapshot()["undocumented_by_event"] == {"some_future_event": 1}


def test_an_mcp_connection_without_a_fingerprint_is_counted():
    """Claude Code documents no fingerprint on this event."""
    _, stats = _session()
    assert stats.snapshot()["unmapped_by_event"]["mcp_server_connection"] == 1


def test_the_session_accounts_for_every_record():
    events, stats = _session()
    snap = stats.snapshot()
    held = sum(snap["unmapped_by_event"].values()) + sum(snap["undocumented_by_event"].values())

    assert sum(snap["received_by_event"].values()) == 10
    assert len(events) + held == 10


def test_the_exporters_clock_is_kept():
    events, _ = _session()
    assert events[0]["timestamp_utc"].startswith("2026-09-21T")


# --------------------------------------------------------------- end to end


def test_credential_read_then_egress_fires_on_the_documented_stream():
    """The prototype's changelog claim, measured against what Claude Code sends."""
    events, _ = _session()
    canonical = [_through_ingest_route(e) for e in events]
    fired = {d.rule_id: d for d in run_detections(canonical)}

    assert "credential-exfil" in fired
    assert fired["credential-exfil"].severity == "critical"
    assert fired["credential-exfil"].correlation_id == SESSION


def test_every_forwarded_body_survives_the_route_model():
    events, _ = _session()
    for event in events:
        validated = ExternalIngestBody(**event).model_dump(exclude_none=True)
        tool = event.get("tool")
        if tool:
            for key in ("input_hash", "traits", "mitre"):
                if tool.get(key):
                    assert validated["tool"][key] == tool[key], key


# -------------------------------------------------------------------- server


@pytest.fixture
def receiver():
    sent: list[dict[str, Any]] = []
    server = otel_ingest.make_server(0, forward=lambda p: sent.append(p) or True)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, sent
    finally:
        server.shutdown()
        server.server_close()


def _post(server, path: str, body: bytes, headers: dict[str, str] | None = None) -> int:
    host, port = server.server_address[:2]
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=body, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - loopback test server
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_the_receiver_listens_on_loopback_only(receiver):
    server, _ = receiver
    assert server.server_address[0] == "127.0.0.1"


def test_a_logs_export_is_forwarded(receiver):
    server, sent = receiver
    assert _post(server, "/v1/logs", FIXTURE.read_bytes()) == 200
    assert len(sent) == len(_session()[0])
    assert server.stats.snapshot()["forwarded"] == len(sent)


def test_a_gzipped_export_is_accepted(receiver):
    server, sent = receiver
    status = _post(server, "/v1/logs", gzip.compress(FIXTURE.read_bytes()),
                   {"Content-Encoding": "gzip"})
    assert status == 200
    assert sent


def test_protobuf_is_refused_with_a_reason_not_swallowed(receiver):
    server, sent = receiver
    assert _post(server, "/v1/logs", b"\x0a\x00",
                 {"Content-Type": "application/x-protobuf"}) == 415
    assert sent == []


def test_metrics_are_acknowledged_so_the_exporter_stops_retrying(receiver):
    server, sent = receiver
    assert _post(server, "/v1/metrics", b"{}") == 200
    assert sent == []
    assert server.stats.snapshot()["metrics_exports_acked"] == 1


def test_an_undelivered_event_is_counted_as_spooled():
    stats = otel_ingest.ReceiverStats()
    stats.note_forward(False)
    assert stats.snapshot()["not_delivered_spooled"] == 1


# ----------------------------------------------------------------------- CLI


def test_cli_prints_the_mapping():
    out = subprocess.run(
        [sys.executable, "-m", "agentmetry.cli", "otel", "--print-mapping"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("unmapped: ") == 23


def test_cli_prints_the_environment_for_claude_code():
    out = subprocess.run(
        [sys.executable, "-m", "agentmetry.cli", "otel", "--print-env", "--listen-port", "4399"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4399" in out.stdout
    assert "OTEL_EXPORTER_OTLP_PROTOCOL=http/json" in out.stdout


def test_the_old_script_path_still_works():
    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "otel_receiver.py"), "--print-mapping"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.count("unmapped: ") == 23
