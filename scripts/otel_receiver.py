#!/usr/bin/env python3
"""OTLP receiver: turn Claude Code's native OpenTelemetry stream into Agentmetry events.

Spike status: working prototype, not yet a shipped feature. It accepts
OTLP/HTTP **JSON** exports (the protocol Claude Code gets via
``OTEL_EXPORTER_OTLP_PROTOCOL=http/json``) on 127.0.0.1:4318, maps the
``claude_code.*`` log events it can onto the external-ingest body, and
forwards them to the orchestrator. Everything else is counted and reported,
never dropped silently — the unmapped list is the input to canonical schema
v1.3, which is the point of running this against real traffic.

Privacy posture mirrors the hook client: tool arguments are hashed here, in
this process, before anything is forwarded; ``prompt``/``response``/``error``
text is never forwarded at all. ``--keep-command`` opts in to storing scrubbed
command text (the AGENTMETRY_LOG_COMMANDS equivalent).

Claude Code side (documented at code.claude.com/docs/en/monitoring-usage):

    CLAUDE_CODE_ENABLE_TELEMETRY=1
    OTEL_LOGS_EXPORTER=otlp
    OTEL_EXPORTER_OTLP_PROTOCOL=http/json
    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
    OTEL_LOG_TOOL_DETAILS=1            # opt-in: tool_parameters in the stream
    OTEL_METRICS_EXPORTER=none         # metrics are aggregates; not yet mapped

    # point the logs endpoint at the receiver explicitly (or rely on endpoint):
    # OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs

Usage:
    python scripts/otel_receiver.py [--orchestrator http://127.0.0.1:8000]
                                    [--port 4318] [--keep-command]

Mapping (26 documented event types → canonical v1.2):
    tool_result            → tool_called / tool_failed   (enriched: traits, MITRE, ATLAS)
    tool_decision          → approval_response
    mcp_server_connection  → mcp_schema                  (partial: only if attrs carry a fingerprint)
    everything else        → counted as unmapped (see --print-mapping)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "orchestrator"))

# Same enrichment surface the hook client uses, so OTel-derived events are
# visible to the command-based sequence rules under the default hashed-only
# config. Degrade to unenriched-but-valid events if any import is missing.
try:
    from agentmetry.hooks.ingest import (
        extract_command,
        hash_arguments,
        redact_arguments,
        scrub_arg_values,
    )
    from agentmetry.core.audit.atlas import attach_atlas
    from agentmetry.core.audit.detection.traits import classify_command
    from agentmetry.core.audit.mitre import get_mitre_mapping
except ImportError:  # pragma: no cover - spike degrades rather than dies
    extract_command = hash_arguments = redact_arguments = scrub_arg_values = None
    attach_atlas = classify_command = get_mitre_mapping = None

#: Documented event types that have no canonical home yet (schema v1.3 input).
#: user_prompt/assistant_response are also deliberately never forwarded: they
#: are the model's words, and the flight recorder's default is structure, not
#: content.
KNOWN_UNMAPPED = {
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
}

_lock = threading.Lock()
_counts: dict[str, int] = {}
_unmapped: dict[str, int] = {}
_forwarded = 0
_forward_errors = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    print(f"[{_now_iso()}] {msg}", flush=True)


def _otlp_val(value: dict[str, Any]) -> Any:
    """Decode one OTLP JSON attribute value into a plain Python value."""
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
        return [_otlp_val(v) for v in value["arrayValue"].get("values", [])]
    if "kvlistValue" in value:
        return _otlp_attrs(value["kvlistValue"].get("values", []))
    if "bytesValue" in value:
        return repr(value["bytesValue"])
    return value


def _otlp_attrs(items: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        key = item.get("key")
        if key:
            out[key] = _otlp_val(item.get("value", {}))
    return out


def _merge_body(record: dict[str, Any], attrs: dict[str, Any]) -> None:
    """If the body is a JSON blob of the same event, let its keys backfill.

    Claude Code documents events by their attributes; some exporter paths
    serialize the payload into the body instead. Attribute wins on conflict.
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


def _ns_to_iso(ns: Any) -> str:
    try:
        seconds = int(ns) / 1_000_000_000
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return _now_iso()


