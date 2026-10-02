"""Claude Code's native OpenTelemetry stream, as Agentmetry events.

Claude Code exports its own telemetry over OTLP, and its documentation leaves
anomaly detection, correlation and alerting to the backend. This module is that
backend's front door: a loopback OTLP/HTTP JSON receiver that maps the
``claude_code.*`` log events it can onto the external-ingest body and sends
them through the hook client's own ``post_ingest``, so they get the same
argument hashing, trait labels, MITRE and ATLAS enrichment, and the same spool
when the orchestrator is down.

Every event that is not forwarded is counted under a name, never dropped
silently. The unmapped counts are the input to canonical schema v1.3.

What this path cannot see, stated where the code is: OTel reports what happened,
after it happened. There is no pre-execution decision here, so no policy can be
enforced from it. Hooks remain the path for deny and ask.

Claude Code side (code.claude.com/docs/en/monitoring-usage)::

    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_PROTOCOL=http/json
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
    OTEL_LOG_TOOL_DETAILS=1      # without it, no tool arguments: hash and traits are empty
    OTEL_METRICS_EXPORTER=none   # metrics are aggregates, acknowledged and not mapped
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agentmetry.hooks.ingest import _hash_tool_args, post_ingest, redact_arguments

#: The receiver binds here and nowhere else. The stream carries tool arguments
#: when OTEL_LOG_TOOL_DETAILS is on, and nothing about it needs another host.
LISTEN_HOST = "127.0.0.1"
DEFAULT_PORT = 4318

#: Documented event types with no canonical home yet: the schema v1.3 input.
#: `user_prompt` and `assistant_response` would never be forwarded regardless.
#: They are the model's words, and the recorder's default is structure, not
#: content.
KNOWN_UNMAPPED = frozenset({
    "user_prompt",
    "assistant_response",
    "api_request",
    "api_error",
    "api_refusal",
    "api_request_body",
    "api_response_body",
    "api_retries_exhausted",
    "internal_error",
    "permission_mode_changed",
    "auth",
    "plugin_installed",
    "plugin_loaded",
    "skill_activated",
    "at_mention",
    "hook_registered",
    "hook_execution_start",
    "hook_execution_complete",
    "hook_plugin_metrics",
    "compaction",
    "subagent_completed",
    "feedback_survey",
    "retention_sweep",
})

#: `tool_decision.source` values that mean a person answered a prompt.
_HUMAN_ACCEPT = frozenset({"user_temporary", "user_permanent"})
_HUMAN_REJECT = frozenset({"user_reject", "user_abort"})

Forward = Callable[[dict[str, Any]], bool]


# --------------------------------------------------------------------- decoding


def otlp_value(value: Any) -> Any:
    """Decode one OTLP JSON ``AnyValue`` into a plain Python value."""
    if not isinstance(value, dict):
        return value
    for key, cast in (
        ("stringValue", str),
        ("boolValue", bool),
        ("intValue", int),
        ("doubleValue", float),
    ):
        if key in value:
            try:
                return cast(value[key])
            except (TypeError, ValueError):
                return value[key]
    if "arrayValue" in value:
        return [otlp_value(v) for v in (value["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in value:
        return otlp_attributes((value["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in value:
        return repr(value["bytesValue"])
    return value


def otlp_attributes(items: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("key"):
            out[item["key"]] = otlp_value(item.get("value", {}))
    return out


def _merge_body(record: dict[str, Any], attrs: dict[str, Any]) -> None:
    """Let a JSON body backfill attributes. An attribute wins on conflict.

    Claude Code documents its events by attributes; some exporter paths put the
    same payload in the body instead.
    """
    body = record.get("body")
    text = body.get("stringValue") if isinstance(body, dict) else None
    if isinstance(text, str) and text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return
        if isinstance(parsed, dict):
            for key, val in parsed.items():
                attrs.setdefault(key, val)


def _timestamp(record: dict[str, Any], attrs: dict[str, Any]) -> str:
    """When it happened, by the exporter's clock, never ours if it said."""
    for ns in (record.get("timeUnixNano"), record.get("observedTimeUnixNano")):
        try:
            if ns and int(ns) > 0:
                return datetime.fromtimestamp(int(ns) / 1e9, tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            continue
    stamped = attrs.get("event.timestamp")
    if isinstance(stamped, str) and stamped:
        return stamped
    return datetime.now(timezone.utc).isoformat()


def _flag(value: Any, default: bool = True) -> bool:
    """Claude Code sends `success` as the string "true" or "false".

    `bool("false")` is True, so reading it as a truthy value recorded every
    failed tool call as a success.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("false", "0", "no", ""):
        return False
    return True


def _json_object(value: Any) -> dict[str, Any] | None:
    """`tool_input` and `tool_parameters` arrive as JSON strings, not objects."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def tool_arguments(attrs: dict[str, Any]) -> dict[str, Any] | None:
    """The tool's arguments, as close to the hook's `tool_input` as OTel gets.

    `tool_input` is the serialized arguments themselves, so it is preferred: it
    is what the hook hashes, and its `command` key is what the traits read.
    Claude Code truncates its values at 512 characters, so a long argument
    hashes differently here than on the hook path.

    `tool_parameters` is a summary, not the arguments. For Bash it carries
    `full_command`, which is enough for traits and MITRE, so that alone is used.
    For an MCP tool it carries only the server and tool names, and a hash of
    those would claim to be a hash of arguments it never saw, so it is not used.

    None when OTEL_LOG_TOOL_DETAILS is off: no argument detail is exported.
    """
    args = _json_object(attrs.get("tool_input"))
    if args is not None:
        return args
    params = _json_object(attrs.get("tool_parameters"))
    if params and params.get("full_command"):
        return {"command": str(params["full_command"])}
    return None


# ---------------------------------------------------------------------- mapping


def _base(attrs: dict[str, Any], ts_iso: str) -> dict[str, Any]:
    # The hook path uses Claude Code's session id for both fields, and OTel's
    # `session.id` is the same value, so one session correlates the same way
    # whichever path recorded it.
    session = str(attrs.get("session.id") or attrs.get("session_id") or "")
    return {
        "source_app": "claude",
        "adapter": "otel",
        "correlation_id": session,
        "session_id": session,
        "timestamp_utc": ts_iso,
        "triggered_by": "otel_receiver",
    }


def _map_tool_result(attrs: dict[str, Any], ts_iso: str) -> dict[str, Any]:
    tool_name = str(attrs.get("tool_name") or "unknown")
    succeeded = _flag(attrs.get("success"))
    args = tool_arguments(attrs)

    tool: dict[str, Any] = {"qualified": tool_name, "server": "claude"}
    if args is not None:
        tool["arguments"] = redact_arguments(args)

    reason = ""
    if not succeeded:
        reason = str(attrs.get("error_type") or "tool_failed")
    elif tool_name == "Task" and args is not None:
        # The hook path's subagent marker, so subagent-swarm-burst counts a
        # Task spawn the same way whichever path recorded it.
        reason = f"subagent_start:{args.get('subagent_type') or 'subagent'}"

    payload = _base(attrs, ts_iso)
    payload.update({
        "event_type": "tool_called" if succeeded else "tool_failed",
        "outcome": "success" if succeeded else "error",
        "reason": reason,
        "tool_qualified": tool_name,
        "model_id": str(attrs.get("model") or attrs.get("gen_ai.request.model") or ""),
        "tool": tool,
    })
    # The hook client's own enrichment: hash the arguments, label traits, map
    # MITRE and ATLAS while the plaintext is visible, keep command text only
    # when AGENTMETRY_LOG_COMMANDS says to. Identical code, so identical output.
    return _hash_tool_args(payload) or payload


def _map_tool_decision(attrs: dict[str, Any], ts_iso: str) -> tuple[dict[str, Any] | None, str]:
    """Forward a human's yes. Count everything else, and say why.

    Detection reads `approval_response` as a person's decision: `success` resets
    the unapproved-write gate, and a `denied` arms approval-denied-then-executed.

    * A `config` or `hook` decision was made by a settings rule or a hook, not a
      person, so recording it as an approval would be false.
    * A human reject is real, but cannot be forwarded yet. That rule binds a
      denial to a later call by argument hash or command, and `tool_decision`
      carries neither, so it would fall back to the tool name and convict every
      later call of the same tool. That is the false positive 0.7.0 removed.
      Binding by `tool_use_id` is a rule change, and the rules are frozen.
    """
    decision = str(attrs.get("decision") or "").lower()
    source = str(attrs.get("source") or "").lower()
    if decision == "accept" and source in _HUMAN_ACCEPT:
        payload = _base(attrs, ts_iso)
        payload.update({
            "event_type": "approval_response",
            "outcome": "success",
            "reason": f"otel_decision:{source}",
            "tool_qualified": str(attrs.get("tool_name") or ""),
            "initiator": {"actor_type": "human", "trigger": "manual", "operator_id": "local"},
        })
        return payload, ""
    if decision == "reject" and source in _HUMAN_REJECT:
        return None, "tool_decision:human_reject"
    return None, f"tool_decision:{source or 'unknown'}"


def map_record(event_name: str, attrs: dict[str, Any], ts_iso: str) -> tuple[dict[str, Any] | None, str]:
    """One `claude_code.*` event as an ingest body, or None and the name it is counted under."""
    if event_name == "tool_result":
        return _map_tool_result(attrs, ts_iso), ""
    if event_name == "tool_decision":
        return _map_tool_decision(attrs, ts_iso)
    if event_name == "mcp_server_connection":
        # Claude Code documents no fingerprint on this event, so in practice it
        # is counted. The mapping stays for an exporter that does carry one.
        fingerprint = attrs.get("server_fingerprint")
        if not fingerprint:
            return None, event_name
        payload = _base(attrs, ts_iso)
        payload.update({
            "event_type": "mcp_schema",
            "schema_fingerprint": str(fingerprint),
            "reason": str(attrs.get("server_name") or ""),
        })
        return payload, ""
    return None, event_name


def iter_records(export: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any], str]]:
    """(event name, attributes, timestamp) for every log record in an OTLP export."""
    for res_log in export.get("resourceLogs", []) or []:
        for scope in (res_log or {}).get("scopeLogs", []) or []:
            for record in (scope or {}).get("logRecords", []) or []:
                if not isinstance(record, dict):
                    continue
                attrs = otlp_attributes(record.get("attributes"))
                _merge_body(record, attrs)
                name = str(attrs.get("event.name") or record.get("eventName") or "")
                name = name.removeprefix("claude_code.")
                if name:
                    yield name, attrs, _timestamp(record, attrs)


# ------------------------------------------------------------------------ stats


class ReceiverStats:
    """What came in, what went out, and what was held back, by name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.received: dict[str, int] = {}
        self.unmapped: dict[str, int] = {}
        self.unknown: dict[str, int] = {}
        self.forwarded = 0
        self.spooled = 0
        self.metrics_acked = 0

    def _bump(self, table: dict[str, int], key: str) -> int:
        with self._lock:
            table[key] = table.get(key, 0) + 1
            return table[key]

    def note_received(self, name: str) -> None:
        self._bump(self.received, name)

    def note_unmapped(self, name: str) -> bool:
        """Count it. True the first time an undocumented name is seen."""
        base = name.split(":", 1)[0]
        if base in KNOWN_UNMAPPED or base in ("tool_decision", "mcp_server_connection"):
            self._bump(self.unmapped, name)
            return False
        return self._bump(self.unknown, name) == 1

    def note_forward(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.forwarded += 1
            else:
                self.spooled += 1

    def note_metrics(self) -> None:
        with self._lock:
            self.metrics_acked += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "forwarded": self.forwarded,
                # post_ingest spools what it cannot deliver; the orchestrator
                # drains the spool at boot.
                "not_delivered_spooled": self.spooled,
                "received_by_event": dict(self.received),
                "unmapped_by_event": dict(self.unmapped),
                "undocumented_by_event": dict(self.unknown),
                "metrics_exports_acked": self.metrics_acked,
            }


def translate(export: dict[str, Any], stats: ReceiverStats) -> list[dict[str, Any]]:
    """Map one OTLP logs export, counting every record under a name."""
    out: list[dict[str, Any]] = []
    for name, attrs, ts_iso in iter_records(export):
        stats.note_received(name)
        payload, counted_as = map_record(name, attrs, ts_iso)
        if payload is not None:
            out.append(payload)
        elif stats.note_unmapped(counted_as):
            _log(f"undocumented event {counted_as!r}: counted, not forwarded")
    return out


def _log(msg: str) -> None:
    print(f"[otel {datetime.now().strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------- server


def _quiet_post(payload: dict[str, Any]) -> bool:
    return post_ingest(payload, quiet=True)


class _Handler(BaseHTTPRequestHandler):
    server_version = "agentmetry-otel/1"
    # OTLP exporters keep the connection alive; HTTP/1.0 semantics stall them.
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        stats: ReceiverStats = self.server.stats  # type: ignore[attr-defined]
        forward: Forward = self.server.forward  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if self.path.startswith("/v1/metrics"):
            # Aggregates, not session events. Acknowledge so the exporter does
            # not retry forever.
            stats.note_metrics()
            self._reply(200)
            return
        if not self.path.startswith("/v1/logs"):
            self._reply(404)
            return
        if "protobuf" in (self.headers.get("Content-Type") or "").lower():
            if not getattr(self.server, "warned_protobuf", False):
                self.server.warned_protobuf = True  # type: ignore[attr-defined]
                _log("received protobuf; set OTEL_EXPORTER_OTLP_PROTOCOL=http/json")
            self._reply(415)
            return
        if (self.headers.get("Content-Encoding") or "").lower() == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                self._reply(400)
                return
        try:
            export = json.loads(raw or b"{}")
        except ValueError:
            self._reply(400)
            return
        if not isinstance(export, dict):
            self._reply(400)
            return

        for payload in translate(export, stats):
            stats.note_forward(forward(payload))
        self._reply(200, b"{}")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path in ("/healthz", "/"):
            stats: ReceiverStats = self.server.stats  # type: ignore[attr-defined]
            self._reply(200, json.dumps(stats.snapshot()).encode())
            return
        self._reply(404)

    def _reply(self, code: int, body: bytes = b"") -> None:
        # Headers end before the body, or HTTP/1.1 clients wait for a separator.
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def make_server(port: int = DEFAULT_PORT, *, forward: Forward | None = None,
                stats: ReceiverStats | None = None) -> ThreadingHTTPServer:
    """A receiver bound to loopback. Port 0 picks a free one (tests)."""
    server = ThreadingHTTPServer((LISTEN_HOST, port), _Handler)
    server.stats = stats or ReceiverStats()  # type: ignore[attr-defined]
    server.forward = forward or _quiet_post  # type: ignore[attr-defined]
    return server


def default_port() -> int:
    try:
        return int(os.environ.get("AGENTMETRY_OTEL_PORT", "") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def claude_env_lines(port: int) -> list[str]:
    return [
        "CLAUDE_CODE_ENABLE_TELEMETRY=1",
        "OTEL_LOGS_EXPORTER=otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL=http/json",
        f"OTEL_EXPORTER_OTLP_ENDPOINT=http://{LISTEN_HOST}:{port}",
        "OTEL_LOG_TOOL_DETAILS=1",
        "OTEL_METRICS_EXPORTER=none",
    ]


def mapping_lines() -> list[str]:
    lines = [
        "mapped:   tool_result -> tool_called / tool_failed (hash, traits, MITRE, ATLAS)",
        "mapped:   tool_decision accepted by a person -> approval_response success",
        "counted:  tool_decision rejected by a person (a denial needs a binding the event lacks)",
        "counted:  tool_decision by config or hook (not a human decision)",
        "partial:  mcp_server_connection -> mcp_schema, only with a fingerprint attribute",
    ]
    lines += [f"unmapped: {name}" for name in sorted(KNOWN_UNMAPPED)]
    return lines


def serve(port: int, orchestrator: str) -> int:
    """Run in the foreground until interrupted, then print the counts."""
    try:
        server = make_server(port)
    except OSError as exc:
        print(f"Cannot listen on {LISTEN_HOST}:{port}: {exc}", file=sys.stderr)
        return 1
    _log(f"OTLP receiver on http://{LISTEN_HOST}:{port} -> {orchestrator}")
    _log("Start Claude Code with:")
    for line in claude_env_lines(port):
        _log(f"  {line}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _log(json.dumps(server.stats.snapshot()))  # type: ignore[attr-defined]
    return 0