def _enrich_tool(tool: dict[str, Any], args: dict[str, Any] | None, keep_command: bool) -> None:
    """Hash args and compute detection features while plaintext is visible.

    This is the hook client's ``_hash_tool_args`` sequence, applied to OTel
    traffic: without it the default hashed-only config leaves every
    command-based sequence rule blind on this source too.
    """
    if args is not None:
        tool["input_hash"] = hash_arguments(args) if hash_arguments else "0" * 64
        cmd = extract_command(args, str(tool.get("qualified") or "")) if extract_command else None
        if classify_command and cmd:
            traits = classify_command(cmd)
            if traits:
                tool["traits"] = traits
        if get_mitre_mapping:
            evidence = cmd or (args if isinstance(args, dict) else None)
            mitre = get_mitre_mapping(str(tool.get("qualified") or ""), evidence)
            if mitre:
                tool["mitre"] = mitre
        if attach_atlas:
            attach_atlas(tool)
        if keep_command and scrub_arg_values and redact_arguments:
            tool["command"] = scrub_arg_values(redact_arguments({"value": cmd})).get("value", "") if cmd else ""
    elif hash_arguments:
        tool["input_hash"] = hash_arguments({})


def map_record(event_name: str, attrs: dict[str, Any], ts_iso: str, keep_command: bool) -> dict[str, Any] | None:
    """One claude_code.* event → ExternalIngestBody shape (or None if unmapped)."""
    session_id = str(attrs.get("session.id") or attrs.get("session_id") or "")
    base: dict[str, Any] = {
        "source_app": "claude",
        "adapter": "otel",
        "correlation_id": session_id,
        "session_id": str(attrs.get("prompt.id") or ""),
        "timestamp_utc": ts_iso,
        "triggered_by": "otel_receiver",
    }
    model_id = str(attrs.get("model") or attrs.get("gen_ai.request.model") or "")

    if event_name == "tool_result":
        tool_name = str(attrs.get("tool_name") or "unknown")
        server = str(attrs.get("mcp_server_scope") or "claude")
        success = attrs.get("success", True)
        params = attrs.get("tool_parameters") or attrs.get("tool_input")
        tool: dict[str, Any] = {"qualified": tool_name, "server": server}
        if isinstance(params, dict):
            _enrich_tool(tool, params, keep_command)
        else:
            _enrich_tool(tool, None, keep_command)
        base.update(
            {
                "event_type": "tool_called" if success else "tool_failed",
                "outcome": "success" if success else "failure",
                "reason": str(attrs.get("error_type") or "") if not success else "",
                "tool_qualified": tool_name,
                "model_id": model_id,
                "tool": tool,
            }
        )
        return base

    if event_name == "tool_decision":
        decision = str(attrs.get("decision") or attrs.get("decision_type") or "unknown")
        base.update(
            {
                "event_type": "approval_response",
                "outcome": decision,
                "reason": str(attrs.get("decision_source") or ""),
                "tool_qualified": str(attrs.get("tool_name") or ""),
                "model_id": model_id,
            }
        )
        return base

    if event_name == "mcp_server_connection" and attrs.get("server_fingerprint"):
        base.update(
            {
                "event_type": "mcp_schema",
                "schema_fingerprint": str(attrs.get("server_fingerprint")),
                "reason": str(attrs.get("server_name") or attrs.get("mcp_server_name") or ""),
            }
        )
        return base

    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "agentmetry-otel-receiver/0.1"
    # OTLP exporters speak HTTP/1.1 with Content-Length; without this the
    # handler defaults to HTTP/1.0 semantics and keep-alive clients stall.
    protocol_version = "HTTP/1.1"

    # Claude Code sends Content-Length and no chunked encoding (v2.1.212+).
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        global _forwarded, _forward_errors
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""

        if self.path.startswith("/v1/metrics"):
            # Metrics are aggregates (cost/tokens/edits), not session events.
            # Acknowledge so the exporter does not retry, count, and stop there.
            with _lock:
                _counts["__metrics_ack__"] = _counts.get("__metrics_ack__", 0) + 1
            self._ok()
            return

        if not self.path.startswith("/v1/logs"):
            self._status(404)
            return

        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            self._status(400)
            return

        keep_command = bool(getattr(self.server, "keep_command", False))
        forward: list[dict[str, Any]] = []
        for res_log in payload.get("resourceLogs", []) or []:
            for scope in res_log.get("scopeLogs", []) or []:
                for record in scope.get("logRecords", []) or []:
                    attrs = _otlp_attrs(record.get("attributes", []) or [])
                    _merge_body(record, attrs)
                    event_name = str(
                        attrs.get("event.name")
                        or record.get("eventName")
                        or ""
                    ).removeprefix("claude_code.")
                    if not event_name:
                        continue
                    ts_iso = _ns_to_iso(record.get("timeUnixNano"))
                    with _lock:
                        _counts[event_name] = _counts.get(event_name, 0) + 1
                    mapped = map_record(event_name, attrs, ts_iso, keep_command)
                    if mapped is not None:
                        forward.append(mapped)
                    elif event_name in KNOWN_UNMAPPED:
                        with _lock:
                            _unmapped[event_name] = _unmapped.get(event_name, 0) + 1
                    else:
                        _log(f"UNKNOWN event: {event_name!r} (add to KNOWN_UNMAPPED or map it)")

        orchestrator = getattr(self.server, "orchestrator", "")
        for body in forward:
            try:
                _post_ingest(orchestrator, body)
                with _lock:
                    _forwarded += 1
            except (urllib.error.URLError, OSError) as exc:
                with _lock:
                    _forward_errors += 1
                _log(f"forward failed ({exc.__class__.__name__}): {exc}")

        self._ok()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path in ("/healthz", "/"):
            self._ok(json.dumps(_summary()).encode())
            return
        self._status(404)

    def _status(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ok(self, body: bytes | None = None) -> None:
        # Headers terminated first, then body: writing the body before
        # end_headers() leaves no separator and stalls HTTP/1.1 clients.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body) if body else 0))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # silence per-request noise
        return


def _post_ingest(orchestrator: str, body: dict[str, Any]) -> None:
    import os

    req = urllib.request.Request(
        f"{orchestrator.rstrip('/')}/api/v1/audit/ingest",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    api_key = os.environ.get("AGENTMETRY_API_KEY")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 201, 202):
            raise OSError(f"ingest returned {resp.status}")


def _summary() -> dict[str, Any]:
    with _lock:
        return {
            "forwarded": _forwarded,
            "forward_errors": _forward_errors,
            "mapped_by_event": dict(_counts),
            "unmapped_by_event": dict(_unmapped),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--orchestrator", default="http://127.0.0.1:8000")
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--keep-command", action="store_true",
                        help="store scrubbed command text (default: hash + traits + MITRE ids only)")
    parser.add_argument("--print-mapping", action="store_true",
                        help="print the mapped/unmapped table and exit")
    args = parser.parse_args()

    if args.print_mapping:
        print("mapped:   tool_result -> tool_called/tool_failed (traits+MITRE+ATLAS)")
        print("mapped:   tool_decision -> approval_response")
        print("partial:  mcp_server_connection -> mcp_schema (needs fingerprint attr)")
        for name in sorted(KNOWN_UNMAPPED):
            print(f"unmapped: {name} (canonical schema v1.3 candidate)")
        return 0

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.orchestrator = args.orchestrator  # type: ignore[attr-defined]
    server.keep_command = args.keep_command  # type: ignore[attr-defined]
    _log(f"OTLP receiver on http://127.0.0.1:{args.port} -> {args.orchestrator}")
    _log("Point Claude Code at it:")
    _log("  CLAUDE_CODE_ENABLE_TELEMETRY=1 OTEL_LOGS_EXPORTER=otlp "
         f"OTEL_EXPORTER_OTLP_PROTOCOL=http/json OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:{args.port}")

    def _heartbeat() -> None:
        while True:
            time.sleep(30)
            s = _summary()
            _log(f"alive: forwarded={s['forwarded']} errors={s['forward_errors']} "
                 f"events={sum(s['mapped_by_event'].values())}")

    threading.Thread(target=_heartbeat, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _log(json.dumps(_summary()))
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
